import logging
from datetime import timedelta

from odoo import models, fields, api

from .account_move import RS_CONFIRMED

_logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    rs_synced = fields.Boolean(string='Synced to RS', compute='_compute_rs_sync_state',
        help="True when rs.ge has this line in its current Odoo form. False after local edits, deletion, or cancellation.")
    rs_sync_state = fields.Selection([
        ('skipped', 'Skipped'),
        ('not_sent', 'Not Sent'),
        ('pending_edit', 'Pending Edit'),
        ('synced', 'Synced'),
        ('confirmed', 'Confirmed'),
        ('superseded', 'Superseded'),
        ('cancelled', 'Cancelled'),
    ], string='RS Sync State', compute='_compute_rs_sync_state',
        help="Detailed line state against rs.ge: skipped, not sent, edited after sync, synced, confirmed, superseded, or cancelled.")

    rs_einv_vat_class = fields.Selection([('taxable', 'Standard'), ('zero', 'Zero-rated'), ('untaxed', 'Exempt or no VAT')], string='rs.ge VAT Class',
        compute='_compute_rs_einv_vat', help="VAT treatment rs.ge gets for this line, from the Tax Category Code of its taxes.")
    rs_einv_vat_amount = fields.Monetary(string='rs.ge VAT', currency_field='currency_id', compute='_compute_rs_einv_vat',
        help="VAT of the line sent to rs.ge (taxes with Tax Category Code S only), in the invoice currency; rs.ge receives it in GEL.")
    rs_einv_goods = fields.Char(string='rs.ge Goods', compute='_compute_rs_einv_goods',
        help="Name rs.ge gets for this line: the product name in the customer's language, else the line label.")

    @api.depends('display_type', 'move_id.rs_einv_id', 'move_id.rs_einv_skip', 'move_id.rs_einv_status', 'move_id.rs_einv_has_pending_changes',
        'move_id.rs_einv_advance_sync_state')
    def _compute_rs_sync_state(self):
        SYNCED_STATES = {'synced', 'confirmed'}
        for line in self:
            move = line.move_id
            status = move.rs_einv_status or ''
            if line.display_type != 'product':
                line.rs_sync_state = False
            elif move.rs_einv_skip:
                line.rs_sync_state = 'skipped'
            elif not move.rs_einv_id:
                line.rs_sync_state = 'not_sent'
            elif move.rs_einv_has_pending_changes:
                line.rs_sync_state = 'pending_edit'
            elif (move.rs_einv_advance_sync_state in ('partial', 'error')
                    and move._rs_uses_native_advance_attach()
                    and getattr(line, 'is_downpayment', False)):
                line.rs_sync_state = 'pending_edit'
            elif status in ('-1', '6', '7'):
                line.rs_sync_state = 'cancelled'
            elif status == '3':
                line.rs_sync_state = 'superseded'
            elif status in RS_CONFIRMED:
                line.rs_sync_state = 'confirmed'
            elif status in ('0', '1', '4', '5'):
                line.rs_sync_state = 'synced'
            else:
                line.rs_sync_state = 'not_sent'
            line.rs_synced = line.rs_sync_state in SYNCED_STATES

    @api.depends('display_type', 'tax_ids', 'tax_ids.ubl_cii_tax_category_code', 'price_total', 'price_subtotal')
    def _compute_rs_einv_vat(self):
        """Preview of the VAT class and amount ``_rs_line_to_payload`` sends for product lines."""
        for line in self:
            if line.display_type == 'product':
                line.rs_einv_vat_class, line.rs_einv_vat_amount = line.move_id._rs_line_vat_class(line)
            else:
                line.rs_einv_vat_class = False
                line.rs_einv_vat_amount = 0.0

    @api.depends('name', 'product_id', 'move_id.partner_id.lang', 'move_id.rs_einv_is_buyer_side')
    def _compute_rs_einv_goods(self):
        for line in self:
            move = line.move_id
            if line.product_id and not move.rs_einv_is_buyer_side:
                product = line.product_id.with_context(display_default_code=False)
                if lang := move._get_lang():
                    product = product.with_context(lang=lang)
                line.rs_einv_goods = product.display_name
            else:
                line.rs_einv_goods = line.name or False


