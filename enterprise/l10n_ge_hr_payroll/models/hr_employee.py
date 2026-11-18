# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    l10n_ge_tax_privilege = fields.Selection(readonly=False, related="version_id.l10n_ge_tax_privilege", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_ge_privilege_used = fields.Float(readonly=False, related="version_id.l10n_ge_privilege_used", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_ge_pension_status = fields.Selection(readonly=False, related="version_id.l10n_ge_pension_status", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_ge_net_salary = fields.Boolean(readonly=False, related="version_id.l10n_ge_net_salary", inherited=True, groups="hr_payroll.group_hr_payroll_user")
