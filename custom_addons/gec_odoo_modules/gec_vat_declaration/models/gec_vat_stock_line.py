from odoo import fields, models


class GecVatStockLine(models.Model):
    _name = 'gec.vat.stock.line'
    _inherit = 'gec.vat.declaration.row'
    _description = 'VAT Declaration Tab 15 Row'
    _order = 'declaration_id, product_code, id'

    declaration_id = fields.Many2one('gec.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    product_ids = fields.Many2many('product.product', string='Products', readonly=True,
        help="Set on rows built by Generate; a row without products was typed.")
    product_code = fields.Char(string='RS Product Code')
    opening_kg = fields.Float(string='Opening (kg)', digits=(16, 4))
    opening_l = fields.Float(string='Opening (L)', digits=(16, 4))
    received_kg = fields.Float(string='Received (kg)', digits=(16, 4))
    received_l = fields.Float(string='Received (L)', digits=(16, 4))
    spec_sold_kg = fields.Float(string='Sold with ნსაფ (kg)', digits=(16, 4))
    spec_sold_l = fields.Float(string='Sold with ნსაფ (L)', digits=(16, 4))
    sold_kg = fields.Float(string='Sold without Discount (kg)', digits=(16, 4))
    sold_l = fields.Float(string='Sold without Discount (L)', digits=(16, 4))
    sold_amount_kg = fields.Float(string='Sold without Discount, Amount (kg)', digits=(16, 2))
    sold_amount_l = fields.Float(string='Sold without Discount, Amount (L)', digits=(16, 2))
    discount_sold_kg = fields.Float(string='Sold with Discount (kg)', digits=(16, 4))
    discount_sold_l = fields.Float(string='Sold with Discount (L)', digits=(16, 4))
    discount_amount_kg = fields.Float(string='Sold with Discount, Amount (kg)', digits=(16, 2))
    discount_amount_l = fields.Float(string='Sold with Discount, Amount (L)', digits=(16, 2))
    own_use_kg = fields.Float(string='Own Use (kg)', digits=(16, 4))
    own_use_l = fields.Float(string='Own Use (L)', digits=(16, 4))
    processed_kg = fields.Float(string='Processed (kg)', digits=(16, 4))
    processed_l = fields.Float(string='Processed (L)', digits=(16, 4))
    closing_kg = fields.Float(string='Closing (kg)', digits=(16, 4))
    closing_l = fields.Float(string='Closing (L)', digits=(16, 4))
