from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('order_id.partner_id')
    def _compute_tax_ids(self):
        super()._compute_tax_ids()
        AccountTax = self.env['account.tax']
        for line in self.filtered(lambda l: l.product_id and l.product_type != 'combo'):
            order = line.order_id
            line.tax_ids = AccountTax._ge_partner_product_taxes(line.tax_ids, order.partner_id, line.product_id, line.company_id, 'sale',
                order.fiscal_position_id)
