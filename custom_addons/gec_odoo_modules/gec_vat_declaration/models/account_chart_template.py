from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _post_load_data(self, template_code, company, template_data):
        super()._post_load_data(template_code, company, template_data)
        if template_code == 'ge' and not company.parent_id:
            self.env['res.company']._gec_vat_seed_fixed_asset_accounts(company)
