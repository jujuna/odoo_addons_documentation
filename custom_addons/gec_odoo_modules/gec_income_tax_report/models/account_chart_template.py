from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _post_load_data(self, template_code, company, template_data):
        super()._post_load_data(template_code, company, template_data)
        if template_code == 'ge' and not company.parent_id:
            self.env['account.tax']._rs_form30_map_ge_taxes(company)
            self.env['rs.form30.account.rule']._rs_form30_seed_account_rules(company)
            self.env['res.company']._rs_form30_seed_pension_accounts(company)
