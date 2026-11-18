from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # No company_id: a Tax ID names one taxpayer on rs.ge whichever company asks.
    rs_un_id = fields.Integer(string='RS Taxpayer ID', copy=False, readonly=True,
        help="rs.ge id of this partner's taxpayer, resolved from its Tax ID on first use and kept, since a Tax ID maps to one taxpayer. Cleared when "
        "the Tax ID changes.")

    def write(self, vals):
        """A new Tax ID means another taxpayer: the cached rs.ge id goes with the old one."""
        if 'vat' in vals and 'rs_un_id' not in vals:
            vals = dict(vals, rs_un_id=0)
        return super().write(vals)
