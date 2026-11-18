from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    rs_form15_is_leasing_company = fields.Boolean(
        string='Leasing Company',
        help="Order 996 art. 88: a leasing company values property it leases out at the "
             "book value it had when first leased out, and its rate is capped at 0.6% "
             "instead of 1% for the whole lease period.")
