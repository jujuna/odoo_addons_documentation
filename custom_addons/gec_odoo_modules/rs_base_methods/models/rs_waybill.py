# -*- coding: utf-8 -*-

from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError


class RsWaybill(models.Model):
    _inherit = 'rs.waybill'

    rs_invoice_link_ids = fields.One2many('rs.einvoice.waybill.link', 'waybill_id', string='RS Invoice Links')
    rs_invoice_count = fields.Integer(compute='_compute_rs_invoice_count')
    is_locked_by_invoice = fields.Boolean(compute='_compute_is_locked_by_invoice', store=True,
        help="True while this waybill is attached to a non-cancelled account.move via rs.einvoice.waybill.link. Blocks re-using the waybill on a "
        "second invoice and cancelling/editing/deleting it.")
    locked_by_move_id = fields.Many2one('account.move', compute='_compute_is_locked_by_invoice', store=True,
        help="The non-cancelled invoice currently holding this waybill, if any.")

    @api.depends('rs_invoice_link_ids')
    def _compute_rs_invoice_count(self):
        for wb in self:
            wb.rs_invoice_count = len(wb.rs_invoice_link_ids.move_id)

    @api.depends('rs_invoice_link_ids', 'rs_invoice_link_ids.move_id.state', 'rs_invoice_link_ids.move_id.reversal_move_ids.state',
        'rs_invoice_link_ids.move_id.reversal_move_ids.rs_einv_skip_reason', 'state')
    def _compute_is_locked_by_invoice(self):
        """Lock on the first linked move that is not cancelled or reversed by an rs.ge cancellation credit note."""
        holder_domain = self.env['account.move']._rs_waybill_holder_domain()
        for wb in self:
            holder = self.env['account.move']
            if wb.state != 'cancelled':
                holder = wb.rs_invoice_link_ids.move_id.filtered_domain(holder_domain)[:1]
            wb.locked_by_move_id = holder
            wb.is_locked_by_invoice = bool(holder)

    # rs.ge rejects cancel, edit and delete of a waybill on a live invoice

    def _rs_assert_not_invoice_linked(self):
        locked = self.filtered('is_locked_by_invoice')
        if not locked:
            return
        details = '\n'.join("  - %s -> %s" % (wb.display_name, wb.locked_by_move_id.display_name) for wb in locked)
        raise UserError(_(
            "This waybill is attached to an invoice and cannot be cancelled, "
            "edited or deleted. Remove it from the invoice first by making a "
            "correction on the invoice, then try again:\n%s",
            details,
        ))

    def _rs_auto_apply_blocked(self):
        """Return a reason to hold an RS.GE goods change while an
        invoice locks the waybill; rs_waybill retries it later."""
        blocked = super()._rs_auto_apply_blocked()
        if blocked or not self.is_locked_by_invoice:
            return blocked
        return _("the waybill is attached to invoice %s. Correct the invoice first, then click Retry.") % self.locked_by_move_id.display_name

    def action_refuse_waybill(self):
        self._rs_assert_not_invoice_linked()
        return super().action_refuse_waybill()

    def action_edit_waybill(self):
        self._rs_assert_not_invoice_linked()
        return super().action_edit_waybill()

    def action_submit_edit_to_rs(self):
        self._rs_assert_not_invoice_linked()
        return super().action_submit_edit_to_rs()

    def action_delete_waybill(self):
        self._rs_assert_not_invoice_linked()
        return super().action_delete_waybill()

    def _validate_waybills_for_invoicing(self):
        if not self:
            raise UserError(_("Select at least one waybill."))
        bad = []
        for rec in self:
            problems = []
            if rec.is_template:
                problems.append(_("template"))
            if rec.waybill_direction != 'seller':
                problems.append(_("not seller-direction"))
            if rec.waybill_status not in ('1', '2'):
                problems.append(_("status must be Active or Completed"))
            if not rec.rs_internal_id:
                problems.append(_("not synced to RS"))
            if not (rec.rs_waybill_number or '').strip():
                problems.append(_("missing rs.ge waybill number"))
            if not (rec.buyer_tin or '').strip():
                problems.append(_("missing buyer TIN"))
            if rec.is_locked_by_invoice:
                problems.append(_("already attached to invoice %s", rec.locked_by_move_id.display_name or ''))
            if problems:
                bad.append("%s (%s)" % (rec.display_name, ', '.join(problems)))
        if bad:
            raise UserError(_("These waybills cannot be invoiced:\n- %s", '\n- '.join(bad)))

        companies = self.mapped('company_id')
        if len(companies) > 1:
            raise UserError(_("Selected waybills belong to multiple companies: %s", ', '.join(companies.mapped('display_name'))))
        if companies and companies != self.env.company:
            raise UserError(_("Selected waybills belong to %s, but you are currently in %s. Switch company first.", companies.display_name,
                self.env.company.display_name))

        tins = {(w.buyer_tin or '').strip() for w in self}
        if len(tins) > 1:
            grouped = {}
            for w in self:
                grouped.setdefault((w.buyer_tin or '').strip(), []).append(w.rs_waybill_number or w.display_name)
            detail = '\n'.join("  TIN %s: %s" % (tin or _("(empty)"), ', '.join(nums)) for tin, nums in grouped.items())
            raise UserError(_("Selected waybills have different buyer TINs:\n%s", detail))

        so_ids = self.mapped('sales_order_id')
        if len(so_ids) > 1:
            grouped = {}
            for w in self:
                key = w.sales_order_id.display_name if w.sales_order_id else _("(no SO)")
                grouped.setdefault(key, []).append(w.rs_waybill_number or w.display_name)
            detail = '\n'.join("  %s: %s" % (name, ', '.join(nums)) for name, nums in grouped.items())
            raise UserError(_("Selected waybills are linked to different sale orders. All waybills must share the same sale order (or none):\n%s",
                detail))

    def _resolve_waybill_partner(self):
        tin = (self[:1].buyer_tin or '').strip()
        if not tin:
            raise UserError(_("Cannot resolve buyer — waybills have no buyer TIN."))

        buyer_ids = self.mapped('buyer_id').filtered(lambda p: p)
        if buyer_ids and len(buyer_ids) == 1:
            return buyer_ids

        Partner = self.env['res.partner']
        matches = Partner.search([('vat', '=', tin)])
        commercials = matches.filtered(lambda p: p.commercial_partner_id == p)
        if len(commercials) == 1:
            return commercials
        if len(commercials) > 1:
            raise UserError(_("Multiple partners match TIN %s: %s. Set buyer_id on the waybills to disambiguate.", tin,
                ', '.join(commercials.mapped('display_name'))))
        if len(matches) == 1:
            return matches.commercial_partner_id
        if len(matches) > 1:
            raise UserError(_("Multiple partners match TIN %s: %s. Set buyer_id on the waybills to disambiguate.", tin,
                ', '.join(matches.mapped('display_name'))))
        raise UserError(_("No partner found with TIN %s. Create the partner first.", tin))

    def action_open_invoice_from_waybill_wizard(self):
        self._validate_waybills_for_invoicing()
        partner = self._resolve_waybill_partner()
        return {
            'name': _('Create RS Invoice from Waybills'),
            'type': 'ir.actions.act_window',
            'res_model': 'rs.invoice.from.waybill.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': partner.id, 'default_waybill_ids': [Command.set(self.ids)], 'default_is_standalone': True},
        }
