from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    waybill_id = fields.One2many('rs.waybill', 'sales_order_id', string='Waybills')
    rs_waybill_locked = fields.Boolean(
        string='RS Waybill Locked',
        compute='_compute_rs_waybill_locked',
        help='True when a linked waybill is live on RS.GE (saved and not cancelled). The '
             'customer and order lines are then read-only here — edit via the waybill.',
    )

    @api.depends('waybill_id.rs_internal_id', 'waybill_id.state')
    def _compute_rs_waybill_locked(self):
        for order in self:
            order.rs_waybill_locked = any(
                w.rs_internal_id and w.state != 'cancelled' for w in order.waybill_id)

    def _action_cancel(self):
        """ Mark the order's own cancel so its deliveries' waybill follow-up does not
            reduce or cancel this order a second time. """
        return super(SaleOrder, self.with_context(rs_order_cancel=True))._action_cancel()

    def action_view_waybills(self):
        self.ensure_one()
        waybills = self.waybill_id
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Waybill'),
            'res_model': 'rs.waybill',
            'context': {'default_sales_order_id': self.id},
        }
        if len(waybills) == 1:
            action.update({'view_mode': 'form', 'res_id': waybills.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('sales_order_id', '=', self.id)]})
        return action


class SalesOrderLine(models.Model):
    _inherit = 'sale.order.line'

    bar_code = fields.Char(string='Bar Code', related='product_id.barcode', store=True)
