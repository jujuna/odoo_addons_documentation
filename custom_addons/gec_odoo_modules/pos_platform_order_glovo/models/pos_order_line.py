from odoo import api, models

from odoo.addons.pos_platform_order_glovo.models.pos_order import changed_by

LOCKED_FIELDS = ['order_id', 'product_id', 'qty', 'price_unit', 'discount', 'tax_ids', 'extra_tax_data']


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        self.env['pos.order'].browse(vals['order_id'] for vals in vals_list if vals.get('order_id'))._check_glovo_order_unchanged()
        self.browse(vals['refunded_orderline_id'] for vals in vals_list if vals.get('refunded_orderline_id')).order_id._check_glovo_manager_only()
        return super().create(vals_list)

    def write(self, vals):
        if changed := changed_by(self, vals, LOCKED_FIELDS):
            (changed.order_id | self.env['pos.order'].browse(vals.get('order_id')))._check_glovo_order_unchanged()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_glovo_order(self):
        self.order_id._check_glovo_order_unchanged()
