from odoo import api, fields, models

from .gec_brand_kit import BUNDLED_FONTS


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Georgian fonts for PDF reports (Document Layout); their TTF @font-face rules are in report_fonts.scss
    font = fields.Selection(selection_add=list(BUNDLED_FONTS.items()),
                            ondelete={key: 'set default' for key in BUNDLED_FONTS})

    @api.model_create_multi
    def create(self, vals_list):
        """New companies get the applied brand kit's logo, report colors and font, like the existing ones."""
        companies = super().create(vals_list)
        kit = self.env['gec.brand.kit']._get_applied()
        if kit:
            companies.write(kit.with_context(bin_size=False)._company_values())
        return companies
