from odoo import fields, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _compute_tax_id(self):
        super()._compute_tax_id()
        AccountTax = self.env['account.tax']
        for line in self.filtered('product_id'):
            line = line.with_company(line.company_id)
            order = line.order_id
            fpos = order.fiscal_position_id or order.fiscal_position_id._get_fiscal_position(order.partner_id)
            line.tax_ids = AccountTax._ge_partner_product_taxes(line.tax_ids, order.partner_id, line.product_id, line.company_id, 'purchase', fpos,
                date=fields.Date.context_today(line, order.date_order))
