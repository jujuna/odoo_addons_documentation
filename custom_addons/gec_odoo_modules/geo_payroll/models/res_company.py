from odoo import models

CORE_GE_PAYROLL = 'l10n_ge_hr_payroll'


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _compute_uninstalled_l10n_module_ids(self):
        """geo_payroll replaces Odoo's Georgian payroll: a new Georgian company must not install it again."""
        super()._compute_uninstalled_l10n_module_ids()
        for company in self:
            company.uninstalled_l10n_module_ids = company.uninstalled_l10n_module_ids.filtered(lambda module: module.name != CORE_GE_PAYROLL)
