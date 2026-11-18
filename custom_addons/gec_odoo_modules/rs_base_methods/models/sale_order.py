# -*- coding: utf-8 -*-

from odoo import models, Command, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _invoiceable_rs_waybills(self):
        self.ensure_one()
        return self.waybill_id.filtered(lambda w: w.waybill_direction == 'seller' and not w.is_template and w.waybill_status in ('1',
            '2') and w.rs_internal_id and (w.rs_waybill_number or '').strip() and not w.is_locked_by_invoice)

    def action_open_rs_invoice_from_waybill_wizard(self):
        self.ensure_one()
        if self.state not in ('sale', 'done'):
            raise UserError(_("The sale order must be confirmed before invoicing."))
        waybills = self._invoiceable_rs_waybills()
        if not waybills:
            raise UserError(_("No active or completed seller waybills are linked to this sale order's deliveries yet."))
        if not self.partner_id.vat:
            raise UserError(_("Partner %s has no Tax ID (VAT). Set it before invoicing on rs.ge.", self.partner_id.display_name))
        return {
            'name': _('Create RS Invoice from Waybills'),
            'type': 'ir.actions.act_window',
            'res_model': 'rs.invoice.from.waybill.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_seed_sale_order_id': self.id,
                'default_waybill_ids': [Command.set(waybills.ids)],
            },
        }
