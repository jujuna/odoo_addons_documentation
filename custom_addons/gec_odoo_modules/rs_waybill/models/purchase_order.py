from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    waybill_id = fields.One2many('rs.waybill', 'purchase_id', string='Waybills')
    waybill_count = fields.Integer(string='Waybill Count', compute='_compute_waybill_count')
    rs_waybill_locked = fields.Boolean(
        string='RS Waybill Locked',
        compute='_compute_rs_waybill_locked',
        help='True when a linked vendor waybill is on RS.GE and not cancelled. The vendor '
             'and order lines are then read-only here — a buyer cannot edit a vendor-issued '
             'waybill on RS, so local edits would silently diverge. Changes arrive from the '
             'vendor via RS sync; use Receive/Reject on the waybill.',
    )


    @api.depends('waybill_id')
    def _compute_waybill_count(self):
        for purchase in self:
            purchase.waybill_count = len(purchase.waybill_id)

    @api.depends('waybill_id.rs_internal_id', 'waybill_id.state')
    def _compute_rs_waybill_locked(self):
        for purchase in self:
            purchase.rs_waybill_locked = any(
                w.rs_internal_id and w.state != 'cancelled' for w in purchase.waybill_id)


    def action_view_waybills(self):
        self.ensure_one()
        waybills = self.waybill_id
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Waybills',
            'res_model': 'rs.waybill',
            'context': {'default_purchase_id': self.id},
        }
        if len(waybills) == 1:
            action.update({'view_mode': 'form', 'res_id': waybills.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('purchase_id', '=', self.id)]})
        return action