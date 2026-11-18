import csv

from odoo import api, fields, models
from odoo.tools import file_open


class ResCountry(models.Model):
    _inherit = 'res.country'

    rs_form30_code = fields.Char(string='rs.ge Country Code', size=3,
        help="Residency code written in the rs.ge Form 30 annex; empty means rs.ge has no code for this country")

    @api.model
    def _rs_form30_load_codes(self):
        """Fill empty rs.ge codes; the csv alone is skipped on upgrade because country ids are noupdate."""
        with file_open('gec_income_tax_report/data/res.country.csv') as handle:
            wanted = {row['id']: row['rs_form30_code'] for row in csv.DictReader(handle) if row['rs_form30_code']}
        data = self.env['ir.model.data'].sudo().search([
            ('model', '=', 'res.country'),
            ('module', 'in', list({xmlid.split('.')[0] for xmlid in wanted})),
            ('name', 'in', [xmlid.split('.', 1)[1] for xmlid in wanted]),
        ])
        code_by_id = {entry.res_id: wanted[f"{entry.module}.{entry.name}"] for entry in data if f"{entry.module}.{entry.name}" in wanted}
        for country in self.browse(list(code_by_id)).exists().filtered(lambda c: not c.rs_form30_code):
            country.rs_form30_code = code_by_id[country.id]
