from odoo import fields, models


class ResCountry(models.Model):
    _inherit = 'res.country'

    gec_cit_preferential = fields.Boolean(
        string='Preferential Taxation',
        help="On the Government of Georgia list of countries with preferential taxation. Payments to persons "
             "registered there feed line 18.1 of the profit tax declaration, and dividends received from them "
             "are taxed when distributed again.")
