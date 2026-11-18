# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    l10n_lb_tax_category = fields.Selection([
        ('main', "Main Employer"),
        ('other', "Other Employer"),
        ('exempt', "Exempt"),
    ], string="Income Tax Category", default='main', required=True,
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="Main Employer: the only employer, or the one chosen by the employee to get the family deduction "
             "(Income Tax Law, art. 31 and 53). A daily or hourly worker gets the daily deduction instead.\n"
             "Other Employer: any other employer, or an employee who also has a business or professional "
             "activity: the tax is withheld without family deduction (art. 53 and 57) and the employee files the "
             "R8 personal declaration before 1 May.\n"
             "Exempt: salaries exempt by art. 47 of the Income Tax Law, e.g. the foreign staff of the embassies "
             "and of the listed international organisations.")
    l10n_lb_spouse_working = fields.Boolean(string="Spouse Working",
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="The spouse of a married employee has a paid or taxable activity. For the income tax, each spouse then "
             "gets the deduction of a single person and the deduction of the children is shared equally (Law No. "
             "324 of 2024, art. 49). The NSSF family allowance of the spouse is only due for a spouse without "
             "paid work nor pension (Social Security Code, art. 46).")
    l10n_lb_net_salary = fields.Boolean(string="LB: Tax Borne by the Employer",
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="The wage is agreed net of the income tax: the tax paid by the employer is itself a cash benefit "
             "(Income Tax Law, art. 49) and is grossed up on the payslip.")
    l10n_lb_nssf_coverage = fields.Selection([
        ('full', "All Branches"),
        ('no_eos', "Without End-of-Service"),
        ('eos_only', "End-of-Service Only"),
        ('none', "Not Covered"),
    ], string="NSSF Coverage", default='full', required=True,
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="All Branches: Lebanese employees, and foreign employees holding a work permit from a state granting "
             "the reciprocity.\n"
             "Without End-of-Service: foreign employees without reciprocity: the employer pays the sickness and "
             "maternity and the family allowances contributions, not the end-of-service ones, and no family "
             "allowance is paid (Social Security Code, art. 9(3)).\n"
             "End-of-Service Only: Palestinian refugees registered with the Ministry of Interior, entitled to the "
             "end-of-service indemnity only (Law No. 128 of 2010).\n"
             "Not Covered: foreign employees working under a contract made abroad with an equivalent social "
             "protection (art. 9(4)).")
    l10n_lb_family_allowance = fields.Boolean(string="NSSF Family Allowances", default=True,
        groups="hr_payroll.group_hr_payroll_user", tracking=1,
        help="The employee receives the NSSF family allowances for the spouse without paid work and the dependent "
             "children (up to 5), paid with the salary for the Fund and offset in the contribution schedule "
             "(Social Security Code, art. 46 to 48). Uncheck it when the other parent receives the allowance of "
             "the children: it is paid to the father unless the mother has the custody.")
    l10n_lb_nssf_number = fields.Char(string="NSSF Registration Number", groups="hr.group_hr_user", tracking=1)
    l10n_lb_tax_number = fields.Char(string="Personal Tax Number", groups="hr.group_hr_user", tracking=1,
        help="Registration number of the employee at the Ministry of Finance, requested by the employer within 3 "
             "months of the hiring (form R3) and used in every declaration (Tax Procedures Law, art. 32 and 34).")

    @api.model
    def _get_whitelist_fields_from_template(self):
        whitelisted_fields = super()._get_whitelist_fields_from_template() or []
        if self.env.company.country_id.code == 'LB':
            whitelisted_fields += [
                'l10n_lb_tax_category',
                'l10n_lb_net_salary',
                'l10n_lb_nssf_coverage',
            ]
        return whitelisted_fields

    def _l10n_lb_get_minimum_wage_gap(self, day=None):
        """Amount missing to reach the official minimum wage on ``day`` (today by default), 0 when it is reached
        (Labour Code, art. 44): the basic salary with the cost-of-living increases and the regular allowances is
        compared with the minimum monthly wage prorated by the part-time rate of the working schedule, the hourly
        wage of a day of the working schedule with the minimum daily wage. The minimum in LBP is converted at the
        rate of the company."""
        self.ensure_one()
        day = day or fields.Date.context_today(self)
        calendar = self.resource_calendar_id
        # sudo: the official minimum wage is public data, read for the HR officers without payroll access
        parameter = self.env['hr.rule.parameter'].sudo()
        if self.wage_type == 'hourly':
            minimum = parameter._get_parameter_from_code('l10n_lb_minimum_wage_daily', day, raise_if_not_found=False)
            wage = self.hourly_wage * (calendar.hours_per_day if calendar else 0.0)
        else:
            minimum = parameter._get_parameter_from_code('l10n_lb_minimum_wage_monthly', day, raise_if_not_found=False)
            if minimum:
                minimum *= calendar.work_time_rate if calendar else 1.0
            wage = self.wage + self._get_property_input_value('COL_ALW') + self._get_property_input_value('REGULAR_ALW')
        lbp = self.env.ref('base.LBP')
        if not minimum or not self.currency_id or (self.currency_id != lbp and not self.env['res.currency.rate'].search_count(
                [('currency_id', '=', lbp.id), ('name', '<=', day)], limit=1)):
            return 0.0
        minimum = lbp._convert(minimum, self.currency_id, self.company_id, day)
        return minimum - wage if self.currency_id.compare_amounts(minimum, wage) > 0 else 0.0

    def _l10n_lb_get_minimum_wage_warning(self):
        """Message of the payroll warning of a version paid below the official minimum wage, empty otherwise."""
        self.ensure_one()
        gap = self._l10n_lb_get_minimum_wage_gap()
        if not gap:
            return ""
        return self.env._(
            "The wage, the cost-of-living increases and the regular allowances are %(gap)s below the official minimum "
            "wage (Labour Code, art. 44).",
            gap=self.currency_id.format(gap))
