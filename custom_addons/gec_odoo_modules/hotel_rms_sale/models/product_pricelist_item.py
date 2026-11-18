from odoo import fields, models


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    hotel_rms_price_id = fields.Many2one('hotel.rms.price', string="Hotel price", ondelete='set null', copy=False, index='btree_not_null')
