# -*- coding: utf-8 -*-

import logging

import psycopg2

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Fields whose change on a synced link implies a remote change on rs.ge.
_REMOTE_SIGNIFICANT_FIELDS = {'waybill_id', 'move_id'}


SYNC_STATE = [('draft', 'Draft'), ('synced', 'Synced'), ('error', 'Error')]

SOURCE = [('manual', 'Manual'), ('wizard', 'Wizard')]


class _BigInteger(fields.Integer):
    """Integer stored as bigint: rs.ge row ids of ``ntos_invoices_inv_nos`` exceed 32 bits."""
    _column_type = ('int8', 'int8')


class RsEinvoiceWaybillLink(models.Model):
    _name = 'rs.einvoice.waybill.link'
    _description = 'RS E-Invoice ↔ Waybill Link'
    _rec_name = 'waybill_id'
    _check_company_auto = True

    move_id = fields.Many2one('account.move', required=True, ondelete='cascade', index=True)
    waybill_id = fields.Many2one('rs.waybill', required=True, index=True, check_company=True, domain=[
        ('waybill_direction', 'in', ('seller', 'buyer')),
        ('is_template', '=', False),
        ('waybill_status', 'in', ('1', '2')),
        ('rs_internal_id', '>', 0),
        ('rs_waybill_number', '!=', False),
    ])

    rs_remote_id = _BigInteger(string='RS Remote ID', copy=False, readonly=True)
    sync_state = fields.Selection(SYNC_STATE, default='draft', required=True, copy=False)
    sync_message = fields.Text(copy=False)
    synced_at = fields.Datetime(copy=False, readonly=True)
    source = fields.Selection(SOURCE, default='manual', required=True, readonly=True)

    company_id = fields.Many2one('res.company', related='move_id.company_id', store=True, index=True, readonly=True)
    waybill_number = fields.Char(related='waybill_id.rs_waybill_number', store=False)
    waybill_status = fields.Selection(related='waybill_id.waybill_status', store=False)
    waybill_direction = fields.Selection(related='waybill_id.waybill_direction', store=False)
    waybill_date = fields.Datetime(related='waybill_id.activation_date', store=False)
    waybill_amount = fields.Float(related='waybill_id.full_amount', store=False)
    buyer_tin = fields.Char(related='waybill_id.buyer_tin', store=False)
    seller_tin = fields.Char(related='waybill_id.seller_tin', store=False)

    _unique_move_waybill = models.Constraint('UNIQUE(move_id, waybill_id)', 'A waybill can only be linked once to the same invoice.')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('rs_auto_sync'):
            move_ids = [v.get('move_id') for v in vals_list if v.get('move_id')]
            moves = self.env['account.move'].browse(move_ids)
            for move in moves:
                if move.move_type == 'in_invoice':
                    raise UserError(_("Waybill links on vendor bills are managed by Sync Waybills — they cannot be added manually."))
        wb_ids = sorted({v['waybill_id'] for v in vals_list if v.get('waybill_id')})
        self._lock_waybills(wb_ids)
        return super().create(vals_list)

    @api.model
    def _lock_waybills(self, waybill_ids):
        """Lock the waybill rows (NOWAIT) so a concurrent link cannot slip past the duplicate check."""
        ids = [wb_id for wb_id in waybill_ids if wb_id]
        if not ids:
            return
        try:
            self.env.cr.execute("SELECT id FROM rs_waybill WHERE id IN %s FOR UPDATE NOWAIT", (tuple(ids),))
        except psycopg2.errors.LockNotAvailable:
            raise UserError(_("Another user is currently attaching one of these waybills to an invoice. Wait a moment and try again."))

    @api.constrains('move_id', 'waybill_id')
    def _check_waybill_not_on_another_invoice(self):
        if not self:
            return
        others = self.search([
            ('waybill_id', 'in', self.waybill_id.ids),
            ('id', 'not in', self.ids),
            ('move_id', 'any', self.env['account.move']._rs_waybill_holder_domain()),
        ])
        if not others:
            return
        by_wb = {}
        for o in others:
            by_wb.setdefault(o.waybill_id.id, o)
        conflicts = []
        for link in self:
            other = by_wb.get(link.waybill_id.id)
            if other and other.move_id != link.move_id:
                conflicts.append("  - %s -> %s (%s)" % (link.waybill_id.display_name, other.move_id.display_name, other.move_id.state))
        if conflicts:
            raise ValidationError(_("The following waybills are already attached to another active invoice. Cancel or delete that invoice first:\n%s",
                '\n'.join(conflicts)))

    @api.constrains('move_id', 'waybill_id')
    def _check_partner_and_type(self):
        for link in self:
            move = link.move_id
            if move.move_type == 'out_invoice':
                expected_dir = 'seller'
                wb_tin = (link.waybill_id.buyer_tin or '').strip()
                tin_label = "buyer"
            elif move.move_type == 'in_invoice':
                expected_dir = 'buyer'
                wb_tin = (link.waybill_id.seller_tin or '').strip()
                tin_label = "seller"
            else:
                raise ValidationError(_("Waybills can only be attached to customer invoices or vendor bills."))
            if move.rs_einv_skip:
                raise ValidationError(_("This document is marked Skip rs.ge; waybill attachment is not allowed."))
            if link.waybill_id.waybill_direction != expected_dir:
                raise ValidationError(_("Waybill %s has direction '%s' but this %s requires '%s'.", link.waybill_id.display_name,
                    link.waybill_id.waybill_direction, 'customer invoice' if move.move_type == 'out_invoice' else 'vendor bill', expected_dir))
            commercial = move.partner_id.commercial_partner_id or move.partner_id
            partner_vat = (commercial.vat or move.partner_id.vat or '').strip()
            if partner_vat and wb_tin and partner_vat != wb_tin:
                raise ValidationError(_("Waybill %s %s TIN (%s) does not match the document partner VAT (%s).", link.waybill_id.display_name,
                    tin_label, wb_tin, partner_vat))

    # Drift guards: a synced row is not changed or deleted while its rs.ge row exists

    def _is_remote_protected(self):
        self.ensure_one()
        return bool(self.sync_state == 'synced' and self.rs_remote_id and self.move_id.rs_einv_id)

    def _detach_remote(self):
        """Delete the row on rs.ge; return True when it is gone, raise UserError if rs.ge fails."""
        self.ensure_one()
        if not self.rs_remote_id or not self.move_id._rs_inv_id_int:
            return True
        service = self.move_id._rs_get_service()
        try:
            service.delete_invoice_waybill_link(self.rs_remote_id, self.move_id._rs_inv_id_int)
        except Exception as e:
            _logger.exception("Failed to detach waybill %s from rs.ge invoice %s", self.waybill_id.display_name, self.move_id.display_name)
            raise UserError(_("Could not detach waybill %s from rs.ge invoice %s: %s", self.waybill_id.display_name, self.move_id.display_name, e))
        return True

    def write(self, vals):
        if not self.env.context.get('rs_auto_sync'):
            for link in self:
                if link.move_id.move_type == 'in_invoice':
                    raise UserError(_("Waybill links on vendor bills are managed by Sync Waybills and cannot be edited manually."))
        protected = self.filtered(lambda l: l._is_remote_protected())
        if protected and _REMOTE_SIGNIFICANT_FIELDS.intersection(vals.keys()):
            raise UserError(_("Cannot change the waybill or invoice on a synced link. Detach it from rs.ge first or cancel the invoice."))
        if vals.get('waybill_id'):
            self._lock_waybills([vals['waybill_id']])
        return super().write(vals)

    def unlink(self):
        if self.env.context.get('rs_skip_remote_detach'):
            return super().unlink()
        for link in self:
            move = link.move_id
            if move.move_type == 'in_invoice':
                raise UserError(_("Waybill links on vendor bills are managed by Sync Waybills and cannot be removed manually."))
            if not (move.rs_einv_replaces_id and not move.rs_einv_id):
                raise UserError(_("Cannot remove waybill %s from invoice %s. To remove a waybill, make a correction first — waybills can be edited "
                    "on the correction draft until it is sent to rs.ge.", link.waybill_id.display_name, move.display_name))
            if link._is_remote_protected():
                link._detach_remote()
        return super().unlink()
