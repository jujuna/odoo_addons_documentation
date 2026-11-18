from odoo import fields, models


class ResCountry(models.Model):
    _inherit = 'res.country'

    rs_country_code = fields.Char(string='RS Country Code', size=3,
        help="3-digit numeric country code used by the Revenue Service Employee Registry (e.g. 036 for Australia, 040 for Austria). Populated via "
        "Settings > RS Employee Registry > Sync Countries from RS.")
