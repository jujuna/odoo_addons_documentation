# Part of Odoo. See LICENSE file for full copyright and licensing details.

import math
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

# Income tax borne by the employer under a net salary agreement
L10N_LB_GROSS_UP_CODES = ('ITS',)
# The bands and the family deduction are split by the period of work, a month counting 30 days (Income Tax Law,
# art. 59)
L10N_LB_TAX_MONTH_DAYS = 30
L10N_LB_TAX_YEAR_DAYS = 360


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _get_data_files_to_update(self):
        # Note: file order should be maintained
        return super()._get_data_files_to_update() + [(
            'l10n_lb_hr_payroll', [
                'data/hr_salary_rule_category_data.xml',
                'data/hr_rule_parameter_data.xml',
                'data/hr_salary_rule_data.xml',
            ])]

    def _get_localdict(self, work_entries=None):
        res = super()._get_localdict(work_entries)
        if self.country_code == 'LB' or self.struct_id.country_code == 'LB':
            # Tax borne by the employer: the gross-up of the iteration in progress, see _get_payslip_lines
            res['l10n_lb_gross_up'] = self.env.context.get('l10n_lb_gross_up', 0.0)
        return res

    # -------------------------------------------------------------------------
    # Currency
    # -------------------------------------------------------------------------

    def _l10n_lb_get_lbp_rate(self):
        """LBP for one unit of the payslip currency. The NSSF ceilings and allowances and the income tax deductions
        and bands are set in LBP; the salaries paid in a foreign currency are converted at the rate of the Lebanese
        pound of the company on the last day of the period, to keep at the official rate of the Banque du Liban
        (NSSF memo 740: 89,500 per USD from 1 February 2024; Decree No. 56 of 2025, art. 17: rate at the end of the
        month for the income tax)."""
        self.ensure_one()
        currency = self.currency_id
        lbp = self.env.ref('base.LBP')
        if currency == lbp:
            return 1.0
        if not self.env['res.currency.rate'].search_count([('currency_id', '=', lbp.id), ('name', '<=', self.date_to)], limit=1):
            raise UserError(self.env._(
                "The payslip of %(employee)s is paid in %(currency)s: set the rate of the Lebanese pound (LBP) at the "
                "official rate of the Banque du Liban to convert the amounts of the law.",
                employee=self.employee_id.name, currency=currency.name))
        return currency._convert(1.0, lbp, self.company_id, self.date_to, round=False)

    def _l10n_lb_from_lbp(self, amount):
        """Amount in LBP converted into the payslip currency."""
        self.ensure_one()
        return amount / self._l10n_lb_get_lbp_rate()

    # -------------------------------------------------------------------------
    # Worked days
    # -------------------------------------------------------------------------

    def _l10n_lb_get_paid_lines(self):
        self.ensure_one()
        return self.worked_days_line_ids.filtered(
            lambda line: not line.work_entry_type_id.is_extra_hours and line.work_entry_type_id.amount_rate > 0)

    def _l10n_lb_get_days_worked(self):
        """Paid days of a daily or hourly worker."""
        self.ensure_one()
        if self.ignore_worked_day_lines:
            return 0.0
        return sum(self._l10n_lb_get_paid_lines().mapped('number_of_days'))

    def _l10n_lb_get_monthly_wage(self, statutory_allowances):
        """Monthly wage of the Labour Code: the basic salary with the cost-of-living increases and the regular
        allowances added to it (Labour Code, art. 57), base of the end-of-service indemnity. The monthly wage of an
        hourly worker is the hourly wage for the weekly hours of the working schedule, 52 weeks in 12 months."""
        self.ensure_one()
        version = self.version_id
        if version.wage_type == 'hourly':
            calendar = version.resource_calendar_id
            return version.hourly_wage * (calendar.hours_per_week if calendar else 0.0) * 52 / 12 + statutory_allowances
        return version.wage + statutory_allowances

    # -------------------------------------------------------------------------
    # National Social Security Fund
    # -------------------------------------------------------------------------

    def _l10n_lb_is_eos_due(self):
        """The end-of-service contribution is due for the employees entitled to the indemnity, until they reach
        64 complete (Social Security Code, art. 9(3) and 73(1))."""
        self.ensure_one()
        if self.version_id.l10n_lb_nssf_coverage not in ('full', 'eos_only'):
            return False
        birthday = self.employee_id.birthday
        return not birthday or relativedelta(self.date_from, birthday).years < self._rule_parameter('l10n_lb_nssf_eos_age')

    def _l10n_lb_compute_family_allowance(self):
        """NSSF family allowance paid with the salary for the Fund: the spouse without paid work nor pension, and
        each dependent child up to 5 (Social Security Code, art. 46 and 47). The month is paid in full when the
        employee is still employed on its last day."""
        self.ensure_one()
        version = self.version_id
        if version.l10n_lb_nssf_coverage != 'full' or not version.l10n_lb_family_allowance:
            return 0.0
        if version.contract_date_end and version.contract_date_end < self.date_to:
            return 0.0
        allowance = self._rule_parameter('l10n_lb_nssf_family_allowance')
        amount = min(version.children, allowance['max_children']) * allowance['child']
        if version.marital == 'married' and not version.l10n_lb_spouse_working:
            amount += allowance['spouse']
        return self._l10n_lb_from_lbp(amount)

    # -------------------------------------------------------------------------
    # Income tax on salaries and wages
    # -------------------------------------------------------------------------

    def _l10n_lb_get_tax_year_payslips(self):
        """Validated payslips of the same calendar year ending before this payslip."""
        self.ensure_one()
        return self.env['hr.payslip'].search([
            ('id', '!=', self.id),
            ('employee_id', '=', self.employee_id.id),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['validated', 'paid']),
            ('date_from', '>=', date(self.date_to.year, 1, 1)),
            ('date_to', '<', self.date_from),
        ])

    def _l10n_lb_get_tax_days(self):
        """Days of work of the period for the proration of the bands and of the deduction: 30 for a whole month,
        the calendar days of employment in the month of the hiring or of the exit (at most 30), the days paid to
        a daily or hourly worker (Income Tax Law, art. 59)."""
        self.ensure_one()
        version = self.version_id
        if version.wage_type == 'hourly':
            return self._l10n_lb_get_days_worked()
        start = max(version.contract_date_start or version.date_version, self.date_from)
        end = min(version.contract_date_end or self.date_to, self.date_to)
        if end < start:
            return 0
        if start == self.date_from and end == self.date_to:
            return L10N_LB_TAX_MONTH_DAYS
        return min((end - start).days + 1, L10N_LB_TAX_MONTH_DAYS)

    def _l10n_lb_get_tax_year_to_date(self):
        """Days of work, taxable income and income tax in LBP of the validated payslips of the calendar year before
        this payslip. The amounts of a payslip in a foreign currency are converted at the rate of the end of its
        month; the tax, withheld in multiples of the rounding of the law, is rounded back to it."""
        self.ensure_one()
        previous_payslips = self._l10n_lb_get_tax_year_payslips()
        line_values = previous_payslips._get_line_values(['TAXABLE', 'ITS'])
        days = taxable = tax = 0.0
        for payslip in previous_payslips:
            rate = payslip._l10n_lb_get_lbp_rate()
            days += payslip._l10n_lb_get_tax_days()
            taxable += line_values['TAXABLE'][payslip.id]['total'] * rate
            tax += float_round(
                -line_values['ITS'][payslip.id]['total'] * rate,
                precision_rounding=payslip._rule_parameter('l10n_lb_its_rounding'))
        return days, taxable, tax

    def _l10n_lb_get_family_deduction(self):
        """Yearly family deduction of the employee (Income Tax Law, art. 31, as replaced by Law No. 324 of 2024,
        art. 49): the taxpayer, the spouse without taxable activity, each dependent child up to 5. When both
        spouses work, each gets the deduction of a single person and the children deduction is shared equally."""
        self.ensure_one()
        version = self.version_id
        deduction = self._rule_parameter('l10n_lb_its_family_deduction')
        children = min(version.children, deduction['max_children']) * deduction['child']
        amount = deduction['single']
        if version.marital == 'married':
            if version.l10n_lb_spouse_working:
                children /= 2
            else:
                amount += deduction['married']
        return amount + children

    def _l10n_lb_compute_progressive_tax(self, taxable_income, share):
        """Tax of the bands of the year (Income Tax Law, art. 58), split by the share of the year worked."""
        self.ensure_one()
        tax = 0.0
        lower_bound = 0.0
        for upper_bound, rate in self._rule_parameter('l10n_lb_its_bands'):
            if upper_bound is not None and taxable_income > upper_bound * share:
                tax += (upper_bound * share - lower_bound) * rate / 100
                lower_bound = upper_bound * share
            else:
                tax += max(taxable_income - lower_bound, 0.0) * rate / 100
                break
        return tax

    def _l10n_lb_compute_income_tax(self, taxable):
        """Income tax of the month in LBP, withheld on the cumulative income of the calendar year (MoF Decision
        620/1 of 2019, art. 4): the taxable income of the year so far in LBP, less the deduction of the days worked
        so far, is taxed with the bands split by the same days, minus the tax already withheld. The result is
        rounded up to LBP 10,000 (Tax Procedures Law, art. 154).

        :param taxable: taxable income of the period in the payslip currency
        """
        self.ensure_one()
        version = self.version_id
        if version.l10n_lb_tax_category == 'exempt':
            return 0.0
        previous_days, previous_taxable, previous_tax = self._l10n_lb_get_tax_year_to_date()
        ytd_days = previous_days + self._l10n_lb_get_tax_days()
        ytd_taxable = previous_taxable + taxable * self._l10n_lb_get_lbp_rate()
        share = ytd_days / L10N_LB_TAX_YEAR_DAYS
        if version.wage_type == 'hourly':
            deduction = self._rule_parameter('l10n_lb_its_daily_deduction') * ytd_days
        elif version.l10n_lb_tax_category == 'main':
            deduction = self._l10n_lb_get_family_deduction() * share
        else:
            deduction = 0.0
        tax = self._l10n_lb_compute_progressive_tax(max(ytd_taxable - deduction, 0.0), share) - previous_tax
        rounding = self._rule_parameter('l10n_lb_its_rounding')
        return max(math.ceil(round(tax / rounding, 6)) * rounding, 0.0)

    # -------------------------------------------------------------------------
    # Termination
    # -------------------------------------------------------------------------

    def _l10n_lb_get_service_dates(self):
        """First day and day after the last day of the service with the employer, at the end of the period or of
        the contract."""
        self.ensure_one()
        version = self.version_id
        start = version.contract_date_start or version.date_version
        end = min(version.contract_date_end or self.date_to, self.date_to)
        return start, end + timedelta(days=1)

    def _l10n_lb_is_end_of_service_computed(self):
        """The employer pays the end-of-service indemnity of the Labour Code (art. 54) on the last payslip of the
        foreign employees outside the end-of-service branch of the NSSF (Social Security Code, art. 9(3)). The
        indemnity of the Lebanese employees, and of the foreign employees covered by the branch, is liquidated by
        the NSSF (art. 51): the employer only pays the amounts agreed or notified, as an input. An employee without
        nationality is considered Lebanese."""
        self.ensure_one()
        version = self.version_id
        nationality = self.employee_id.country_id
        if not nationality or nationality.code == 'LB' or version.l10n_lb_nssf_coverage in ('full', 'eos_only'):
            return False
        return bool(version.contract_date_end) and self.date_from <= version.contract_date_end <= self.date_to

    def _l10n_lb_compute_end_of_service(self, statutory_allowances):
        """End-of-service indemnity of the Labour Code (art. 54): half a month of wage below one year of service, a
        month of wage for each year of service from one year. The law does not set the fractions of a year: a year
        begun counts for its months, a month begun as a whole month, as the NSSF does for its indemnity (Social
        Security Code, art. 51)."""
        self.ensure_one()
        start, end = self._l10n_lb_get_service_dates()
        service = relativedelta(end, start)
        wage = self._l10n_lb_get_monthly_wage(statutory_allowances)
        if not service.years:
            return wage / 2
        return (service.years + (service.months + (1 if service.days else 0)) / 12) * wage

    # -------------------------------------------------------------------------
    # Tax borne by the employer
    # -------------------------------------------------------------------------

    def _get_payslip_lines(self, force_categories_by_code=None):
        net_payslips = self.filtered(lambda payslip: payslip.country_code == 'LB' and payslip.version_id.l10n_lb_net_salary)
        res = super(HrPayslip, self - net_payslips)._get_payslip_lines(force_categories_by_code=force_categories_by_code)
        for payslip in net_payslips:
            res.extend(payslip._l10n_lb_get_grossed_up_payslip_lines(force_categories_by_code=force_categories_by_code))
        return res

    def _l10n_lb_get_grossed_up_payslip_lines(self, force_categories_by_code=None):
        """The GROSS_UP line must cover exactly the income tax borne by the employer. The tax paid by the employer
        is itself a cash benefit (Income Tax Law, art. 49), so the computation is repeated with the tax of the
        previous iteration as gross-up until it is stable. The tax only grows with the gross-up and is rounded to
        LBP 10,000, so the iteration ends."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        gross_up = 0.0
        for _iteration in range(50):
            lines = super(HrPayslip, self.with_context(l10n_lb_gross_up=gross_up))._get_payslip_lines(
                force_categories_by_code=force_categories_by_code)
            tax = -sum(line['total'] for line in lines if line['code'] in L10N_LB_GROSS_UP_CODES)
            if not float_compare(tax, gross_up, precision_rounding=rounding):
                return lines
            gross_up = tax
        raise UserError(self.env._(
            "The income tax of %(employee)s borne by the employer could not be grossed up, check the salary rules of the structure.",
            employee=self.employee_id.name))
