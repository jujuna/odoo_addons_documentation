from odoo import fields, models


class RsEinvoiceCorrectionLine(models.Model):
    _inherit = 'rs.einvoice.correction.line'

    rs_good_id = fields.Integer('RS Petroleum ID', readonly=True)
    rs_g_number_alt = fields.Float(string='Quantity (kg)', readonly=True)
