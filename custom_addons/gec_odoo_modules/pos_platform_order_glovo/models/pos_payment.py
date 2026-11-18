from odoo import api, models

from odoo.addons.pos_platform_order_glovo.models.pos_order import changed_by

LOCKED_FIELDS = ['pos_order_id', 'payment_method_id', 'amount']


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    @api.model_create_multi
    def create(self, vals_list):
        self.env['pos.order'].browse(vals['pos_order_id'] for vals in vals_list if vals.get('pos_order_id'))._check_glovo_order_unchanged()
        return super().create(vals_list)

    def write(self, vals):
        if changed := changed_by(self, vals, LOCKED_FIELDS):
            (changed.pos_order_id | self.env['pos.order'].browse(vals.get('pos_order_id')))._check_glovo_order_unchanged()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_glovo_order(self):
        self.pos_order_id._check_glovo_manager_only()
