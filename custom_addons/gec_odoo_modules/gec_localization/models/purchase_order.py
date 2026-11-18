from odoo import api, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.onchange('partner_id')
    def _onchange_partner_id_default_taxes(self):
        self.filtered(lambda order: order.company_id._gec_is_georgian()).order_line._compute_tax_id()
