# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    l10n_ge_tax_privilege = fields.Selection([
        ('none', "None"),
        ('a', "GEL 3,000 (Veterans, Single Parents...)"),
        ('b', "GEL 6,000 (Disability, Peacekeeping Injury)"),
        ('c', "GEL 6,000 (High-Mountain Settlement)"),
    ], string="Annual Tax Privilege", default='none', required=True,
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="Taxable income not taxed each calendar year, applied at this employer on the certificate of the "
             "Revenue Service (form II-082) (Tax Code, art. 82(2)):\n"
             "GEL 3,000: war veterans, 'Mother of Georgia', single parents, adopters for one year, foster parents.\n"
             "GEL 6,000: persons with a disability from childhood or a severe or significant disability, persons "
             "seriously injured in peacekeeping operations.\n"
             "GEL 6,000 (high-mountain settlement): permanent residents of a high-mountain settlement on the income "
             "of the work there.")
    l10n_ge_privilege_used = fields.Float(string="Privilege Used Before Hiring",
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="Part of the annual privilege already used at a previous employer in the year of the hiring, as shown "
             "on the certificate of the Revenue Service (form II-082).")
    l10n_ge_pension_status = fields.Selection([
        ('participant', "Participant"),
        ('opted_out', "Opted Out"),
        ('not_covered', "Not Covered"),
    ], string="Funded Pension", default='participant', required=True,
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="Participant: Georgian citizens and foreigners with a permanent residence permit, joined automatically "
             "or voluntarily: 2% withheld and 2% paid by the employer (Law on Funded Pensions, art. 3).\n"
             "Opted Out: employee aged 40 or more in 2018 who left the scheme within 5 months of the joining (art. "
             "22).\n"
             "Not Covered: foreigners without a permanent residence permit, employees aged 60 (men) or 55 (women) in "
             "2018 who did not join, employees drawing their funded pension (art. 1, 3 and 32).")
    l10n_ge_net_salary = fields.Boolean(string="GE: Net Salary Basis",
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="Decides who pays the income tax and pension: if enabled, the employer covers them on the employee's "
             "behalf; if disabled, they are deducted from the employee's own salary. The amount paid by the employer "
             "is itself salary income (Tax Code, art. 73(4)) and is grossed up on the payslip.")

    @api.model
    def _get_whitelist_fields_from_template(self):
        whitelisted_fields = super()._get_whitelist_fields_from_template() or []
        if self.env.company.country_id.code == 'GE':
            whitelisted_fields += [
                'l10n_ge_net_salary',
            ]
        return whitelisted_fields