class RsEinvoiceAdvanceSettlement(models.Model):
    _name = 'rs.einvoice.advance.settlement'
    _description = 'RS Advance Settlement Audit'
    _order = 'synced_at desc, id desc'

    final_move_id = fields.Many2one('account.move', string='Final Invoice', required=True, ondelete='cascade', index=True)
    advance_move_id = fields.Many2one('account.move', string='Advance Invoice', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', related='final_move_id.company_id', store=True, index=True, readonly=True)
    currency_id = fields.Many2one('res.currency', related='final_move_id.company_currency_id', readonly=True)
    advance_rs_id = fields.Char(string='Advance RS ID', required=True, readonly=True, index=True)
    vat_amount = fields.Monetary(string='VAT Attached', currency_field='currency_id', readonly=True)
    action = fields.Selection([('attached', 'Attached'), ('updated', 'Updated'), ('already', 'Already Attached')], string='Action', readonly=True)
    rs_status = fields.Char(string='RS Status', readonly=True)
    rs_message = fields.Char(string='RS Message', readonly=True)
    synced_at = fields.Datetime(string='Synced At', readonly=True)


class RsEinvoiceLog(models.Model):
    _name = 'rs.einvoice.log'
    _description = 'RS E-Invoice Log'
    _order = 'create_date desc'

    move_id = fields.Many2one('account.move', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', related='move_id.company_id', store=True, index=True, readonly=True)
    name = fields.Char(required=True)
    level = fields.Selection([('info', 'Info'), ('warning', 'Warning'), ('error', 'Error')], default='info', required=True, index=True)

    @api.model
    def _cron_vacuum(self, retain_days=90, retain_errors_days=365):
        """Errors stay longer than info and warnings, to keep the audit context."""
        cutoff = fields.Datetime.now() - timedelta(days=retain_days)
        err_cutoff = fields.Datetime.now() - timedelta(days=retain_errors_days)
        infos = self.search([('level', 'in', ['info', 'warning']), ('create_date', '<', cutoff)])
        n_info = len(infos)
        infos.unlink()
        errors = self.search([('level', '=', 'error'), ('create_date', '<', err_cutoff)])
        n_err = len(errors)
        errors.unlink()
        if n_info or n_err:
            _logger.info("rs.einvoice.log vacuum: removed %d info/warning + %d error rows", n_info, n_err)
        return n_info + n_err


class RsEinvoiceCorrectionLine(models.Model):
    _name = 'rs.einvoice.correction.line'
    _description = 'RS Line Snapshot (buyer-pulled)'
    _order = 'move_id, id'

    move_id = fields.Many2one('account.move', required=True, ondelete='cascade', index=True, help="The vendor bill this rs.ge line belongs to.")
    company_id = fields.Many2one('res.company', related='move_id.company_id', store=True, index=True, readonly=True)
    snapshot_type = fields.Selection([('rs_pulled', 'Pulled from rs.ge')], required=True, readonly=True)
    rs_line_id = fields.Char(string='RS Line ID', readonly=True)
    goods = fields.Char(string='Goods', readonly=True)
    g_unit = fields.Char(string='Unit', readonly=True)
    g_number = fields.Float(string='Qty', readonly=True)
    full_amount = fields.Float(string='Full Amount', readonly=True)
    drg_amount = fields.Float(string='VAT Amount', readonly=True)

    def _cron_vacuum_snapshots(self, retain_pulled_days=180):
        pulled_cutoff = fields.Datetime.now() - timedelta(days=retain_pulled_days)
        pulled = self.search([('snapshot_type', '=', 'rs_pulled'), ('create_date', '<', pulled_cutoff)])
        n_pulled = len(pulled)
        if n_pulled:
            pulled.unlink()
            _logger.info("rs.einvoice.correction.line vacuum: removed %d pulled snapshots", n_pulled)
        return n_pulled
