from odoo import models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _gec_is_georgian(self):
        self.ensure_one()
        # sudo: a user working in a branch only cannot read the root company
        return self.root_id.sudo().account_fiscal_country_id.code == 'GE'
