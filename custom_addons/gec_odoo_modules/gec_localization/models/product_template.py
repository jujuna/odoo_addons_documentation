from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    not_taxed = fields.Boolean(string="Not Taxed",
        help="No tax is proposed for this product on orders, invoices and bills. A tax can still be added by hand on the line.")
    supplier_taxes_id = fields.Many2many(domain=[('type_tax_use', '=', 'purchase'), ('gec_is_withholding', '=', False)])
