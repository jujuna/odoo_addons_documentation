# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

from odoo.addons.rs_einvoice.models.account_move import rs_to_int

_logger = logging.getLogger(__name__)


SYNC_SUMMARY = [('none', 'None'), ('draft', 'Draft'), ('synced', 'Synced'), ('error', 'Error')]


class AccountMove(models.Model):
    _inherit = 'account.move'

    rs_einv_waybill_link_ids = fields.One2many('rs.einvoice.waybill.link', 'move_id', string='RS Waybills', copy=False)
    rs_einv_waybill_count = fields.Integer(compute='_compute_rs_einv_waybill_summary')
    rs_einv_waybill_has_links = fields.Boolean(compute='_compute_rs_einv_waybill_summary')
    rs_einv_waybill_sync_state = fields.Selection(SYNC_SUMMARY, compute='_compute_rs_einv_waybill_summary')

    @api.model
    def _rs_waybill_holder_domain(self):
        """Domain of moves that hold their waybills: not cancelled,
        not reversed by a Skip rs.ge 'replacement' credit note."""
        return Domain('state', '!=', 'cancel') & Domain('reversal_move_ids', 'not any',
            [('state', '=', 'posted'), ('rs_einv_skip_reason', '=', 'replacement')])

    @api.constrains('state', 'rs_einv_waybill_link_ids')
    def _check_waybill_links_unique_active(self):
        holder = self._rs_waybill_holder_domain()
        for move in self:
            if not move.rs_einv_waybill_link_ids or not move.filtered_domain(holder):
                continue
            wb_ids = move.rs_einv_waybill_link_ids.waybill_id.ids
            if not wb_ids:
                continue
            others = self.env['rs.einvoice.waybill.link'].search([
                ('waybill_id', 'in', wb_ids),
                ('move_id', '!=', move.id),
                ('move_id', 'any', holder),
            ])
            if others:
                conflicts = '\n'.join("  - %s -> %s (%s)" % (o.waybill_id.display_name, o.move_id.display_name, o.move_id.state) for o in others)
                raise ValidationError(_("Cannot reactivate this invoice — these waybills are now attached to another active invoice:\n%s", conflicts))

    @api.depends('rs_einv_waybill_link_ids.sync_state')
    def _compute_rs_einv_waybill_summary(self):
        for move in self:
            links = move.rs_einv_waybill_link_ids
            move.rs_einv_waybill_count = len(links)
            move.rs_einv_waybill_has_links = bool(links)
            if not links:
                move.rs_einv_waybill_sync_state = 'none'
            elif any(l.sync_state == 'error' for l in links):
                move.rs_einv_waybill_sync_state = 'error'
            elif any(l.sync_state == 'draft' for l in links):
                move.rs_einv_waybill_sync_state = 'draft'
            else:
                move.rs_einv_waybill_sync_state = 'synced'

    @staticmethod
    def _rs_match_remote_waybill_row(rows, wb_no, claimed):
        """Return the id of the first unclaimed rs.ge row for waybill ``wb_no``, or 0."""
        for row in rows:
            if str(row.get('overhead_no') or '').strip() != wb_no:
                continue
            rid = rs_to_int(row.get('id'))
            if rid and rid not in claimed:
                return rid
        return 0

    def _rs_sync_waybill_links(self, service):
        """Push unsynced links to rs.ge; a link is 'synced' only if a re-read finds its waybill number, else 'error'."""
        self.ensure_one()
        if not self.rs_einv_id:
            return
        target_id = self._rs_inv_id_int
        if not target_id:
            return

        def _read_remote_rows():
            try:
                return service.get_invoice_waybills(target_id) or []
            except Exception as e:
                _logger.info("get_invoice_waybills during sync failed for inv_id=%s: %s", target_id, e)
                return None

        for link in self.rs_einv_waybill_link_ids:
            if link.sync_state == 'synced' and link.rs_remote_id:
                continue
            waybill = link.waybill_id
            wb_no = (waybill.rs_waybill_number or '').strip()
            if not wb_no:
                link.sync_state = 'error'
                link.sync_message = _("Waybill has no rs.ge waybill number.")
                continue
            overhead_dt = waybill.activation_date or waybill.delivery_date \
                or fields.Datetime.now()
            try:
                if link.rs_remote_id:
                    try:
                        service.delete_invoice_waybill_link(link.rs_remote_id, target_id)
                    except Exception as e:
                        _logger.info("delete_invoice_waybill_link before re-save failed: %s", e)
                ok = service.save_invoice_waybill_link(target_id, wb_no, overhead_dt)
                if not ok:
                    link.sync_state = 'error'
                    link.sync_message = _("rs.ge returned False on save_ntos_invoices_inv_nos.")
                    link.rs_remote_id = 0
                    continue
                rows = _read_remote_rows()
                if rows is None:
                    link.sync_state = 'error'
                    link.sync_message = _("rs.ge accepted the save but the verification read failed. Click Update on RS to retry.")
                    link.rs_remote_id = 0
                    continue
                claimed = set(self.rs_einv_waybill_link_ids.filtered(lambda l: l.id != link.id and l.rs_remote_id).mapped('rs_remote_id'))
                matched_id = self._rs_match_remote_waybill_row(rows, wb_no, claimed)
                if not matched_id:
                    link.sync_state = 'error'
                    link.sync_message = _("rs.ge accepted the save but the verification read did not return an unclaimed row for waybill %s.", wb_no)
                    link.rs_remote_id = 0
                    continue
                link.rs_remote_id = matched_id
                link.sync_state = 'synced'
                link.synced_at = fields.Datetime.now()
                link.sync_message = False
            except Exception as e:
                link.sync_state = 'error'
                link.sync_message = str(e)
                _logger.exception("Failed to sync waybill link %s", link.id)

    def _rs_find_product_for_pulled(self, snap):
        """Prefer the product the waybill line resolved (matched by name,
        the e-invoice line has no barcode), else rs_einvoice's search."""
        key = self._rs_pulled_match_key(snap.goods)
        if key:
            Product = self.env['product.product']
            for line in self.rs_einv_waybill_link_ids.waybill_id.line_ids:
                if self._rs_pulled_match_key(line.name) != key:
                    continue
                if line.product_id:
                    return line.product_id
                bar_code = (line.bar_code or '').strip()
                if bar_code:
                    product = Product.search([('barcode', '=', bar_code), *Product._check_company_domain(self.company_id)], limit=1)
                    if product:
                        return product
        return super()._rs_find_product_for_pulled(snap)

    def _rs_refresh_waybill_links(self, service):
        """Re-read the rs.ge rows and update each link's remote id and sync state."""
        self.ensure_one()
        if not self.rs_einv_id or not self.rs_einv_waybill_link_ids:
            return
        target_id = self._rs_inv_id_int
        if not target_id:
            return
        try:
            rows = service.get_invoice_waybills(target_id) or []
        except Exception as e:
            _logger.info("Refresh waybill links failed: %s", e)
            return
        rows_by_id = {}
        for r in rows:
            rid = rs_to_int(r.get('id'))
            if rid:
                rows_by_id[rid] = r
        claimed_ids = {link.rs_remote_id for link in self.rs_einv_waybill_link_ids if link.rs_remote_id and link.rs_remote_id in rows_by_id}
        for link in self.rs_einv_waybill_link_ids.with_context(rs_auto_sync=True):
            if link.rs_remote_id and link.rs_remote_id in rows_by_id:
                link.sync_state = 'synced'
                link.sync_message = False
                continue
            wb_no = (link.waybill_id.rs_waybill_number or '').strip()
            matched_id = self._rs_match_remote_waybill_row(rows, wb_no, claimed_ids)
            if matched_id:
                link.rs_remote_id = matched_id
                claimed_ids.add(matched_id)
                link.sync_state = 'synced'
                link.sync_message = False
            elif link.sync_state == 'synced':
                link.sync_state = 'draft'
                link.rs_remote_id = 0

    def _rs_create_invoice(self, service):
        res = super()._rs_create_invoice(service)
        if self.rs_einv_id and self.rs_einv_waybill_link_ids:
            self._rs_sync_waybill_links(service)
        return res

    def action_rs_edit(self):
        res = super().action_rs_edit()
        for move in self:
            if move.rs_einv_id and move.rs_einv_waybill_link_ids:
                move._rs_sync_waybill_links(move._rs_get_service())
        return res

    def action_rs_send(self):
        for move in self:
            unsynced = move.rs_einv_waybill_link_ids.filtered(lambda l: l.sync_state != 'synced')
            if unsynced:
                raise UserError(_("%d waybill link(s) are not synced to rs.ge. Click 'Update on RS' first, then try sending again.", len(unsynced)))
        return super().action_rs_send()

    def unlink(self):
        return super(AccountMove, self.with_context(rs_skip_remote_detach=True)).unlink()

    def action_rs_delete(self):
        res = super().action_rs_delete()
        for move in self:
            if not move.rs_einv_id and move.rs_einv_waybill_link_ids:
                move.rs_einv_waybill_link_ids.with_context(rs_auto_sync=True).write({
                    'sync_state': 'draft',
                    'rs_remote_id': 0,
                    'synced_at': False,
                    'sync_message': False,
                })
        return res

    def action_rs_refresh_status(self):
        res = super().action_rs_refresh_status()
        for move in self:
            if move.rs_einv_id and move.rs_einv_waybill_link_ids:
                move._rs_refresh_waybill_links(move._rs_get_service())
        return res

    def _rs_carry_waybill_links_to_replacement(self):
        """Recreate the waybill links on the reissue replacement, after the cancel frees them."""
        self.ensure_one()
        replacement = self.rs_einv_replaced_by_id
        links = self.rs_einv_waybill_link_ids
        if not replacement or not links or replacement.state == 'cancel':
            return
        have = set(replacement.rs_einv_waybill_link_ids.waybill_id.ids)
        Link = self.env['rs.einvoice.waybill.link'].with_context(rs_auto_sync=True)
        created = False
        for link in links:
            if link.waybill_id.id in have:
                continue
            Link.create({
                'move_id': replacement.id,
                'waybill_id': link.waybill_id.id,
                'source': link.source,
                'sync_state': 'draft',
            })
            created = True
        if created and replacement.rs_einv_id:
            replacement._rs_refresh_waybill_links(replacement._rs_get_service())

    def _rs_auto_cancel_after_rs_cancellation(self, event_message=None):
        """Carry the waybill links to the replacement once the original no longer holds them."""
        res = super()._rs_auto_cancel_after_rs_cancellation(event_message=event_message)
        if (self.rs_einv_replaced_by_id and not self.filtered_domain(self._rs_waybill_holder_domain())):
            self._rs_carry_waybill_links_to_replacement()
        return res

    def action_open_rs_waybill_links(self):
        """Smart button: open the waybill links as a list."""
        self.ensure_one()
        return {
            'name': _('Waybill Links'),
            'type': 'ir.actions.act_window',
            'res_model': 'rs.einvoice.waybill.link',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id},
        }

    def _rs_sync_buyer_waybill_links(self, service):
        """Link the bill to the buyer waybills rs.ge attached, skipping known links; return the count created."""
        self.ensure_one()
        if self.move_type != 'in_invoice' or not self.rs_einv_id:
            return 0
        target_id = self._rs_inv_id_int
        if not target_id:
            return 0
        try:
            rows = service.get_invoice_waybills(target_id) or []
        except Exception as e:
            _logger.info("get_invoice_waybills failed for bill %s: %s", self.id, e)
            return 0

        existing_numbers = {(link.waybill_id.rs_waybill_number or '').strip() for link in self.rs_einv_waybill_link_ids}
        commercial = self.partner_id.commercial_partner_id or self.partner_id
        seller_tin = (commercial.vat or self.partner_id.vat or '').strip()
        Waybill = self.env['rs.waybill']
        Link = self.env['rs.einvoice.waybill.link'].with_context(rs_auto_sync=True)

        wb_numbers = {str(row.get('overhead_no') or '').strip() for row in rows}
        wb_numbers -= existing_numbers
        wb_numbers.discard('')
        waybill_by_number = {}
        if wb_numbers:
            wb_domain = [
                ('rs_waybill_number', 'in', list(wb_numbers)),
                ('waybill_direction', '=', 'buyer'),
                ('company_id', 'in', (False, self.company_id.id)),
            ]
            if seller_tin:
                wb_domain.append(('seller_tin', '=', seller_tin))
            for waybill in Waybill.search(wb_domain):
                waybill_by_number.setdefault((waybill.rs_waybill_number or '').strip(), waybill)

        created = 0
        for row in rows:
            wb_no = str(row.get('overhead_no') or '').strip()
            if not wb_no or wb_no in existing_numbers:
                continue
            waybill = waybill_by_number.get(wb_no)
            if not waybill:
                continue
            row_id = rs_to_int(row.get('id'))
            Link.create({
                'move_id': self.id,
                'waybill_id': waybill.id,
                'sync_state': 'synced',
                'rs_remote_id': row_id,
                'synced_at': fields.Datetime.now(),
                'source': 'wizard',
            })
            existing_numbers.add(wb_no)
            created += 1
        if created:
            self._rs_log("Synced %d waybill link(s) from rs.ge to this bill." % created)
        return created

    def action_rs_sync_buyer_waybills(self):
        """Sync Waybills button on vendor bills."""
        self.ensure_one()
        if self.move_type != 'in_invoice':
            raise UserError(_("Sync Waybills only applies to vendor bills."))
        if not self.rs_einv_id:
            raise UserError(_("Pull this bill from rs.ge first — then waybill links can be synced."))
        service = self._rs_get_service()
        created = self._rs_sync_buyer_waybill_links(service)
        if not created:
            self._rs_log("Sync Waybills: no new waybill links to add.")
        return True

    def action_rs_buyer_pull(self):
        """Sync the waybill links before the pull builds the lines,
        so they can be tied to the waybills' purchase orders."""
        for move in self:
            if (move.move_type == 'in_invoice' and move.rs_einv_id and not move.rs_einv_skip):
                move._rs_sync_buyer_waybill_links(move._rs_get_service())
        return super().action_rs_buyer_pull()

    def _rs_auto_import_pulled_to_bill_lines(self):
        res = super()._rs_auto_import_pulled_to_bill_lines()
        self._rs_link_purchase_order_lines()
        return res

    def _rs_merge_pulled_to_bill_lines(self):
        res = super()._rs_merge_pulled_to_bill_lines()
        self._rs_link_purchase_order_lines()
        return res

    def _rs_link_purchase_order_lines(self):
        """Tie draft bill lines to purchase order lines like core's _update_purchase_order_lines,
        using the waybills' orders, else the vendor's order matching the rs.ge total."""
        self.ensure_one()
        if self.move_type != 'in_invoice' or self.state != 'draft':
            return
        lines = self._rs_product_lines().filtered(lambda line: line.product_id and not line.purchase_line_id)
        if not lines:
            return
        orders = (self.rs_einv_waybill_link_ids.waybill_id.purchase_id | self.invoice_line_ids.purchase_line_id.order_id)
        order_lines = orders.filtered(lambda order: order.state == 'purchase' and order.company_id == self.company_id).order_line
        if not order_lines:
            method, order_lines, _dummy = self._match_purchase_orders([], self.commercial_partner_id.id,
                sum(self.rs_einv_pulled_line_ids.mapped('full_amount')), False, 10)
            if method != 'total_match':
                return
        order_lines = order_lines.filtered(lambda po_line: po_line.product_id and po_line.qty_to_invoice > 0) - self.invoice_line_ids.purchase_line_id
        if not order_lines:
            return
        self._update_purchase_order_lines(order_lines)
        linked = lines.filtered('purchase_line_id')
        if not linked:
            return
        order_names = ', '.join(linked.purchase_line_id.order_id.mapped('name'))
        if not self.invoice_origin:
            self.invoice_origin = order_names
        self._rs_log("Linked %d bill line(s) to purchase order(s) %s." % (len(linked), order_names))
