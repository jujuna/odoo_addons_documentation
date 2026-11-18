# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, datetime, time

from dateutil.relativedelta import relativedelta

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

# Income tax and pension borne by the employer under a net salary agreement
L10N_GE_GROSS_UP_CODES = ('PIT', 'PENSION_EE')
# Recovery of the sums owed by the employee, together within 50% of the net pay (Labour Code, art. 43)
L10N_GE_CAPPED_DEDUCTION_CODES = ('ADVANCE_RECOVERY', 'LOAN_RECOVERY', 'DAMAGE_RECOVERY', 'DEDUCTION')


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _get_data_files_to_update(self):
        # Note: file order should be maintained
        return super()._get_data_files_to_update() + [(
            'l10n_ge_hr_payroll', [
                'data/hr_salary_rule_category_data.xml',
                'data/hr_rule_parameter_data.xml',
                'data/hr_salary_rule_data.xml',
            ])]

    def _get_localdict(self, work_entries=None):
        res = super()._get_localdict(work_entries)
        if self.country_code == 'GE' or self.struct_id.country_code == 'GE':
            # Tax borne by the employer: the gross-up of the iteration in progress, see _get_payslip_lines
            res['l10n_ge_gross_up'] = self.env.context.get('l10n_ge_gross_up', 0.0)
        return res

    # -------------------------------------------------------------------------
    # Currency
    # -------------------------------------------------------------------------

    def _l10n_ge_from_gel(self, amount):
        """Amount of the law in GEL converted into the payslip currency, at the official rate of the National Bank
        of Georgia kept in the currency rates (Tax Code, art. 73(10))."""
        self.ensure_one()
        gel = self.env.ref('base.GEL')
        if self.currency_id == gel:
            return amount
        return gel._convert(amount, self.currency_id, self.company_id, self.date_to, round=False)

    def _l10n_ge_get_year_payslips(self):
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

    def _l10n_ge_sum_lines(self, payslips, code):
        return payslips._get_line_values([code], compute_sum=True)[code]['sum']['total']

    # -------------------------------------------------------------------------
    # Wage
    # -------------------------------------------------------------------------

    def _l10n_ge_get_month_hours(self):
        """Hours of a month of the working schedule: the weekly hours x 52 / 12. The law sets no divisor."""
        self.ensure_one()
        calendar = self.version_id.resource_calendar_id
        weekly_hours = calendar.hours_per_week if calendar and calendar.hours_per_week else self._rule_parameter('l10n_ge_weekly_hours')
        return weekly_hours * 52 / 12

    def _l10n_ge_get_monthly_pay(self, fixed_pay):
        """Fixed monthly pay of the contract: the wage and the regular allowances. Base of the severance."""
        self.ensure_one()
        version = self.version_id
        if version.wage_type == 'hourly':
            return version.hourly_wage * self._l10n_ge_get_month_hours() + fixed_pay
        return version.wage + fixed_pay

    # -------------------------------------------------------------------------
    # Funded pension
    # -------------------------------------------------------------------------

    def _l10n_ge_is_pension_due(self):
        """The employer withholds 2% and pays 2% for the participants of the funded pension scheme. The resident
        employees of an employer that does not withhold the income tax pay 4% themselves (Law on Funded Pensions,
        art. 2(j.c) and 3(6))."""
        self.ensure_one()
        version = self.version_id
        return version.l10n_ge_pension_status == 'participant' and self.company_id.l10n_ge_tax_regime != 'fiz'

    def _l10n_ge_compute_state_pension(self, base):
        """Contribution of the State on the salary of the calendar year, for information: 2% of the first GEL
        24,000 and 1% up to GEL 60,000 (Law on Funded Pensions, art. 3(6)(e) and (f)). Computed on the salary paid
        by this employer only."""
        self.ensure_one()
        year_to_date = self._l10n_ge_sum_lines(self._l10n_ge_get_year_payslips(), 'TAXABLE')
        amount = 0.0
        lower_bound = 0.0
        for upper_bound, rate in self._rule_parameter('l10n_ge_pension_state_bands'):
            upper_bound = self._l10n_ge_from_gel(upper_bound) if upper_bound is not None else None
            start = max(year_to_date, lower_bound)
            end = year_to_date + base if upper_bound is None else min(year_to_date + base, upper_bound)
            amount += max(end - start, 0.0) * rate / 100
            if upper_bound is None:
                break
            lower_bound = upper_bound
        return amount

    # -------------------------------------------------------------------------
    # Personal income tax
    # -------------------------------------------------------------------------

    def _l10n_ge_get_pit_rate(self):
        """Rate of the tax regime of the company (Tax Code, art. 23(7) and 81(1); Law on Innovations, art. 15^3
        and 15^7). The salary of an innovative start-up above the monthly exempt amount is taxed at the standard
        rate."""
        self.ensure_one()
        rates = self._rule_parameter('l10n_ge_pit_rates')
        regime = self.company_id.l10n_ge_tax_regime
        if regime == 'startup_1':
            return rates['standard']
        if regime not in rates:
            raise UserError(self.env._(
                "The income tax regime of %(company)s does not exist on %(date)s.",
                company=self.company_id.name, date=self.date_to))
        return rates[regime]

    def _l10n_ge_get_pit_base(self, taxable, pension):
        """Income taxed before the annual privilege: the salary less the employee pension contribution (Tax Code,
        art. 82(1)(b3); Instruction on Tax Administration, art. 38(7)), and less the salary exempt up to GEL 10,000
        a month in the first 3 years of an innovative start-up (Government Resolution No. 424 of 2025, art. 9)."""
        self.ensure_one()
        base = taxable - pension
        if self.company_id.l10n_ge_tax_regime == 'startup_1':
            base -= min(taxable, self._l10n_ge_from_gel(self._rule_parameter('l10n_ge_pit_startup_cap')))
        return max(base, 0.0)

    def _l10n_ge_get_privilege_used(self):
        """Part of the annual privilege used by the validated payslips of the calendar year: what their income tax
        line did not tax, the base of the line being the income after the privilege."""
        self.ensure_one()
        payslips = self._l10n_ge_get_year_payslips()
        line_values = payslips._get_line_values(['TAXABLE', 'PENSION_EE', 'PIT'], vals_list=['total', 'amount'])
        return sum(
            self._l10n_ge_get_pit_base(
                line_values['TAXABLE'][payslip.id]['total'],
                -line_values['PENSION_EE'][payslip.id]['total'],
            ) - line_values['PIT'][payslip.id]['amount']
            for payslip in payslips
        )

    def _l10n_ge_compute_privilege(self, taxable, pension):
        """Part of the annual privilege used by the period: the taxable income of the calendar year up to GEL 3,000
        or 6,000 is not taxed (Tax Code, art. 82(2)), applied cumulatively from 1 January at one employer, after
        the amount used at a previous employer in the year of the hiring (Instruction on Tax Administration,
        art. 39^1). The privilege is consumed by the income after the pension contribution."""
        self.ensure_one()
        version = self.version_id
        if version.l10n_ge_tax_privilege == 'none' or self.company_id.l10n_ge_tax_regime == 'fiz':
            return 0.0
        annual = self._l10n_ge_from_gel(self._rule_parameter('l10n_ge_pit_privileges')[version.l10n_ge_tax_privilege])
        used = self._l10n_ge_get_privilege_used()
        start = version.contract_date_start or version.date_version
        if start and start.year == self.date_to.year:
            used += version.l10n_ge_privilege_used
        return max(min(self._l10n_ge_get_pit_base(taxable, pension), annual - used), 0.0)

    def _l10n_ge_get_pit_taxable_base(self, taxable, pension):
        """Income taxed at source on the payment: payment - pension contribution - privilege (Tax Code, art. 154;
        Instruction on Tax Administration, art. 38(7)(i))."""
        self.ensure_one()
        privilege = self._l10n_ge_compute_privilege(taxable, pension)
        return max(self._l10n_ge_get_pit_base(taxable, pension) - privilege, 0.0)

    # -------------------------------------------------------------------------
    # Termination and deductions
    # -------------------------------------------------------------------------

    def _l10n_ge_get_departure(self):
        """Departure of the employee ending the contract in the period of the payslip."""
        self.ensure_one()
        departure = self.version_id.departure_id
        if departure.departure_date and self.date_from <= departure.departure_date <= self.date_to:
            return departure
        return self.env['hr.employee.departure']

    def _l10n_ge_get_severance_months(self):
        """Severance of an employer termination on economic grounds, unsuitability, long incapacity or another
        objective ground: 1 month of remuneration with at least 30 days' notice, 2 months with a shorter notice
        (Labour Code, art. 48(1) and (2))."""
        self.ensure_one()
        departure = self._l10n_ge_get_departure()
        if not departure.departure_reason_id.l10n_ge_severance:
            return 0
        months = self._rule_parameter('l10n_ge_severance_months')
        return months['short_notice' if departure.l10n_ge_short_notice else 'notice']

    def _l10n_ge_get_unused_leave_days(self):
        """Days of annual leave allocated and neither taken nor expired on the departure date, paid to the employee
        (Labour Code, art. 31(5)). The time-off type of the annual leave is set in the payroll settings."""
        self.ensure_one()
        departure = self._l10n_ge_get_departure()
        leave_type = self.company_id.l10n_ge_annual_leave_type_id
        if not departure or not leave_type:
            return 0.0
        employee = self.employee_id
        allocation_data = leave_type.with_company(self.company_id).get_allocation_data(employee, target_date=departure.departure_date)
        remaining = allocation_data[employee][0][1]['remaining_leaves'] if allocation_data.get(employee) else 0.0
        if leave_type.unit_of_measure == 'hour':
            calendar = self.version_id.resource_calendar_id or self.company_id.resource_calendar_id
            remaining /= calendar.hours_per_day or 8.0
        return max(remaining, 0.0)

    def _l10n_ge_get_leave_daily_wage(self, fixed_pay):
        """Pay of a day of annual leave: the total wage of the previous month divided by its working days
        (Labour Code, art. 36). The fixed monthly pay of the contract is used without a payslip the previous
        month."""
        self.ensure_one()
        month_start = self.date_from.replace(day=1) - relativedelta(months=1)
        month_end = month_start + relativedelta(months=1, days=-1)
        previous_payslips = self.env['hr.payslip'].search([
            ('id', '!=', self.id),
            ('employee_id', '=', self.employee_id.id),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['validated', 'paid']),
            ('date_from', '>=', month_start),
            ('date_to', '<=', month_end),
        ])
        if previous_payslips:
            monthly_wage = self._l10n_ge_sum_lines(previous_payslips, 'GROSS')
        else:
            monthly_wage = self._l10n_ge_get_monthly_pay(fixed_pay)
        calendar = self.version_id.resource_calendar_id or self.company_id.resource_calendar_id
        working_days = calendar.get_work_duration_data(
            datetime.combine(month_start, time.min), datetime.combine(month_end, time.max), compute_leaves=False)['days']
        return monthly_wage / working_days if working_days else 0.0

    def _l10n_ge_get_deduction_room(self, code, categories, result_rules):
        """Amount the recovery can still take: the sums owed by the employee are deducted within 50% of the
        remuneration (Labour Code, art. 43), applied to the net pay of the period before them."""
        self.ensure_one()
        already_deducted = -sum(
            result_rules[deduction_code]['total']
            for deduction_code in L10N_GE_CAPPED_DEDUCTION_CODES[:L10N_GE_CAPPED_DEDUCTION_CODES.index(code)]
        )
        net_before = categories['GE_REMUNERATION_BASE'] + already_deducted
        cap = net_before * self._rule_parameter('l10n_ge_deduction_cap') / 100
        return max(min(cap - already_deducted, categories['GE_REMUNERATION_BASE']), 0.0)

    # -------------------------------------------------------------------------
    # Tax borne by the employer
    # -------------------------------------------------------------------------

    def _get_payslip_lines(self, force_categories_by_code=None):
        net_payslips = self.filtered(lambda payslip: payslip.country_code == 'GE' and payslip.version_id.l10n_ge_net_salary)
        res = super(HrPayslip, self - net_payslips)._get_payslip_lines(force_categories_by_code=force_categories_by_code)
        for payslip in net_payslips:
            res.extend(payslip._l10n_ge_get_grossed_up_payslip_lines(force_categories_by_code=force_categories_by_code))
        return res

    def _l10n_ge_get_grossed_up_payslip_lines(self, force_categories_by_code=None):
        """The GROSS_UP line must cover exactly the income tax and the employee pension contribution borne by the
        employer. What the employer pays is itself salary income (Tax Code, art. 73(4)), so the computation is
        repeated with the amounts of the previous iteration as gross-up until they are stable: they grow by
        2% + 20% x 98% of the gross-up, so the iteration converges."""
        self.ensure_one()
        gross_up = tax = 0.0
        for _iteration in range(50):
            lines = super(HrPayslip, self.with_context(l10n_ge_gross_up=gross_up))._get_payslip_lines(
                force_categories_by_code=force_categories_by_code)
            tax = -sum(line['total'] for line in lines if line['code'] in L10N_GE_GROSS_UP_CODES)
            if float_is_zero(tax - gross_up, precision_digits=6):
                return lines
            gross_up = tax
        if float_is_zero(tax - gross_up, precision_rounding=self.currency_id.rounding or 0.01):
            return lines
        raise UserError(self.env._(
            "The income tax and pension of %(employee)s borne by the employer could not be grossed up, check the salary rules of the structure.",
            employee=self.employee_id.name))
