from odoo import fields, models


class HotelRmsRoomType(models.Model):
    _inherit = 'hotel.rms.room.type'

    product_tmpl_id = fields.Many2one('product.template', string="Odoo room product", check_company=True, ondelete='set null',
        domain="[('rent_periodicity', 'in', ('days', 'nights'))]",
        help="The rental product that sells this room type: its rental order "
        "lines are the reservations and its pricelist price is the current price.")

    _product_tmpl_unique = models.Constraint('UNIQUE(product_tmpl_id)', "An Odoo product can be the room product of one room type only.")
