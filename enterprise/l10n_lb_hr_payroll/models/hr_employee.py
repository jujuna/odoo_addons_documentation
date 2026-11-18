# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    l10n_lb_tax_category = fields.Selection(readonly=False, related="version_id.l10n_lb_tax_category", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_lb_spouse_working = fields.Boolean(readonly=False, related="version_id.l10n_lb_spouse_working", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_lb_net_salary = fields.Boolean(readonly=False, related="version_id.l10n_lb_net_salary", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_lb_nssf_coverage = fields.Selection(readonly=False, related="version_id.l10n_lb_nssf_coverage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_lb_family_allowance = fields.Boolean(readonly=False, related="version_id.l10n_lb_family_allowance", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_lb_nssf_number = fields.Char(readonly=False, related="version_id.l10n_lb_nssf_number", inherited=True, groups="hr.group_hr_user")
    l10n_lb_tax_number = fields.Char(readonly=False, related="version_id.l10n_lb_tax_number", inherited=True, groups="hr.group_hr_user")
