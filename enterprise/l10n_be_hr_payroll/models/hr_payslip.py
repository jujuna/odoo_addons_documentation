# Part of Odoo. See LICENSE file for full copyright and licensing details.

from calendar import monthrange, isleap
from collections import defaultdict, Counter
from datetime import date, datetime, time, timedelta, UTC
from zoneinfo import ZoneInfo
import math

from dateutil import rrule
from dateutil.relativedelta import relativedelta, MO, SU

from odoo import api, models, fields, Command
from odoo.tools import date_utils, float_compare, float_round, float_is_zero, pdf, single_email_re
from odoo.tools.safe_eval import expr_eval
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.misc import frozendict
from odoo.tools.intervals import Intervals
from odoo.addons.l10n_be_hr_payroll.models.hr_version import BIK_RULE_PARAMETERS
from odoo.addons.l10n_be_hr_payroll.models.hr_employee_departure import EMPLOYER_NOTICE_REASON_CODES, RESIGNATION_REASON_CODES


from odoo.addons.l10n_be_hr_payroll.models.utils import round_eurocent

# The premiums of the variable remuneration of the double holiday pay, on top of the variable revenues
DOUBLE_HOLIDAY_VARIABLE_PREMIUM_CODES = ('PREMSUN', 'PREMHOL')


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Company Car',
        compute='_compute_vehicle_id', store=True, readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")

    l10n_be_is_double_pay = fields.Boolean(compute='_compute_l10n_be_is_double_pay')
    l10n_be_is_december = fields.Boolean(compute='_compute_l10n_be_is_december')
    l10n_be_joint_committee_id = fields.Many2one(related='version_id.l10n_be_joint_committee_id')
    l10n_be_effective_marital = fields.Selection(
        selection=lambda self: self.env['hr.version']._get_marital_status_selection(), compute="_compute_effective_marital")
    l10n_be_meal_vouchers_report_id = fields.Many2one('l10n_be.meal.vouchers.report', index=True, readonly=True, copy=False)
    l10n_be_sum_additional_hours = fields.Float(compute='_compute_l10n_additional_hours_checks', store=True)
    l10n_be_wrong_additional_hours_on_sundays_or_public_holidays = fields.Boolean(compute='_compute_l10n_additional_hours_checks', store=True)
    l10n_be_working_hours_limit_per_day_exceeded = fields.Boolean(compute='_compute_l10n_additional_hours_checks', store=True)
    l10n_be_working_hours_limit_per_week_exceeded = fields.Boolean(compute='_compute_l10n_additional_hours_checks', store=True)
    l10n_be_additional_hours_during_working_time = fields.Boolean(compute='_compute_l10n_additional_hours_checks', store=True)
    l10n_be_arrear_salary = fields.Boolean(string="Arrears Salary", help="Employee's remuneration that is paid or awarded late due to a public authority's default, negligence, or exceptional measure, or because of a dispute between the employer and the worker.")
    l10n_be_is_arrear_eligible = fields.Boolean(compute='_compute_l10n_be_is_arrear_eligible')
    l10n_be_needs_flxwage_declaration = fields.Boolean(related='version_id.l10n_be_needs_flxwage_declaration', store=True)
    l10n_be_flexi_declaration_id = fields.One2many('l10n.be.flexi.at.work', 'payslip_id', string="Flexi@Work", readonly=True)
    l10n_be_273_line_ids = fields.One2many('l10n_be.273_xx.line', 'payslip_id', copy=False)
    l10n_be_281_xx_ids = fields.Many2many('l10n_be.281_xx', 'l10n_be_281_xx_hr_payslip_rel', 'payslip_id', 'l10n_be_281_xx_id')
    l10n_be_onss_contribution = fields.Monetary(compute='_compute_line_values_dependent_fields', string='NSSO')
    l10n_be_withholding_taxes = fields.Monetary(compute='_compute_line_values_dependent_fields', string='Withholding Taxes')
    l10n_be_is_reported = fields.Boolean(compute='_compute_l10n_be_is_reported', help="Indicates whether this payslip is declared in any finalized Belgian declaration report (e.g. 273.XX).")
    l10n_be_is_dmfa_reported = fields.Boolean()
    l10n_be_dmfa_id = fields.Many2one('l10n_be.dmfa', string='DMFA Report', index=True, readonly=True)
    l10n_be_274_xx_ids = fields.Many2many(
        'l10n_be.274_xx', 'l10n_be_274_xx_hr_payslip_rel', 'payslip_id', 'sheet_id',
        string="274.XX Sheets", copy=False)
    l10n_be_fiscal_date = fields.Date(
        string="Fiscal Date", compute='_compute_l10n_be_fiscal_date', store=True, readonly=False, copy=False,
        help="Period this payslip must be fiscally attached to. It defaults to the pay period, and is "
             "deferred to the confirmation date for remunerations paid late, either because they are "
             "arrears or because their pay period has already been declared.")

    def _get_basic_wage_line_codes(self):
        codes = super()._get_basic_wage_line_codes()
        return codes | {'BASIC', 'BONUS_BASIC', 'DH_BASIC', 'WARRANT_BASIC', 'TERM_BASIC'}

    def _get_salary_wage_line_codes(self):
        return {'SALARY', 'BONUS_SALARY', 'DH_SALARY', 'TERM_SALARY', 'PAY_SIMPLE', 'WARRANT_SALARY'}

    def _get_onss_line_codes(self):
        return {'ONSS', 'ONSS_SOLIDARITY_BONUS', 'ONSS_BONUS', 'ONSS_DOUBLE_HOLIDAY', 'ONSS_TERM', 'ONSS_HOLIDAY_TERM_SIMPLE', 'ONSS_HOLIDAY_TERM_DOUBLE', 'WARRANT_ONSS'}

    def _get_gross_wage_line_codes(self):
        codes = super()._get_gross_wage_line_codes()
        return codes | {'GROSS', 'GROSS_NP', 'BONUS_GROSS', 'DH_GROSS', 'WARRANT_GROSS', 'TERM_GROSS', 'HOLIDAY_TERM_GROSS'}

    def _get_total_basic_wage_without_double_holiday(self):
        basic_codes = self._get_basic_wage_line_codes() - {'DH_BASIC'}
        line_values = self._get_line_values(basic_codes, compute_sum=True)
        return sum(line_values[code]['sum']['total'] for code in basic_codes)

    @api.depends('employee_id', 'date_from', 'date_to', 'version_id.car_id.future_driver_id')
    def _compute_vehicle_id(self):
        for slip in self.filtered(lambda s: s.state not in ['validated', 'cancel']):
            contract_sudo = slip.version_id.sudo()
            car = contract_sudo.car_id
            if slip.employee_id and slip.date_from and slip.date_to:
                # a car changed during the period: the payslip takes the car of the most calendar days (the new
                # one on a tie), which owes the CO2 contribution of the month
                days_by_car = defaultdict(float)
                versions_sudo = contract_sudo.browse(slip._get_period_contracts())
                for version in versions_sudo.filtered('car_id'):
                    days_by_car[version.car_id] += slip._get_be_contract_days_in_payslip_range_prorata(
                        version.date_start, version.date_end)
                if days_by_car:
                    car = max(reversed(days_by_car), key=days_by_car.get)
            if car:
                future_driver = car.future_driver_id
                if future_driver and future_driver == slip.employee_id.work_contact_id:
                    tmp_vehicle = self.env['fleet.vehicle'].search(
                        [('driver_id', '=', future_driver.id)], limit=1)
                    slip.vehicle_id = tmp_vehicle
                else:
                    slip.vehicle_id = car
            else:
                slip.vehicle_id = False

    @api.depends('employee_id', 'version_id', 'struct_id', 'date_from', 'date_to')
    def _compute_input_line_ids(self):
        res = super()._compute_input_line_ids()
        balance_by_employee = self._get_salary_advance_balances()
        mobility_payment_by_slip = self._get_l10n_be_mobility_amounts()

        for slip in self:
            if not slip.employee_id or not slip.date_from or not slip.date_to or slip.country_code != 'BE':
                continue
            # Collect the BE-specific input amounts by code, then materialise them
            # in a single write (same pattern as the base _compute_input_line_ids)
            # rather than one self.update per value.
            amount_by_code = {}
            # If a double holiday pay should be recovered
            if slip.struct_id.code == 'BEDOUBLE':
                amount_by_code['EU_LEAVE_DEDUC'] = slip._get_sum_european_time_off_days()
                amount_by_code['DOUBLERECOVERY'] = slip._get_double_pay_to_recover()
            elif slip.struct_id.code == 'BEMONTHLY':
                # the December settlement of the holiday pay concerns all the employees (not the workers, whose
                # holiday pay is paid by a holiday fund, nor the flexi-jobs, whose wage includes it)
                # (not in a salary simulation of an employee not saved yet: no payslip of the year to settle)
                if slip.l10n_be_is_december and slip.employee_id.id and not slip.version_id.is_worker() \
                        and not slip.version_id.is_flexi():
                    december_regularization = slip._l10n_be_get_december_holiday_regularization()
                    amount_by_code['SIMPLE_DECEMBER'] = slip.currency_id.round(december_regularization.get('simple', 0))
                    if slip.version_id.filtered_domain(self.env['hr.version']._l10n_be_get_double_holiday_pay_domain()):
                        amount_by_code['DOUBLE_DECEMBER_BASIC'] = slip.currency_id.round(december_regularization.get('double', 0))
                if (
                    slip.version_id.fuel_card_personal_use
                    and slip.version_id.fuel_card
                    and not slip.version_id.car_id
                    and not slip.version_id.l10n_be_mobility_budget
                ):
                    amount_by_code['FUEL_CARD_PRIV'] = slip.version_id.fuel_card_personal_use
                balance = (
                    balance_by_employee[slip.employee_id]["SALARYADVREC"]
                    + balance_by_employee[slip.employee_id]["SALARYADV"]
                )
                if balance > 0:
                    amount_by_code['SALARYADVREC'] = balance
                if (slip.l10n_be_is_december or slip._is_last_monthly_payslip()) and slip in mobility_payment_by_slip:
                    mobility_remaining = mobility_payment_by_slip[slip]['MOBILITY_REMAINING']
                    mobility_remaining -= sum(slip.input_line_ids.filtered(lambda l: l.code == 'MOBILITY_TO_PAY').mapped('amount'))
                    amount_by_code['MOBILITY_PAYMENT'] = max(0.0, mobility_remaining)

            # CCT90BONUSPLAN (BECCT90 structure) is entered manually via the payslip inputs section.
            # This BE-specific compute has no amount to contribute for it, so it stays untouched here.
            auto_input_codes = {'EU_LEAVE_DEDUC', 'DOUBLERECOVERY', 'SIMPLE_DECEMBER', 'DOUBLE_DECEMBER_BASIC', 'FUEL_CARD_PRIV', 'SALARYADVREC', 'MOBILITY_PAYMENT'}
            rules_by_code = {rule.code: rule for rule in slip.struct_id.rule_ids}
            input_line_vals = [
                Command.unlink(line.id)
                for line in slip.input_line_ids
                if line.code in auto_input_codes
            ]
            allow_zero_input_codes = {'MOBILITY_PAYMENT'}
            for code, amount in amount_by_code.items():
                rule = rules_by_code.get(code)
                if not rule or (not amount and code not in allow_zero_input_codes):
                    continue
                input_line_vals.append(Command.create({
                    'salary_rule_id': rule.id,
                    'amount': amount,
                }))
            if input_line_vals:
                slip.update({'input_line_ids': input_line_vals})
        return res

    @api.depends('date_from')
    def _compute_l10n_be_is_arrear_eligible(self):
        current_year = fields.Date.context_today(self).year
        for slip in self:
            slip.l10n_be_is_arrear_eligible = bool(slip.date_from) and current_year > slip.date_from.year

    @api.depends('l10n_be_273_line_ids.sheet_id.state', 'l10n_be_281_xx_ids.state')
    def _compute_l10n_be_is_reported(self):
        for payslip in self:
            payslip.l10n_be_is_reported = (
                any(report.state in ['ready', 'done'] for report in payslip.l10n_be_273_line_ids.sheet_id) or
                any(report.state in ['ready', 'done'] for report in payslip.l10n_be_281_xx_ids)
            )

    @api.depends('date_to')
    def _compute_l10n_be_fiscal_date(self):
        # A remuneration is fiscally attached to its pay period until it turns out to be paid
        # late, in which case the deferral happens on confirmation. See _l10n_be_defer_fiscal_date.
        for payslip in self:
            payslip.l10n_be_fiscal_date = payslip.date_to

    def _get_gross_wage_base_categories(self):
        """Salary rule category each gross wage code totals.

        A declaration adds the base up itself instead of reading the aggregate line, so it needs
        to know which category that line totals. Kept per code, because a rule may belong to two
        bases at once (the holiday pay regularization, the European leaves deduction): a payslip
        counts it in the base of the aggregate line of its structure only, see
        :meth:`_l10n_be_get_gross_wage_base_values`.
        """
        return {
            'GROSS': 'WITHHOLDING_BASE',
            'GROSS_NP': 'YEARLY_WITHHOLDING_BASE',
            'BONUS_GROSS': 'BONUS_WITHHOLDING_BASE',
            'DH_GROSS': 'DH_WITHHOLDING_BASE',
            'WARRANT_GROSS': 'WARRANT_WITHHOLDING_BASE',
            'TERM_GROSS': 'TERMINATION_WITHHOLDING_BASE',
            'HOLIDAY_TERM_GROSS': 'TERMINATION_HOLIDAY_WITHHOLDING_BASE',
        }

    def _l10n_be_get_gross_wage_base_values(self, date_from, date_to):
        """Rebuild per payslip the taxable salary that belongs to [date_from, date_to], by gross wage code.

        A base only counts for the payslips whose structure computes its aggregate line: a rule
        belonging to two bases is part of the taxable salary of its payslip once, in the base its
        structure totals.

        :return: {gross wage code: {payslip id: amount}}
        """
        gross_codes = self._get_gross_wage_line_codes()
        structure_codes = {structure: set(structure.rule_ids.mapped('code')) for structure in self.struct_id}
        base_values = {}
        for code, category_code in self._get_gross_wage_base_categories().items():
            if code not in gross_codes:
                continue
            payslips = self.filtered(lambda p: code in structure_codes.get(p.struct_id, ()))
            base_values[code] = payslips._l10n_be_get_declaration_base(category_code, date_from, date_to)
        return base_values

    def _l10n_be_get_declaration_base(self, category_code, date_from, date_to):
        """Rebuild per payslip the amounts of a base that belong to [date_from, date_to].

        A declaration cannot add up the aggregate line that displays a base: the aggregate carries
        a single period attachment, while the amounts inside it each follow their own. So the base
        is rebuilt from the two sources the payslip computation accumulates it from, the payslip
        lines and the worked day amounts, each tagged with the category or one of its children.

        The payslip lines follow their own attachment. The worked days have none of their own:
        they are the remuneration of the period being paid, so they follow their payslip.
        """
        result = defaultdict(float)
        category_codes = list(self._get_child_category_ids(category_code))
        if not self or not category_codes:
            return result
        # Same lines as the domain ('salary_rule_id.category_ids.code', 'in', category_codes) &
        # _l10n_be_get_fiscal_line_domain(date_from, date_to), but only on the columns of the lines:
        # with the joins on the rules, their categories and the payslips, outdated statistics lead
        # the planner to go through all the lines for each payslip (seconds per query).
        rules = self.env['hr.salary.rule'].search([
            ('category_ids.code', 'in', category_codes),
            ('active', 'in', (True, False)),  # the rules of the lines, archived or not
        ])
        fiscal_period_payslips = self.filtered(
            lambda p: p.l10n_be_fiscal_date and date_from <= p.l10n_be_fiscal_date <= date_to)
        pay_period_payslips = self.filtered(
            lambda p: p.date_from and p.date_to and p.date_from >= date_from and p.date_to <= date_to)
        lines = Domain([
            ('slip_id', 'in', self.ids),
            ('salary_rule_id', 'in', rules.ids),
        ]) & (
            Domain([('l10n_be_follow_pay_period', '=', False), ('slip_id', 'in', fiscal_period_payslips.ids)])
            | Domain([('l10n_be_follow_pay_period', '=', True), ('slip_id', 'in', pay_period_payslips.ids)])
        )
        for payslip, total in self.env['hr.payslip.line']._read_group(lines, ['slip_id'], ['total:sum']):
            result[payslip.id] += total or 0.0

        attached_payslips = self._l10n_be_get_attached_worked_days(date_from, date_to).payslip_id
        if attached_payslips:
            worked_days = Domain([
                ('payslip_id', 'in', attached_payslips.ids),
                ('work_entry_type_id.category_ids.code', 'in', category_codes),
            ])
            for payslip, amount in self.env['hr.payslip.worked_days']._read_group(worked_days, ['payslip_id'], ['amount:sum']):
                result[payslip.id] += amount or 0.0
        return result

    def _l10n_be_get_attached_worked_days(self, date_from, date_to):
        """Worked days a fiscal declaration covering [date_from, date_to] must add up.

        The worked days have no attachment of their own: they are the remuneration of the period
        being paid, so they follow the fiscal date of their payslip. A payslip of the pay period
        whose fiscal date was deferred to the next period is declared there, its worked days too.
        """
        return self.filtered(
            lambda p: not p.ignore_worked_day_lines and p.l10n_be_fiscal_date
            and date_from <= p.l10n_be_fiscal_date <= date_to).worked_days_line_ids

    @api.model
    def _l10n_be_get_fiscal_period_domain(self, date_from, date_to):
        """Payslips a fiscal declaration covering [date_from, date_to] must take into account:
        those attached to it by their fiscal date, and those attached to it by their pay period.

        Nothing here keeps a payslip out of a declaration that already reported it: a payslip
        belongs to a single period per declaration stream, and it is its fiscal date that moves
        when its own pay period is closed. Each report family excludes its own finalized
        declarations where it needs to, which the annual recaps deliberately do not.
        """
        fiscal_period = Domain([
            ('l10n_be_fiscal_date', '>=', date_from),
            ('l10n_be_fiscal_date', '<=', date_to),
        ])
        pay_period = Domain([
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
        ])
        return fiscal_period | pay_period

    def _l10n_be_filter_declared_withholding_taxes(self):
        """Payslips the withholding tax declarations (274, 281) declare as taxed.

        The versions without withholding taxes are left out (e.g. the cross-border workers, taxed abroad), but the
        students: their taxable remuneration is declared, with a withholding tax of 0.
        """
        return self.filtered(lambda p: not p.version_id.no_withholding_taxes or p.version_id.is_student())

    def _l10n_be_filter_economic_unemployment(self):
        # Read from the worked days instead of loading every worked day line of every payslip
        payslip_ids = {payslip.id for payslip, in self.env['hr.payslip.worked_days']._read_group(
            [('payslip_id', 'in', self.ids), ('work_entry_type_id.l10n_be_economic_unemployment', '=', True)],
            ['payslip_id'],
        )}
        return self.filtered(lambda payslip: payslip.id in payslip_ids)

    @api.model
    def _l10n_be_get_overtime_category(self):
        # The category of the work entry types of the overtime giving right to the legal overtime premium,
        # voluntary overtime and overtime to recover included, for the 274.44/274.55 exemptions and the box 18 of
        # the 281.10. Overtime to recover gives right to its premium as well: its pay is the premium, the base hours
        # are paid when they are recovered. A part-timer's additional hours paid with an overtime premium of 50% or
        # 100% (003.12, 003.08) give right to it too, as the social secretariat declares them (box 18 of the 281.10,
        # 274.55 exemption). A copy of these work entry types keeps the category.
        # Called for each payslip from its salary rules: the id is cached, env.ref would check its existence.
        return self.env['hr.salary.rule.category'].browse(
            self.env['ir.model.data']._xmlid_to_res_id('l10n_be_hr_payroll.OVERTIME_TAX_RELIEF'))

    @api.model
    def _l10n_be_get_overtime_joint_committee(self, version):
        """ The joint committee of the yearly cap of the overtime with a reduced tax burden (274.44 for the joint
        committee 200, 274.55 for the 302): the one of the payslip's version, as in the 281.10, the employee may
        have changed of joint committee during the year. The hotel industry has its own cap, all the other employers
        the one of the CP 200. The company directors (CP 999 or under an employment contract) have no overtime.

        :return: '200', '302' or False (no reduced tax burden)
        """
        jc = version.l10n_be_joint_committee_id
        if version._l10n_be_is_company_director():
            return False
        # Called for each payslip: the id is cached, env.ref would check its existence.
        cp302 = self.env['l10n.be.joint.committee'].browse(
            self.env['ir.model.data']._xmlid_to_res_id('l10n_be_hr_payroll.l10n_be_joint_committee_302'))
        if jc and jc.is_descendant_of(cp302):
            return '302'
        return '200'

    @api.model
    def _l10n_be_get_overtime_cap(self, joint_committee, company, target_date, raise_if_not_found=True):
        """ The yearly cap of overtime hours with a reduced tax burden of a joint committee ('200' or '302', see
        _l10n_be_get_overtime_joint_committee). The registered cash system of the hotel industry raises it. """
        if joint_committee == '200':
            code = 'cp200_overtime_threshold'
        elif company._l10n_be_has_white_cash_register():
            code = 'cp302_overtime_threshold_white_cash_register'
        else:
            code = 'cp302_overtime_threshold_not_white_cash_register'
        return self.env['hr.rule.parameter']._get_parameter_from_code(code, target_date, raise_if_not_found=raise_if_not_found)

    def _l10n_be_get_overtime_hours_consumed(self, company, date_start):
        """ The part of the yearly caps of overtime with a reduced tax burden already consumed before date_start by
        the employees of these payslips: the overtime of their validated or paid payslips of the year, by joint
        committee of the payslip. The cap is per employer: the company and all its branches.

        :return: defaultdict {(employee, joint committee): hours}
        """
        worked_days_groups = self.env['hr.payslip.worked_days']._read_group(
            domain=[
                ('payslip_id.state', 'in', ['paid', 'validated']),
                ('payslip_id.company_id', 'child_of', company.root_id.id),
                ('payslip_id.date_from', '>=', date(date_start.year, 1, 1)),
                ('payslip_id.date_to', '<', date_start),
                ('payslip_id.employee_id', 'in', self.employee_id.ids),
                ('work_entry_type_id.category_ids', 'in', self._l10n_be_get_overtime_category().ids),
            ],
            groupby=['payslip_id.employee_id', 'payslip_id.version_id', 'work_entry_type_id'],
            aggregates=['number_of_hours:sum'],
        )
        consumed_by_employee_jc = defaultdict(float)
        for employee, version, work_entry_type, hours in worked_days_groups:
            # the overtime paid without premium consumes no cap (see _is_extra_hours_qualifying)
            if self._is_extra_hours_qualifying(work_entry_type):
                consumed_by_employee_jc[employee, self._l10n_be_get_overtime_joint_committee(version)] += hours
        return consumed_by_employee_jc

    def _l10n_be_get_complementary_indemnity_warning(self):
        """The complementary indemnities of the bridging pensions (RCC: worker code 879) and of the dismissed or
        career break workers (RCIC: 883, 885) are declared on the 281.17 and the 281.18, with their own withholding
        tax, which Odoo doesn't compute: paid by a payslip, they are declared as remuneration (274.10, 281.10).

        :return: the warning on the declarations of these payslips, False without such payslip
        """
        employees = self.filtered(
            lambda p: p.version_id.l10n_be_worker_code_id.dmfa_code in ('879', '883', '885')).employee_id
        if not employees:
            return False
        return self.env._(
            "The complementary indemnities (RCC, RCIC: worker codes 879, 883, 885) are declared on the 281.17 or "
            "the 281.18, which Odoo doesn't do: they are declared here as remuneration. Declare them through your "
            "social secretariat and correct the declarations of: %(names)s",
            names=", ".join(employees.mapped('name')),
        )

    def _l10n_be_filter_remuneration_form(self, form):
        """Payslips whose remunerations are declared on the 281.10 (employees), 281.20 (company directors) or
        281.30 (other directors), and their withholding taxes on the 274.10, 274.20 or 274.30."""
        def get_form(payslip):
            # The presence tokens of a company director are director remunerations (281.20), whatever the flag. A
            # director under an employment contract is declared on the 281.20 too (attraction principle).
            if payslip.version_id._l10n_be_is_company_director():
                return '281.20'
            return '281.30' if payslip.version_id.l10n_be_include_employee_in_281_30 else '281.10'
        return self.filtered(lambda payslip: get_form(payslip) == form)

    def _l10n_be_get_professional_fees_joint_committee_code(self):
        """The joint committee whose flat-rate professional fees apply: the ones of the company directors (999) for a
        director under an employment contract, whose remunerations are director remunerations."""
        self.ensure_one()
        if self.version_id._l10n_be_is_director_under_employment_contract():
            return '999'
        return self.l10n_be_joint_committee_id.egov3_code or '200'

    @api.model
    def _l10n_be_get_fiscal_line_domain(self, date_from, date_to):
        """Payslip lines a fiscal declaration covering [date_from, date_to] must add up.

        Both halves of the declaration period are covered: the amounts following the fiscal
        period of their payslip, and the amounts staying attached to its pay period.
        """
        fiscal_period = Domain([
            ('l10n_be_follow_pay_period', '=', False),
            ('slip_id.l10n_be_fiscal_date', '>=', date_from),
            ('slip_id.l10n_be_fiscal_date', '<=', date_to),
        ])
        pay_period = Domain([
            ('l10n_be_follow_pay_period', '=', True),
            ('slip_id.date_from', '>=', date_from),
            ('slip_id.date_to', '<=', date_to),
        ])
        return fiscal_period | pay_period

    @api.depends('line_ids.total')
    def _compute_line_values_dependent_fields(self):
        all_line_values = self._get_line_values(['P.P', 'DH_PP', 'ONSS', 'ONSS_DOUBLE_HOLIDAY'], vals_list=['total'])
        for payslip in self:
            payslip.l10n_be_onss_contribution = -(all_line_values['ONSS'][payslip.id]['total'] + all_line_values['ONSS_DOUBLE_HOLIDAY'][payslip.id]['total'])
            payslip.l10n_be_withholding_taxes = -(all_line_values['P.P'][payslip.id]['total'] + all_line_values['DH_PP'][payslip.id]['total'])

    def _get_common_localdict(self):
        """
        Values put in this dict will be shared accross all of self's records so
        that they are only fetched once per batch, rather than once per payslip
        """
        common_localdict = super()._get_common_localdict()
        be_payslips = self.filtered(lambda p: p.struct_id.country_id.code == 'BE')
        if not be_payslips:
            return common_localdict

        def year_payslips_domain(payslip):
            return Domain([
                ('employee_id', '=', payslip.employee_id.id),
                ('date_to', '>=', date(payslip.date_to.year, 1, 1)),
                ('date_to', '<=', date(payslip.date_to.year, 12, 31)),
            ])

        def quarter_payslips_domain(payslip):
            quarter_start, quarter_end = date_utils.get_quarter(payslip.date_to)
            return Domain([
                ('employee_id', '=', payslip.employee_id.id),
                ('date_to', '>=', quarter_start),
                ('date_to', '<=', quarter_end),
            ])

        def month_payslips_domain(payslip):
            month_start = date(payslip.date_to.year, payslip.date_to.month, 1)
            month_end = month_start + relativedelta(months=1, days=-1)
            return Domain([
                ('employee_id', '=', payslip.employee_id.id),
                ('date_to', '>=', month_start),
                ('date_to', '<=', month_end),
            ])

        def previous_month_domain(payslip):
            prev_month = payslip.date_from + relativedelta(day=1, days=-1)
            return Domain([
                ('employee_id', '=', payslip.employee_id.id),
                ('date_to', '>=', prev_month.replace(day=1)),
                ('date_to', '<=', prev_month),
                ('state', 'in', ('validated', 'paid')),
            ])

        if self.env.context.get('salary_simulation'):
            # salary simluation should not be affected by other payslips
            all_year_payslips = self.env['hr.payslip']
        else:
            # all the keys reusing the year payslips care about validated/paid
            # payslips only
            all_year_payslips = self.search(Domain.OR([
                year_payslips_domain(be_payslip) for be_payslip in be_payslips
            ]) & Domain('state', 'in', ('validated', 'paid')))

        year_payslips_by_employee = all_year_payslips.grouped('employee_id')

        def payslips_line_values(line_values, payslips):
            result = defaultdict(lambda: defaultdict(lambda: {'total': 0.0}))
            for code, values_by_payslip in line_values.items():
                for payslip_id in payslips.ids:
                    if payslip_id in values_by_payslip:
                        total = values_by_payslip[payslip_id]['total']
                        result[code]['sum']['total'] += total
                        result[code][payslip_id]['total'] += total
            return result

        # use these keys to easily get self's validated/paid payslips during
        # self's current year/quarter/month
        common_localdict["l10n_be_year_payslips_by_payslip"] = {
            be_payslip: year_payslips_by_employee.get(be_payslip.employee_id, self.env["hr.payslip"]).filtered_domain(
                year_payslips_domain(be_payslip),
            )
            for be_payslip in be_payslips
        }
        common_localdict["l10n_be_quarter_payslips_by_payslip"] = {
            be_payslip: year_payslips_by_employee.get(be_payslip.employee_id, self.env["hr.payslip"]).filtered_domain(
                quarter_payslips_domain(be_payslip),
            )
            for be_payslip in be_payslips
        }
        common_localdict['l10n_be_month_payslips_by_payslip'] = {
            payslip: quarter_payslips.filtered_domain(month_payslips_domain(payslip))
            for payslip, quarter_payslips in common_localdict['l10n_be_quarter_payslips_by_payslip'].items()
        }

        wanted_line_codes = (
            'SALARY', 'BONUS_SALARY', 'EmpBonus.A', 'EmpBonus.B', 'EmpBonus.1', 'GROSS', 'P.P', 'P.P.DEDEH', 'P.P.DED',
            'EMP_BONUS_SALARY', 'SECTORIAL.BONUS', 'CANTEEN', 'EmpBonus.A.CO', 'EmpBonus.B.CO', 'EmpBonus.Total.CO',
        )
        month_payslips_by_payslip = common_localdict["l10n_be_month_payslips_by_payslip"]
        month_line_values = (
            self.env["hr.payslip"].union(month_payslips_by_payslip.values())._get_line_values(wanted_line_codes)
        )
        common_localdict['l10n_be_month_line_values_by_payslip'] = {
            payslip: payslips_line_values(month_line_values, month_payslips)
            for payslip, month_payslips in month_payslips_by_payslip.items()
        }

        all_month_exemption_payslips = self.search([
            ('date_to', '>=', min(be_payslips.mapped('date_from')) + relativedelta(day=1)),
            ('date_to', '<=', min(be_payslips.mapped('date_from')) + relativedelta(day=31)),
            ('struct_id.country_id.code', '=', 'BE'),
            '|',
                ('state', 'in', ('validated', 'paid')),
                '&',
                    ('state', 'in', ('draft')),
                    ('payslip_run_id', 'in', be_payslips.payslip_run_id.ids),
                    ('id', 'not in', be_payslips.ids)
        ])
        wanted_line_codes = (
            'WITHHOLDING_TAX_EX_274_32', 'WITHHOLDING_TAX_EX_274_33', 'WITHHOLDING_TAX_EX_274_34',
            "WITHHOLDING_TAX_EX_274_44", "WITHHOLDING_TAX_EX_274_55", "WITHHOLDING_TAX_EX_274_62", "WITHHOLDING_TAX_EX_274_81",
            'T_WITHHOLDING_TAX_EX_274_74', 'WITHHOLDING_TAX_EX_274_74', 'T_WITHHOLDING_TAX_EX_274_75', 'WITHHOLDING_TAX_EX_274_75', 'PPTOTAL',
        )
        common_localdict['l10n_be_exemptions_month_payslips'] = all_month_exemption_payslips
        common_localdict['l10n_be_exemptions_month_line_values'] = all_month_exemption_payslips._get_line_values(
            wanted_line_codes, compute_sum=True
        )

        prev_month_payslips_by_payslip = {
            payslip: year_payslips_by_employee.get(payslip.employee_id, self.env["hr.payslip"]).filtered_domain(
                previous_month_domain(payslip),
            )
            for payslip in be_payslips
        }
        prev_month_line_values = (
            self.env["hr.payslip"]
            .union(prev_month_payslips_by_payslip.values())
            ._get_line_values(["EmpBonus.A.CO", "EmpBonus.B.CO", "EmpBonus.Total.CO"])
        )
        common_localdict['l10n_be_prev_month_line_values_by_payslip'] = {
            payslip: payslips_line_values(prev_month_line_values, prev_month_payslips)
            for payslip, prev_month_payslips in prev_month_payslips_by_payslip.items()
        }

        # The transportation exemption is granted on the monthly total, whatever rule fed it
        common_localdict['l10n_be_month_transportation_base_by_payslip'] = {
            payslip: sum(month_payslips.line_ids.filtered(
                lambda line: 'TRANSPORTATION_BASE' in line.salary_rule_id.category_ids.mapped('code')
            ).mapped('total'))
            for payslip, month_payslips in common_localdict['l10n_be_month_payslips_by_payslip'].items()
        }

        # DPV optimization: prefetch previous year work entries once for the whole batch. Each payslip reads the
        # entries of its employee: only when the payslips are of the same year, else each one generates its own.
        be_dpv_payslips = be_payslips.filtered(lambda p: p.struct_id.code == "BEDOUBLE")
        entries_by_employee = defaultdict(list)
        if be_dpv_payslips and len({p.date_from.year for p in be_dpv_payslips}) == 1:
            year = be_dpv_payslips[0].date_from.year - 1
            date_from = date(year, 1, 1)
            date_to = date(year, 12, 31)
            previous_year_work_entries = be_dpv_payslips.employee_id.version_ids.filtered('resource_calendar_id').generate_work_entries(date_from, date_to)
            for entry in previous_year_work_entries:
                entries_by_employee[entry['employee_id']].append(entry)
        common_localdict['l10n_be_prev_year_work_entries'] = dict(entries_by_employee)

        work_hours_by_calendar_and_period = {}

        for payslip in self:
            ref_calendar = payslip.version_id._get_reference_calendar()
            # The number of expected work hours depends both on the calendar and on the period
            key = (ref_calendar, payslip.date_from, payslip.date_to)

            if key not in work_hours_by_calendar_and_period:
                work_hours_by_calendar_and_period[key] = ref_calendar.get_work_hours_count(payslip.date_from, payslip.date_to)

        common_localdict['work_hours_by_calendar_and_period'] = work_hours_by_calendar_and_period

        # Sectoral bonus optimization: prefetch the reference period work entries once for the whole batch
        be_sectorial_payslips = be_payslips.filtered(
            lambda p: p.struct_id.code == "BEMONTHLY" and p._is_cp200_annual_sectorial_bonus_eligible())
        sectorial_entries_by_employee = defaultdict(list)
        if be_sectorial_payslips:
            reference_periods = [p._get_cp200_annual_bonus_reference_period() for p in be_sectorial_payslips]
            ref_start = min(period[0] for period in reference_periods)
            ref_end = max(period[1] for period in reference_periods)
            sectorial_work_entries = be_sectorial_payslips.employee_id.version_ids.filtered('resource_calendar_id').generate_work_entries(ref_start, ref_end)
            for entry in sectorial_work_entries:
                sectorial_entries_by_employee[entry['employee_id']].append(entry)
        common_localdict['l10n_be_sectorial_bonus_work_entries'] = dict(sectorial_entries_by_employee)

        # Intellectual property: yearly IP of the validated/paid payslips, fetched once for the batch
        # (one grouped query): total of the current year (yearly limit, artist lump-sum costs) and
        # average of the 4 previous years (above the yearly limit, the IP is a regular remuneration)
        ip_payslips = be_payslips.filtered(lambda p: p.version_id.ip_wage_rate > 0)
        ip_totals_by_employee_year = defaultdict(float)
        ip_remuneration_by_employee_year = defaultdict(float)
        if ip_payslips and not self.env.context.get('salary_simulation'):
            years = {p.date_to.year for p in ip_payslips}
            for employee, year_start, total in self.env['hr.payslip.line']._read_group(
                [
                    ('employee_id', 'in', ip_payslips.employee_id.ids),
                    ('code', '=', 'IP'),
                    ('slip_id.state', 'in', ('validated', 'paid')),
                    ('date_to', '>=', date(min(years) - 4, 1, 1)),
                    ('date_to', '<=', date(max(years), 12, 31)),
                ],
                ['employee_id', 'date_to:year'],
                ['total:sum'],
            ):
                ip_totals_by_employee_year[employee.id, year_start.year] += total
            # The maximum share of the IP is assessed on the total remuneration of the taxable period (the year):
            # remuneration subject to ONSS, the IP exempt from it included, of the validated payslips of the year
            year_payslips = self.search([
                ('employee_id', 'in', ip_payslips.employee_id.ids),
                ('state', 'in', ('validated', 'paid')),
                ('date_to', '>=', date(min(years), 1, 1)),
                ('date_to', '<=', date(max(years), 12, 31)),
            ]) - self
            if year_payslips:
                onss_bases = year_payslips._l10n_be_get_declaration_base(
                    'ONSS_BASE', date(min(years), 1, 1), date(max(years), 12, 31))
                ip_exemptions = year_payslips._get_line_values(['IP.EXEMPT'])['IP.EXEMPT']
                for year_payslip in year_payslips:
                    ip_remuneration_by_employee_year[year_payslip.employee_id.id, year_payslip.date_to.year] += \
                        onss_bases[year_payslip.id] - ip_exemptions[year_payslip.id]['total']

        def previous_years_average(payslip):
            # Art. 37, al. 2 CIR 92: average of the 4 previous taxable periods, without the one the activity started
            # in (and the ones before): only the complete years of activity count
            year = payslip.date_to.year
            start_date = payslip.employee_id.sudo().first_contract_date
            years = [year - n for n in range(1, 5) if not start_date or year - n > start_date.year]
            if not years:
                return 0.0
            return sum(ip_totals_by_employee_year[payslip.employee_id.id, y] for y in years) / len(years)

        common_localdict['l10n_be_ip_data_by_payslip'] = {
            payslip: {
                'year_total': ip_totals_by_employee_year[payslip.employee_id.id, payslip.date_to.year],
                'year_remuneration': ip_remuneration_by_employee_year[payslip.employee_id.id, payslip.date_to.year],
                'previous_years_average': previous_years_average(payslip) if payslip in ip_payslips else 0.0,
            }
            for payslip in be_payslips
        }
        common_localdict['l10n_be_quarter_totals_by_payslip'] = {payslip: {} for payslip in be_payslips}
        # Loss on commission: whether the employee earned variable revenues, fetched once for the batch
        # and only for the payslips with a leave that may cause a loss on commission
        loss_payslips = be_payslips.filtered(lambda payslip: any(
            worked_day.code in ('006.00', '016.00')
            or 'VARIABLE_SALARY_LOSS' in worked_day.work_entry_type_id.category_ids.mapped('code')
            for worked_day in payslip.worked_days_line_ids
        ))
        common_localdict['l10n_be_variable_revenues_by_payslip'] = loss_payslips._l10n_be_get_variable_revenues_by_payslip()

        # Compute mobility amounts once for the whole batch to avoid per-payslip queries
        common_localdict['l10n_be_mobility_amounts_by_payslip'] = be_payslips._get_l10n_be_mobility_amounts()

        return common_localdict

    def _get_bachelor_274_34_exemptions(self, common_localdict, round_localdict):
        valid_274_34_payslips = self.env['l10n_be.274_xx']._get_valid_274_34_payslips(self)

        global_line_values = common_localdict['global_line_values']

        # Get total master + doctor exemption for the current month
        total_32_33_exemption = \
            global_line_values['WITHHOLDING_TAX_EX_274_32']['sum']['total'] + \
            global_line_values['WITHHOLDING_TAX_EX_274_33']['sum']['total'] + \
            common_localdict['l10n_be_exemptions_month_line_values']['WITHHOLDING_TAX_EX_274_32']['sum']['total'] + \
            common_localdict['l10n_be_exemptions_month_line_values']['WITHHOLDING_TAX_EX_274_33']['sum']['total']

        prev_bachelor_exemption = common_localdict['l10n_be_exemptions_month_line_values']['WITHHOLDING_TAX_EX_274_34']['sum']['total']

        bachelor_34_exemption_by_slip = {}
        total_bachelor_exemption = 0

        for payslip in valid_274_34_payslips:
            _, _, exemption = self.env['l10n_be.274_xx']._get_rd_basic_exemption_vals(payslip, global_line_values)
            bachelor_34_exemption_by_slip[payslip] = exemption
            total_bachelor_exemption += exemption

        bachelor_rate = self.env['l10n_be.274_xx']._get_bachelor_exemption_rate(min(self.mapped('date_from')))
        max_exemption = (total_32_33_exemption * bachelor_rate) - prev_bachelor_exemption
        capped_bachelor_total = min(total_bachelor_exemption, max_exemption)
        capping_ratio = capped_bachelor_total / total_bachelor_exemption if total_bachelor_exemption else 1

        for payslip in valid_274_34_payslips:
            bachelor_34_exemption_by_slip[payslip] *= capping_ratio

        round_localdict.update({
            'bachelor_34_exemption_by_slip': bachelor_34_exemption_by_slip
        })

    def _l10n_be_is_shift_exemption_work_entry_type(self, work_entry_type):
        """
        Whether the hours of the time type count in the third-time rule of the team and night shifts withholding
        tax exemptions (274.74 / 274.75, CIR 92 art. 275/5) (and, before 2025, in the share of the continuous team
        hours, see _l10n_be_is_shift_exemption_taxable_work_entry_type): the paid hours (worked, overtime, paid time
        off, sickness), the workers' annual holidays (paid by the holiday fund) and the recoverable overtime (026)
        included, without the public holidays, the working time reduction days (RTT), the recovered overtime and,
        from 2025, the guaranteed salary from the 2nd week of sickness (the 1st week counts). The time types are
        recognized by their Belgian codes, the rubrics of the payroll secretariats: the denominator of Partena
        (circular 11/2021) is made of the rubrics 001.00 to 041.99, 050.00 to 087.99 and 090.00 to 107.99, the
        workers' holidays 142.00 to 142.03 and 142.20 to 142.23 and 026, without 006.00, 006.10 to 006.15, 006.50 to
        006.99, 015.45, 015.49, 017.45, 019, 046, 050.01 to 050.09, 051.01 to 051.09 and, since 01/01/2025, 072, 082
        and 092. The time types without such a code count when they are paid. Called on a payslip, the date of the
        guaranteed salary rule is the end of its period (from 2025 without a payslip).
        """
        code = work_entry_type.code or ''
        public_holiday = (
            code in ('006.00', '202.00') or '006.10' <= code <= '006.15' or '006.50' <= code <= '006.99'
        )
        working_time_reduction = (
            code in ('015.45', '015.49', '017.45', '019.45', '019.49')
            or '019.00' <= code <= '019.03' or '019.50' <= code <= '019.99'
        )
        # 046: recovered overtime
        if public_holiday or working_time_reduction or code[:4] == '046.':
            return False
        # 072 / 082 / 092: guaranteed salary from the 2nd week of sickness, out since 01/01/2025
        if code[:4] in ('072.', '082.', '092.') and not (len(self) == 1 and self.date_to < date(2025, 1, 1)):
            return False
        if code[:4] == '026.' or '142.00' <= code <= '142.03' or '142.20' <= code <= '142.23':
            return True
        if '050.01' <= code <= '050.09' or '051.01' <= code <= '051.09':
            return False
        if len(code) == 6 and code[3] == '.' and code.replace('.', '', 1).isdigit() and not (
            '001.00' <= code < '042.00' or '050.00' <= code < '088.00' or '090.00' <= code < '108.00'
        ):
            return False
        return work_entry_type.amount_rate > 0

    @api.model
    def _l10n_be_is_shift_exemption_taxable_work_entry_type(self, work_entry_type):
        """
        Whether the hours of the time type count in the share of the continuous team hours of the team shifts
        withholding tax exemption (274.74), from 2025: the hours of the taxable remuneration, worked or suspended,
        which is not the set of hours of the third-time rule (see _l10n_be_is_shift_exemption_work_entry_type). As
        the social secretariats apply it since 01/01/2025 (Partena), the public holidays (006), the working time
        reduction days (015.45, 015.49, 017.45, 019), the recovered overtime (046) and the recoverable overtime (026)
        count, the workers' annual holidays (142, paid by the holiday fund, outside of the taxable remuneration) and
        the guaranteed salary from the 2nd week of sickness (072, 082, 092) don't. The time types are recognized by
        their Belgian codes, the rubrics of the payroll secretariats: the denominator of Partena is made of the
        rubrics 001.00 to 041.99, 046, 050.00 to 087.99 and 090.00 to 107.99, without 039.23 (net voluntary
        overtime), 050.01 to 050.09, 051.01 to 051.09, 072, 082, 092 and 142, the rubrics 026 included whatever the
        rate of their time type (026.00 pays the premium only). The time types without such a code count when they
        are paid.
        """
        code = work_entry_type.code or ''
        if (
            code[:4] in ('072.', '082.', '092.') or code == '039.23'
            or '050.01' <= code <= '050.09' or '051.01' <= code <= '051.09'
        ):
            return False
        if code[:4] == '026.':
            return True
        if work_entry_type.amount_rate <= 0:
            return False
        if len(code) == 6 and code[3] == '.' and code.replace('.', '', 1).isdigit():
            return (
                '001.00' <= code < '042.00' or code[:4] == '046.' or '050.00' <= code < '088.00'
                or '090.00' <= code < '108.00'
            )
        return True

    def _get_l10n_be_full_pay_worked_hours(self, work_entry_type_filter=None):
        """
        Total hours of the period counted by the third-time rule of the Night/Team/Continuous Team withholding tax
        exemptions (274.74/274.75), see _l10n_be_is_shift_exemption_work_entry_type. Unpaid time off is excluded.
        Another selection of the time types can be given as `work_entry_type_filter` (a function of the work entry
        type returning whether its hours count).
        """
        self.ensure_one()
        work_entry_type_filter = work_entry_type_filter or self._l10n_be_is_shift_exemption_work_entry_type
        return sum(
            line.number_of_hours
            for line in self.worked_days_line_ids
            if work_entry_type_filter(line.work_entry_type_id)
        )

    def _get_l10n_be_contteam_share(self):
        """
        The share of the continuous team hours in the hours of the period, the share of the taxable remuneration (and
        of its withholding tax) on which the team shifts exemption (274.74) applies at the continuous team rate (25 %),
        the rest at the team rate (22.8 %) (CIR 92, art. 275/5).

        It is not the ratio of the third-time rule (the eligibility, see l10n_be.274_xx._is_team_exemption_eligible,
        unchanged). Since 01/01/2025, the taxable base and the withholding tax are split on the hours entering the
        taxable remuneration (see _l10n_be_is_shift_exemption_taxable_work_entry_type): the continuous team hours,
        worked or suspended on the days the worker would have worked in continuous team (public holiday, working time
        reduction day, recovered overtime, ...), over all those hours. Before 2025 the hours of the third-time rule
        were used for both.
        """
        self.ensure_one()
        work_entry_type_filter = None  # the hours of the third-time rule
        if self.date_to >= date(2025, 1, 1):
            work_entry_type_filter = self._l10n_be_is_shift_exemption_taxable_work_entry_type
            if not self._get_l10n_be_full_pay_worked_hours(work_entry_type_filter):
                # no hours in the taxable remuneration (only workers' holidays, ...): the hours of the third-time rule
                work_entry_type_filter = None
        total_hours = self._get_l10n_be_full_pay_worked_hours(work_entry_type_filter)
        if not total_hours:
            return 0.0
        return min(1.0, self._get_l10n_be_category_option_hours('PREMIUM_PAY_CONTTEAM', work_entry_type_filter) / total_hours)

    def _get_l10n_be_category_option_hours(self, category_code, work_entry_type_filter=None):
        """
        Total worked day hours tagged with the given premium pay category option (or one of
        its descendants), among the ones the third-time rule counts (the premiums of the public
        holidays, of the working time reduction days, ... are not part of it): the time off
        counts when it carries the option, or when it replaces attendances of the working schedule
        carrying it (see _get_l10n_be_category_option_leave_hours). Reads the worked day lines directly
        (rather than going through ``_get_category_options_data``, which needs a live ``work_entries``
        list and is therefore unusable for already validated payslips), so it works uniformly for this
        batch and for previously validated payslips alike. Another selection of the time types than the
        third-time rule's can be given as `work_entry_type_filter` (see _get_l10n_be_full_pay_worked_hours).
        """
        self.ensure_one()
        work_entry_type_filter = work_entry_type_filter or self._l10n_be_is_shift_exemption_work_entry_type
        return sum(
            line.number_of_hours
            for line in self.worked_days_line_ids
            if category_code in line.category_options_ids._get_codes_with_ancestors()
            and work_entry_type_filter(line.work_entry_type_id)
        ) + self._get_l10n_be_category_option_leave_hours(category_code, work_entry_type_filter)

    def _get_l10n_be_category_option_leave_hours(self, category_code, work_entry_type_filter=None):
        """
        Hours of time off replacing attendances of the working schedule tagged with the given premium pay category
        option (or one of its descendants), among the ones the third-time rule counts, when the time off doesn't
        carry the option itself. The team (resp. night) shifts exemptions (274.74 / 274.75) count the paid time off
        as team (resp. night) hours on the days the worker would have worked in team (resp. at night) (confirmed by
        Partena's experts), while the premium is not paid on them: the time off work entries don't carry the options
        of the attendances they replace, they are found here by intersecting the time off of the period with the
        tagged attendances of the schedule. The hours of a time type are capped by its worked days lines. Another
        selection of the time types than the third-time rule's can be given as `work_entry_type_filter`.
        """
        self.ensure_one()
        work_entry_type_filter = work_entry_type_filter or self._l10n_be_is_shift_exemption_work_entry_type
        hours_by_type = defaultdict(float)
        for line in self.worked_days_line_ids:
            work_entry_type = line.work_entry_type_id
            if (
                work_entry_type.count_as == 'absence'
                and category_code not in line.category_options_ids._get_codes_with_ancestors()
                and work_entry_type_filter(work_entry_type)
            ):
                hours_by_type[work_entry_type] += line.number_of_hours
        if not hours_by_type:
            return 0.0
        no_option = self.env['hr.salary.rule.category']
        no_attendance = self.env['resource.calendar.attendance']
        leave_hours_by_type = defaultdict(float)
        for version in self.worked_days_line_ids.version_id:
            version_sudo = version.sudo().with_company(version.company_id)
            calendar = version_sudo.resource_calendar_id
            if not any(
                category_code in attendance.category_options_ids._get_codes_with_ancestors()
                for attendance in calendar.attendance_ids
            ):
                continue
            date_from = max(self.date_from, version.date_start)
            date_to = min(self.date_to, version.date_end or self.date_to)
            if date_from > date_to:
                continue
            tz = ZoneInfo(version._get_tz())
            start_dt = datetime.combine(date_from, time.min, tzinfo=tz)
            end_dt = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
            attendances = version_sudo._get_attendance_intervals(start_dt, end_dt).get(version.employee_id.resource_id.id, [])
            premium_attendances = Intervals([
                (start, stop, attendance)
                for start, stop, attendance in attendances
                if category_code in attendance.category_options_ids._get_codes_with_ancestors()
            ])
            if not premium_attendances:
                continue
            leaves_by_type = defaultdict(list)
            for vals in version_sudo._get_version_work_entries_values(start_dt, end_dt):
                work_entry_type = vals['work_entry_type_id']
                if (
                    vals['version_id'] == version
                    and vals.get('date_start') and vals.get('date_stop')
                    and work_entry_type in hours_by_type
                    and category_code not in vals.get('category_options_ids', no_option)._get_codes_with_ancestors()
                ):
                    leaves_by_type[work_entry_type].append((
                        vals['date_start'] if vals['date_start'].tzinfo else vals['date_start'].replace(tzinfo=UTC),
                        vals['date_stop'] if vals['date_stop'].tzinfo else vals['date_stop'].replace(tzinfo=UTC),
                        no_attendance,
                    ))
            for work_entry_type, leaves in leaves_by_type.items():
                leave_hours_by_type[work_entry_type] += sum(
                    (stop - start).total_seconds() / 3600
                    for start, stop, _attendances in Intervals(leaves) & premium_attendances
                )
        return sum(min(hours, hours_by_type[work_entry_type]) for work_entry_type, hours in leave_hours_by_type.items())

    def _get_team_night_274_74_75_exemptions(self, common_localdict, round_localdict):
        """
        WITHHOLDING_TAX_EX_274_74 (Team/Continuous Team) and WITHHOLDING_TAX_EX_274_75 (Night) are
        "mutualized" exemptions: the money isn't computed employee per employee but
        capped on the sum of the withholding tax of every eligible employee of the
        month (this batch + already validated payslips earlier this month).

        The amount already granted on previously validated payslips this month is
        kept as-is (no retroactive recomputation). Only the room left in the pool is distributed to
        this batch's eligible payslips, each capped at its own withholding tax: the surplus of the payslips
        capped to their withholding tax (e.g. a flexi-job's, whose taxable part is in the base without
        withholding tax) goes to the others whatever their order, as the 274 does
        (l10n_be.274_xx._get_shift_exemption_pooled_values).

        That withholding tax is the one of the remuneration: the flat-rate taxes of the economic
        unemployment supplements and of the replacement incomes are not part of the cap.
        """
        global_line_values = common_localdict['global_line_values']
        month_line_values = common_localdict['l10n_be_exemptions_month_line_values']
        localdicts = common_localdict['localdicts']

        def pooled_exemptions(code, payslips):
            # the theoretical exemption the previously validated payslips of the month didn't use
            pool = month_line_values[f'T_{code}']['sum']['total'] - month_line_values[code]['sum']['total']
            exemption_by_slip, room_by_slip = {}, {}
            for payslip in payslips:
                # the flat-rate tax lines are negative, as the voluntary withholding tax, which is part of the cap
                withholding_tax = (
                    global_line_values['PPTOTAL'][payslip.id]['total']
                    + global_line_values['ECONOMIC_UNEMPLOYMENT.P.P'][payslip.id]['total']
                    + global_line_values['REPLACEMENT_REVENUE.P.P'][payslip.id]['total']
                    - global_line_values['FISC_VOL'][payslip.id]['total']
                )
                remaining_available_pp = max(
                    0.0, withholding_tax - localdicts[payslip.id]['categories']['TAX_EXEMPTION_GRANTED'])
                theoretical_exemption = global_line_values[f'T_{code}'][payslip.id]['total']
                exemption_by_slip[payslip] = min(remaining_available_pp, theoretical_exemption)
                room_by_slip[payslip] = remaining_available_pp - exemption_by_slip[payslip]
                pool += theoretical_exemption - exemption_by_slip[payslip]
            for payslip in payslips:
                extra_amount = max(0.0, min(room_by_slip[payslip], pool))
                exemption_by_slip[payslip] += extra_amount
                pool -= extra_amount
            return exemption_by_slip

        # a payslip eligible to the team shifts exemption is not to the night shifts one
        team_payslips = self.filtered(lambda p: global_line_values['T_WITHHOLDING_TAX_EX_274_74'][p.id]['total'])
        night_payslips = (self - team_payslips).filtered(
            lambda p: global_line_values['T_WITHHOLDING_TAX_EX_274_75'][p.id]['total'])
        team_74_exemption_by_slip = pooled_exemptions('WITHHOLDING_TAX_EX_274_74', team_payslips)
        night_75_exemption_by_slip = pooled_exemptions('WITHHOLDING_TAX_EX_274_75', night_payslips)

        round_localdict.update({
            'team_74_exemption_by_slip': team_74_exemption_by_slip,
            'night_75_exemption_by_slip': night_75_exemption_by_slip
        })

    def _get_round_common_localdict(self, round_nb, common_localdict):
        round_common_localdict = super()._get_round_common_localdict(round_nb, common_localdict)

        if round_nb == 2:
            self._get_bachelor_274_34_exemptions(common_localdict, round_common_localdict)

        if round_nb == 3:
            self._get_team_night_274_74_75_exemptions(common_localdict, round_common_localdict)

        return round_common_localdict

    def _l10n_be_get_benefit_versions(self):
        """The versions whose benefits in kind of a device or a company car (and the car's CO2 contribution) the
        payslip carries: the versions of its worked days. A regular payslip without any worked days line (a month
        without any work entry: a suspension the time does not register, a variable schedule without a planned day)
        carries those of its own version: the benefit of a company car is due for every day it is made available,
        whatever the performances (art. 36, § 2 CIR 92), as the CO2 contribution for every month (art. 38, § 3quater of
        the law of 29 June 1981). Not on an arrears payslip, nor when another payslip of the employee in the period
        already has worked days on that version (it carries them)."""
        self.ensure_one()
        versions = self.worked_days_line_ids.version_id
        if versions or self.l10n_be_arrear_salary or self.ignore_worked_day_lines or self.is_outside_contract \
                or not self.version_id:
            return versions
        others = self.search([
            ('employee_id', '=', self.employee_id.id),
            ('id', '!=', self._origin.id),
            ('state', '!=', 'cancel'),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ])
        if self.version_id in others.worked_days_line_ids.version_id:
            return versions
        return self.version_id

    def _get_period_contracts(self):
        # Returns all the employee contracts over the same payslip period, to avoid
        # double remunerations for some line codes
        self.ensure_one()
        if self.env.context.get('salary_simulation') and self.env.context.get('origin_version_id'):
            return self.env.context['origin_version_id']
        contracts = self.employee_id._get_versions_with_contract_overlap_with_period(
            self.date_from,
            self.date_to,
        ).sorted('date_start')
        return contracts.ids

    def _get_payslip_line_total(self, amount, quantity, rate, rule):
        total = super()._get_payslip_line_total(amount, quantity, rate, rule)
        if self.company_id.country_id.code != 'BE':
            return total
        return float_round(total, precision_rounding=0.01, rounding_method='HALF-UP')

    def _get_max_basic_salary_contract(self, versions):
        self.ensure_one()
        if len(versions) == 1:
            return versions
        for version in versions:
            date_from = max([version.date_start, self.date_from])
            date_end = min([version.date_end, self.date_to]) if version.date_end else self.date_to
            work_entries_vals = version.filtered('resource_calendar_id').generate_work_entries(date_from, date_end)
            all_work_hours = version.get_work_hours(self.date_from, date_end, work_entries_vals)
            work_hours = sum(
                hours for (work_entry_type_id, _options), hours in all_work_hours.items()
                if work_entry_type_id.amount_rate != 0)
            if not float_is_zero(work_hours, precision_digits=2):
                return version
        return versions[0]

    @api.depends('struct_id', 'date_from')
    def _compute_l10n_be_is_december(self):
        for payslip in self:
            payslip.l10n_be_is_december = payslip.struct_id.code == "BEMONTHLY" and payslip.date_from and payslip.date_from.month == 12

    @api.depends('struct_id')
    def _compute_l10n_be_is_double_pay(self):
        for payslip in self:
            payslip.l10n_be_is_double_pay = payslip.struct_id.code == "BEDOUBLE"

    def _l10n_be_get_holiday_pay_provision_base(self, gross):
        """ Return the base on which the holiday pay tax provision is computed.
        We start from the monthly gross salary and add back the days that count for the
        double holiday pay but were not paid on this payslip (legal leave, public holidays, ...).
        Without this top up the provision would stop growing whenever the employee is on such an absence.
        """
        self.ensure_one()
        non_assimilated_codes = self.env['hr.work.entry.type'].search([('category_ids.code', '=', 'UNASSIMILATED')]).mapped('code')
        wage = self.version_id._get_contract_wage()
        # Assimilated but unpaid days have been deducted from the gross salary: add
        # their value back with the same daily factor so that the deduction cancels
        # out and a fully assimilated month reaches the same base as a worked month.
        assimilated_unpaid = self.worked_days_line_ids.filtered(
            lambda wd: not wd.is_paid
            and wd.code not in non_assimilated_codes
            and wd.code != '202.00'
            and not wd.work_entry_type_id.is_extra_hours
            and not wd.work_entry_type_id.l10n_be_is_time_credit
            and not wd.work_entry_type_id.l10n_be_economic_unemployment,
        )
        top_up = sum(wd._l10n_be_get_workday_amount(wage) for wd in assimilated_unpaid)
        return gross + top_up

    def _l10n_be_get_report_supplementary_hours(self):
        """ Supplementary hours of the month and of the year to date, for the payslip PDF, split between the hours
        with a reduced tax burden and the other ones. The hours with a reduced tax burden are the overtime of the
        274.44/274.55 exemptions within the yearly cap of the joint committee of the payslip, consumed as for these
        declarations (see l10n_be.274_xx._get_extra_hours_lines_ids). The other ones are the rest of the extra hours.
        The year to date adds the validated or paid payslips of the year of the employer (company and branches).
        """
        self.ensure_one()
        overtime_category = self._l10n_be_get_overtime_category()
        company = self.company_id.root_id

        def is_supplementary(work_entry_type):
            return work_entry_type.is_extra_hours or overtime_category in work_entry_type.category_ids

        month_total = sum(wd.number_of_hours for wd in self.worked_days_line_ids if is_supplementary(wd.work_entry_type_id))
        [[previous_total]] = self.env['hr.payslip.worked_days']._read_group(
            domain=Domain([
                ('payslip_id.state', 'in', ['paid', 'validated']),
                ('payslip_id.company_id', 'child_of', company.id),
                ('payslip_id.date_from', '>=', date(self.date_from.year, 1, 1)),
                ('payslip_id.date_to', '<', self.date_from),
                ('payslip_id.employee_id', '=', self.employee_id.id),
            ]) & (
                Domain('work_entry_type_id.is_extra_hours', '=', True)
                | Domain('work_entry_type_id.category_ids', 'in', overtime_category.ids)
            ),
            aggregates=['number_of_hours:sum'],
        )

        consumed = self._l10n_be_get_overtime_hours_consumed(company, self.date_from)
        year_with = sum(
            min(hours, self._l10n_be_get_overtime_cap(joint_committee, company, self.date_from, raise_if_not_found=False) or 0.0)
            for (_employee, joint_committee), hours in consumed.items() if joint_committee
        )
        month_with = 0.0
        if joint_committee := self._l10n_be_get_overtime_joint_committee(self.version_id):
            cap = self._l10n_be_get_overtime_cap(joint_committee, company, self.date_from, raise_if_not_found=False) or 0.0
            month_overtime = sum(
                wd.number_of_hours for wd in self.worked_days_line_ids
                if self._is_extra_hours_qualifying(wd.work_entry_type_id))
            month_with = min(month_overtime, max(cap - consumed[self.employee_id, joint_committee], 0.0))
            year_with += month_with
        return {
            'month_with': month_with,
            'year_with': year_with,
            'month_without': month_total - month_with,
            'year_without': previous_total + month_total - year_with,
        }

    def _l10n_be_get_report_time_off_counters(self):
        """ Allocation counters of the pay period, per time off type, for the payslip PDF:
            - 'time_off' for the regular allocations
            - 'overtime' for the time off credited by the overtime rules
            The initial budget is the one allocated at the start of the year, or of the contract if later. What is
            granted after it, by a later allocation or by an accrual plan, is earned in the month it is granted.
            Only the counters that moved during the period or with a budget left are reported.
        """
        self.ensure_one()
        employee = self.employee_id.sudo()
        version = self.version_id.sudo()
        # The schedule of the payslip: the conversions of a past payslip don't follow a later change of schedule
        hours_per_day = version.resource_calendar_id.hours_per_day or 8.0
        initial_day = min(max(date(self.date_from.year, 1, 1), version.contract_date_start or self.date_from), self.date_to)
        # The budget granted until these days included, and the time off taken before these moments
        grant_days = {
            'initial': initial_day,
            'start': max(self.date_from - relativedelta(days=1), initial_day),
            'end': self.date_to,
        }
        moments = {
            'start': datetime.combine(max(self.date_from, initial_day), time.min),
            'end': datetime.combine(self.date_to + relativedelta(days=1), time.min),
        }

        # Overtime credits, in days, dated by the attendance or leave they come from.
        logs = self.env['hr.time.rule.allocation.log'].sudo().search([
            ('allocation_id.employee_id', '=', employee.id),
            ('allocation_id.state', '=', 'validate'),
        ])
        credits = defaultdict(list)
        for res_model, model_logs in logs.grouped('res_model').items():
            sources = self.env[res_model].sudo().browse(model_logs.mapped('res_id')).exists()
            start_by_source = dict(zip(sources.ids, sources.mapped(sources._time_rule_span_start_field), strict=True))
            for log in model_logs:
                credits[log.allocation_id].append((start_by_source.get(log.res_id, datetime.min), log.days))

        active_allocations = self.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('work_entry_type_id.requires_allocation', '=', True),
            ('date_from', '<=', self.date_to),
            '|', ('date_to', '=', False), ('date_to', '>=', self.date_from),
        ])
        allocations = active_allocations | logs.allocation_id
        work_entry_types = allocations.work_entry_type_id
        first_day = min(allocations.mapped('date_from'), default=self.date_from)
        # The accrual plans granted their time off at each accrual date, not all at once on the allocation's start
        accrual_data = active_allocations._l10n_be_simulate_accrual(grant_days.values())

        def unit(work_entry_type):
            return 'hours' if work_entry_type.unit_of_measure == 'hour' else 'days'

        def part_before(leave, moment):
            if leave.work_entry_type_id.count_days_as == 'calendar':
                return (moment.date() - leave.request_date_from).days
            return employee._get_leave_days_data_batch(
                leave.date_from, moment, domain=[('holiday_id', '=', leave.id)],
            )[employee.id][unit(leave.work_entry_type_id)]

        def used_until(moment, accrual_allocations_data):
            crossing = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate'),
                ('work_entry_type_id', 'in', work_entry_types.ids),
                ('date_from', '<=', moment),
                ('date_to', '>', moment),
            ])
            consumed, uncovered = employee.with_context(ignored_leave_ids=crossing.ids)._get_consumed_leaves(
                work_entry_types, target_date=moment.date(), ignore_future=True,
                precomputed_allocations=accrual_allocations_data)
            used = defaultdict(float)
            for allocation in allocations:
                work_entry_type = allocation.work_entry_type_id
                used[work_entry_type] += consumed[employee][work_entry_type][allocation][f'{unit(work_entry_type)}_leaves_taken']
            for work_entry_type in work_entry_types:
                used[work_entry_type] += sum(
                    excess['amount'] for day, excess in uncovered[employee][work_entry_type]['excess_days'].items()
                    if not excess['is_virtual'] and day >= first_day)
            for leave in crossing:
                used[leave.work_entry_type_id] += part_before(leave, moment)
            return used

        def regular_granted(regular, day):
            return sum(
                allocation._l10n_be_get_accrued_duration(accrual_data[day][allocation]) if allocation.accrual_plan_id
                else amount if allocation.date_from <= day else 0.0
                for allocation, amount in regular.items()
            )

        used_at = {key: used_until(moment, accrual_data[grant_days[key]]) for key, moment in moments.items()}
        result = {'time_off': [], 'overtime': []}
        for work_entry_type, type_allocations in allocations.grouped('work_entry_type_id').items():
            to_hours = 1.0 if unit(work_entry_type) == 'hours' else hours_per_day
            from_days = hours_per_day / to_hours
            # An open-ended allocation may hold a regular budget besides the overtime credits.
            regular = {
                allocation: max(allocation[f'number_of_{unit(work_entry_type)}'] - sum(days for _date, days in credits[allocation]) * from_days, 0.0)
                for allocation in type_allocations & active_allocations
            }

            # Per section, the budget granted before each bound and what is left of it: leaves use
            # the regular budget first, the overtime credits next, any overdraft the regular one.
            budgets = {'time_off': {}, 'overtime': {}}
            for key, moment in moments.items():
                regular_amount = regular_granted(regular, grant_days[key])
                credit_granted = sum(days for allocation in type_allocations for start, days in credits[allocation] if start < moment) * from_days
                used = used_at[key][work_entry_type]
                credit_used = min(max(used - regular_amount, 0.0), credit_granted)
                budgets['time_off'][key] = (regular_amount, regular_amount - used + credit_used)
                budgets['overtime'][key] = (credit_granted, credit_granted - credit_used)

            sections = [('time_off', 1.0)]
            if work_entry_type in logs.allocation_id.work_entry_type_id:
                sections.append(('overtime', to_hours))
            for section, factor in sections:
                (granted_start, left_start), (granted_end, left_end) = budgets[section]['start'], budgets[section]['end']
                counter = {
                    'name': work_entry_type.name,
                    'unit': work_entry_type.unit_of_measure,
                    # the overtime credits have no initial budget
                    'initial': regular_granted(regular, grant_days['initial']) * factor if section == 'time_off' else 0.0,
                    'previous': left_start * factor,
                    'earned': (granted_end - granted_start) * factor,
                    'final': left_end * factor,
                }
                counter['taken'] = counter['previous'] + counter['earned'] - counter['final']
                if (
                    not float_is_zero(counter['earned'], precision_digits=2)
                    or not float_is_zero(counter['taken'], precision_digits=2)
                    or float_compare(counter['final'], 0.0, precision_digits=2) > 0
                ):
                    result[section].append(counter)
        return result

    def _get_eco_vouchers_amount(self, get_explanation=False):
        self.ensure_one()
        eco_config = self.env['hr.rule.parameter']._get_parameter_from_code('eco_voucher_config', self.date_to, raise_if_not_found=False) or {}

        # Reference period: 12 months ending month before payment
        # E.g. Month 6 -> Ref: 1st June Prev -> 31st May Curr
        ref_date_end = self.date_from - relativedelta(months=1, day=31)
        ref_date_start = ref_date_end + relativedelta(days=1, months=-12)

        # Broad search to identify JCs in history
        all_contracts = self.employee_id._get_versions_with_contract_overlap_with_period(ref_date_start, self.date_to)
        relevant_jcs = all_contracts.mapped('l10n_be_joint_committee_id')

        current_month = self.date_from.month
        is_departing = self._l10n_be_is_last_payslip()
        matching_jc_codes = [
            code for code, cfg in eco_config.items()
            if (cfg.get('month') == current_month or is_departing) and code in relevant_jcs.mapped('egov3_code')
        ]

        if not matching_jc_codes:
            return (0.0, {'jc_codes': 'None', 'total': 0.0}) if get_explanation else 0.0

        # 128.00 (maternity), 128.05 (paternity) and 135.00 (unpredictable) are
        # assimilated periods: the days they cover remain valid. 147.00 (credit
        # time), 147.05 (parental time off) and 142.99 (youth time off) are
        # structural reductions of the working time already reflected in the
        # version's work_time_rate (and thus in the granted amount), so they
        # must not be counted again as absence days. 165.00 (sectoral compensatory
        # rest) is paid by a third party, not by the employer: assimilated as well.
        assimilated_codes = ['128.00', '128.05', '135.00', '165.00']
        structural_codes = ['147.00', '147.05', '142.99']
        unpaid_work_entry_types = self.env['hr.work.entry.type'].search([
            ('amount_rate', '=', 0.0),
            ('code', 'not in', assimilated_codes + structural_codes),
            ('country_id.code', 'in', [False, 'BE']),
        ])
        # Work entry types that don't testify of the occupation state on their own:
        # structural reductions behave like days off for the employee, public
        # holidays (006.00) happen whether the employee is absent or not, and out
        # of contract (000.00) days are not part of the occupation. Those days are not
        # working days: like week-ends, they enter neither the valid nor the
        # invalid count.
        neutral_codes = structural_codes + ['006.00', '000.00']

        total_amount = 0
        for jc_code in matching_jc_codes:
            jc_config = eco_config.get(jc_code)
            jc_month = jc_config.get('month')

            # Targeted fix for departing employees: adjust ref period to match JC cycle
            jc_ref_end, jc_ref_start = ref_date_end, ref_date_start
            if is_departing and jc_month != current_month:
                target_year = self.date_from.year
                if self.date_from.month > jc_month:
                    target_year += 1
                jc_ref_end = date(target_year, jc_month, 1) - relativedelta(days=1)
                jc_ref_start = jc_ref_end - relativedelta(months=12) + relativedelta(days=1)

            # Filter versions for this specific JC using the standard contract helper
            all_contracts_jc = self.employee_id._get_versions_with_contract_overlap_with_period(jc_ref_start, jc_ref_end)
            jc_versions = all_contracts_jc.filtered(lambda v: v.l10n_be_joint_committee_id.egov3_code == jc_code)
            if not jc_versions:
                continue

            # Generate the work entries over the reference period once for every
            # version of the joint committee: the working days actually performed
            # or assimilated are counted from the work entry dates.
            work_entries_vals_by_version = defaultdict(list)
            for vals in jc_versions.filtered('resource_calendar_id').generate_work_entries(jc_ref_start, jc_ref_end):
                work_entries_vals_by_version[vals['version_id'].id].append(vals)

            # The granted amount depends on the weekly working time, which may change
            # from one version to the next, so each version is prorated on its own
            # (with its own work time rate and its own valid/invalid working days).
            theoretical_days_by_calendar = {}  # calendar: its theoretical working dates
            # a public holiday registered for the employee alone is no more a working day than one of the calendar,
            # over the whole reference period: each version is prorated on the days of the whole period
            public_holiday_dates = self._get_eco_vouchers_public_holiday_dates(
                [vals for vals_list in work_entries_vals_by_version.values() for vals in vals_list])
            jc_amount = 0
            company_executive_type = self.env.ref('hr.contract_type_company_executive', raise_if_not_found=False)
            for version in jc_versions.sorted('date_start'):
                work_time_rate = version.work_time_rate
                # skip versions with 0% work time rate such as full parental time off or credit time, but not the
                # flexi-jobs of the Horeca, without a fixed working time: they are granted on their days of work
                is_horeca_flexi = jc_code == '302' and version.is_flexi()
                if not work_time_rate and not is_horeca_flexi:
                    continue
                # the eco-vouchers of the sectoral agreements are owed to the workers, not to the company directors
                # (even under an employment contract): a director's period of the reference period grants nothing
                if version._l10n_be_is_company_director() or version.employee_type_id == company_executive_type:
                    continue
                # Students get no eco-vouchers by default, and the Horeca agreement excludes them.
                if version.is_student():
                    continue
                version_from = max(jc_ref_start, version.date_start)
                version_to = min(jc_ref_end, version.date_end or jc_ref_end)
                if version_from > version_to:
                    continue
                # The proration is expressed in working days: the days the employee
                # actually worked or that are assimilated, over the days the
                # calendar theoretically schedules for the whole reference period,
                # so that a full reference period yields exactly the granted amount.
                valid_days, invalid_days = self._get_eco_vouchers_working_days(
                    work_entries_vals_by_version[version.id], unpaid_work_entry_types, neutral_codes)
                calendar = version.resource_calendar_id
                if calendar not in theoretical_days_by_calendar:
                    theoretical_days_by_calendar[calendar] = self._get_eco_vouchers_theoretical_working_dates(
                        calendar, jc_ref_start, jc_ref_end)
                theoretical_days = len(theoretical_days_by_calendar[calendar] - public_holiday_dates)

                if 'amount_from_rate' in jc_config:
                    amount = jc_config['amount_from_rate'][-1][1]
                    for rate_threshold, rate_amount in jc_config['amount_from_rate']:
                        if work_time_rate >= rate_threshold:
                            amount = rate_amount
                            break
                    if theoretical_days:
                        jc_amount += max(0, (valid_days / theoretical_days) * amount)
                elif jc_code == '302':
                    # - Full-time: 250 * complete_months/12 + 250 * partial_working_days/divisor
                    # - Part-time: 250 * working_days/divisor
                    # Divisor: 260 for 5-day week, 312 for 6-day week (company reference).
                    max_amount = jc_config['max_amount']
                    days_per_week = version.resource_calendar_id.days_per_week
                    if not days_per_week:
                        reference_calendar = version._get_reference_calendar()
                        half_day_hours_threshold = reference_calendar.hours_per_day * 3 / 4
                        days_per_week = version.resource_calendar_id._get_days_per_week_for_period(
                            version_from, version_to, half_day_hours_threshold
                        )
                    if not days_per_week:
                        days_per_week = 5
                    divisor = 312 if days_per_week >= 6 else 260

                    def _count_working_days(d_from, d_to, calendar=version.resource_calendar_id):
                        return calendar.get_work_duration_data(
                            datetime.combine(d_from, time.min).replace(tzinfo=UTC),
                            datetime.combine(d_to, time.max).replace(tzinfo=UTC),
                            compute_leaves=False,
                        )['days']

                    if is_horeca_flexi:
                        # a flexi-job has no fixed working time: its days of work (or assimilated) count one by one
                        amount = max_amount * valid_days / divisor
                    elif work_time_rate >= 1.0:
                        # Full-time: complete months use months/12 (contract-based, attendance
                        # irrelevant). Only the first and last months can be partial.
                        total_months = (version_to.year - version_from.year) * 12 + (version_to.month - version_from.month) + 1
                        first_month_end = date(version_from.year, version_from.month, 1) + relativedelta(day=31)
                        last_month_start = date(version_to.year, version_to.month, 1)
                        last_month_end = last_month_start + relativedelta(day=31)
                        complete_months = 0
                        partial_working_days = 0

                        if total_months == 1:
                            if version_from.day == 1 and version_to == first_month_end:
                                complete_months = 1
                            else:
                                partial_working_days = _count_working_days(version_from, version_to)
                        else:
                            if version_from.day == 1:
                                complete_months += 1
                            else:
                                partial_working_days += _count_working_days(version_from, first_month_end)
                            complete_months += total_months - 2
                            if version_to == last_month_end:
                                complete_months += 1
                            else:
                                partial_working_days += _count_working_days(last_month_start, version_to)

                        amount = max_amount * complete_months / 12
                        if partial_working_days:
                            amount += max_amount * max(0, partial_working_days - invalid_days) / divisor
                    else:
                        # Part-time: count actual working days (each day = 1 regardless of
                        # duration); do NOT scale by work_time_rate — days_per_week already
                        # captures how many distinct days/week the employee works.
                        working_days = max(0, _count_working_days(version_from, version_to) - invalid_days)
                        amount = max_amount * working_days / divisor
                    jc_amount += max(0, min(amount, max_amount))
                else:
                    if theoretical_days:
                        jc_amount += max(0, (valid_days / theoretical_days) * jc_config['max_amount'] * min(1, work_time_rate))
            # one reference period never grants more than the joint committee's full amount, whatever the versions and
            # their calendars (a calendar planned day by day schedules only its own days)
            if 'amount_from_rate' in jc_config:
                jc_max_amount = max(rate_amount for dummy, rate_amount in jc_config['amount_from_rate'])
            else:
                jc_max_amount = jc_config['max_amount']
            total_amount += min(jc_amount, jc_max_amount)

        explanation_info = {
            'jc_codes': ', '.join(matching_jc_codes),
            'total': float_round(total_amount, precision_digits=2),
        }
        return (total_amount, explanation_info) if get_explanation else total_amount

    def _get_eco_vouchers_working_days(self, work_entries_vals, unpaid_work_entry_types, neutral_codes):
        """ Count the valid and invalid working days over the given (already
        generated) work entry values.

        A date carrying a non neutral work entry is a working day: it is valid
        when actually worked or covered by an assimilated absence (sick time
        off, paid time off, maternity, ...), even partly (a partial resumption
        of work), invalid when only covered by non assimilated (unpaid)
        absences. Neutral entries (public holidays, structural reductions such
        as credit time) are not working days at all, like week-ends.

        :return: (valid working days, invalid working days)
        """
        working_dates = set()
        valid_dates = set()
        for vals in work_entries_vals:
            work_entry_type = vals.get('work_entry_type_id')
            if not work_entry_type or work_entry_type.code in neutral_codes:
                continue
            working_dates.add(vals['date'])
            if work_entry_type not in unpaid_work_entry_types:
                valid_dates.add(vals['date'])
        return len(valid_dates), len(working_dates - valid_dates)

    def _get_eco_vouchers_public_holiday_dates(self, work_entries_vals):
        """ The dates of the public holidays the work entries carry, those of the calendar and those registered for
        the employee alone (a replacement day): neither worked nor theoretical working days. """
        return {
            vals['date'] for vals in work_entries_vals
            if vals.get('work_entry_type_id') and vals['work_entry_type_id'].code == '006.00'
        }

    def _get_eco_vouchers_theoretical_working_days(self, calendar, date_from, date_to):
        return len(self._get_eco_vouchers_theoretical_working_dates(calendar, date_from, date_to))

    def _get_eco_vouchers_theoretical_working_dates(self, calendar, date_from, date_to):
        """ The days the calendar theoretically schedules real work over
        ``[date_from, date_to]``: week-ends, public holidays (through the
        calendar global leaves) and structural slots (e.g. credit time) are
        excluded, so that the result is directly comparable with the working
        days counted from the work entries. An employee occupied over the whole
        period without any non assimilated absence gets exactly the full
        granted amount.
        """
        # the calendar-level intervals hold the public holidays of every company: only the payslip's company's count
        work_intervals = calendar._work_intervals_batch(
            datetime.combine(date_from, time.min).replace(tzinfo=UTC),
            datetime.combine(date_to, time.max).replace(tzinfo=UTC),
            domain=[('count_as', '=', 'absence'), ('company_id', 'in', [False, self.company_id.id])],
        )[False]
        return {
            start.date()
            for start, dummy, attendances in work_intervals
            if any(
                not attendance.work_entry_type_id or attendance.work_entry_type_id.count_as == 'working_time'
                for attendance in attendances
            )
        }

    def _get_l10n_be_month_seized_amounts(self):
        """ Disposable earnings and seized amounts of the other validated payslips of the employee
        for the same calendar month. """
        self.ensure_one()
        month_start = self.date_to + relativedelta(day=1)
        other_payslips = self.search([
            ('id', '!=', self._origin.id),
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ['validated', 'paid']),
            ('date_to', '>=', month_start),
            ('date_to', '<=', month_start + relativedelta(day=31)),
        ])
        if not other_payslips:
            return 0.0, 0.0
        PayslipLine = self.env['hr.payslip.line']
        disposable = PayslipLine._read_group([
            ('slip_id', 'in', other_payslips.ids),
            ('code', '=', 'DISPOSABLE_EARNINGS'),
        ], aggregates=['total:sum'])[0][0]
        seized = PayslipLine._read_group([
            ('slip_id', 'in', other_payslips.ids),
            ('salary_rule_id.category_ids.code', '=', 'SEIZED_AMOUNT'),
        ], aggregates=['total:sum'])[0][0]
        return disposable, -seized

    def _get_l10n_be_max_seizable_amount(self, expected_net):
        """ Seizable amount left on the payslip, for its disposable earnings `expected_net`.

        The brackets apply to the total of the sums paid in the calendar month (Code judiciaire,
        art. 1409 § 1): the disposable earnings of the other validated payslips of the month (double
        holiday pay, 13th month, ...) are added, and what they already seized is deducted.
        """
        # Source: https://emploi.belgique.be/fr/themes/remuneration/protection-de-la-remuneration/saisie-et-cession-sur-salaires
        self.ensure_one()
        rates = self.env['hr.rule.parameter']._get_parameter_from_code('seizable_percentages', self.date_to, raise_if_not_found=False)
        child_increase = self.env['hr.rule.parameter']._get_parameter_from_code('seizable_amount_child', self.date_to, raise_if_not_found=False)
        if not rates or not child_increase:
            return expected_net
        other_disposable, other_seized = self._get_l10n_be_month_seized_amounts()
        month_net = expected_net + other_disposable
        dependent_children = self.version_id.l10n_be_dependent_children_attachment
        max_seizable_amount = 0
        lower_bound = 0
        for _left, right, rate in rates:
            max_seizable_amount += max(0, min(month_net, right) - lower_bound) * rate
            lower_bound = right
        return max(0, max_seizable_amount - dependent_children * child_increase - other_seized)

    @api.depends("date_from", "employee_id.marital")
    def _compute_effective_marital(self):
        for slip in self:
            slip.l10n_be_effective_marital = slip.employee_id._get_effective_marital_at_date(slip.date_from)

    def _get_salary_advance_balances(self):
        balance_by_employee = super()._get_salary_advance_balances()
        all_payslips = self.search([
            ('struct_id.country_id', '=', 'BE'),
            ('state', 'in', ('validated', 'paid')),
            ('employee_id', 'in', self.employee_id.ids),
        ])
        line_values = all_payslips._get_line_values(['SALARYADVREC', 'SALARYADV'])
        for payslip in all_payslips:
            balance_by_employee[payslip.employee_id]['SALARYADV'] += line_values['SALARYADV'][payslip.id]['total']
            balance_by_employee[payslip.employee_id]['SALARYADVREC'] += line_values['SALARYADVREC'][payslip.id]['total']  # negative amount
        return balance_by_employee

    def _get_worked_day_lines_hours_per_day(self, version):
        self.ensure_one()
        if version.l10n_be_time_credit:
            return version._get_reference_calendar().hours_per_day
        return super()._get_worked_day_lines_hours_per_day(version)

    def _get_out_of_contract_calendar(self, version):
        self.ensure_one()
        if version.l10n_be_time_credit:
            return version._get_reference_calendar()
        return super()._get_out_of_contract_calendar(version)

    def _get_out_of_period_duration(self, start, stop, reference_calendar):
        if reference_calendar.calendar_type == 'variable' and reference_calendar.hours_per_week \
                and not reference_calendar.attendance_ids.filtered('recurrency'):
            # a schedule planned day by day plans nothing outside the contract: the days of its regime (Monday to
            # Friday or Saturday) at the hours of its week
            weekdays = 6 if reference_calendar.days_per_week > 5 else 5
            days = sum(1 for day in rrule.rrule(rrule.DAILY, dtstart=start.date(), until=stop.date()) if day.weekday() < weekdays)
            return {'days': days, 'hours': reference_calendar.hours_per_week / weekdays * days}
        return super()._get_out_of_period_duration(start, stop, reference_calendar)

    def _get_worked_day_lines_values(self, version, work_entries_vals):
        self.ensure_one()
        res = []
        if self.struct_id.country_id.code != 'BE':
            return super()._get_worked_day_lines_values(version, work_entries_vals)
        # If a belgian payslip has half-day attendances/time off, it the worked days lines should
        # be separated
        work_hours = version._get_work_hours_split_half(self.date_from, self.date_to, work_entries_vals)
        work_hours_ordered = sorted(work_hours.items(), key=lambda x: x[1])
        for worked_days_data, duration_data in work_hours_ordered:
            work_entry_type_id, category_options = worked_days_data
            number_of_days, number_of_hours = duration_data
            work_entry_type = self.env['hr.work.entry.type'].browse(work_entry_type_id)
            attendance_line = {
                'version_id': version.id,
                'sequence': work_entry_type.sequence,
                'work_entry_type_id': work_entry_type_id,
                'number_of_days': number_of_days,
                'number_of_hours': number_of_hours,
                'category_options_ids': category_options,
            }
            res.append(attendance_line)
        return res

    def _l10n_be_get_loss_on_commission_amount_public_holiday(self, result_rules):
        """ The loss on commission on the public holidays of the payslip, kept for the databases whose salary rule
        COM_LOSS_PH is not updated yet.
        """
        self.ensure_one()
        number_of_days, daily_amount = self._l10n_be_get_loss_on_commission_public_holiday_values(result_rules)
        return number_of_days * daily_amount

    def _l10n_be_get_loss_on_commission_public_holiday_values(self, result_rules):
        """ The loss on commission on the public holidays of the payslip.

        :return: tuple (number of public holiday days, average daily variable revenue), the quantity and the amount
            of the salary rule line
        """
        self.ensure_one()
        public_holiday_number_of_days = self._get_worked_days_line_values(
            ['006.00'], ['number_of_days'], compute_sum=True
        )['006.00']['sum']['number_of_days']
        average_daily_variable_revenue = self._l10n_be_get_civil_year_average_daily_variable_revenues(
            result_rules, excluded_codes={'COM_LOSS_PH'})
        return public_holiday_number_of_days, average_daily_variable_revenue

    def _l10n_be_get_civil_year_average_daily_variable_revenues(self, result_rules, excluded_codes=None):
        """ The daily variable revenue of a suspension whose reference period is the previous civil year (public
        holidays, small unemployment, sickness of the workers...): the average of the previous civil year, of the
        months of the current year for an employee hired during the year, the commissions of the month by worked
        day for an employee hired during the month.
        """
        self.ensure_one()
        first_contract_date = self.employee_id._get_first_contract_date()
        if not first_contract_date:
            return 0
        if first_contract_date.year == self.date_from.year and first_contract_date.month == self.date_from.month:
            # If employee joined during current month, average variable salary = commissions / # worked days
            commissions = result_rules['COMMISSION']['total'] + result_rules['COMMISSION_ADV']['total']
            worked_days = self._get_worked_days_line_values(['002.00'], ['number_of_days'], compute_sum=True)['002.00']['sum']['number_of_days']
            return commissions / worked_days if worked_days else 0
        if first_contract_date.year == self.date_from.year:
            # If employee joined during current year, compute monthly average variable salary of current year
            return self._get_last_year_average_daily_variable_revenues(excluded_codes=excluded_codes)
        # Else compute last civil year monthly average variable salary
        return self.with_context(
            variable_revenue_date_from=date(year=self.date_from.year, month=1, day=1)
        )._get_last_year_average_daily_variable_revenues(excluded_codes=excluded_codes)

    @api.model
    def _l10n_be_get_variable_revenue_codes(self):
        """ The codes of the salary rules of the variable revenues (VARIABLE_REVENUES category), archived ones
        included: they may be found on the payslips of the reference periods.
        """
        return self.env['hr.salary.rule'].with_context(active_test=False).search([
            ('category_ids', 'in', self.env.ref('l10n_be_hr_payroll.VARIABLE_REVENUES').ids),
        ]).mapped('code')

    def _l10n_be_is_loss_on_commission_pto_monthly(self):
        """ Whether the loss on commission on paid time off is compensated monthly (COM_LOSS_PTO) instead of with
        the double holiday pay (SIMPLE_VARIABLE): only in JC 200, the joint committee of COM_LOSS_PTO, while the
        monthly benefit is active.
        """
        self.ensure_one()
        joint_committee = self.version_id.l10n_be_joint_committee_id
        if not joint_committee or not joint_committee.is_descendant_of(
                self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200')):
            return False
        # sudo: hr.contract.salary.benefit - only its state is read
        monthly = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly', raise_if_not_found=False)
        return bool(monthly and monthly.sudo().active)

    def _l10n_be_has_variable_revenues(self, variable_revenues_by_payslip=None):
        """ Whether the employee earned variable revenues in the reference periods of the loss on
            commission: the last 12 months and the previous civil year.

            :param variable_revenues_by_payslip: the values fetched once for the payslips computed
                together (`l10n_be_variable_revenues_by_payslip` of the localdict of the rules)
        """
        self.ensure_one()
        if variable_revenues_by_payslip is not None and self in variable_revenues_by_payslip:
            return variable_revenues_by_payslip[self]
        return self._l10n_be_get_variable_revenues_by_payslip()[self]

    def _l10n_be_get_variable_revenues_by_payslip(self):
        """ See `_l10n_be_has_variable_revenues`, by payslip, in one query. """
        payslips = self.filtered(lambda payslip: payslip.employee_id and payslip.date_from)
        result = dict.fromkeys(self, False)
        if not payslips:
            return result
        dates_by_employee = defaultdict(list)
        for employee, day in self.env['hr.payslip.line']._read_group([
            ('employee_id', 'in', payslips.employee_id.ids),
            ('slip_id.state', 'in', ['validated', 'paid']),
            ('code', 'in', self._l10n_be_get_variable_revenue_codes()),
            ('total', '!=', 0),
            ('date_from', '>=', min(payslips.mapped('date_from')) + relativedelta(years=-1, month=1, day=1)),
            ('date_from', '<', max(payslips.mapped('date_from'))),
        ], ['employee_id', 'date_from:day']):
            dates_by_employee[employee.id].append(day)
        for payslip in payslips:
            start = payslip.date_from + relativedelta(years=-1, month=1, day=1)
            result[payslip] = any(start <= day < payslip.date_from for day in dates_by_employee[payslip.employee_id.id])
        return result

    def _get_last_year_average_daily_variable_revenues(self, excluded_codes=None):
        self.ensure_one()
        days_per_week = self.version_id.resource_calendar_id.days_per_week
        if not days_per_week:
            return 0
        last_year_monthly_variable_revenue = self._get_last_year_average_variable_revenues(excluded_codes=excluded_codes)
        return last_year_monthly_variable_revenue / (25 * days_per_week / 6)

    def _l10n_be_get_loss_on_commission_amount_sickness(self, result_rules):
        # The reference period of the variable revenue is the previous civil year, except for the sickness of the
        # employees and the extra-legal holidays: the 12 months before the month of the suspension, as for the
        # annual holidays
        self.ensure_one()
        work_entry_type_codes = self.env['hr.work.entry.type'].search([('category_ids.code', '=', 'VARIABLE_SALARY_LOSS')]).mapped('code')
        if not work_entry_type_codes:
            return 0
        worked_day_line_values = self._get_worked_days_line_values(
            work_entry_type_codes, ['number_of_days'], compute_sum=True
        )
        twelve_months_codes = {'011.00'} if self.version_id.is_worker() else {'011.00', '013.00', '017.42'}
        twelve_months_days = sum(
            worked_day_line_values[code]['sum']['number_of_days'] for code in work_entry_type_codes if code in twelve_months_codes)
        civil_year_days = sum(
            worked_day_line_values[code]['sum']['number_of_days'] for code in work_entry_type_codes if code not in twelve_months_codes)
        amount = 0
        if twelve_months_days:
            amount += self._get_last_year_average_daily_variable_revenues() * twelve_months_days
        if civil_year_days:
            amount += self._l10n_be_get_civil_year_average_daily_variable_revenues(result_rules) * civil_year_days
        return amount

    def _l10n_be_get_loss_on_commission_amount_pto(self):
        self.ensure_one()
        worked_day_line_values = self._get_worked_days_line_values(
            ['016.00'], ['number_of_days'], compute_sum=True
        )
        number_of_days = worked_day_line_values['016.00']['sum']['number_of_days']
        daily_variable = self._get_last_year_average_daily_variable_revenues()
        amount = daily_variable * number_of_days
        explanation_info = {
            'daily_variable': float_round(daily_variable, precision_digits=2),
            'number_of_days': float_round(number_of_days, precision_digits=2),
        }
        return amount, explanation_info

    def _get_last_year_average_variable_revenues(self, excluded_codes=None, included_codes=None):
        date_from = self.env.context.get('variable_revenue_date_from', self.date_from)
        first_version_date = self.employee_id._get_first_contract_date()
        if not first_version_date:
            return 0
        start = first_version_date
        end = date_from + relativedelta(day=31, months=-1)
        number_of_month = (end.year - start.year) * 12 + (end.month - start.month) + 1
        number_of_month = min(12, number_of_month)
        if number_of_month <= 0:
            return 0
        return self.employee_id._get_last_year_variable_revenues(
            date_from=date_from, excluded_codes=excluded_codes, included_codes=included_codes) / number_of_month

    def _get_l10n_be_double_holiday_variable_revenues(self, work_entries=None):
        self.ensure_one()
        force_avg_variable_revenues = self._get_input_line_amount('VARIABLE')
        if force_avg_variable_revenues:
            return force_avg_variable_revenues

        versions = self.employee_id.version_ids.filtered(lambda v:
            v.contract_date_start and v.structure_type_id == self.struct_id.type_id
        )
        if not versions:
            return 0.0

        # The Sunday and public holiday premiums are part of the variable remuneration of the double holiday pay, as the
        # social secretariats compute it; not of the other averages of the variable revenues (13th month, simple
        # holiday pay, notice, loss on commission)
        last_year_variable_per_month = self.with_context(
            variable_revenue_date_from=self.date_from
        )._get_last_year_average_variable_revenues(included_codes=DOUBLE_HOLIDAY_VARIABLE_PREMIUM_CODES)

        # We should then prorate the amount regarding leave rights.
        # Example: 5000€ commissions, employee arrived in october
        # Monthly commission = 5000€ / 8 = 625€
        # Then we need to check the legal leaves right (from January to December)
        # He worked 3 months at this company and 3 months from the holiday attest
        # Double variable base = 625 * 10/20 = 287.5€

        year = self.date_from.year - 1
        date_from = date(year, 1, 1)
        date_to = date(year, 12, 31)

        number_of_months = self._compute_double_holiday_assimilated_months(date_from, date_to, versions, work_entries=work_entries)

        attestations = self.employee_id.l10n_be_holiday_attest_ids.filtered(
            lambda attest: attest.year == year and attest.prev_double_holiday_pay_paid > 0,
        )

        if attestations:
            for attest in attestations:
                number_of_months += attest._get_number_of_months() * attest.prev_work_time_rate

        return last_year_variable_per_month * (number_of_months / 12)

    def _get_l10n_be_simple_holiday_variable_revenues(self):
        self.ensure_one()
        force_avg_variable_revenues = self._get_input_line_amount('VARIABLE')
        if force_avg_variable_revenues:
            last_year_variable_per_month = force_avg_variable_revenues
        else:
            last_year_variable_per_month = self.with_context(
                variable_revenue_date_from=self.date_from
            )._get_last_year_average_variable_revenues()

        last_year_variable_per_day = last_year_variable_per_month / 20.83

        legal_time_off_work_entry_types = self.env['hr.work.entry.type'].search([
            ('code', '=', '016.00')
        ])

        legal_leaves_allocations = sum(self.env['hr.leave.allocation'].search([
            ('employee_id', '=', self.employee_id.id),
            ('work_entry_type_id', 'in', legal_time_off_work_entry_types.ids),
            ('state', '=', 'validate'),
            ('date_from', '>', date(self.date_from.year - 1, 12, 31)),
            ('date_from', '<', date(self.date_from.year + 1, 1, 1))
        ]).mapped('number_of_days'))
        result = last_year_variable_per_day * legal_leaves_allocations
        explanation_info = {'explanation': self.env._(
            "Result = Average Variable Revenue per Day (%(last_year)s €) * Legal Leave Allocation Days (%(legal_leaves)s)",
            last_year=float_round(last_year_variable_per_day, precision_digits=2),
            legal_leaves=float_round(legal_leaves_allocations, precision_digits=2)
        )}

        return result, explanation_info

    def _get_last_year_average_warrant_revenues(self):
        warrant_payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ['validated', 'paid']),
            ('struct_id.code', '=', 'BEWARRANT'),
            ('date_from', '>=', self.date_from + relativedelta(months=-12, day=1)),
            ('date_from', '<', self.date_from),
        ], order="date_from asc")
        total_amount = warrant_payslips._get_line_values(['WARRANT_BASIC'], compute_sum=True)['WARRANT_BASIC']['sum']['total']
        first_version_date = self.employee_id._get_first_contract_date()
        if not first_version_date:
            return 0
        # Only complete months count
        if first_version_date.day != 1:
            start = first_version_date + relativedelta(day=1, months=1)
        else:
            start = first_version_date
        end = self.date_from + relativedelta(day=31, months=-1)
        number_of_month = (end.year - start.year) * 12 + (end.month - start.month) + 1
        number_of_month = min(12, number_of_month)
        return total_amount / number_of_month if number_of_month else 0

    def _compute_number_complete_months_of_work(self, date_from, date_to, versions, use_work_rate=False):
        days_by_version_by_year = defaultdict(lambda: defaultdict(dict))
        for day in rrule.rrule(rrule.DAILY, dtstart=date_from + relativedelta(day=1), until=date_to + relativedelta(day=31)):
            days_by_version_by_year[day.year][day.month][day.date()] = None

        public_holidays = [(leave.date_from.date(), leave.date_to.date()) for leave in self.employee_id._get_public_holidays(date_from, date_to)]
        for version in versions:
            attendances_by_date = version.resource_calendar_id._get_attendances_by_date(date_from, date_to)

            previous_week_start = max(version.date_start + relativedelta(weeks=-1, weekday=MO(-1)), date_from + relativedelta(day=1))
            next_week_end = min(version.date_end + relativedelta(weeks=+1, weekday=SU(+1)) if version.date_end else date.max, date_to)
            days_to_check = rrule.rrule(rrule.DAILY, dtstart=previous_week_start, until=next_week_end)
            for day in days_to_check:
                day = day.date()

                # Full time credit time doesn't count
                if version.l10n_be_time_credit and not version.work_time_rate:
                    continue
                if version.date_start <= day <= (version.date_end or date.max):
                    days_by_version_by_year[day.year][day.month][day] = version
                elif (not attendances_by_date[day].filtered(lambda a: a._is_work_period()) or
                        any(date_from <= day <= date_to for date_from, date_to in public_holidays)):
                    days_by_version_by_year[day.year][day.month][day] = 'holiday'

        months = 0
        for invalid_days_by_months in days_by_version_by_year.values():
            for days in invalid_days_by_months.values():
                counter = Counter(days.values())
                if None in counter:
                    continue
                if use_work_rate:
                    under_contract_days = sum(counter.values()) - counter.pop('holiday', 0)
                    for version, n_days in counter.items():
                        months += n_days / under_contract_days * version.work_time_rate
                else:
                    months += 1
        return months

    @api.depends('worked_days_line_ids', 'worked_days_line_ids.number_of_hours', 'date_from', 'date_to', 'employee_id', 'version_id')
    def _compute_l10n_additional_hours_checks(self):
        # The hours a part time worker performs on top of their own schedule, up to a full
        # time one: the plain ones and the ones already paid at +50% / +100%.
        additional_hours_codes = ['003.00', '003.12', '003.08']
        valid_payslips = self.filtered(lambda p: p.date_from and p.date_to and p.employee_id and p.version_id)
        worked_days_data = valid_payslips._get_worked_days_line_values(additional_hours_codes, vals_list=['number_of_hours'])

        payslips_to_check = self.env['hr.payslip']
        for payslip in valid_payslips:
            payslip.l10n_be_sum_additional_hours = 0
            payslip.l10n_be_wrong_additional_hours_on_sundays_or_public_holidays = False
            payslip.l10n_be_additional_hours_during_working_time = False
            payslip.l10n_be_working_hours_limit_per_day_exceeded = False
            payslip.l10n_be_working_hours_limit_per_week_exceeded = False
            if any(worked_days_data[code][payslip.id]['number_of_hours'] for code in additional_hours_codes):
                payslips_to_check |= payslip
        # Few payslips carry additional hours: only their versions need the work intervals and
        # the work entries below, which are by far the most expensive part of the checks.
        if not payslips_to_check:
            return

        # Additional hours and overtime both carry the "Extra Hours" salary rule category,
        # but overtime is authorized beyond the legal daily and weekly maxima, so it never
        # counts towards them.
        overtime_codes = set(self.env['hr.work.entry.type'].search([
            ('is_extra_hours', '=', True),
            ('country_id.code', '=', 'BE'),
        ]).mapped('code')) - set(additional_hours_codes)

        # The periods stay those of all the payslips: the intervals of a flexible calendar are
        # cut in blocks of 7 days from their start.
        global_datetime_from = fields.Datetime.to_datetime(
            min(valid_payslips.mapped('date_from')) + relativedelta(weekday=MO(-1))).replace(tzinfo=UTC)
        global_datetime_to = fields.Datetime.to_datetime(
            max(valid_payslips.mapped('date_to')) + relativedelta(days=1)).replace(tzinfo=UTC)
        all_versions = payslips_to_check.mapped('employee_id.version_ids').filtered('resource_calendar_id')

        calendar_work_intervals = {}
        for calendar in all_versions.mapped('resource_calendar_id'):
            calendar_version = all_versions.filtered(lambda v: v.resource_calendar_id == calendar)
            resources_per_tz = {}
            for version in calendar_version:
                for tz, tz_resources in version._get_resources_per_tz().items():
                    resources_per_tz[tz] = resources_per_tz.get(tz, self.env['resource.resource']) | tz_resources
            calendar_work_intervals[calendar.id] = calendar._work_intervals_batch(
                global_datetime_from, global_datetime_to, resources_per_tz
            )

        # Batch work entries generation
        global_date_from = min(valid_payslips.mapped('date_from')) + relativedelta(weekday=MO(-1))
        global_date_to = max(valid_payslips.mapped('date_to'))
        all_work_entries_vals = all_versions.generate_work_entries(global_date_from, global_date_to)

        entries_by_version = defaultdict(list)
        for entry in all_work_entries_vals:
            entries_by_version[entry.get('version_id')].append(entry)

        for payslip in payslips_to_check:
            payslip.l10n_be_sum_additional_hours = float_round(
                worked_days_data['003.00'][payslip.id]['number_of_hours'], precision_digits=2)

            public_leaves = payslip.version_id.resource_calendar_id.global_leave_ids.filtered(
                lambda leave: leave.work_entry_type_id.code == '006.00')
            public_holidays_dates = {l.date() for l in public_leaves.mapped('date_from')}

            # If the month doesn't start with Monday, take the rest of the first week from the previous month:
            first_week_monday = payslip.date_from + relativedelta(weekday=MO(-1))
            work_entries_vals = []
            for version in payslip.employee_id.version_ids.filtered('resource_calendar_id'):
                for entry in entries_by_version.get(version, []):
                    entry_date = entry['date']
                    if first_week_monday <= entry_date <= payslip.date_to:
                        work_entries_vals.append(entry)

            work_entries_vals_by_date = defaultdict(float)
            work_entries_vals_by_week = defaultdict(float)
            # The maxima concern the additional hours: they are only checked on the days and weeks that carry some.
            additional_hours_dates = set()
            additional_hours_weeks = set()

            for entry in work_entries_vals:
                if entry['work_entry_type_id'].count_as == 'absence' or entry['work_entry_type_id'].code in overtime_codes:
                    continue

                _, week_number, _ = entry['date'].isocalendar()
                work_entries_vals_by_week[week_number] += entry['duration']
                if entry['work_entry_type_id'].code in additional_hours_codes:
                    additional_hours_weeks.add(week_number)

                if entry['date'] < payslip.date_from:
                    continue

                work_entries_vals_by_date[entry['date']] += entry['duration']
                if entry['work_entry_type_id'].code in additional_hours_codes:
                    additional_hours_dates.add(entry['date'])
                    entry_version = entry.get('version_id')

                    effective_version = entry_version if entry_version else payslip.version_id
                    entry_calendar = effective_version.resource_calendar_id

                    cal_intervals_dict = calendar_work_intervals.get(entry_calendar.id, {}) if entry_calendar else {}
                    employee_intervals = cal_intervals_dict.get(effective_version.employee_id.resource_id.id, Intervals())

                    standard_work_duration_on_date = sum(
                        attendance.duration_hours
                        for attendance in entry_calendar.attendance_ids._filter_by_date(entry['date'])
                    )

                    if standard_work_duration_on_date > 0:
                        # only the entries of a time off carry it, not those of a calendar leave
                        for leave in entry.get('leave_ids', ()):
                            leave_start = fields.Datetime.to_datetime(leave.date_from).replace(tzinfo=UTC)
                            leave_end = fields.Datetime.to_datetime(leave.date_to).replace(tzinfo=UTC)

                            leave_interval = Intervals([(leave_start, leave_end, leave)])

                            if employee_intervals & leave_interval:
                                payslip.l10n_be_additional_hours_during_working_time = True
                                break

                    # Within the monthly credit, additional hours carry no supplement, whatever the day. Beyond it,
                    # they carry the overtime one, raised from +50% to +100% on a Sunday or a public holiday (royal
                    # decree of 25 June 1990, art. 3; labour law, art. 29 § 1). Plain hours beyond the credit are
                    # the monthly check's.
                    is_sunday_or_public_holiday = entry['date'].weekday() == 6 or entry['date'] in public_holidays_dates
                    if is_sunday_or_public_holiday and entry['work_entry_type_id'].code == '003.12':
                        payslip.l10n_be_wrong_additional_hours_on_sundays_or_public_holidays = True

            day_limit = 9
            reference_calendar = payslip.version_id._get_reference_calendar()
            week_limit = reference_calendar.full_time_required_hours if reference_calendar else 40
            # the durations of the entries are floats: 4 h + 4 h 40 + 20 min add up to 9.000000000000002
            if any(float_compare(work_entries_vals_by_date[d], day_limit, precision_digits=2) > 0 for d in additional_hours_dates):
                payslip.l10n_be_working_hours_limit_per_day_exceeded = True
            if any(float_compare(work_entries_vals_by_week[w], week_limit, precision_digits=2) > 0 for w in additional_hours_weeks):
                payslip.l10n_be_working_hours_limit_per_week_exceeded = True

    def _l10n_be_get_work_entry_vals_by_date(self, date_from, date_to, work_entries=None):
        work_entries_vals = work_entries or self.employee_id.version_ids.filtered('resource_calendar_id').generate_work_entries(
            date_from, date_to)
        work_entries_vals_by_date = defaultdict(list)
        for vals in work_entries_vals:
            work_entries_vals_by_date[vals['date']].append(vals)
        return work_entries_vals_by_date

    def _l10n_be_get_public_holiday_dates(self, date_from, date_to, versions):
        """ Days of the public holidays from the month of date_from to date_to, in the time zone of each version.
        They are not worked days: e.g. starting on Monday 4 May 2026, after the 1st of May (Friday) and the weekend,
        covers the whole month.

        :return: {version: set of dates}
        """
        self.ensure_one()
        public_holidays = self.employee_id._get_public_holidays(
            date_from + relativedelta(day=1, days=-1), date_to + relativedelta(days=1))
        dates_by_tz = defaultdict(set)
        for tz_name in set(versions.mapped(lambda v: v._get_tz())):
            tz = ZoneInfo(tz_name)
            for leave in public_holidays:
                start = leave.date_from.replace(tzinfo=UTC).astimezone(tz).date()
                # The end is exclusive: a public holiday ending at midnight does not cover the next day
                stop = (leave.date_to.replace(tzinfo=UTC).astimezone(tz) - timedelta(milliseconds=1)).date()
                dates_by_tz[tz_name].update(day.date() for day in rrule.rrule(rrule.DAILY, dtstart=start, until=stop))
        return {version: dates_by_tz[version._get_tz()] for version in versions}

    def _l10n_be_get_version_by_date(self, date_from, date_to, versions):
        self.ensure_one()
        public_holiday_dates_by_version = self._l10n_be_get_public_holiday_dates(date_from, date_to, versions)

        def works_on_date(calendar, public_holiday_dates, d):
            return d not in public_holiday_dates and calendar._works_on_date(d)

        def is_less_or_first_work_day_of_month(calendar, public_holiday_dates, d):
            current_date = date(d.year, d.month, 1)
            while not works_on_date(calendar, public_holiday_dates, current_date):
                current_date += timedelta(days=1)
                if current_date.month != d.month:
                    return False
            return d <= current_date

        version_by_date = defaultdict(lambda: defaultdict(dict))
        for day in rrule.rrule(rrule.DAILY, dtstart=date_from, until=date_to):
            version_by_date[day.year][day.month][day.date()] = None

        for idx, version in enumerate(versions):
            calendar = version.resource_calendar_id
            date_start = max(version.date_start, date_from)
            next_version_start = versions[idx + 1].date_start if idx < len(versions) - 1 else date.max
            date_end = min(
                version.date_end or date.max,
                version.departure_date or date.max,
                date_to,
                next_version_start - relativedelta(days=1),
            )
            public_holiday_dates = public_holiday_dates_by_version[version]
            if is_less_or_first_work_day_of_month(calendar, public_holiday_dates, date_start):
                new_date_start = date_start - relativedelta(days=1)
                while new_date_start.month == date_start.month and not works_on_date(calendar, public_holiday_dates, new_date_start) and date_from <= new_date_start:
                    date_start = new_date_start
                    new_date_start -= relativedelta(days=1)

            new_date_end = date_end + relativedelta(days=1)
            while not works_on_date(calendar, public_holiday_dates, new_date_end) and new_date_end <= date_to and new_date_end < next_version_start:
                date_end = new_date_end
                new_date_end += relativedelta(days=1)

            days_to_check = rrule.rrule(rrule.DAILY, dtstart=date_start, until=date_end)

            for day in days_to_check:
                day = day.date()
                if version_by_date[day.year][day.month][day]:
                    continue
                version_by_date[day.year][day.month][day] = version
        return version_by_date

    def _compute_13th_month_presence_prorated_fixed_wage(self, date_from, date_to, versions):
        self.ensure_one()

        def round_half_days(duration):
            return round(duration * 2) / 2

        unpaid_work_entry_types = self.env['hr.work.entry.type'].search(
            domain=[
                ('code', 'in', ('158.00', '155.00')),
                ('country_code', '=', 'BE'),
            ]
        )

        work_entries_vals_by_date = self._l10n_be_get_work_entry_vals_by_date(date_from, date_to)
        fte_basic = self.version_id._get_contract_wage() / self.version_id.work_time_rate if self.version_id.work_time_rate else 0
        company_avg_hours_per_day = self.version_id._get_reference_calendar().hours_per_day

        payslip_amount = 0
        n_months = 0

        sick_work_entry_types = [
            self.env.ref('hr_work_entry.be_work_entry_type_sick_leave'),  # Sick Time Off
            self.env.ref('hr_work_entry.l10n_be_work_entry_type_long_sick'),  # Long Term Sick
            self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period'),  # days of illness after 30th day
            self.env.ref('hr_work_entry.l10n_be_work_entry_type_partial_incapacity'),  # Partial Incapacity
        ]
        unpredictable_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_unpredictable')

        covered_time_offs = self.env['hr.leave']
        pfa_calendar_sick_days_remaining = 60
        pfa_sick_calendar_days_to_defer = 0  # used to report time off to deduct to next month
        pfa_unpredictable_days_remaining = 10

        all_work_entry_vals = [vals for vals_by_date in work_entries_vals_by_date.values() for vals in vals_by_date]
        sick_work_entries_vals = [vals for vals in all_work_entry_vals if vals['work_entry_type_id'] in sick_work_entry_types]
        unpredictable_work_entries_vals = [vals for vals in all_work_entry_vals if vals['work_entry_type_id'] == unpredictable_work_entry_type]

        # If the first work entry of the year is a sick work entry, check for last year work entries
        # If already sick in december last year, we should deduct these days, except if the employee came back to work
        # for at least the sickness relapse period (14 calendar days before 2026, 56 since 2026)
        first_date_of_year = min(work_entries_vals_by_date)
        work_entries_first_day = [vals for vals in all_work_entry_vals if vals['date'] == first_date_of_year]
        if work_entries_vals_by_date.values() and all(we['work_entry_type_id'] in sick_work_entry_types for we in work_entries_first_day):
            last_year_work_entries_vals = self.employee_id.version_ids.filtered('resource_calendar_id').generate_work_entries(
                date_from - relativedelta(years=1),
                date_to - relativedelta(years=1))
            last_date_of_last_year = max(vals['date'] for vals in last_year_work_entries_vals) if last_year_work_entries_vals else False
            work_entries_last_day = [vals for vals in last_year_work_entries_vals if vals['date'] == last_date_of_last_year]
            if last_year_work_entries_vals and all(we['work_entry_type_id'] in sick_work_entry_types for we in work_entries_last_day):
                last_year_sick_work_entries_vals = [vals for vals in last_year_work_entries_vals if vals['work_entry_type_id'] in sick_work_entry_types]
                # Check if has worked for the relapse period consecutive days. If yes, then do not deduct last year sick days
                # We ignore half days of sickness, as sick time off are not taken in half days in Belgium
                relapse_period = self.env['hr.rule.parameter'].sudo()._get_parameter_from_code(
                    'sickness_relapse_period_days', date=date_from)
                has_worked_relapse_period = False
                consecutive_work_days_counter = 0
                current_date = date_from
                while current_date < date_to:
                    work_entries_vals_date = work_entries_vals_by_date.get(current_date)
                    if not work_entries_vals_date or any(vals['work_entry_type_id'] not in sick_work_entry_types for vals in work_entries_vals_date):
                        consecutive_work_days_counter += 1
                    else:
                        consecutive_work_days_counter = 0
                        leave_ids = self.env['hr.leave']
                        for vals in work_entries_vals_date:
                            if vals.get('leave_ids'):
                                leave_ids |= vals['leave_ids']
                        if leave_ids:
                            current_date = max(leave_ids.mapped('date_to')).date() + relativedelta(days=1)
                            continue

                    # If worked the relapse period in consecutive calendar days, counter is set to 60 days for the year
                    if consecutive_work_days_counter >= relapse_period:
                        has_worked_relapse_period = True
                        break
                    current_date += relativedelta(days=1)

                if not has_worked_relapse_period:
                    last_year_sick_calendar_days = 0
                    last_year_covered_time_offs = self.env['hr.leave']
                    last_year_sick_work_entries_vals_by_date = defaultdict(list)
                    for vals in last_year_sick_work_entries_vals:
                        last_year_sick_work_entries_vals_by_date[vals['date']].append(vals)

                    for sick_wes_vals in last_year_sick_work_entries_vals_by_date.values():
                        for sick_we_vals in sick_wes_vals:
                            if 'leave_ids' in sick_we_vals:
                                if sick_we_vals['leave_ids'] not in last_year_covered_time_offs:
                                    leaves = sick_we_vals['leave_ids']
                                    last_year_sick_calendar_days += leaves._get_calendar_days(
                                        date_from - relativedelta(years=1),
                                        date_to - relativedelta(years=1)
                                    )
                                    last_year_covered_time_offs |= leaves
                            else:
                                last_year_sick_calendar_days += round_half_days(sick_we_vals['duration'] / company_avg_hours_per_day)

                    pfa_calendar_sick_days_remaining = max(0, pfa_calendar_sick_days_remaining - last_year_sick_calendar_days)

        version_by_date = self._l10n_be_get_version_by_date(date_from, date_to, versions)
        public_holiday_dates_by_version = self._l10n_be_get_public_holiday_dates(date_from, date_to, versions)
        for year, versions_by_month in version_by_date.items():
            for month, version_by_day in versions_by_month.items():

                is_month_dropped = False
                for day, version in version_by_day.items():
                    if not version:
                        is_month_dropped = True
                        break
                    if day in public_holiday_dates_by_version[version]:
                        is_calendar_day = False
                    else:
                        is_calendar_day = version.resource_calendar_id._works_on_date(day)
                    work_entries_vals_date = work_entries_vals_by_date.get(day)
                    if is_calendar_day and (not work_entries_vals_date or all(vals['work_entry_type_id'] in unpaid_work_entry_types for vals in work_entries_vals_date)):
                        is_month_dropped = True
                        break

                if is_month_dropped:
                    continue

                days_in_month = monthrange(year, month)[1]
                monthly_calendar_sick_time_off_days = 0
                monthly_covered_time_offs = self.env['hr.leave']
                days_by_version_counter = Counter(version_by_day.values())
                for version, n_days in days_by_version_counter.items():
                    month_sick_work_entries_vals = [
                        vals for vals in sick_work_entries_vals if vals['date'].month == month and vals['version_id'] == version
                    ]
                    calendar_sick_time_off_days = 0
                    month_sick_work_entries_vals_by_date = defaultdict(list)
                    for vals in month_sick_work_entries_vals:
                        month_sick_work_entries_vals_by_date[vals['date']].append(vals)
                    for sick_wes_vals in month_sick_work_entries_vals_by_date.values():
                        for sick_we_vals in sick_wes_vals:
                            if 'leave_ids' in sick_we_vals:
                                if sick_we_vals['leave_ids'] not in covered_time_offs:
                                    leaves = sick_we_vals['leave_ids']
                                    calendar_sick_time_off_days += leaves._get_calendar_days(
                                        date_from, date_to
                                    )
                                    covered_time_offs |= leaves
                            else:
                                calendar_sick_time_off_days += round_half_days(sick_we_vals['duration'] / company_avg_hours_per_day)

                            # Used to know how many days worked in month
                            if 'leave_ids' in sick_we_vals:
                                if sick_we_vals['leave_ids'] not in monthly_covered_time_offs:
                                    leaves = sick_we_vals['leave_ids']
                                    monthly_calendar_sick_time_off_days += leaves._get_calendar_days(
                                        date(year, month, 1), date(year, month, days_in_month)
                                    )
                                    monthly_covered_time_offs |= leaves
                            else:
                                monthly_calendar_sick_time_off_days += round_half_days(sick_we_vals['duration'] / company_avg_hours_per_day)

                    month_unpredictable_work_entries_vals = [vals for vals in unpredictable_work_entries_vals if vals['date'].month == month]
                    unpredictable_days = len(list({vals['date'] for vals in month_unpredictable_work_entries_vals}))

                    max_sick_days_to_remove = min(monthly_calendar_sick_time_off_days, calendar_sick_time_off_days)
                    sick_days_to_remove = min(n_days, pfa_sick_calendar_days_to_defer + max_sick_days_to_remove)
                    if calendar_sick_time_off_days > sick_days_to_remove:
                        pfa_sick_calendar_days_to_defer += calendar_sick_time_off_days - sick_days_to_remove
                    else:
                        pfa_sick_calendar_days_to_defer -= max(0, sick_days_to_remove - max_sick_days_to_remove)

                    # Remove sick days
                    non_assimilated_days = max(0, sick_days_to_remove - pfa_calendar_sick_days_remaining)
                    pfa_calendar_sick_days_remaining = max(0, pfa_calendar_sick_days_remaining - sick_days_to_remove)

                    # Remove unpredictable days
                    non_assimilated_days += max(0, unpredictable_days - pfa_unpredictable_days_remaining)
                    pfa_unpredictable_days_remaining = max(0, pfa_unpredictable_days_remaining - unpredictable_days)

                    n_days -= non_assimilated_days

                    work_time_rate = version.work_time_rate
                    # Compute the real work time rate if partial incapacity. Partial incapacity should count in the work time rate in the PFA
                    if version.l10n_be_time_credit:
                        work_time_rate = version.resource_calendar_id._l10n_be_get_work_time_rate_med_included(date_from, date_to, version._get_reference_calendar())

                    payslip_amount += ((n_days / days_in_month) / 12) * (fte_basic * work_time_rate)
                    n_months += (n_days / days_in_month)

        first_version_date = self.employee_id._get_first_contract_date()
        if first_version_date.year == self.date_from.year and first_version_date.month >= 7:
            return 0, 0
        return payslip_amount, n_months

    def _l10n_be_get_sick_leave_twelve_months_cutoff_date(self, employee, reference_date):
        return employee._l10n_be_get_sick_leave_twelve_months_cutoff_date(reference_date)

    def _compute_double_holiday_assimilated_months(self, date_from, date_to, versions, base_version=False, work_entries=None, current_time_credit_rate=1.0):
        self.ensure_one()

        work_entries_vals_by_date = self._l10n_be_get_work_entry_vals_by_date(date_from, date_to, work_entries=work_entries)

        non_assimilated_work_entry_type_codes = self.env['hr.work.entry.type'].search([('category_ids.code', '=', 'UNASSIMILATED')]).mapped('code')
        already_processed_leaves = self.env['hr.leave']
        deductions_by_month = defaultdict(float)  # {month: calendar days to deduct}

        version_by_date = self._l10n_be_get_version_by_date(date_from, date_to, versions)
        number_of_months = 0
        # the months are weighed against the current occupation, the current time credit included: its pay is the base
        current_work_time_rate = (base_version or self.version_id).work_time_rate * current_time_credit_rate
        twelve_months_sick_cutoff = self._l10n_be_get_sick_leave_twelve_months_cutoff_date(self.employee_id, date_to)

        for year, versions_by_month in version_by_date.items():
            for month, version_by_day in versions_by_month.items():
                days_by_version_counter = Counter(version_by_day.values())
                days_in_month = monthrange(year, month)[1]

                # ------ Step 1 ------
                # On first encounter of each leave, fill the deductions_by_month for every month it contributes
                # non-assimilated days to. Future months are therefore already populated when reached.
                for day in version_by_day:
                    for work_entry in work_entries_vals_by_date.get(day, []):
                        leaves = work_entry.get('leave_ids', self.env['hr.leave'])
                        for leave in leaves:
                            if leave in already_processed_leaves:
                                continue
                            work_entry_type = work_entry.get('work_entry_type_id') or self.env['hr.work.entry.type']
                            already_processed_leaves |= leave

                            # Non-assimilated: every calendar day of this leave counts.
                            if work_entry_type.code in non_assimilated_work_entry_type_codes:
                                leave_from = max(leave.request_date_from, date_from)
                                leave_end = min(leave.request_date_to, date_to)
                                for dt in rrule.rrule(rrule.MONTHLY, dtstart=leave_from.replace(day=1), until=leave_end):
                                    month_start = dt.date()
                                    deductions_by_month[month_start.month] += leave._get_calendar_days(
                                        month_start, min(leave_end, month_start + relativedelta(day=31))
                                    )

                # ------ Step 2 ------
                # Apply this month's deduction across versions
                month_deduction = deductions_by_month.get(month, 0)
                for version, n_days in days_by_version_counter.items():
                    if version is None:
                        continue
                    actual_deduction = min(n_days, month_deduction)
                    n_days -= actual_deduction
                    # Note: Should consider the real days to reflect on correct version
                    # instead of a arbitrary count for the month
                    month_deduction = max(month_deduction - actual_deduction, 0)
                    if not n_days:
                        continue  # the version's days of the month are all unassimilated

                    work_time_rate = min(1, version.work_time_rate / current_work_time_rate) if current_work_time_rate else 0
                    # Compute the real work time rate if partial incapacity. Partial incapacity should count in the work time rate in the PFA
                    if version.l10n_be_time_credit and twelve_months_sick_cutoff >= date(year, month, 1):
                        assimilated_days = min(n_days, (twelve_months_sick_cutoff - max(version.date_start, date(year, month, 1))).days + 1)
                        non_assimilated_days = n_days - assimilated_days
                        non_assimilated_work_time_rate = work_time_rate * non_assimilated_days / n_days
                        work_time_rate_with_sickness = min(1, version.resource_calendar_id._l10n_be_get_work_time_rate_med_included(date_from, date_to, version._get_reference_calendar()) / current_work_time_rate) if current_work_time_rate else 0
                        assimilated_work_time_rate = work_time_rate_with_sickness * assimilated_days / n_days
                        work_time_rate = non_assimilated_work_time_rate + assimilated_work_time_rate

                    number_of_months += ((n_days / days_in_month) * work_time_rate)
        return number_of_months

    def _get_paid_amount_13th_month(self):
        versions = self.employee_id.version_ids.filtered(lambda v:
            v.contract_date_start and v.structure_type_id == self.struct_id.type_id
        )
        first_version_date = min(self.employee_id._get_first_versions().mapped('date_start') or [False])
        if not versions or not first_version_date:
            return 0.0

        if first_version_date.year == self.date_from.year and first_version_date.month > 6:
            return 0.0

        date_from = max(first_version_date + relativedelta(day=1), self.date_from + relativedelta(day=1, month=1))
        date_to = self.date_to + relativedelta(day=31)

        force_months = self._get_input_line_amount('MONTH')
        if force_months:
            n_months = force_months
            if n_months < 6:
                return 0.0
            fixed_salary = self.version_id._get_contract_wage() * n_months / 12
        else:
            fixed_salary, n_months = self._compute_13th_month_presence_prorated_fixed_wage(date_from, date_to, versions)

        force_avg_variable_revenues = self._get_input_line_amount('VARIABLE')
        if force_avg_variable_revenues:
            avg_variable_revenues = force_avg_variable_revenues
        else:
            avg_variable_revenues = self.with_context(
                variable_revenue_date_from=self.date_from
            )._get_last_year_average_variable_revenues()

        # Fixed salary is already prorated according to n_months, no need to do it again
        paid_amount = fixed_salary + (avg_variable_revenues * n_months / 12)

        # For sales representatives (CP200), there is a limit for the PFA
        if self.version_id.l10n_be_egov3_code == '200' and self.version_id.l10n_be_is_sale_representative:
            category_d_min_salary = self.version_id._get_employee_min_wage(reference_date=self.date_to, salary_scale='D')
            paid_amount = min(paid_amount, max(self.version_id._get_contract_wage(), category_d_min_salary))

        return paid_amount

    def _l10n_be_get_category_dict(self):
        """
        Returns the dict that groups work entry type codes per category:
        {category_name<str>, {code1, code2, code3}<set[str]>
        """
        self.ensure_one()
        return self._rule_parameter('l10n_be_work_entry_categories')

    def _l10n_be_get_we_category(self, work_entry) -> str | None:
        """
        Returns what category (defined in the cp302 docs) a work entry is in
        based on its work entry type code
        """
        self.ensure_one()
        we_categories = self._l10n_be_get_category_dict()
        for category, codes in we_categories.items():
            if work_entry['work_entry_type_id'].code in codes:
                return category
        return None

    def _l10n_be_get_uninterrupted_leave_of_category(self, category: str, reference_datetime) -> dict | None:
        """
        Returns the range of datetime of uninterrupted leave of `category` around
        `reference_time`, or None if none is found.
        An uninterrupted can be a series of leaves that are not interrupted by
        another leave of another category, or by a work time.

        The given category's work entry type codes should be only leave with
        `count_as` set to `absence`
        """
        self.ensure_one()

        date_from = None
        date_to = None

        all_leaves = self.env['hr.leave'].search([
            ('work_entry_type_id.code', 'in', self._l10n_be_get_category_dict()[category]),
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('company_id', 'in', self.env.companies.ids),
            ('work_entry_type_id.count_as', '=', 'absence'),
            ('date_from', '!=', False),
            ('date_to', '!=', False),
        ])
        leaves_before = all_leaves.filtered_domain([('date_from', '<=', reference_datetime)])
        leaves_after = all_leaves.filtered_domain([('date_to', '>=', reference_datetime)])

        # set date_from to start date of earliest consecutive leave
        for leave_before in leaves_before.sorted('date_from', reverse=True):
            work_hours_between_leaves = self.version_id.resource_calendar_id.get_work_hours_count(
                leave_before.date_to,
                date_from or reference_datetime,
                compute_leaves=False,
            )
            if work_hours_between_leaves:
                break  # not consecutive
            date_from = leave_before.date_from

        # set date_to to end date of latest consecutive leave
        for leave_after in leaves_after.sorted('date_from'):
            work_hours_between_leaves = self.version_id.resource_calendar_id.get_work_hours_count(
                date_to or reference_datetime,
                leave_after.date_from,
                compute_leaves=False,
            )
            if work_hours_between_leaves:
                break  # not consecutive
            date_to = leave_after.date_to

        if not date_from or not date_to:
            # reference_datetime is not in a leave of given category
            return None

        return {'start': date_from, 'stop': date_to}

    def _l10n_be_get_uninterrupted_leaves_of_category_in_range(self, category: str, date_start, date_stop) -> list[dict]:
        """
        Return a sorted list of all uninterrupted ranges of leaves that cover
        the given period. The return value is not capped.
        The returned uninterrupted leaves are leave of work entry type of `category`.
        """
        self.ensure_one()

        # convert date_start and date_stop to timezone-naive datetimes
        date_start = date_start.astimezone(UTC).replace(tzinfo=None)
        date_stop = date_stop.astimezone(UTC).replace(tzinfo=None)

        # ranges are of format {'start': date, 'stop': date}
        ranges = []

        category_codes = self._l10n_be_get_category_dict()[category]
        # the same leaves as the ones of _l10n_be_get_uninterrupted_leave_of_category: a refused or pending leave
        # isn't part of an uninterrupted range
        leave_domain = Domain([
            ('work_entry_type_id.code', 'in', category_codes),
            ('employee_id', '=', self.employee_id.id),
            ('company_id', 'in', self.env.companies.ids),
            ('state', '=', 'validate'),
            ('work_entry_type_id.count_as', '=', 'absence'),
        ])

        # first leave in the given range
        leave = self.env['hr.leave'].search(
            leave_domain
            & Domain('date_from', '<=', date_stop)
            & Domain('date_to', '>=', date_start),
            order="date_from asc",
            limit=1,
        )

        while leave:
            ranges.append(
                self._l10n_be_get_uninterrupted_leave_of_category(category, leave.date_from),
            )
            if not ranges[-1]['stop'] or ranges[-1]['stop'] >= date_stop:
                break  # we reached end of range. No need to continue
            # get the leave just after the uninterrupted range
            leave = self.env['hr.leave'].search(
                leave_domain
                & Domain('date_from', '<=', date_stop)
                & Domain('date_to', '>', ranges[-1]['stop']),
                order="date_from asc",
                limit=1,
            )

        return ranges

    def _cp302_get_assimilable_sick_leaves(self, work_entries_of_year, last_work_day: date) -> list[dict]:
        """
        Only one sick period can be assimilated (at a rate of 50%) per year,
        following these conditions:
        - Should be uninterrupted of at least 6 months (even accross years)
        - Only assimilate the days of the current year
        - If the sick period is > than a year, then this whole period can be
        assimilated only once.
        - No more than 6 months per year can be assimilated

        (The above values are from 2026. They're store as rule parameters
        as they're subject to change)

        This function will return the assimilable time of these sick periods

        :param work_entries_of_year: a sorted list of all the work entries from
            the beginning of the year up to the last day of work of the year
        :param last_work_day: the last day worked in the year
        """
        self.ensure_one()

        employee_tz = ZoneInfo(self.employee_id._get_tz())

        # get uninterrupted sick leave ranges in current year
        year = last_work_day.year
        beginning_of_year = datetime(year, 1, 1, tzinfo=employee_tz)
        sick_leave_ranges = self._l10n_be_get_uninterrupted_leaves_of_category_in_range(
            'sick_leave',
            beginning_of_year,
            datetime.combine(last_work_day, time.max, tzinfo=employee_tz),
        )

        if not sick_leave_ranges:
            return []  # no sick leave in current year

        # uninterrupted sick leaves longer than `multi_assimilation_threshold`
        # cannot be assimilated more than once. So we need to know what sick
        # leaves have been assimilated for previous years each time there is a
        # sick leave accross two years
        while sick_leave_ranges[0]['start'].astimezone(employee_tz) < beginning_of_year:
            year -= 1
            beginning_of_year = datetime(year, 1, 1, tzinfo=employee_tz)
            end_of_year = datetime.combine(date(year, 12, 31), time.max, tzinfo=employee_tz)
            uninterrupted_leaves = self._l10n_be_get_uninterrupted_leaves_of_category_in_range(
                'sick_leave', beginning_of_year, end_of_year,
            )
            if uninterrupted_leaves[-1] == sick_leave_ranges[0]:
                # last leave of year is the first leave of the year after.
                uninterrupted_leaves.pop()
            sick_leave_ranges = uninterrupted_leaves + sick_leave_ranges

        # the rest of the function only cares about the date (no need for hours)
        sick_leave_ranges = [
            {'start': range['start'].date(), 'stop': range['stop'].date()}
            for range in sick_leave_ranges
        ]

        # group each range per year they cover
        ranges_per_year = defaultdict(list)
        for date_range in sick_leave_ranges:
            years = range(date_range['start'].year, date_range['stop'].year + 1)
            for year in years:
                ranges_per_year[year].append(date_range)

        def is_assimilable_once(range):
            if not range['stop']:
                return True
            # consecutive sick leaves > this rule param cannot be assimilated twice
            multi_assimilation_threshold = self._rule_parameter('cp302_13th_month_sick_leaves_multi_assimilation_threshold')
            return range['stop'] >= range['start'] + relativedelta(**multi_assimilation_threshold)

        def is_long_enough_to_be_assimilated(range):
            if not range['stop']:
                return True
            # consecutive sick leaves < this rule param cannot be assimilated
            min_uninterrupted_period = self._rule_parameter('cp302_13th_month_sick_leaves_min_uninterrupted_period')
            # the stop date is included: 6 months from 3 March end on 2 September
            return range['stop'] >= range['start'] + relativedelta(**min_uninterrupted_period) - relativedelta(days=1)

        # ranges longer than multi_assimilation_threshold cannot be assimilated
        # more than once, so let's keep track of them when they're assimilated
        ranges_assimilable_once = set()

        # Will contain the actual ranges where sick leaves can be assimilated
        assimilated_ranges = []

        for year in sorted(ranges_per_year.keys()):
            # removing ranges that cannot be assimilated again
            year_ranges = [
                range for range in ranges_per_year[year]
                if frozendict(range) not in ranges_assimilable_once
            ]
            # only ranges >= `min_uninterrupted_period` up to end of year are assimilable
            year_ranges = [
                range for range in year_ranges
                if is_long_enough_to_be_assimilated({
                    'start': range['start'],
                    'stop': min(range['stop'] or date.max, date(year, 12, 31)),
                })
            ]
            if not year_ranges:
                continue  # no range >= 6 months in this year

            # workaround for relativedelta's lack of relational operators
            def is_relativedelta_lte_zero(relative_delta):
                reference = date(2000, 1, 1)
                return reference + relative_delta <= reference

            # all the remaining ranges can be assimilated, but no more than this
            # duration can be assimilated per year
            max_year_assimilable_time = self._rule_parameter('cp302_13th_month_sick_leaves_max_year_assimilable_time')
            remaining_assimilable_time = relativedelta(**max_year_assimilable_time)
            for assimilable_range in sorted(year_ranges, key=lambda r: r['start']):
                if is_relativedelta_lte_zero(remaining_assimilable_time):
                    break  # all time already assimilated for this year
                if is_assimilable_once(assimilable_range):
                    ranges_assimilable_once.add(frozendict(assimilable_range))
                assimilation_start = max(assimilable_range['start'], date(year, 1, 1))
                assimilation_end = min(
                    assimilable_range['stop'] or date.max,
                    assimilation_start + remaining_assimilable_time - relativedelta(days=1),
                    date(year, 12, 31),
                )
                assimilated_ranges.append({'start': assimilation_start, 'stop': assimilation_end})
                # remove the assimilated time from the yearly quota
                remaining_assimilable_time -= relativedelta(assimilation_end + relativedelta(days=1), assimilation_start)

        # work entries in the ranges are the assimilable long sick leaves
        def is_in_assimilated_ranges(date):
            for assimilated_range in assimilated_ranges:
                if assimilated_range['start'] <= date <= assimilated_range['stop']:
                    return True
            return False

        # all the sick leaves in the ranges are the ones we can assimilate
        sick_leave_codes = self._l10n_be_get_category_dict()['sick_leave']
        sick_leave_work_entries = (
            we for we in work_entries_of_year
            if we['work_entry_type_id'].code in sick_leave_codes and is_in_assimilated_ranges(we['date'])
        )

        return [{
            'date': we['date'],
            'hours': we['duration'],
            'rate': self._rule_parameter('cp302_13th_month_sick_leaves_assimilation_rate'),
        } for we in sick_leave_work_entries]

    def _cp302_get_always_assimilable_time(self, work_entries) -> list[dict]:
        """
        Some specific kinds of work entries are always assimilated to the
        employee's worked days.
        This function will return the assimilable time of these work entries
        """
        self.ensure_one()
        always_assimilable_categories = {
            'legal_leave',
            'extra_legal_leave',
            'public_holiday',
            'small_unemployment',
            'compensatory_rest',
            'civic_duty',
            'public_mandate',
            'union_obligation',
            'strike',
            'temporary_unemployment',
            'unemployment_force_majeure',
            'working_time',
        }
        category_dict = self._l10n_be_get_category_dict()
        always_assimilable_codes = {
            code
            for category in always_assimilable_categories
            for code in category_dict[category]
        }
        return [
            {
                'date': we['date'],
                'hours': we['duration'],
                'rate': 1,
            } for we in work_entries
            if we['work_entry_type_id'].code in always_assimilable_codes
        ]

    def _cp302_get_limited_calendar_assimilable_time(self, work_entries_of_year, last_work_day) -> list[dict]:
        """
        Some work entries are limited, not by fixed amount of days per year,
        but rather per calendar period per uninterrupted work entry range.

        e.g.: military service limited to 6 calendar months means that all
        periods of military service can be assimilated up to six months per
        uninterrupted period. Years and working days don't matter.

        This function will return the assimilable time of these work entries

        :param last_work_day: The last day worked by the employee in the year.
        :param work_entries_of_year: a sorted list of all the work entries from
            the beginning of the year up to the last day of work of the year
        """
        self.ensure_one()

        maternity_leave_limit = self._rule_parameter('cp302_13th_month_maternity_leave_calendar_limit')
        military_service_limit = self._rule_parameter('cp302_13th_month_military_service_calendar_limit')
        categories_calendar_limit = {
            'maternity_leave': relativedelta(**maternity_leave_limit),
            'military_service': relativedelta(**military_service_limit),
        }

        # ranges are of format {'start': date, 'stop': date}
        assimilated_ranges = []
        for category, limit in categories_calendar_limit.items():
            # get ranges of consecutive leaves current category in year (not capped to year)
            ranges = self._l10n_be_get_uninterrupted_leaves_of_category_in_range(
                category,
                datetime(last_work_day.year, 1, 1).astimezone(ZoneInfo(self.employee_id._get_tz())),
                datetime.combine(last_work_day, time.max, tzinfo=ZoneInfo(self.employee_id._get_tz())),
            )
            # cap the ranges's stop dates to the categories limit
            for range in ranges:
                max_stop = min(range['start'] + limit - relativedelta(days=1), datetime.combine(last_work_day, time.max))
                if not range['stop'] or range['stop'] > max_stop:
                    range['stop'] = max_stop
            assimilated_ranges += ranges

        def is_in_assimilated_ranges(work_entry):
            for range in assimilated_ranges:
                if range['start'].date() <= work_entry['date'] <= range['stop'].date():
                    return True
            return False

        return [{
            'date': we['date'],
            'hours': we['duration'],
            'rate': 1,
        } for we in work_entries_of_year if is_in_assimilated_ranges(we)]

    def _cp302_get_yearly_limited_assimilable_time(self, work_entries_of_year) -> list[dict]:
        """
        Some specific kind of work entries can only be assimilated with a yearly
        limit (e.g.: max 10 days of paternity leave).
        This function will return the assimilable time of these work entries

        :param work_entries_of_year: a sorted list of all the work entries from
            the beginning of the year up to the last day of work of the year
        """
        self.ensure_one()

        work_hours_per_day = self.version_id.resource_calendar_id.hours_per_day
        # limit per year per work entry category
        remaining_hours = {
            'union_education': work_hours_per_day * self._rule_parameter('cp302_13th_month_union_education_day_limit'),
            'compelling_reason': work_hours_per_day * self._rule_parameter('cp302_13th_month_compelling_reason_day_limit'),
            'paternity_leave': work_hours_per_day * self._rule_parameter('cp302_13th_month_paternity_leave_day_limit'),
            'military_reserve_call': work_hours_per_day * self._rule_parameter('cp302_13th_month_military_reserve_call_day_limit'),
        }

        assimilable_time = []
        for work_entry in work_entries_of_year:
            category = self._l10n_be_get_we_category(work_entry)
            if category not in remaining_hours:
                continue  # work entry is not relevant
            if remaining_hours[category] <= 0:
                continue  # all assimilable hours have been counted
            assimilable_time.append({
                'date': work_entry['date'],
                'hours': min(work_entry['duration'], remaining_hours[category]),
                'rate': 1,
            })
            remaining_hours[category] -= work_entry['duration']

        return assimilable_time

    def _cp302_get_assimilable_partial_incapacities(self, work_entries_of_year):
        """
        The first 12 months of partial incapacity (of at least 66%), following a
        total incapacity, can be assimilated.

        :param work_entries_of_year: a sorted list of all the work entries from
            the beginning of the year up to the last day of work of the year
        """
        # NOTE Odoo currently lacks a way to define partial incapacities
        # correctly. This cannot be reliably implemented as of now.
        return []

    def _cp302_get_prestated_and_assimilated_time(self, date_from, last_work_day):
        """
        For the computation of the thirteenth month for the Joint Committee 302,
        we need to know the number of days that can be counted as days of work.
        There are two categories:
        - Prestated days (days where real work has been done)
        - Assimilated days:
           - Always assimilated (legal leaves, strikes, etc.)
           - Assimilated up to a calendar limit per uninterrupted period
           - Assimilated up to N days/year
           - 12 first months of partial incapacity following total incapacity
           - Six consecutive months of sick leave (with some conditions)
           - Up to 7 days of uninterrupted sick leave (with some conditions)

        :param date_from: the first day where hours can be assimilated. Usually
            the beginning of the year
        :param last_work_day: The last day worked by the employee in the year.
        :return: a list of dict of this format:
            [{
                'date': day of prestated/assimilated time,
                'hours': number of hours prestated/assimilated by self.employee_id,
                'rate': rate of which the hours can be assimilated
            }]
        """
        self.ensure_one()
        work_entries = self.employee_id.generate_work_entries(date_from, last_work_day)
        work_entries.sort(key=lambda we: we['date'])
        return sorted([
            *self._cp302_get_always_assimilable_time(work_entries),
            *self._cp302_get_limited_calendar_assimilable_time(work_entries, last_work_day),
            *self._cp302_get_yearly_limited_assimilable_time(work_entries),
            *self._cp302_get_assimilable_partial_incapacities(work_entries),
            *self._cp302_get_assimilable_sick_leaves(work_entries, last_work_day),
        ], key=lambda pa: pa['date'])

    def _cp302_can_get_13th_month(self, worked_days_in_year: float, last_work_day: date) -> bool:
        """
        Returns whether the employee has the requirements to get a 13th month
        The conditions have been taken from Partena's sectorial documentation
        """
        self.ensure_one()

        # these are the values of hr.departure_reason.l10n_be_reason_code
        departures = {
            'resigned': 343,
            'fired': 342,
            'fired_serious_misconduct': 355,
            'resigned_serious_employer_misconduct': 356,
            'resigned_force_majeure': 352,
            'resigned_retired': 340,
            'resigned_anitcipated_retirement': 354,
            'fired_early_retirement': 353,  # prépension
        }

        # According to the joint committeee, a worker should at least have
        # worked two months in the year, if not, we can count accross previous
        # years for uninterrupted seniority. This the same as regular seniority
        seniority = last_work_day - min(self.employee_id._get_last_consecutive_versions(self.date_to).mapped('date_start')) + timedelta(days=1)
        required_seniority = self._rule_parameter('cp302_13th_month_required_seniority')
        if (
            seniority < timedelta(**required_seniority)
            # limit doesn't apply to temporary workers
            and self.version_id.l10n_be_dimona_category != 'ext'
        ):
            return False

        # NOTE for flexi-jobs, you can only have your thirteenth month if your
        # contract is > than a period, or if you have many successive contracts
        # (< 1 work day between them) for more than this period.
        # This is basically the same as how we compute regular seniority, so we
        # can compare the duration against the seniority
        flx_required_seniority = self._rule_parameter('cp302_13th_month_flx_required_seniority')
        if self.version_id.is_flexi() and seniority < timedelta(**flx_required_seniority):
            return False

        beginning_of_year = date(self.date_to.year, 1, 1)
        seniority_in_year = min(seniority, last_work_day - beginning_of_year + timedelta(days=1))
        departure_reason_code = self.employee_id.departure_reason_id.l10n_be_reason_code

        # an employee resigning due to force majeure can get his 13th month if
        # he worked at least two months during the year
        force_majeure_required_seniority = self._rule_parameter('cp302_13th_month_force_majeure_required_seniority')
        if (
            departure_reason_code == departures['resigned_force_majeure']
            and seniority_in_year < timedelta(**force_majeure_required_seniority)
        ):
            return False

        # fired employees still have their 13th month if they worked a certain period in the year,
        # or if their contract lasted more than a certain period (not their seniority)
        fired_min_y_seniority = self._rule_parameter('cp302_13th_month_fired_min_eligible_year_seniority')
        fired_min_contract_duration = self._rule_parameter('cp302_13th_month_fired_min_eligible_contract_duration')
        if (
            departure_reason_code == departures['fired']
            and not (
                seniority_in_year >= timedelta(**fired_min_y_seniority)
                or last_work_day >= self.version_id.contract_date_start + relativedelta(**fired_min_contract_duration) - relativedelta(days=1)
            )
        ):
            return False
        # same thing if employee resigned due to a serious employer misconduct
        emp_mis_min_y_seniority = self._rule_parameter('cp302_13th_month_emp_mis_min_eligible_year_seniority')
        emp_mis_min_contract_duration = self._rule_parameter('cp302_13th_month_emp_mis_min_eligible_contract_duration')
        if (
            departure_reason_code == departures['resigned_serious_employer_misconduct']
            and not (
                seniority_in_year >= timedelta(**emp_mis_min_y_seniority)
                or last_work_day >= self.version_id.contract_date_start + relativedelta(**emp_mis_min_contract_duration) - relativedelta(days=1)
            )
        ):
            return False

        # resigned employees can have their 13th months if they still work up to
        # the end of the year (including the notice period)
        if departure_reason_code == departures['resigned']:
            return last_work_day >= date(self.date_to.year, 12, 31)

        # fired employees for "faute grave" never get their 13th month
        if departure_reason_code == departures['fired_serious_misconduct']:
            return False

        # employees with determined contract duration (CDD) don't get their 13th
        # month if they end their contract sooner than expected
        if (
            self.version_id.fixed_term
            and departure_reason_code is not False
            and self.employee_id.departure_date
            and self.employee_id.departure_date < self.version_id.contract_date_end
        ):
            return False

        # temporary workers must have worked at least a certain amount of days
        # (prestated & assimilated) in the payment year to get their 13th month
        min_year_worked_days = self._rule_parameter('cp302_13th_month_temporary_workers_min_worked_days_in_year')
        if self.version_id.l10n_be_dimona_category == 'ext' and worked_days_in_year < min_year_worked_days:
            return False

        # students cannot have a 13th month
        if self.version_id.l10n_be_dimona_category == 'stu':
            return False

        # cases explicitly allowed in the documentation:
        if departure_reason_code in (
            departures['resigned_anitcipated_retirement'],
            departures['fired_early_retirement'],
            departures['resigned_retired'],
        ):
            return True

        return True

    def _cp302_get_assimilable_hours_after_contract(self) -> float:
        """
        Per the Joint Committee 302, if the worker stops working for some
        specific reasons, then some days after the end of the contract can still
        be assimilated

        :return: number of hours, after the contract end, in the year, that
                should be assimilated.
        """
        self.ensure_one()

        departure_reason_code = self.employee_id.departure_reason_id.l10n_be_reason_code

        # all the following cases depend on departure reasons
        if not departure_reason_code:
            return 0
        if not (self.date_from <= self.employee_id.departure_date <= self.date_to):
            # this payslip and the employee's departure are not at the same time.
            # this is probably a misconfiguration on the user's side.
            return 0

        # these are the values of hr.departure_reason.l10n_be_reason_code
        departures = {
            'dead': 357,
            'resigned_retired': 340,
            'resigned_anitcipated_retirement': 354,
            'fired_early_retirement': 353,
        }

        work_hours_to_eoy = self.version_id.resource_calendar_id.get_work_hours_count(
            self.employee_id.departure_date,
            date(self.date_to.year, 12, 31),
            compute_leaves=False,
        )

        # days after the end of the contract are still assimilated for retired personnel
        if departure_reason_code in (
            departures['resigned_anitcipated_retirement'],
            departures['resigned_retired'],
        ):
            return work_hours_to_eoy

        # days after the end of the contract are still assimilated (at a certain
        # rate) for early retired personnel (prépension)
        if departure_reason_code == departures['fired_early_retirement']:
            assimilation_rate = self._rule_parameter('cp302_13th_month_early_retirement_assimilation_rate')
            return work_hours_to_eoy * assimilation_rate

        # a time period after the death of the personnel can still be assimilated
        if departure_reason_code == departures['dead']:
            assimilable_death_time = self._rule_parameter('cp302_13th_month_assimilable_death_time')
            work_hours_in_six_mo = self.version_id.resource_calendar_id.get_work_hours_count(
                self.employee_id.departure_date,
                self.employee_id.departure_date + relativedelta(**assimilable_death_time) - relativedelta(days=1),
                compute_leaves=False,
            )
            return min(work_hours_to_eoy, work_hours_in_six_mo)

        return 0

    def _cp302_get_paid_amount_13th_month(self, year_payslips):
        """
        Computes and returns the value of the 13th month the worker should receive
        from the Horeca Social Fund, following the rules defined for the Joint Committee 302.
        """
        self.ensure_one()

        last_work_day = min(
            self.employee_id.l10n_be_get_last_work_day_of_year(self.date_to.year) or date.max,
            self.date_to,
        )
        prestated_and_assimilated_time = self._cp302_get_prestated_and_assimilated_time(
            date(self.date_to.year, 1, 1), last_work_day,
        )

        # we need to know how many days were worked in the year, no matter the
        # duration of the prestations for some conditions for the 13th month
        worked_days_in_year = len({time['date'] for time in prestated_and_assimilated_time})
        if not self._cp302_can_get_13th_month(worked_days_in_year, last_work_day):
            return 0

        accounted_hours = sum(time['hours'] * time['rate'] for time in prestated_and_assimilated_time)

        # if the contract ends before the eoy, then, under some conditions,
        # hours between the end of contract and the eoy can be assimilated
        if last_work_day != date(self.date_to.year, 12, 31):
            accounted_hours += self._cp302_get_assimilable_hours_after_contract()

        # NOTE "personnel rémunéré au pourcentage de service"'s max 13th month would
        # be the (monthly) ONSS contribution, but this worker type is not supported by Odoo
        if self.wage_type == 'hourly':
            # personnel paid per hour (usually workers) should have a base 13th
            # month equal to 4.333 weeks of pay
            weeks_per_month = 4 + 1 / 3
            hours_per_month = self.version_id.resource_calendar_id.hours_per_week * weeks_per_month
            full_13th_month = hours_per_month * self.version_id._get_contract_wage()
        else:
            # personnel paid per month (usually employees) should have a base
            # 13th month equal to their last monthly pay
            full_13th_month = self.version_id._get_contract_wage()

        calendar = self.version_id.resource_calendar_id
        if calendar.calendar_type == 'variable':
            # a planned schedule has no year of its own: a twelfth per weekly hours x 52 / 12 worked or assimilated
            max_workable_hours_in_year = calendar.hours_per_week * 52
        else:
            max_workable_hours_in_year = calendar.get_work_hours_count(
                date(self.date_to.year, 1, 1),
                date(self.date_to.year, 12, 31),
                compute_leaves=False,
            )

        # proratise the result and get the 13th month for the whole year up to self.date_to
        worked_hours_ratio = (accounted_hours / max_workable_hours_in_year) if max_workable_hours_in_year else 0
        thirteen_month = min(full_13th_month, full_13th_month * worked_hours_ratio)

        # we need to deduct what has already been paid during the year if needed
        previous_payslips_of_year = year_payslips.filtered_domain(
            [('date_to', '<', self.date_to)],
        )
        already_paid_13th_month = sum(previous_payslips_of_year.line_ids.filtered_domain([['code', '=', 'CP302THIRTEEN']]).mapped('total'))
        return thirteen_month - already_paid_13th_month

    def _l10n_be_get_paid_double_holiday(self, base_month=False, work_entries=None, get_explanation=False, include_attests=True):
        """
        :param include_attests: add the months of the previous employers' holiday certificates of the previous year,
            whose double holiday pay is recovered separately (DOUBLERECOVERY)
        """
        self.ensure_one()
        double_holiday_pay_domain = self.env['hr.version']._l10n_be_get_double_holiday_pay_domain()
        versions = self.employee_id.version_ids.filtered(lambda v:
            v.contract_date_start and v.structure_type_id == self.struct_id.type_id
        ).filtered_domain(double_holiday_pay_domain)
        if not versions:
            return (0.0, {}) if get_explanation else 0.0

        if not base_month or base_month > self.date_from:
            base_version = self.version_id
        else:
            base_version = self.employee_id._get_version(base_month)
        if not base_version.filtered_domain(double_holiday_pay_domain):
            return (0.0, {}) if get_explanation else 0.0

        # 92% of the gross pay of the month the holidays start (art. 38, 2° AR 30.03.1967): under time credit, the pay
        # of the hours still worked (a partial resumption after an incapacity, 122.04, keeps the contract's pay); with
        # the benefits in kind bearing ONSS (art. 38bis only leaves out what bears none)
        holiday_month = base_month if base_month and base_month <= self.date_from else self.date_from
        time_credit_rate = 1.0
        if base_version.l10n_be_time_credit:
            calendar, reference_calendar = base_version.resource_calendar_id, base_version._get_reference_calendar()
            month_start, month_end = holiday_month.replace(day=1), holiday_month + relativedelta(day=31)
            occupied = calendar._l10n_be_get_work_time_rate_time_credit_included(month_start, month_end, reference_calendar)
            if occupied:
                time_credit_rate = min(1.0, calendar._l10n_be_get_work_time_rate_med_included(
                    month_start, month_end, reference_calendar) / occupied)
        # an employee paid by the hour gets the monthly wage of his hours (hourly wage * weekly hours * 13 / 3)
        basic = base_version._l10n_be_get_monthly_wage(holiday_month.year) * time_credit_rate + sum(
            self.env['hr.rule.parameter']._get_parameter_from_code(parameter_code, holiday_month, raise_if_not_found=False) or 0.0
            for field_name, parameter_code in BIK_RULE_PARAMETERS.items() if base_version[field_name])
        force_months = self._get_input_line_amount('MONTH')

        year = self.date_from.year - 1
        date_from = date(year, 1, 1)
        date_to = date(year, 12, 31)
        pre_attestation = 0

        if force_months:
            number_of_months = force_months
            fixed_salary = basic * number_of_months / 12
        else:
            number_of_months = self._compute_double_holiday_assimilated_months(
                date_from, date_to, versions, base_version, work_entries, current_time_credit_rate=time_credit_rate)
            fixed_salary = (number_of_months / 12) * basic
            attests = self.employee_id.l10n_be_holiday_attest_ids.filtered(
                lambda a: include_attests and a.year == year and a.prev_double_holiday_pay_paid > 0)
            # basic is already the pay of the current occupation: the certificate months are weighed like the
            # months worked here, by the certificate fraction over the current one, capped at 1 (a fraction that
            # was higher before keeps the current pay)
            current_work_time_rate = base_version.work_time_rate * time_credit_rate
            for attest in attests:
                attest_work_time_rate = min(1, attest.prev_work_time_rate / current_work_time_rate) if current_work_time_rate else 0
                attestation = basic * (attest._get_number_of_months() / 12) * attest_work_time_rate
                fixed_salary += attestation
                pre_attestation += attestation

        explanation_info = {k: float_round(v, precision_digits=2) for k, v in [('basic', basic), ('months', number_of_months), ('pre_attestation', pre_attestation)]}
        return (fixed_salary, explanation_info) if get_explanation else fixed_salary

    def _get_paid_amount_cct90_bonus_plan(self):
        self.ensure_one()
        return self._get_input_line_amount('CCT90BONUSPLAN')

    def _is_active_belgian_languages(self):
        active_langs = self.env['res.lang'].with_context(active_test=True).search([]).mapped('code')
        return any(lang in ['fr_BE', 'fr_FR', 'nl_BE', 'nl_NL', 'de_DE'] for lang in active_langs)

    def _get_postponed_time_off_to_pay(self):
        self.ensure_one()
        return self.env['hr.leave.allocation']._read_group([
            ('employee_id', '=', self.employee_id.id),
            ('state', '!=', 'refuse'),
            ('work_entry_type_id.code', '=', '142.24'),
            ('date_from', '>=', self.date_from + relativedelta(years=1, month=1, day=1)),
            ('date_from', '<=', self.date_from + relativedelta(years=1, month=12, day=31)),
        ],
            aggregates=['number_of_days:sum']
        )[0][0]

    def _get_sum_european_time_off_days(self, check=False):
        self.ensure_one()
        two_years_payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_to', '<=', date(self.date_from.year, 12, 31)),
            ('date_from', '>=', date(self.date_from.year - 2, 1, 1)),
            ('state', 'in', ['validated', 'paid']),
        ])
        european_time_off_amount = two_years_payslips.filtered(lambda p: p.date_from.year < self.date_from.year)._get_worked_days_line_values(['142.20'], ['amount'], True)['142.20']['sum']['amount']
        already_recovered_amount = two_years_payslips._get_line_values(['EU_LEAVE_DEDUC'], compute_sum=True)['EU_LEAVE_DEDUC']['sum']['total']
        return european_time_off_amount + already_recovered_amount

    def _is_invalid(self):
        invalid = super()._is_invalid()
        translated_from = self.env.context.get('translated_from')
        if self.country_code == 'BE' and translated_from:
            original_lang = self.env['res.lang'].with_context(active_test=False).search([('code', '=', translated_from)], limit=1)
            translation_message = self.env._(
                'This document is a translation, only the original %(language)s document holds legal value.',
                language=original_lang.name or translated_from)
            # Keep the draft status visible on the translation of a draft payslip
            return f"{invalid} {translation_message}" if invalid else translation_message
        return invalid

    def _get_negative_net_rule(self):
        self.ensure_one()
        if self.struct_id.code == 'BEMONTHLY':
            return self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_negative_net')
        return super()._get_negative_net_rule()

    def _issues_dependencies(self):
        return super()._issues_dependencies() + [
            'payroll_config_id.l10n_be_employer_category_id',
            'version_id.l10n_be_joint_committee_id', 'version_id.l10n_be_salary_scale_id',
            'employee_id.private_email', 'employee_id.work_email',
            ]

    def _l10n_be_get_missing_information_issues(self):
        """ Return the issues about the employee information required to generate the payslips """
        versions_with_scales = self.version_id._l10n_be_filter_with_salary_scales()
        issues_by_payslip = defaultdict(list)
        for payslip in self:
            employee = payslip.employee_id
            employee_action = employee._get_records_action(
                name=self.env._("Employee"),
                context={**self.env.context, 'version_id': payslip.version_id.id},
            )
            if payslip.version_id in versions_with_scales and not payslip.version_id.l10n_be_salary_scale_id:
                issues_by_payslip[payslip].append({
                    'message': self.env._("Salary scale is required for joint committee %(joint_committee)s.",
                        joint_committee=payslip.version_id.l10n_be_joint_committee_id.display_name),
                    'action_text': self.env._("Set Salary Scale"),
                    'action': employee_action,
                    'level': 'danger',
                })
            if employee.private_email and not single_email_re.match(employee.private_email.strip()):
                issues_by_payslip[payslip].append({
                    'message': self.env._("Private email %(email)s has an invalid format", email=employee.private_email),
                    'action_text': self.env._("Fix Email"),
                    'action': employee_action,
                    'level': 'warning',
                })
            if employee.work_email and not single_email_re.match(employee.work_email.strip()):
                issues_by_payslip[payslip].append({
                    'message': self.env._("Work email %(email)s has an invalid format", email=employee.work_email),
                    'action_text': self.env._("Fix Email"),
                    'action': employee_action,
                    'level': 'warning',
                })
        return issues_by_payslip

    def action_confirm_arrear_payslip_done(self):
        return self.with_context(l10n_be_arrear_validation_confirmed=True).action_payslip_done()

    @api.model
    def _get_employees_from_records(self, records):
        if records._name == 'resource.calendar':
            # Schedule warnings (reference working schedule issue) block the employees currently working on
            # these schedules, not the ones that only had a past version on them.
            return self.env['hr.employee'].search([('resource_calendar_id', 'in', records.ids)])
        return super()._get_employees_from_records(records)

    def action_payslip_done(self):
        arrear_slips = self.filtered('l10n_be_arrear_salary')
        res = super().action_payslip_done()
        belgian_slips = self.filtered(lambda p: p.country_code == 'BE')
        belgian_slips._l10n_be_defer_fiscal_date()
        belgian_slips._l10n_be_apply_correction_fiscal_period()
        belgian_slips._l10n_be_flag_274_corrections()
        belgian_slips._check_create_wech006()
        belgian_slips._check_create_wech007()
        belgian_slips._check_create_wech008()
        belgian_slips._check_create_zima002()
        belgian_slips._check_create_zima003()
        for slip in arrear_slips:
            quarter = (slip.date_from.month - 1) // 3 + 1
            slip.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=self.env._('Generate DmfA correction'),
                note=self.env._(
                    'This arrears payslip targets %(year)s Q%(quarter)s. '
                    'Please manually generate a DmfA correction for that quarter.',
                    year=slip.date_from.year, quarter=quarter),
            )

        zero_net_payslips = self.filtered(lambda slip: slip.country_code == 'BE' and slip.net_wage <= 0)
        if zero_net_payslips:
            zero_net_payslips.action_payslip_paid()

        existing_dmfa_reports = self.env['l10n_be.dmfa'].sudo().search([
            ('state', 'in', ['done', 'paid']),
            ('declaration_type', '=', 'original'),
            ('company_id', 'in', self.company_id.root_id.ids),
        ])

        report_date_boundaries = []
        for report in existing_dmfa_reports:
            report_date_boundaries.append((report, report.quarter_start, report.quarter_end))

        for ps in self:
            for report, start_date, end_date in report_date_boundaries:
                # only the declarations of the company of the payslip
                if ps.company_id in report.branch_ids and ps.date_from <= end_date and ps.date_to >= start_date:
                    ps.l10n_be_is_dmfa_reported = False
                    report.is_correction_needed = True

        self._l10n_be_refresh_termination_holidays()
        self._l10n_be_generate_termination_documents()
        return res

    def _l10n_be_flag_274_corrections(self):
        """A filed 274.XX whose period these payslips belong to no longer matches payroll."""
        payslips = self.filtered(lambda p: p.date_from and p.date_to)
        if not payslips:
            return
        filed_reports = self.env['l10n_be.274_xx'].sudo().search([
            ('state', 'in', ['ready', 'done']),
            ('declaration_type', '=', 'original'),
            ('company_id', 'in', payslips.company_id.root_id.ids),
            ('date_start', '<=', max(payslips.mapped('date_to'))),
            ('date_end', '>=', min(payslips.mapped('date_from'))),
        ])
        for report in filed_reports:
            declared = payslips.filtered(
                lambda p: (p.l10n_be_fiscal_date and report.date_start <= p.l10n_be_fiscal_date <= report.date_end)
                or (report.date_start <= p.date_from and p.date_to <= report.date_end))
            if declared and declared.company_id.root_id == report.company_id:
                report.is_correction_needed = True

    def action_payslip_unpaid(self):
        res = super().action_payslip_unpaid()
        self.filtered(lambda p: p.country_code == 'BE')._l10n_be_flag_274_corrections()
        return res

    def action_payslip_cancel(self):
        # a declared payslip cancelled has to be removed from its DMFA with a modification
        declared_dmfas = self.sudo().l10n_be_dmfa_id.filtered(
            lambda d: d.state in ['done', 'paid'] and d.declaration_type == 'original')
        res = super().action_payslip_cancel()
        declared_dmfas.is_correction_needed = True
        self.filtered(lambda p: p.country_code == 'BE')._l10n_be_flag_274_corrections()
        latest_273_xx_report = self.l10n_be_273_line_ids.sheet_id.filtered(
            lambda r: r.state in ['ready', 'done']
        ).sorted('id', reverse=True)[:1]
        if latest_273_xx_report:
            latest_273_xx_report.is_correction_needed = True

        latest_281_xx_report = self.l10n_be_281_xx_ids.filtered(
            lambda r: r.state in ['ready', 'done']
        ).sorted('id', reverse=True)[:1]
        if latest_281_xx_report:
            latest_281_xx_report.is_correction_needed = True
        return res

    def _get_payslips_pdf_lang(self):
        belgian_payslips = self.filtered(lambda p: p.company_id.country_code == 'BE')
        non_belgian_payslips = self - belgian_payslips
        lang_map = {}
        # Non-BE payslips fallback
        if non_belgian_payslips:
            lang_map.update(super(HrPayslip, non_belgian_payslips)._get_payslips_pdf_lang())
        if not belgian_payslips:
            return lang_map

        def base_language(code):
            return code.split('_')[0] if code else ''

        for payslip in belgian_payslips:
            # The legal language is the one of the employer location: the work location of the version,
            # or the DMFA unit of the version address when the work location has no payslip language. Without
            # any payslip language, it is the one of the language region of the location.
            locations = payslip.version_id.work_location_id | payslip.version_id.l10n_be_location_unit
            work_location = next((location for location in locations if location.payslip_language_id), None) \
                or next((location for location in locations if location.competence), locations[:1])
            legal_lang = work_location.payslip_language_id.code or work_location._l10n_be_get_competence_lang()

            # Skip super(): it falls back to the current user's language when no payslip language is set,
            # so the same payslip could get a different translation depending on who generates it.
            employee_lang = payslip.employee_id.lang or payslip.employee_id.user_id.lang or None

            if not legal_lang or not employee_lang or base_language(employee_lang) == base_language(legal_lang):
                lang_map[payslip] = (legal_lang or employee_lang or self.env.user.lang or self.env.lang, None)
            elif work_location.competence == 'br' and base_language(employee_lang) in ('fr', 'nl'):
                lang_map[payslip] = (employee_lang, None)
            else:
                lang_map[payslip] = (legal_lang, employee_lang)

        return lang_map

    def _prepare_payslip_pdf_content(self, report, languages):
        self.ensure_one()
        if self.company_id.country_code != 'BE':
            return super()._prepare_payslip_pdf_content(report, languages)
        main_lang, second_lang = languages

        pdf_parts = []

        # Main official payslip
        pdf_parts.append(self._generate_payslip_pdf(main_lang, report))

        # Optional second translated payslip
        if second_lang and main_lang != second_lang:
            pdf_parts.append(self._generate_payslip_pdf(second_lang, report, translated_from=main_lang))

        return pdf.merge_pdf(pdf_parts)

    def _generate_payslip_pdf(self, lang, report, translated_from=False):
        # in the document layout of the company of the payslip, not the one of the current company
        pdf_content, _ = self.env['ir.actions.report'].sudo().with_company(self.company_id).with_context(
            lang=lang,
            translated_from=translated_from
        )._render_qweb_pdf(report, self.id)
        return pdf_content

    def _get_pdf_reports(self):
        res = super()._get_pdf_reports()
        report_n = self.env.ref('l10n_be_hr_payroll.action_report_termination_holidays_n')
        report_n1 = self.env.ref('l10n_be_hr_payroll.action_report_termination_holidays_n1')
        for payslip in self:
            if payslip.struct_id.code == 'BEHOLN1':
                res[report_n1] |= payslip
            elif payslip.struct_id.code == 'BEHOLN':
                res[report_n] |= payslip
        return res

    def _get_data_files_to_update(self):
        # Note: file order should be maintained
        return super()._get_data_files_to_update() + [(
            'l10n_be_hr_payroll', [
                'data/hr_rule_parameters_data.xml',
                'data/hr_payroll_structure_data.xml',
                'data/hr_salary_rule_category_data.xml',
                'data/hr_salary_rule_data.xml',
            ])]

    def _get_versions_with_company_car_within_payslip_period(self):
        self.ensure_one()

        versions = self.env['hr.version'].browse(self._get_period_contracts()).filtered('car_id')
        return versions

    def _get_be_contract_days_in_payslip_range_prorata(self, date_start, date_end):
        """
        Return the ratio of the payslip month during which the given
        contract period overlaps with the payslip period.
        """
        self.ensure_one()
        if not date_start:
            return 0

        payslip_start = self.date_from
        payslip_end = self.date_to

        overlap_start = max(payslip_start, date_start)
        overlap_end = min(payslip_end, date_end or payslip_end)
        if overlap_start > overlap_end:
            return 0

        days_in_month = monthrange(payslip_end.year, payslip_end.month)[1]
        return ((overlap_end - overlap_start).days + 1) / days_in_month

    @api.model
    def _l10n_be_reduction_beta_g(self, mu_glob, at_least_half_time):
        """Target-group βg factor per μ(glob). Shared between the payslip
        estimation and the DMFA quarterly computation."""
        if mu_glob < 0.275 and not at_least_half_time:
            return 0.0
        if mu_glob < 0.55:
            return 1.0
        if mu_glob < 0.80:
            return 1.0 + (mu_glob - 0.55)
        return 1.0 / mu_glob if mu_glob else 0.0

    @api.model
    def _l10n_be_elderly_reduction_params(self, employee, date_ref, competence):
        """Return (brackets, quarterly_wage_cap) for a given employee / region
        competence ('br', 'wa', ...) at date_ref. Each bracket is a
        (dmfa_code, age_min, age_max, G) tuple; the 'pension' sentinel is
        resolved to the statutory pension age for date_ref.

        Wallonia-specific per-employee overrides:
        - Workers hired pre-2023-07 and aged 55-65 at that date
          keep the legacy 8320 brackets afterwards.
        - Workers hired or became eligible on/after 2026-04-01 have the 8321/8322
        """
        region_map = {'br': 'brussels', 'wa': 'wallonia'}
        region_key = region_map.get(competence)
        if not region_key:
            return [], 0.0
        # this reduction is removed from brussels starting Q3 2026
        if competence == 'br' and date_ref >= date(2026, 7, 1):
            return [], 0.0

        rule_param = self.env['hr.rule.parameter'].sudo()._get_parameter_from_code
        hire_date = employee._get_first_contract_date(date_limit=date_ref)
        # the Walloon reduction is removed for the engagements from 1 July 2026
        if competence == 'wa' and hire_date and hire_date >= date(2026, 7, 1):
            return [], 0.0
        # transition date from the old code 8320 (transition state) to 8321/8322 (permanant codes)
        # if an employee was already under code 8320 he should stay in it , if he only became eligibile after the cutoff date , then he moves to the new codes 8321/8322
        cutoff = date(2023, 7, 1)
        brackets_param_date = date_ref
        if competence == 'wa' and hire_date and employee.birthday:
            eligibility_date = max(
                employee.birthday + relativedelta(years=55),
                hire_date,
            )
            if eligibility_date < cutoff:
                brackets_param_date = cutoff - timedelta(days=1)
        brackets_raw = rule_param(
            f'l10n_be_elderly_reduction_brackets_{region_key}',
            date=brackets_param_date, raise_if_not_found=False,
        ) or []
        pension_age = rule_param(
            'l10n_be_pension_age', date=date_ref, raise_if_not_found=False,
        )
        brackets = [
            (code, amin, pension_age if amax == 'pension' else amax, g)
            for (code, amin, amax, g) in brackets_raw
        ]
        if competence == 'wa' and hire_date and hire_date >= date(2026, 4, 1):
            brackets = [
                (code, 57 if (code == 8321 and g == 'G2') else amin, amax, g)
                for (code, amin, amax, g) in brackets
            ]
        g_amounts = rule_param('l10n_be_target_group_g_amounts', date=date_ref) or {}
        brackets = [
            (code, amin, amax, g_amounts[g.lower()])
            for (code, amin, amax, g) in brackets
        ]
        # 8321 (under 60) is for the workers engaged at that age (at the end of the quarter of the engagement), not for
        # the ones getting older in service
        brackets_8321 = [b for b in brackets if b[0] == 8321]
        if competence == 'wa' and hire_date and brackets_8321:
            hire_age = employee._l10n_be_age_at_quarter_end(employee, hire_date)
            if not min(b[1] for b in brackets_8321) <= hire_age <= max(b[2] for b in brackets_8321):
                brackets = [b for b in brackets if b[0] != 8321]
        age = employee._l10n_be_age_at_quarter_end(employee, date_ref)
        brackets = [b for b in brackets if b[1] <= age <= b[2]]
        if competence == 'wa' and hire_date and hire_date >= date(2026, 4, 1):
            # lower cap for the engagements from 1 April 2026
            cap_code = 'l10n_be_elderly_reduction_cap_wallonia_new_hires'
        elif competence == 'wa':
            cap_code = 'l10n_be_elderly_reduction_cap_wallonia'
        else:
            quarter_end_month = ((date_ref.month - 1) // 3 + 1) * 3
            cap_code = (
                'l10n_be_elderly_reduction_cap_q4'
                if quarter_end_month == 12 and date_ref >= date(2024, 7, 1)
                else 'l10n_be_elderly_reduction_cap_standard'
            )
        cap = rule_param(cap_code, date=date_ref)
        return brackets, cap

    @api.model
    def _l10n_be_elderly_reduction_codes(self):
        """DMFA deduction codes used by the elderly-worker target-group
        reduction, collected from the dated bracket rule parameters so the
        deduction filtering stays in sync with the parameter tables instead
        of a hardcoded list."""
        bracket_values = self.env['hr.rule.parameter.value'].sudo().search([
            ('code', 'in', [
                'l10n_be_elderly_reduction_brackets_brussels',
                'l10n_be_elderly_reduction_brackets_wallonia',
            ]),
        ])
        return {
            bracket[0]
            for value in bracket_values
            for bracket in expr_eval(value.parameter_value)
        }

    def _l10n_be_target_group_reduction_methods(self):
        """Target-group reductions declared in the DMFA: {suffix: (specs, qualifies)}.

        specs(employee, quarter_start) gates one reduction on the conditions of
        the worker and returns declaration specs ({'code', 'g', optional
        'p_max', 'starting_date'}). qualifies(spec, occupation), optional (None),
        checks the conditions assessed per occupation line.

        The amount of each occupation line qualifying for a spec is Pg = G x mu
        x beta_g, see _l10n_be_target_group_occupation_amount. The DMFA declares
        it; the payslips compute the same amounts on the quarter covered so far
        for the reductions of _l10n_be_target_group_reduction_line_codes.
        Extend this dictionary to add a reduction."""
        return {
            'elderly': (self._l10n_be_target_group_specs_elderly, self._l10n_be_target_group_occupation_qualifies_elderly),
            'artist': (self._l10n_be_target_group_specs_artist, self._l10n_be_target_group_occupation_qualifies_artist),
            'unexperienced_flander': (
                self._l10n_be_target_group_specs_unexperienced_flander,
                self._l10n_be_target_group_occupation_qualifies_unexperienced_flander),
            'acs': (self._l10n_be_target_group_specs_acs, None),
        }

    @api.model
    def _l10n_be_target_group_reductions(self):
        """Suffixes of the target-group reductions declared in the DMFA, see
        _l10n_be_target_group_reduction_methods."""
        return list(self._l10n_be_target_group_reduction_methods())

    def _l10n_be_target_group_specs(self, reduction, employee, quarter_start):
        """Declaration specs of the reduction for the worker, see _l10n_be_target_group_reduction_methods."""
        specs_method = self._l10n_be_target_group_reduction_methods().get(reduction, (None, None))[0]
        return specs_method(employee, quarter_start) if specs_method else []

    @api.model
    def _l10n_be_target_group_reduction_line_codes(self):
        """Target-group reductions also computed on the payslips, so that they
        can be taken into account in accounting and invoicing: {suffix: code of
        the salary rule computing it}. On the last payslip of the quarter
        (_l10n_be_is_last_payslip_of_quarter), the rule calls
        _is_l10n_be_target_group_reduction_needed as condition and
        _get_l10n_be_target_group_reduction as amount. The payslips of the
        quarter then add up to what the DMFA declares, as both compute it the
        same way."""
        return {
            'unexperienced_flander': 'ONSSUNEXPERIENCED',
            'elderly': 'ONSSELDERLY',
            'artist': 'ONSSEMPLOYER_ARTIST_REDUCTION',
        }

    def _l10n_be_target_group_specs_elderly(self, employee, quarter_start):
        self.ensure_one()
        if not employee or not employee.birthday:
            return []
        competence = self.version_id.l10n_be_working_region
        if not competence:
            return []
        brackets, cap = self._l10n_be_elderly_reduction_params(employee, quarter_start, competence)
        if competence == 'wa' and self.version_id.l10n_be_work_exemption in ('2', '3', '4', '5'):
            # No Walloon reduction for a worker fully exempted from work during the quarter
            return []
        # TODO : When service_exemption_notion are implemented, in case of wallonia reduction , it should only apply when 0, 7 or 8 are mentionned in service_exemption_notion
        specs = []
        hire_date = employee._get_first_contract_date(date_limit=quarter_start + relativedelta(months=3, days=-1))
        for (code, _amin, _amax, G) in brackets:
            spec = {'code': int(code), 'g': G, 'wage_ceiling': cap}
            # The date of the start of the right, the hire date, is mandatory for 8321, and for 8322 from 2026/2
            if hire_date and (int(code) == 8321 or (int(code) == 8322 and quarter_start >= date(2026, 4, 1))):
                spec['starting_date'] = hire_date.isoformat()
            specs.append(spec)
        return specs

    def _l10n_be_target_group_occupation_qualifies_elderly(self, spec, occupation):
        """The reference wage S of the occupation line must not exceed the
        ceiling of the region."""
        reference_wage = occupation['reference_wage']
        return bool(reference_wage and reference_wage <= spec['wage_ceiling'])

    def _l10n_be_target_group_specs_unexperienced_flander(self, employee, quarter_start):
        """Flemish NSSO reduction for unexperienced employees (DMFA 6340),
        conditions on the worker for the quarter: the quarter belongs to the 4
        quarters of the right, and the employee had not reached the legal
        pension age on the last day of the quarter of entry into service. The
        conditions on the occupation line are checked by
        _l10n_be_target_group_occupation_qualifies_unexperienced_flander.
        https://www.socialsecurity.be/employer/instructions/dmfa/nl/latest/instructions/deductions/structuralreduction_targetgroupreductions/persons_without_recent_sustained_work_experience_vl.html
        """
        self.ensure_one()
        employee = employee or self.employee_id
        current_quarter = date_utils.get_quarter(quarter_start)[0]
        engagement_date = self._get_l10n_be_unexperienced_engagement_date(employee, current_quarter)
        # The right covers the quarter of the hiring and the 3 following ones.
        if not engagement_date or current_quarter > self._l10n_be_unexperienced_last_quarter(engagement_date):
            return []
        birthday = employee.sudo().birthday
        if not birthday:
            return []
        parameters = self.env['hr.rule.parameter'].sudo()
        entry_quarter_end = date_utils.get_quarter(engagement_date)[1]
        pension_age = parameters._get_parameter_from_code(
            'l10n_be_pension_age', date=entry_quarter_end, raise_if_not_found=False)
        if pension_age and relativedelta(entry_quarter_end, birthday).years >= pension_age:
            return []
        # The reduction exists from 2025 (its wage ceiling is only defined from then)
        wage_ceiling = parameters._get_parameter_from_code(
            'l10n_be_unexperienced_salary_ceiling', date=quarter_start, raise_if_not_found=False)
        if not wage_ceiling:
            return []
        return [{
            'code': 6340,
            'g': parameters._get_parameter_from_code('l10n_be_target_group_g_amounts', date=quarter_start)['g1'],
            'wage_ceiling': wage_ceiling,
            'starting_date': engagement_date.isoformat(),
        }]

    def _l10n_be_target_group_occupation_qualifies_unexperienced_flander(self, spec, occupation):
        """Conditions on the occupation line, as the reduction is computed per
        occupation line: it is granted for an occupation in a Flemish
        establishment unit, of an employee the version certifies as eligible,
        whose reference wage S of the line is strictly lower than the ceiling."""
        version = occupation['version']
        reference_wage = occupation['reference_wage']
        return bool(
            version.l10n_be_onss_reduction_unexperienced_employees_flander
            and version.l10n_be_working_region == 'fl'
            # A line without remuneration has no reference wage to compare the ceiling with
            and reference_wage
            and reference_wage < spec['wage_ceiling']
        )

    @api.model
    def _l10n_be_unexperienced_last_quarter(self, engagement_date):
        """Start of the last quarter covered by the right opened at
        engagement_date: the quarter of entry into service and the 3 that
        follow."""
        return date_utils.get_quarter(engagement_date)[0] + relativedelta(months=9)

    @api.model
    def _get_l10n_be_unexperienced_engagement_date(self, employee, current_quarter):
        """Contract start date of the engagement opening the reduction right
        current_quarter belongs to, if any.

        The right is granted for the quarter of entry into service and the 3
        quarters that follow, whether or not the employee is occupied during
        them: a quarter without occupation, above the wage ceiling or worked
        outside Flanders still counts towards the maximum of 4. A re-engagement
        inside that window is part of the same employment period; a later one
        opens a new right, provided the employee meets all the conditions again
        (which the flag on the version certifies). Only the engagements flagged
        open a right, looked up on all the employees sharing the NISS in the
        company, a rehire being a new employee.
        https://www.vlaanderen.be/doelgroepvermindering-voor-personen-zonder-recente-duurzame-werkervaring
        """
        employees = employee.sudo()
        if employee.niss and employee.niss != '/':
            # A rehired employee is a new employee, the former one being archived:
            # the same person is found by the NISS in the company, as in the DMFA
            employees = self.env['hr.employee'].sudo().with_context(active_test=False).search([
                ('niss', '=', employee.niss),
                ('company_id', '=', employee.company_id.id),
            ])
        # Only an engagement certified for the reduction opens a right
        contract_starts = employees.with_context(active_test=True).version_ids.filtered(
            lambda version: version.contract_date_start and version.l10n_be_onss_reduction_unexperienced_employees_flander
        ).mapped('contract_date_start')
        engagement_date = None
        for contract_start in sorted(set(contract_starts)):
            quarter = date_utils.get_quarter(contract_start)[0]
            if quarter > current_quarter:
                break
            if engagement_date is None or quarter > self._l10n_be_unexperienced_last_quarter(engagement_date):
                engagement_date = contract_start
        return engagement_date

    @api.model
    def _l10n_be_target_group_occupation_amount(self, spec, occupation, mu_global):
        """Pg = G x mu x beta_g of an occupation line, capped at p_max if any.
        Shared by the payslips and the declaration."""
        # No minimum for the reductions of the artists (4300) and of the subsidised contract employees (ACS)
        at_least_half_time = occupation['at_least_half_time'] or spec['code'] in (4000, 4001, 4300)
        amount = round_eurocent(spec['g'] * occupation['mu'] * self._l10n_be_reduction_beta_g(
            mu_global, at_least_half_time))
        if spec.get('p_max') is not None:
            amount = min(amount, spec['p_max'])
        return amount

    @api.model
    def _l10n_be_target_group_occupation_qualifies(self, reduction, spec, occupation):
        """Whether the occupation line meets the conditions of the reduction
        assessed per occupation line, if the reduction has any."""
        qualifies_method = self._l10n_be_target_group_reduction_methods().get(reduction, (None, None))[1]
        return qualifies_method(spec, occupation) if qualifies_method else True

    @api.model
    def _l10n_be_target_group_occupation(self, payslips, mu, hours_per_week, reference_wage):
        """An occupation line as the target-group reductions see it, built the
        same way by the payslips and by the declaration, from the payslips of
        the line, its fraction of prestations mu, the weekly hours of the worker
        and its reference wage S."""
        # The line is assessed on the version of its last payslip
        version = payslips.sorted('date_to')[-1:].version_id
        uu = version._get_reference_calendar().full_time_required_hours if version else 0
        return {
            'version': version,
            'payslips': payslips,
            'mu': mu,
            'at_least_half_time': hours_per_week >= uu / 2.0,
            'reference_wage': reference_wage,
        }

    def _l10n_be_group_payslips_by_occupation(self, payslips):
        """[(versions, payslips)] of the occupation lines of the employee covered
        by payslips, a payslip belonging to the line of its version, as in the
        declaration (see DMFAWorker._prepare_occupations)."""
        self.ensure_one()
        occupation_groups = []
        # Only the lines of the given payslips are needed, rather than the whole history of the employee
        occupation_data = payslips.version_id.filtered('active').sorted('date_start', reverse=True)._get_occupation_dates()
        for versions, _date_from, _date_to in occupation_data:
            slips = payslips.filtered(lambda p, versions=versions: p.version_id in versions)
            if slips:
                occupation_groups.append((versions, slips))
        return occupation_groups

    def _l10n_be_get_quarter_payslips_so_far(self, validated_quarter_payslips, same_person=True):
        """The payslips of the quarter generated so far, this one included: the
        validated ones and the draft ones of the same payrun already computed,
        a payrun computing its payslips in sequence. Shared by the quarterly
        reductions computed on the payslips (structural and target groups).
        With same_person, the payslips of the same person rehired as another
        employee are included: the declaration groups the payslips by NISS."""
        self.ensure_one()
        quarter_start, quarter_end = date_utils.get_quarter(self.date_to)
        payslips = validated_quarter_payslips | self
        employees = self.employee_id
        niss = self.employee_id.niss
        if same_person and niss and niss != '/':
            employees = self.env['hr.employee'].sudo().with_context(active_test=False).search([
                ('niss', '=', niss),
                ('company_id', '=', self.company_id.id),
            ])
            # Same quarter as the declaration and validated_quarter_payslips: the payslips ending in it
            payslips |= self.env['hr.payslip'].search([
                ('employee_id', 'in', (employees - self.employee_id).ids),
                ('state', 'in', ['validated', 'paid']),
                ('date_to', '>=', quarter_start),
                ('date_to', '<=', quarter_end),
            ])
        if self.payslip_run_id:
            payslips |= self.payslip_run_id.slip_ids.filtered(
                lambda p: p.employee_id in employees
                and p.date_from >= quarter_start
                and p.date_to <= quarter_end
                and p.state == 'draft'
                and p.line_ids
            )
        return payslips

    def _get_l10n_be_target_group_occupations(self, quarter_payslips, result_rules):
        """The occupation lines of the quarter as covered by quarter_payslips,
        the payslips generated so far, this one included: the quarter is treated
        as if it stopped here. Built the same way as the declaration builds
        them, see DMFAWorker._prepare_occupation_deductions."""
        self.ensure_one()
        dmfa = self.env['l10n_be.dmfa']
        # This payslip is still being computed: its own amounts come from the
        # rules already computed rather than from its lines
        return [
            self._l10n_be_target_group_occupation(
                payslips,
                mu=dmfa._get_l10n_be_mu(payslips[:1].version_id, payslips=payslips),
                hours_per_week=payslips.sorted('date_to')[-1].version_id.resource_calendar_id.hours_per_week or 0.0,
                reference_wage=dmfa._get_l10n_be_reference_wage(
                    payslips[:1].version_id, payslips=payslips.with_context(current_payslip_id=self.id), result_rules=result_rules),
            )
            for _versions, payslips in self._l10n_be_group_payslips_by_occupation(quarter_payslips)
            # A flexi-job gets no reduction and its hours stay out of μ, as in the declaration
            if not payslips[:1].version_id.is_flexi()
        ]

    def _l10n_be_target_group_reduction_values(self, reduction, validated_quarter_payslips, result_rules):
        """(earned, granted) for a target-group reduction computed on the
        payslips: earned is the reduction of the quarter covered so far, summed
        over the specs and the occupation lines qualifying for them; granted is
        what the earlier payslips of the quarter already granted."""
        self.ensure_one()
        quarter_payslips = self._l10n_be_get_quarter_payslips_so_far(validated_quarter_payslips)
        occupations = self._get_l10n_be_target_group_occupations(quarter_payslips, result_rules)
        mu_global = sum(occupation['mu'] for occupation in occupations)
        specs = self._l10n_be_target_group_specs(reduction, self.employee_id, date_utils.get_quarter(self.date_to)[0])
        earned = sum(
            self._l10n_be_target_group_occupation_amount(spec, occupation, mu_global)
            for spec in specs
            for occupation in occupations
            if self._l10n_be_target_group_occupation_qualifies(reduction, spec, occupation)
        )
        line_code = self._l10n_be_target_group_reduction_line_codes()[reduction]
        earlier_payslips = quarter_payslips - self
        # The lines are signed as a reduction of the employer contributions
        granted = -sum(earlier_payslips.line_ids.filtered(lambda line: line.code == line_code).mapped('total'))
        return earned, granted

    def _l10n_be_target_group_reduction_may_apply(self, reduction, validated_quarter_payslips):
        """Cheap check before computing the reduction on the payslip: an earlier
        payslip of the quarter granted it (to regularise), or the employee may be
        eligible."""
        self.ensure_one()
        line_code = self._l10n_be_target_group_reduction_line_codes().get(reduction)
        if not line_code or any(line.code == line_code for line in validated_quarter_payslips.line_ids):
            return True
        if reduction == 'unexperienced_flander':
            # Only an engagement certified for the reduction opens the right
            return any(version.l10n_be_onss_reduction_unexperienced_employees_flander for version in self.employee_id.version_ids)
        if reduction == 'elderly':
            # A regional reduction, by the age of the worker
            return bool(self.employee_id.birthday and self.version_id.l10n_be_working_region in ('br', 'wa'))
        if reduction == 'artist':
            return self.version_id.l10n_be_worker_code_id.dmfa_code in ('046', '047')
        return True

    def _is_l10n_be_target_group_reduction_needed(self, reduction, validated_quarter_payslips, result_rules):
        """Whether to put a line for the reduction on this payslip, the last one
        of the quarter (checked by the rule): something is earned, or the earlier
        payslips of the quarter granted an amount to regularise."""
        if not self._l10n_be_target_group_reduction_may_apply(reduction, validated_quarter_payslips):
            return False
        earned, granted = self._l10n_be_target_group_reduction_values(reduction, validated_quarter_payslips, result_rules)
        return not float_is_zero(earned, precision_digits=2) or not float_is_zero(granted, precision_digits=2)

    def _l10n_be_target_group_reduction_cap(self, reduction, validated_quarter_payslips, result_rules):
        """The most the target-group reduction can grant on the quarter covered
        so far: the employer's basic contributions left after the structural
        reduction and the other target-group reductions computed on the
        payslips, as the declaration caps them (see
        DMFAWorker._cap_target_group_reductions). None without contribution
        rates, the declaration not capping then either."""
        self.ensure_one()
        if not self._get_onss_global_rates()['total_rate']:
            return None
        earlier_payslips = self._l10n_be_get_quarter_payslips_so_far(validated_quarter_payslips) - self
        other_codes = set(self._l10n_be_target_group_reduction_line_codes().values()) - {
            self._l10n_be_target_group_reduction_line_codes()[reduction]}
        # The structural and target-group reductions are negative lines
        codes = {'ONSSEMPLOYERBASIC', 'ONSS_STRUCTURAL'} | other_codes
        quarter_total = sum(earlier_payslips.line_ids.filtered(lambda line: line.code in codes).mapped('total'))
        quarter_total += sum(result_rules[code]['total'] for code in codes if code in result_rules)
        return max(round_eurocent(quarter_total), 0.0)

    def _get_l10n_be_target_group_reduction(self, reduction, validated_quarter_payslips, result_rules):
        """What this payslip grants (negative) or gives back (positive): the
        reduction of the quarter, at most the contributions left (see
        _l10n_be_target_group_reduction_cap), regularised against what the
        earlier payslips of the quarter granted (a correction after the last
        payslip)."""
        earned, granted = self._l10n_be_target_group_reduction_values(reduction, validated_quarter_payslips, result_rules)
        cap = self._l10n_be_target_group_reduction_cap(reduction, validated_quarter_payslips, result_rules)
        if cap is not None:
            earned = min(earned, cap)
        return round_eurocent(granted - earned)

    def _l10n_be_target_group_specs_artist(self, employee, quarter_start):
        # https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/structuralreduction_targetgroupreductions/artists.html
        self.ensure_one()
        threshold = 3 * (self.env['hr.rule.parameter'].sudo()._get_parameter_from_code(code='l10n_be_average_guaranteed_minimum_monthly_income', date=quarter_start, raise_if_not_found=False) or 0.0)
        if self.version_id.l10n_be_worker_code_id.dmfa_code in ['046', '047'] and self.version_id.l10n_be_working_region != 'fl':
            g_amount = self._rule_parameter('l10n_be_target_group_g_amounts')['g12']
            reduction_max_cap = self._rule_parameter('l10n_be_onss_employer_reduction_artist_cap')
            return [{'code': 4300, 'g': g_amount, 'p_max': reduction_max_cap, 'wage_threshold': threshold}]
        return []

    def _l10n_be_target_group_occupation_qualifies_artist(self, spec, occupation):
        """The reference wage S of the occupation line must reach the threshold."""
        return occupation['reference_wage'] >= spec['wage_threshold']

    def _l10n_be_get_quarterly_structural_deduction(self, result_rules, quarter_payslips):
        """
        To accurately compute the quarterly structural deduction, we use:
        1. All finalized (validated or paid) payslips for the quarter.
        2. Any draft payslips belonging to the current payrun (batch).

        Including draft payslips from the current run handles edge cases like batch corrections
        or multiple contracts in a single month. Because a payrun computes payslips sequentially,
        earlier draft payslips in the batch will have already generated the payslip lines.
        Since we compute the structural deduction for each month and check the previously claimed
        amounts, the total across the payslips in the quarter will be accurate.
        """
        self.ensure_one()
        # The payslips of the employee only, as before (no lookup of the same person by NISS on every payslip)
        payslips = self._l10n_be_get_quarter_payslips_so_far(quarter_payslips, same_person=False).filtered(
            lambda p: p == self or (
                p.version_id.structure_type_id == self.version_id.structure_type_id
                and p.company_id == self.company_id
                and p.line_ids
            )
        )

        # Divide into occupations - based on the working schedule since the working hours affect the structural deduction computation
        occupation_groups = self._l10n_be_group_payslips_by_occupation(payslips)

        # mu global and total structural deduction is computed as the sum of all mu's and deductions for each occupation
        mu_global = sum(self.env['l10n_be.dmfa']._get_l10n_be_mu(slips[:1].version_id, payslips=slips) for _, slips in occupation_groups)
        quarterly_deduction = sum(
            self.env['l10n_be.dmfa']._get_l10n_be_structural_deduction_3000(slips.with_context(current_payslip_id=self.id), mu_global, result_rules)
            for _, slips in occupation_groups
        )
        return quarterly_deduction, payslips

    def _l10n_be_get_monthly_regularized_structural_deduction(self, result_rules, quarter_payslips):
        """
        Compute the monthly structural deduction based on the target quarterly deduction, and regularize it
        based on the deductions already applied in the current quarter.
        """
        self.ensure_one()
        # Compute the deductions that were applied in the previous payslips and subtract from the total deduction to find the
        # deduction (or correction) to apply for the current payslip
        target_quarterly_deduction, payslips = self._l10n_be_get_quarterly_structural_deduction(result_rules, quarter_payslips)
        already_deducted = sum(line.total for line in (payslips - self).line_ids.filtered(lambda line: line.code == "ONSS_STRUCTURAL"))
        return -target_quarterly_deduction - already_deducted

    def _l10n_be_target_group_specs_acs(self, employee, quarter_start):
        self.ensure_one()
        if not self.version_id._l10n_be_is_eligible_for_acs_deduction():
            return []
        quarter_start, quarter_end = date_utils.get_quarter(self.date_to)
        code = 4001 if self.version_id.company_id.current_payroll_config_id.l10n_be_sector in ['public_federal_regional', 'public_other'] else 4000

        payslips = self.env['hr.payslip'].search([
                ('employee_id', '=', self.employee_id.id),
                ('state', 'in', ['validated', 'paid']),
                ('date_from', '>=', quarter_start),
                ('date_to', '<=', quarter_end),
                ('company_id', '=', self.company_id.id),
                ('version_id.structure_type_id', '=', self.version_id.structure_type_id.id)
            ])
        g_amount = sum(line.total for line in payslips.line_ids.filtered(lambda line: line.code == "ONSSEMPLOYERBASIC"))
        dmfa = self.env['l10n_be.dmfa']
        # Without the flexi-jobs, as in the declaration
        mu_global = sum(
            dmfa._get_l10n_be_mu(slips[:1].version_id, payslips=slips)
            for _versions, slips in self._l10n_be_group_payslips_by_occupation(payslips)
            if not slips[:1].version_id.is_flexi()
        )
        for payslip in payslips:
            if payslip.date_to.month in (3, 6, 9, 12):
                payslips = self.env['hr.payslip'].search([
                    ('employee_id', '=', self.employee_id.id),
                    ('state', 'in', ['validated', 'paid']),
                    ('date_from', '>=', quarter_start),
                    ('date_to', '<=', quarter_end),
                    ('company_id', '=', payslip.company_id.id),
                    ('version_id.structure_type_id', '=', payslip.version_id.structure_type_id.id)
                ])
                g_amount -= dmfa._get_l10n_be_structural_deduction_3000(payslips, mu_global)
        return [{'code': code, 'g': g_amount}]

    def _get_l10n_be_onss_acs_reduction(self, result_rules, quarter_payslips):
        self.ensure_one()

        if self.version_id._l10n_be_is_eligible_for_acs_deduction():
            result = -result_rules['ONSSEMPLOYERBASIC']['total'] if result_rules['ONSSEMPLOYERBASIC'] else 0.0
            if self.date_to.month in (3, 6, 9, 12):  # compute and substract ded3000 amount based on niss
                total_quarter_structural_deduction, _ = self._l10n_be_get_quarterly_structural_deduction(result_rules, quarter_payslips)
                result += total_quarter_structural_deduction
            return round(result, 2)
        return 0.0

    def _get_l10n_be_atn_car_regularization_amount(self, result_rules):
        """
        Compute the ATN car regularization for the current payslip.

        The regularization compares:
            - the theoretical ATN after applying the legal minimum &
            - the total ATN already paid on previous payslips plus the current month's ATN,
        over the days covered by the payslips of the year in Odoo. Days without a
        payslip in Odoo (e.g. before the company started using it) are left alone
        as nothing is known about what was paid for them.

        The rule is triggered on:
            - the December payslip, or
            - the employee's final payslip when leaving the company.
        Differences below 1 EUR are ignored.
        """
        self.ensure_one()

        min_legal_car_atn = self.env['hr.rule.parameter']._get_parameter_from_code('min_car_atn', self.date_to, raise_if_not_found=False)
        year_start = self.date_from.replace(month=1, day=1)
        year_end = self.date_to  # can be end of the year or end of the contract
        days_in_year = 366 if isleap(year_start.year) else 365

        versions = self.employee_id._get_versions_with_contract_overlap_with_period(year_start, year_end)
        versions = versions.filtered('car_id')
        if not versions:
            return 0.0

        previous_payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('struct_id', '=', self.struct_id.id),
            ('credit_note', '=', False),
            ('date_from', '>=', year_start),
            ('date_to', '<', self.date_from),
            ('state', 'in', ['validated', 'paid']),
        ])

        covered_days = 0
        theoretical_atn = 0.0
        for payslip in previous_payslips | self:
            for version in versions:
                overlap_start = max(payslip.date_from, version.date_start)
                overlap_end = min(payslip.date_to, version.date_end or payslip.date_to)
                if overlap_start > overlap_end:
                    continue
                days = (overlap_end - overlap_start).days + 1
                theoretical_atn += version.car_id._get_theoretical_car_atn(date=overlap_start) * days / days_in_year
                covered_days += days

        # the final ATN that should have been paid, after applying the legal minimum on the covered period
        atn_to_pay = max(theoretical_atn, min_legal_car_atn * covered_days / days_in_year)
        atn_paid = previous_payslips._get_line_values(['ATN.CAR'], compute_sum=True)['ATN.CAR']['sum']['total']
        atn_paid += result_rules['ATN.CAR']['total'] if 'ATN.CAR' in result_rules else 0.0

        # negative: the employee paid too much and is refunded, positive: he has to pay the difference
        regularization = atn_to_pay - atn_paid
        return regularization if abs(regularization) >= 1.0 else 0.0

    def _get_be_private_car_reimbursement_amount(self, work_entries):
        self.ensure_one()
        code = self.version_id.l10n_be_joint_committee_id.egov3_code
        granted_days_qty = self._get_be_benefit_count('PRIVATE_CAR', work_entries)
        result_rate = 100

        # CP 200 and 302 from February 2026: daily scale
        if code in ['200', '302'] and self.date_from >= date(2026, 2, 1):
            daily_amount = self.version_id._get_private_car_daily_amount(ref_date=self.date_from)
            return (daily_amount, granted_days_qty, result_rate)

        # Otherwise: monthly amount, split on the working days of the reference calendar
        reference_working_days = len([a for a in self.version_id._get_reference_calendar()._get_attendances_by_date(
            self.date_from + relativedelta(day=1),
            self.date_from + relativedelta(day=31),
        ).values() if a])
        if not reference_working_days:
            return (0, 0, result_rate)
        monthly_amount = self.version_id._get_private_car_reimbursed_amount(ref_date=self.date_from)
        # Full month: the monthly amount, even with more granted days than the reference calendar
        if granted_days_qty >= reference_working_days:
            return (monthly_amount / reference_working_days, reference_working_days, result_rate)
        # Partial month: daily rate = monthly amount x 3 months / (13 weeks x 5 days)
        return (monthly_amount * 3 / 13 / 5, granted_days_qty, result_rate)

    def _get_be_private_car_reimursement_amount(self, work_entries):
        # Deprecated (misspelled), kept for compatibility: use _get_be_private_car_reimbursement_amount
        return self._get_be_private_car_reimbursement_amount(work_entries)

    def _get_be_bike_reimbursement_amounts(self, result_rules, work_entries):
        # Returns the daily bike reimbursement split into its exempt and taxable parts. The whole reimbursement is
        # paid: the part above the exempt amount per kilometer, or above the yearly exempt amount, is taxable.
        self.ensure_one()
        version = self.version_id
        quantity = self._get_be_benefit_count('PRIVATE_CAR', work_entries)
        if not result_rules['BASIC']['total'] or not quantity:
            return (0, 0)
        joint_committee_code = self.l10n_be_joint_committee_id.egov3_code or '200'
        # The hotel industry (302) has its own cap, the other joint committees follow the one of the employees (200)
        yearly_maximum = self._rule_parameter(
            'bike_max_reimbursement_yearly_cp302' if joint_committee_code == '302' else 'bike_max_reimbursement_yearly_cp200')
        # ytd includes the current payslip once the rule had its turn, and this helper is called
        # by both rules: substracting the running total gives the previous payslips in both cases.
        already_exempted = result_rules['CYCLE']['ytd'] - result_rules['CYCLE']['total']
        amount = version._get_bike_reimbursed_amount(reference_date=self._get_ytd_reference_date())
        exempt_rate = self._rule_parameter('bike_exempt_reimbursement_per_km', raise_if_not_found=False)
        exempt_amount = min(amount, exempt_rate * version.bike_transport_employee_kilometer * 2) if exempt_rate else amount
        exempt_amount = max(0, min(yearly_maximum - already_exempted, exempt_amount * quantity)) / quantity
        return (exempt_amount, amount - exempt_amount)

    def _get_be_lsa_bike_travel_amounts(self, result_rules, inputs):
        """The lump sum bike commute allowance of the kilometers entered on the payslip, capped yearly, split into
        its exempt part (up to the exempt amount per kilometer) and its taxable part, as the bike reimbursement.

        :return: (exempt amount, taxable amount, kilometers)
        """
        self.ensure_one()
        kilometers = inputs['LSA_BIKE_TRAVEL_KM'].amount if 'LSA_BIKE_TRAVEL_KM' in inputs else 0.0
        if kilometers <= 0:
            return (0, 0, 0)
        # ytd includes the current payslip once the rule had its turn, and this helper is called by both rules:
        # substracting the running total gives the previous payslips in both cases.
        already_paid = sum(
            result_rules[code]['ytd'] - result_rules[code]['total'] for code in ('LSA_BIKE_TRAVEL_KM', 'LSA_BIKE_TRAVEL_KM.TAX'))
        yearly_maximum = self._rule_parameter('representation_fees_bike_travel_max_yearly')
        amount = max(0, min(yearly_maximum - already_paid, self.version_id.l10n_be_lsa_bike_travel_amount * kilometers))
        exempt_rate = self._rule_parameter('bike_exempt_reimbursement_per_km', raise_if_not_found=False)
        exempt_amount = min(amount, exempt_rate * kilometers) if exempt_rate else amount
        return (exempt_amount, amount - exempt_amount, kilometers)

    def _get_be_cp999_flat_rate_social_contributions(self, result_rules):

        monthly_revenues = result_rules['GROSS.M']['total']

        min_amount = self._rule_parameter('l10n_be_dir_flat_rate_deduction_min', raise_if_not_found=False)
        max_amount = self._rule_parameter('l10n_be_dir_flat_rate_deduction_max', raise_if_not_found=False)
        rate_by_threshold = self._rule_parameter('l10n_be_dir_flat_rate_deduction', raise_if_not_found=False)

        if not min_amount or not max_amount or not rate_by_threshold:
            return 0

        base_amount = min_amount
        previous_threshold = 0

        for threshold, rate in sorted(rate_by_threshold.items()):
            if monthly_revenues <= threshold:
                result = base_amount + (monthly_revenues - previous_threshold) * rate
                break
            base_amount += (threshold - previous_threshold) * rate
            previous_threshold = threshold
        else:
            result = min(monthly_revenues, max_amount)
        return min(monthly_revenues, result)

    def _is_extra_hours_qualifying(self, work_entry_type):
        """
        Check if a work entry type qualifies as an overtime giving right to the withholding tax reduction: the
        category of the overtime giving right to the legal overtime premium, as for the 274.44/274.55 exemptions and
        the box 18 of the 281.10 (see :meth:`_l10n_be_get_overtime_category`), with a premium of at least 20%. The
        overtime paid at 100%, without premium (rate 1.0), gives right neither to the reduction nor to the
        exemption, and doesn't consume their yearly cap of hours (art. 154bis CIR 92: the overtime giving right to
        an overtime premium). Without rate (0.0: the overtime to recover of the databases installed before its
        rate was set), the overtime keeps its category. The premium of the line still picks the reduction rate.
        """
        if self._l10n_be_get_overtime_category() not in work_entry_type.category_ids:
            return False
        return not work_entry_type.amount_rate or self._l10n_be_get_overtime_premium_rate(work_entry_type) >= 0.2

    @api.model
    def _l10n_be_get_recoverable_overtime_codes(self):
        """The overtime recovered later: only its premium is paid with the overtime (026.00 50%, 026.01 100%)."""
        return ['026.00', '026.01']

    @api.model
    def _l10n_be_get_overtime_premium_rate(self, work_entry_type):
        """The overtime premium of a work entry type: 1.5 pays the hour and a 50% premium, 0.5 (026.00, hours
        recovered later) pays the 50% premium alone, so both are a 50% premium; 1.0 for an overtime recovered later
        (026.01) is its 100% premium alone. A premium pay category adds its own premium. A premium from 20% to 50%
        gives right to the reduction of 66.81%, a premium of 50% or more to the one of 57.75%, a premium under 20%
        to none."""
        amount_rate = work_entry_type.amount_rate
        if work_entry_type.code in self._l10n_be_get_recoverable_overtime_codes():
            rate = amount_rate
        else:
            rate = amount_rate - 1.0 if amount_rate >= 1.0 else amount_rate
        for category in work_entry_type.category_ids | work_entry_type.optional_category_ids:
            for child in category.children_ids:
                if child.is_premium_pay and child.premium_percentage_hourly_rate > 0:
                    rate += child.premium_percentage_hourly_rate
        return rate

    def _check_withholding_extra_hours_reduction(self):
        self.ensure_one()
        return any(self._is_extra_hours_qualifying(line.work_entry_type_id) for line in self.worked_days_line_ids)

    def _get_withholding_extra_hours_reduction(self):
        self.ensure_one()

        # Art. 275/1 CIR 92 and Annexe III: the yearly cap of overtime hours of the joint committee, as for the
        # exemption of the 274.XX. The 360 hours of the hotel industry (circular 2024/C/6) only apply to it.
        joint_committee = self.version_id.l10n_be_joint_committee_id
        if joint_committee and joint_committee.is_descendant_of(self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')):
            overtime_threshold_code = 'cp302_overtime_threshold_white_cash_register' if self.company_id._l10n_be_has_white_cash_register() else 'cp302_overtime_threshold_not_white_cash_register'
        else:
            overtime_threshold_code = 'cp200_overtime_threshold'
        annual_cap = self.env['hr.rule.parameter']._get_parameter_from_code(overtime_threshold_code, self.date_to, raise_if_not_found=False) or 0.0

        tier1_rate = self.env['hr.rule.parameter']._get_parameter_from_code(
            'overtime_withholding_tax_reduction_rate_tier1', self.date_to, raise_if_not_found=False
        )
        tier2_rate = self.env['hr.rule.parameter']._get_parameter_from_code(
            'overtime_withholding_tax_reduction_rate_tier2', self.date_to, raise_if_not_found=False
        )

        previous_payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', max(date(self.date_from.year, 1, 1), self.version_id.contract_date_start)),
            ('date_to', '<', self.date_from),
            ('state', 'in', ['validated', 'paid']),
        ])

        used_extra_hours = sum(
            line.number_of_hours
            for line in previous_payslips.mapped('worked_days_line_ids')
            if self._is_extra_hours_qualifying(line.work_entry_type_id))

        remaining_hours_cap = max(0.0, annual_cap - used_extra_hours)
        if remaining_hours_cap <= 0:
            return 0.0

        total_deduction = 0.0
        for line in self.worked_days_line_ids:
            if not self._is_extra_hours_qualifying(line.work_entry_type_id):
                continue

            # the overtime premium picks the reduction rate
            line_rate = self._l10n_be_get_overtime_premium_rate(line.work_entry_type_id)

            if line_rate < 0.2:
                continue

            extra_hours = min(line.number_of_hours, remaining_hours_cap)
            if extra_hours <= 0:
                break

            if 0.2 <= line_rate < 0.5:
                deduction_rate = tier1_rate
            else:
                deduction_rate = tier2_rate

            # Art. 154bis and 275/1 CIR 92: the reduction and the employer's exemption (274.44) share one base, the pay
            # of the hours before the premium, at the hourly wage the overtime line is valued at: under a time credit
            # the version's wage is the full-time wage, prorated as the line prorates it for the part-time schedule
            base_amount = extra_hours * line._l10n_be_get_normal_hourly_wage()
            total_deduction += base_amount * deduction_rate
            remaining_hours_cap -= extra_hours

        return total_deduction

    def _get_be_withholding_taxes_transport_deduction(self, work_entries):
        self.ensure_one()

        version = self.version_id

        if version.private_car_employee_kilometer or version.car_id:
            yearly_transport_amount = 0
            if version.car_id:
                yearly_transport_amount += version.car_atn
            if version.private_car_employee_kilometer:
                result, result_qty, result_rate = self._get_be_private_car_reimbursement_amount(work_entries)
                private_car_amount = result * result_qty * result_rate / 100
                yearly_transport_amount += private_car_amount * 12

            yearly_exemption_amount = self._rule_parameter('private_car_withholding_monthly_exemption') * 12
            return min(yearly_transport_amount, yearly_exemption_amount)

        return 0

    def _l10n_be_is_isolated(self):
        self.ensure_one()
        return self.l10n_be_effective_marital in ('divorced', 'single', 'widower', 'separated')

    def _l10n_be_is_coupled(self):
        self.ensure_one()
        return self.l10n_be_effective_marital in ('married', 'cohabitant')

    def _get_be_withholding_taxes_marital_deduction(self):
        self.ensure_one()
        version = self.version_id
        if not version.is_non_resident:
            if version.l10n_be_resident_situation == 'cross_border':
                return 0
            if self._is_eligible_for_bareme_I():
                return self._get_bareme_I_deduction()
            if self._is_eligible_for_bareme_II():
                return self._get_bareme_II_deduction()
            return 0

        # contract non convering all the year
        current_year = self.date_from.year
        if not (version.contract_date_start <= date(current_year, 1, 1) and (not version.contract_date_end or version.contract_date_end >= date(current_year, 12, 31))):
            return self._get_bareme_III_deduction()

        # contract covering all the year
        if version.work_in_belgium_over_75:
            if self._is_eligible_for_bareme_I():
                return self._get_bareme_I_deduction()
            if self._is_eligible_for_bareme_II():
                return self._get_bareme_II_deduction()
            return 0

        return self._get_bareme_III_deduction()

    def _get_bareme_I_deduction(self):
        self.ensure_one()
        return self._rule_parameter('deduct_single_with_income')

    def _get_bareme_II_deduction(self):
        self.ensure_one()
        return 2 * self._rule_parameter('deduct_single_with_income')

    def _get_bareme_III_deduction(self):
        self.ensure_one()
        return 0

    def _is_eligible_for_bareme_I(self):
        return self._l10n_be_is_isolated() or (self._l10n_be_is_coupled() and self.version_id.spouse_fiscal_status != 'without_income' and not self.version_id.disabled_spouse_bool)

    def _is_eligible_for_bareme_II(self):
        return self._l10n_be_is_coupled() and (self.version_id.spouse_fiscal_status == 'without_income' or self.version_id.disabled_spouse_bool)

    def _get_be_withholding_taxes_family_charges_deduction(self):
        self.ensure_one()

        version = self.version_id
        total_reduction = 0

        if self._is_eligible_for_bareme_I() or self._is_eligible_for_bareme_II():
            if version.disabled:
                total_reduction += self._rule_parameter('disabled_worker_deduction')
            if version.other_senior_dependent:
                total_reduction += self._rule_parameter('dependent_senior_deduction') * version.other_senior_dependent
            if version.dependent_juniors:
                total_reduction += self._rule_parameter('disabled_dependent_deduction') * version.dependent_juniors

        if self._is_eligible_for_bareme_I():
            if self._l10n_be_is_isolated() and version.dependent_children:
                total_reduction += self._rule_parameter('disabled_dependent_deduction')
            if self._l10n_be_is_coupled() and version.spouse_fiscal_status == 'low_income':
                total_reduction += self._rule_parameter('spouse_low_income_deduction')
            if self._l10n_be_is_coupled() and version.spouse_fiscal_status == 'low_pension':
                total_reduction += self._rule_parameter('spouse_other_income_deduction')

        if self._is_eligible_for_bareme_II():
            if version.disabled_spouse_bool:
                total_reduction += self._rule_parameter('disabled_dependent_deduction')

        # Child Allowances
        n_children = version.dependent_children
        if n_children > 0:
            children_deduction = self._rule_parameter('dependent_basic_children_deduction')
            if n_children <= 8:
                total_reduction += children_deduction.get(n_children, 0.0)
            if n_children > 8:
                total_reduction += children_deduction.get(8, 0.0) + (n_children - 8) * self._rule_parameter('dependent_children_deduction')

        return total_reduction

    def _compute_basic_bareme(self, yearly_net_taxable_amount):
        """ Apply the progressive bareme to a yearly net taxable amount, with the Scale II income split for married employees with a non-working spouse. """
        def apply_brackets(value):
            rates = self._rule_parameter('basic_bareme_rates')
            # The last bracket has no upper limit in the parameter table, so float('inf') is used as a stand-in.
            rates = [(limit or float('inf'), rate) for limit, rate in rates]
            rates = sorted(rates)
            basic_bareme = 0
            previous_limit = 0
            for limit, rate in rates:
                # Tax only the slice of income that falls within this bracket at its marginal rate, the tax of each
                # slice rounded to the cent.
                basic_bareme += float_round(max(min(value, limit) - previous_limit, 0) * rate, precision_rounding=0.01)
                previous_limit = limit
            return float_round(basic_bareme, precision_rounding=0.01)

        version = self.version_id
        if not version.is_non_resident and self._is_eligible_for_bareme_II():
            # Scale II allocates up to 30 percent of income to the non-working spouse, reducing the total tax.
            amount_for_spouse = min(yearly_net_taxable_amount * 0.3, self._get_be_max_spouse_income())
            return apply_brackets(amount_for_spouse) + apply_brackets(yearly_net_taxable_amount - amount_for_spouse)
        return apply_brackets(yearly_net_taxable_amount)

    def _get_be_max_spouse_income(self):
        """ Scale II: the maximum income allotted to the spouse without income. From November 2026, a higher maximum
        applies to the whole year when both spouses reach the age by January 1st of the tax year (the next year). """
        self.ensure_one()
        seniors = self._rule_parameter('max_spouse_income_seniors', raise_if_not_found=False)
        if seniors:
            tax_year_start = date(self.date_to.year + 1, 1, 1)
            birthdates = (self.employee_id.birthday, self.version_id.spouse_birthdate)
            if all(birthdates) and all(birthdate + relativedelta(years=seniors['age']) <= tax_year_start for birthdate in birthdates):
                return seniors['amount']
        return self._rule_parameter('max_spouse_income')

    def _get_be_withholding_taxes_basic_bareme(self, result_rules, work_entries):
        self.ensure_one()

        version = self.version_id

        gross_code = 'GROSS.NET.Y' if self.struct_id.code == 'BEMONTHLY' else 'TERM_GROSS_NET_Y'
        yearly_net_taxable_revenue = result_rules[gross_code]['total']  # Base imposable nette

        # Only the termination structure lacks a CAR.PRIV line, so it still needs the private-car reimbursement fictively added to the taxable base.
        termination_struct = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        if self.struct_id == termination_struct and version.private_car_employee_kilometer:
            result, result_qty, result_rate = self._get_be_private_car_reimbursement_amount(work_entries)
            private_car_amount = result * result_qty * result_rate / 100
            yearly_net_taxable_revenue += private_car_amount * 12

        return self._compute_basic_bareme(yearly_net_taxable_revenue)

    def _l10n_be_is_last_payslip(self):
        """ Check if this payslip is the last one of the employee (leaving the company). """
        self.ensure_one()
        employee = self.employee_id
        contract_end = self.version_id.contract_date_end
        # The employee leaves through an explicit departure date falling in this slip.
        leaves_on_departure_date = bool(employee.departure_date and self.date_from <= employee.departure_date <= self.date_to)
        # Or a fixed term contract ends in this slip with no later version starting after it.
        contract_ends_in_slip = bool(contract_end and self.date_from <= contract_end <= self.date_to)
        # Only look for a later version when there is a contract end to compare against.
        has_later_version = contract_end and employee.version_ids.filtered(lambda v: v.date_start > contract_end)
        ends_fixed_term_contract = contract_ends_in_slip and not has_later_version
        return leaves_on_departure_date or ends_fixed_term_contract

    def _l10n_be_is_last_payslip_of_quarter(self, quarter_payslips, month_payslips):
        """
        If a validated/paid payslip (or self) is at the end of the current
        quarter, then self is the last payslip of the quarter
        e.g.:
          - we have validated payslips in Jan, Feb and Mar, Mar is the last
            payslip of the quarter
          - if we then correct the Feb payslip (so we make a new one), then Feb2
            is also a last payslip of the quarter (as no payslip is supposed to
            be generated afterwards)
        """
        self.ensure_one()

        # if the employee stops working before the end of quarter, then we
        # consider his last work day as the end of the quarter
        _, quarter_end = date_utils.get_quarter(self.date_to)
        last_quarter_month = min(
            self.employee_id.l10n_be_get_last_work_day_of_year(self.date_to.year) or date.max,
            quarter_end,
        ).month
        if last_quarter_month != max(p.date_to.month for p in (quarter_payslips | self)):
            return False

        # 13th month payslips are considered the last payslip of the quarter only
        # if there is already a monthly payslip in the same month
        is_thirteen = self.struct_id.code == 'BETHIRTEEN'
        return not is_thirteen or self._l10n_be_has_monthly_payslip_in_same_month(month_payslips)

    def _l10n_be_has_monthly_payslip_in_same_month(self, month_payslips):
        self.ensure_one()
        return any(p.struct_id.code == 'BEMONTHLY' for p in month_payslips - self)

    def _l10n_be_csss_get_total_contribution(self, frequency: str, taxable_amount: float) -> float:
        """
        Returns the total special social contribution (CSSS) that should be paid
        if the employee has gained `taxable_amount`. This function does not
        deduct the already paid CSSS for the quarter.
        :param frequency: 'monthly' or 'quarterly' to use the corresponding rates
        """
        self.ensure_one()
        # there are different contribution rates per marital status
        if self._l10n_be_is_isolated():
            rates = self._rule_parameter(f'special_social_contribution_{frequency}_rate_single')
        elif self._l10n_be_is_coupled():
            if self.version_id.spouse_fiscal_status == 'without_income':
                rates = self._rule_parameter(f'special_social_contribution_{frequency}_rate_couple_single_income')
            else:
                rates = self._rule_parameter(f'special_social_contribution_{frequency}_rate_couple_dual_income')
        else:
            raise UserError(self.env._(
                'Employee "%(name)s" has an unsupported marital status "%(status)s" for the computation of the special social contribution',
                name=self.employee_id.name,
                status=self.l10n_be_effective_marital,
            ))

        special_social_contrib = 0
        # we need to apply the values of the first matching rate only
        for rate in sorted(rates, key=lambda r: r['from'], reverse=True):
            if rate['from'] > taxable_amount:
                continue
            # rate percentage must be applied on any cent >= rate beginning
            exceeding_amount = taxable_amount - max(0, rate['from'] - 0.01)
            contribution = rate['amount'] + exceeding_amount * (rate.get('percentage', 0) / 100)
            special_social_contrib = min(rate.get('max', float('inf')), max(contribution, rate.get('min', 0)))
            break
        return special_social_contrib

    def _l10n_be_csss_get_gross_onss_wage(self, result_rules, validated_payslips_in_period):
        """
        Any gross salary received during the month (or quarter) must be subject
        to the Special Social Contribution (CSSS). The wage is increased by 8%
        for workers, as the ONSS basis (see _l10n_be_get_onss_basis_uplift).
        The IRC (wage on termination fees) is not returned here as it is used
        for another part of the computation
        """
        self.ensure_one()
        relevant_codes = ('SALARY', 'BONUS_SALARY', 'CP302THIRTEEN', 'WARRANT_SALARY')
        line_values = validated_payslips_in_period._get_line_values(relevant_codes, compute_sum=True)
        gross_onss_salary = sum(line_values[code]['sum']['total'] for code in relevant_codes)
        if self not in validated_payslips_in_period:
            gross_onss_salary += sum(result_rules[code]['total'] for code in relevant_codes)
        # the base subject to the ONSS: 108% for the blue collars, except in the employer categories 036 and 320
        return gross_onss_salary * self._l10n_be_get_onss_basis_uplift()

    def _l10n_be_csss_get_simple_holiday_pay(self, result_rules, validated_payslips_in_period):
        """
        Any simple holiday pay (simple pécule de vacances) received during the
        month (or quarter) must be subject to the Special Social Contribution (CSSS).
        """
        self.ensure_one()
        simple_holiday_pay = validated_payslips_in_period._get_line_values(['PAY_SIMPLE'], compute_sum=True)['PAY_SIMPLE']['sum']['total']
        if self not in validated_payslips_in_period:
            simple_holiday_pay += result_rules['PAY_SIMPLE']['total']
        return simple_holiday_pay

    def _l10n_be_csss_get_irc_per_quarter(self, result_rules, validated_payslips_in_period) -> dict[tuple, float]:
        """
        When an employee does not do all of his notice period, and instead
        receives all of it in the termination fees (indemnité de rupture de
        contrat, IRC), this sum is subject to the CSSS, but, the amount has to
        be split per quarter of the notice period, and the CSSS must be applied
        per quarter instead of all at once.
        :return dict: the irc split per quarter in this format:
            {(quarter_start, quarter_stop): irc_amount}
        """
        self.ensure_one()

        if not self.employee_id.departure_date or not self.employee_id.l10n_be_notice_period_theoretical_end:
            return {}  # no possible irc if we don't have a notice

        irc = validated_payslips_in_period._get_line_values(['TERM_SALARY'], compute_sum=True)['TERM_SALARY']['sum']['total']
        if self not in validated_payslips_in_period:
            irc += result_rules['TERM_SALARY']['total']

        unprestated_notice_start = self.employee_id.departure_date + relativedelta(days=1)
        unprestated_notice_end = self.employee_id.l10n_be_notice_period_theoretical_end

        def notice_hours_in_period(date_from, date_to):
            date_from = max(date_from, unprestated_notice_start)
            date_to = min(date_to, unprestated_notice_end)
            return self.version_id.resource_calendar_id.get_work_hours_count(date_from, date_to, compute_leaves=False)

        work_hours_in_notice = notice_hours_in_period(unprestated_notice_start, unprestated_notice_end)
        if not work_hours_in_notice:
            return {}

        # the IRC should be divided by each quarter of the notice period. We can
        # acheive it by doing a proratization on the workable hours.
        quarters_in_notice: dict[tuple, float] = {}
        quarter_start, quarter_end = date_utils.get_quarter(unprestated_notice_start)
        while quarter_start < unprestated_notice_end:
            irc_in_quarter = irc * (notice_hours_in_period(quarter_start, quarter_end) / work_hours_in_notice)
            quarters_in_notice[quarter_start, quarter_end] = irc_in_quarter
            quarter_start, quarter_end = date_utils.get_quarter(quarter_start + relativedelta(months=3))

        return quarters_in_notice

    def _l10n_be_get_special_social_contribution(self, result_rules, quarter_payslips, month_payslips, frequency: str):
        """
        The Special Social Contribution (CSSS) is a quarterly tax on the gross
        wage of the employee.
        To avoid reducing the salary too much at the end of a quarter, we take
        monthly advances with adapted rates to spread the tax on the quarter.
        :param frequency: either 'monthly' or 'quarterly' to get either the
            monthly estimation, or the real CSSS based on quarterly rates
        """
        self.ensure_one()
        if self.version_id.is_non_resident:
            return 0

        if frequency not in ('monthly', 'quarterly'):
            raise UserError(self.env._(
                "Invalid special social contribution frequency (%(invalid_freq)s)",
                invalid_freq=frequency,
            ))

        validated_payslips_in_period = quarter_payslips if frequency == 'quarterly' else month_payslips

        gross_onss_salary = self._l10n_be_csss_get_gross_onss_wage(result_rules, validated_payslips_in_period)
        simple_holiday_pay = self._l10n_be_csss_get_simple_holiday_pay(result_rules, validated_payslips_in_period)

        # get notice period paid sum (IRC), split per quarter
        irc_per_quarter = self._l10n_be_csss_get_irc_per_quarter(result_rules, validated_payslips_in_period)

        # if we have an IRC for this payslip's quarter, we have to use it for
        # the main CSSS computation
        additional_irc = 0
        quarter_start, quarter_end = date_utils.get_quarter(self.date_to)
        if (quarter_start, quarter_end) in irc_per_quarter:
            additional_irc = irc_per_quarter[quarter_start, quarter_end]
            if self.version_id.is_worker():
                additional_irc *= self._rule_parameter('worker_onss_calculation_basis_uplift')  # worker uplift on ONSS wages
            # we will remove this quarter's irc to avoid counting it again later
            irc_per_quarter.pop((quarter_start, quarter_end))

        special_social_contribution = self._l10n_be_csss_get_total_contribution(
            frequency, gross_onss_salary + simple_holiday_pay + additional_irc,
        )

        # any IRC during the notice period is subject to the CSSS. Since no
        # other payslip will be generated for that salary, we have to compute it
        # now and add it to this payslip's CSSS
        for quarter_irc in irc_per_quarter.values():
            if self.version_id.is_worker():
                quarter_irc *= self._rule_parameter('worker_onss_calculation_basis_uplift')  # worker uplift on ONSS wages
            special_social_contribution += self._l10n_be_csss_get_total_contribution('quarterly', quarter_irc)

        # we should deduct what has already been paid during the period
        other_validated_payslips_in_period = validated_payslips_in_period - self
        advances = -other_validated_payslips_in_period._get_line_values(['M.ONSS'], compute_sum=True)['M.ONSS']['sum']['total']

        return special_social_contribution - advances

    def _l10n_be_get_full_time_working_days(self, version):
        """The working days of a full-time worker in the company over the payslip period, from the
        reference calendar of the version, public holidays included."""
        self.ensure_one()
        tz = ZoneInfo(version._get_tz())
        return version._get_reference_calendar().get_work_duration_data(
            datetime.combine(self.date_from, time.min, tz), datetime.combine(self.date_to, time.max, tz),
            compute_leaves=False,
        )['days']

    def _get_be_benefit_count(self, benefit, work_entries):
        # MEAL_VOUCHER counts the days granting the benefit, while the JC302 PRIVATE_CAR also
        # counts each shift of an interrupted day, capped at 2 per day (double reimbursement).
        self.ensure_one()
        if self.env.context.get('salary_simulation'):
            if benefit in ['MEAL_VOUCHER', 'PRIVATE_CAR']:
                return 20

        benefit_category = self.env.ref(f'l10n_be_hr_payroll.{benefit}', raise_if_not_found=False)
        if not benefit_category:
            return 0
        granting_entries = [
            vals for vals in work_entries
            if benefit_category.id in (vals['work_entry_type_id'].category_ids | vals.get('category_options_ids', self.env['hr.salary.rule.category'])).ids
        ]
        if benefit in ['MEAL_VOUCHER', 'PRIVATE_CAR']:
            if benefit == 'PRIVATE_CAR' and self.version_id._l10n_be_counts_interrupted_transport_shifts():
                entries_per_day = Counter(vals['date'] for vals in granting_entries)
                return sum(min(count, 2) for count in entries_per_day.values())
            return len({vals['date'] for vals in granting_entries})
        return 0

    def _get_be_ip(self, result_rules):
        self.ensure_one()
        if self.version_id.ip_wage_rate <= 0:
            return 0.0
        return result_rules['BASIC']['total'] * self.version_id.ip_wage_rate

    def _get_be_ip_values(self, result_rules, categories, ip_data):
        """ Split the intellectual property (IP) of the payslip.

        The values are computed once per payslip (memoized in ip_data) so that every IP rule
        relies on the same figures. The first call comes from the `IP.EXEMPT` rule (sequence 535),
        i.e. once the ONSS base is complete but still contains the whole IP.

        - ip: the gross IP (BASIC x ip_wage_rate), capped on the room left under the yearly limit: the
          exceeding part is paid as a regular remuneration
        - total_remuneration: the remuneration subject to ONSS, IP included
        - onss_exempt: the part of the IP exempt from ONSS, i.e. the IP up to the maximum share
          (30 %, since 2026) of the total remuneration, unless the ONSS contributions are forced on
          the contract
        - onss_part: the part of the IP subject to ONSS
        - within_limits: whether the IP withholding tax applies, i.e. the IP of the year doesn't exceed
          the maximum share of the total remuneration of the year and the average IP received during
          the 4 previous years doesn't exceed the yearly limit. Otherwise the IP is taxed as a regular
          remuneration.

        The yearly limit exists since the income year 2023, the share of the withholding tax since
        2024 and the one of the ONSS exemption since 2026: without a rule parameter value, the
        related conditions don't apply and the whole IP is subject to ONSS.
        """
        self.ensure_one()
        if 'values' in ip_data:
            return ip_data['values']
        ip = self._get_be_ip(result_rules)
        yearly_limit = self._rule_parameter('ip_limit', raise_if_not_found=False)
        if ip > 0 and yearly_limit:
            # yearly cap: only the room left under the limit is paid as IP
            ip = max(0.0, min(ip, float_round(yearly_limit - ip_data['year_total'], precision_digits=2)))
        values = {
            'ip': ip,
            'total_remuneration': 0.0,
            'onss_exempt': 0.0,
            'onss_part': 0.0,
            'within_limits': False,
        }
        if ip > 0:
            # the ONSS base still contains the IP, unless the exemption line was already computed
            total = categories['ONSS_BASE'] - result_rules['IP.EXEMPT']['total']
            max_share = self._rule_parameter('ip_max_remuneration_share', raise_if_not_found=False)
            # The share is assessed on the taxable period (the year), the IP and the remuneration of the validated
            # payslips of the year included. The ONSS exemption stays assessed on the payslip.
            share_ok = not max_share or float_compare(
                ip_data['year_total'] + ip,
                max_share * (ip_data.get('year_remuneration', 0.0) + total),
                precision_digits=2) <= 0
            average_ok = not yearly_limit or float_compare(ip_data['previous_years_average'], yearly_limit, precision_digits=2) <= 0
            # The ONSS exemption of the IP (DmfA code 47) only exists since 2026, the share of the tax since 2024
            onss_max_share = self._rule_parameter('ip_onss_max_remuneration_share', raise_if_not_found=False)
            onss_max_ip = float_round(onss_max_share * total, precision_digits=2) if onss_max_share else 0.0
            onss_exempt = 0.0 if not onss_max_share or self.version_id.ip_onss else min(ip, onss_max_ip)
            values.update({
                'total_remuneration': total,
                'onss_exempt': onss_exempt,
                'onss_part': ip - onss_exempt,
                'within_limits': share_ok and average_ok,
            })
        ip_data['values'] = values
        return values

    def _l10n_be_has_ip_flat_rate_costs(self):
        """ Whether the lump-sum professional costs are deducted from the IP of the payslip: since the
        Loi-programme of 30.05.2026, they are only granted to the owners of a certificate of artistic
        work for the income paid or attributed from 11.06.2026, and to every beneficiary before. The
        income is paid on the last day of the payslip period.
        Source: SPF Finances, 273S 2026 instructions, note 6
        https://finances.belgium.be/sites/default/files/downloads/121-273s-2026-fr.pdf
        """
        self.ensure_one()
        return self.version_id.ip_artist or self.date_to < date(2026, 6, 11)

    def _get_be_ip_flat_rate_costs(self, result_rules, categories, ip_data):
        """ Lump-sum professional costs on the IP (see `_l10n_be_has_ip_flat_rate_costs`): 50 % of
        the yearly IP up to the first bracket, 25 % between the first and the second bracket, nothing
        above. The brackets are yearly amounts: the costs are assessed on the IP of this payslip on
        top of the IP of the validated payslips of the year.
        """
        self.ensure_one()
        ip = self._get_be_ip_values(result_rules, categories, ip_data)['ip']
        if ip <= 0:
            return 0.0
        bracket_1 = self._rule_parameter('ip_deduction_bracket_1')
        bracket_2 = self._rule_parameter('ip_deduction_bracket_2')
        year_ip = ip_data['year_total']

        def tranche(lower, upper):
            # part of the IP of this payslip falling between both yearly amounts
            return max(0.0, min(year_ip + ip, upper) - max(year_ip, lower))

        return 0.5 * tranche(0.0, bracket_1) + 0.25 * tranche(bracket_1, bracket_2)

    def _get_be_ip_deduction(self, result_rules, categories, ip_data):
        self.ensure_one()
        # the IP subject to the IP withholding tax (TAXABLE_273S category) is the whole IP of the payslip
        ip_values = self._get_be_ip_values(result_rules, categories, ip_data)
        ip = ip_values['ip']
        if ip <= 0 or not categories['TAXABLE_273S']:
            return 0.0
        # the withholding tax applies on the IP net of its ONSS part
        onss_rate = self._get_onss_global_rates()['personal_rate']
        taxable_amount = ip - ip_values['onss_part'] * onss_rate / 100
        if self._l10n_be_has_ip_flat_rate_costs():
            taxable_amount -= self._get_be_ip_flat_rate_costs(result_rules, categories, ip_data)
        return - max(taxable_amount, 0.0) * self._rule_parameter('ip_tax_rate')

    def _l10n_be_init_work_bonus_explanation(self, explanation_info):
        no_worked_days = self.env._("No worked days")
        explanation_info.update({
            'salary_formula': no_worked_days,
            'reference_salary': 0,
            'base_bonus_formula': no_worked_days,
            'base_bonus': 0,
            'proration_formula': no_worked_days,
            'onss': 0,
            'calculated_bonus': 0,
            'already_paid': 0,
            'carry_over': 0,
        })

    def _l10n_be_update_work_bonus_explanation(self, explanation_info, gross, salary, base_bonus, base_bonus_formula,
                                               is_full_time, paid_days, total_days, paid_hours, total_hours):
        """
        Details how the work bonus reference salary (S) and the granted amount (P) are obtained.
        A full time worker is prorated on days (J/D), a part time one on hours (H/U).
        """
        gross = float_round(gross, precision_digits=4)
        base_bonus = float_round(base_bonus, precision_digits=4)
        if not is_full_time:
            paid, total = float_round(paid_hours, precision_digits=4), float_round(total_hours, precision_digits=4)
            salary_formula = self.env._(
                "(Gross (%(gross)s) / Paid hours (%(paid)s), rounded (2-digits)) * Total hours (%(total)s)",
                gross=gross, paid=paid, total=total)
            proration_formula = self.env._(
                "Basic bonus (%(base_bonus)s) * (Paid hours (%(paid)s) / Total hours (%(total)s), rounded (2-digits))",
                base_bonus=base_bonus, paid=paid, total=total)
        elif float_compare(paid_days, total_days, precision_digits=2):
            paid, total = float_round(paid_days, precision_digits=4), float_round(total_days, precision_digits=4)
            salary_formula = self.env._(
                "(Gross (%(gross)s) / Paid days (%(paid)s), rounded (2-digits)) * Total days (%(total)s)",
                gross=gross, paid=paid, total=total)
            proration_formula = self.env._(
                "Basic bonus (%(base_bonus)s) * (Paid days (%(paid)s) / Total days (%(total)s), rounded (2-digits))",
                base_bonus=base_bonus, paid=paid, total=total)
        else:
            salary_formula = self.env._("Gross (%(gross)s), complete month", gross=gross)
            proration_formula = self.env._(
                "Basic bonus (%(base_bonus)s), complete month", base_bonus=base_bonus)
        explanation_info.update({
            'salary_formula': salary_formula,
            'reference_salary': float_round(salary, precision_digits=4),
            'base_bonus_formula': base_bonus_formula,
            'base_bonus': base_bonus,
            'proration_formula': proration_formula,
        })

    @api.model
    def _get_employment_bonus_excluded_codes(self):
        # 026.00 / 026.01 pay the premium of overtime recovered later: its hours are declared when the rest is taken
        return ['147.00', '147.05', '147.07', '040.27', '040.28', '039.23', '147.04', '147.08', '147.13'] \
            + self._l10n_be_get_recoverable_overtime_codes()

    def _l10n_be_get_employment_bonus_fractions(self, worked_days_payslip):
        """Whether the days formula applies (full time, without time credit, out of Horeca), the hours (H) and days
        (J) with a performance in the month, and the hours (U) and days (D) of the month in the full-time regime: the
        reference wage of the employment bonus is the pay of a full month at full time, and part-time or incomplete
        months get a share of the bonus."""
        self.ensure_one()
        excluded_codes = self._get_employment_bonus_excluded_codes()
        onss_base = self.env.ref('l10n_be_hr_payroll.ONSS_BASE')
        # the time declared with a performance code (DmfA 1, 3, 4, 5, 20, 38): the paid time in the ONSS pay, and in a
        # month with pay the time performed but paid later or unpaid; extra hours add hours but no days
        performances = worked_days_payslip.worked_days_line_ids.filtered(
            lambda wd: wd.code not in excluded_codes and onss_base in wd.work_entry_type_id.category_ids
        )
        paid_performances = performances.filtered('amount')
        if paid_performances:
            performances = paid_performances | (performances - paid_performances).filtered(
                lambda wd: wd.work_entry_type_id.dmfa_code in ('1', '3', '4', '5', '20', '38'))
        else:
            performances = paid_performances
        paid_hours = round(sum(performances.mapped('number_of_hours')), 2)  # H
        paid_days = sum(performances.filtered(lambda wd: not wd.work_entry_type_id.is_extra_hours).mapped('number_of_days'))  # J
        version = self.version_id
        reference_calendar = version._get_reference_calendar()
        calendar = version.resource_calendar_id
        tz = ZoneInfo(version._get_tz())
        period = (datetime.combine(self.date_from, time.min, tz), datetime.combine(self.date_to, time.max, tz))

        def regime_month(regime_calendar):
            # D counts the days the regime plans whatever their hours, as J counts a day paid in full: a short day (4 h
            # on Friday) is one day, not the half day a calendar makes of a day under 3/4 of its average day
            intervals = regime_calendar._attendance_intervals_batch(*period)[False]
            return self.env['resource.calendar']._get_attendance_intervals_days_data(intervals)

        if calendar.calendar_type == 'variable' and reference_calendar.hours_per_week:
            if version.work_time_rate >= 1.0 and calendar.attendance_ids.filtered('recurrency'):
                # a full-time cycle (days repeated every week or every few weeks) sets the regime's hours of each
                # month: those of a full-time worker on the same cycle
                month = calendar.get_work_duration_data(
                    datetime.combine(self.date_from, time.min, tz), datetime.combine(self.date_to, time.max, tz),
                    compute_leaves=False,
                )
                return False, paid_hours, round(month['hours'], 2), paid_days, month['days']
            month = {'hours': 0}
            if reference_calendar.calendar_type == 'fixed' or reference_calendar.attendance_ids.filtered('recurrency'):
                # planned day by day: the month of the ONSS reference person, the hours its week, or its cycle of a few
                # weeks, plans over the days of the month (U, the hours corresponding to D, the days of its regime)
                month = regime_month(reference_calendar)
            if not month['hours']:
                # without a theoretical week of the reference person, its full-time week spread over the working days
                # of the regime (Monday to Friday or Saturday)
                weekdays = 6 if calendar.days_per_week > 5 else 5
                days = sum(
                    1 for day in rrule.rrule(rrule.DAILY, dtstart=self.date_from, until=self.date_to)
                    if day.weekday() < weekdays
                )
                month = {'hours': reference_calendar.hours_per_week / weekdays * days, 'days': days}
            if (version.work_time_rate >= 1.0 and not version.l10n_be_time_credit
                    and version.l10n_be_joint_committee_id.egov3_code != '302'):
                # a full-time worker out of Horeca declares days: the days formula, complete (S = W) when paid for all
                # the days its planning holds in a month of contract, else against the days of the regime (D)
                if (version.contract_date_start <= self.date_from
                        and (not version.contract_date_end or version.contract_date_end >= self.date_to)):
                    planned = calendar.get_work_duration_data(
                        datetime.combine(self.date_from, time.min, tz), datetime.combine(self.date_to, time.max, tz),
                        compute_leaves=False,
                    )
                    if planned['days'] and float_compare(paid_days, planned['days'], precision_digits=2) >= 0:
                        return True, paid_hours, round(planned['hours'], 2), paid_days, paid_days
                return True, paid_hours, round(month['hours'], 2), paid_days, month['days']
            # the hours formula
            return False, paid_hours, round(month['hours'], 2), paid_days, month['days']
        month = regime_month(reference_calendar)
        if not month['hours']:
            # no reference schedule to measure the month: the employee's own worked days
            own = worked_days_payslip[0].worked_days_line_ids.filtered(lambda wd: wd.code not in excluded_codes)
            month = {'hours': sum(own.mapped('number_of_hours')), 'days': sum(own.mapped('number_of_days'))}
        # a time credit or a partial resumption reduces the week of a full-time contract, and Horeca declares the hours
        # of its full-time workers: hours, as for a part time
        is_full_time = (version.work_time_rate >= 1.0 and not version.l10n_be_time_credit
                        and version.l10n_be_joint_committee_id.egov3_code != '302')
        return is_full_time, paid_hours, round(month['hours'], 2), paid_days, month['days']

    def _l10n_be_get_work_bonus_year_end_excess(self, salary, month_payslips):
        """The part of the year-end premiums (13th month, BETHIRTEEN) paid in the month beyond the reference wage (S)
        of the month: the reference wage of the employment bonus is the gross wage of the calendar month, the premiums
        of the month included, "à l'exclusion de la prime de fin d'année à concurrence du salaire mensuel de référence
        (S)" (ONSS administrative instructions, bonus à l'emploi). The other premiums paid apart are in W by their
        EMP_BONUS_SALARY line; the one of a 13th month payslip is not in its premium. The excess is added to S, after
        the proration of W to the month of the regime (it is no pay of the hours of the month).

        :param salary: S without the year-end premiums
        :return: the amount to add to S
        """
        self.ensure_one()
        year_end_payslips = (month_payslips - self).filtered(lambda p: p.struct_id.code == 'BETHIRTEEN')
        if not year_end_payslips:
            return 0.0
        line_values = year_end_payslips._get_line_values(['BONUS_SALARY', 'EMP_BONUS_SALARY'], compute_sum=True)
        year_end = line_values['BONUS_SALARY']['sum']['total'] - line_values['EMP_BONUS_SALARY']['sum']['total']
        return max(0.0, year_end - salary)

    def _l10n_be_get_work_bonus_reference_salary(self, result_rules, month_payslips):
        """The reference wage (S) of the employment bonus, as its volets measure it. The bounds of the bonus apply to
        S, below the pay of the month when more hours (or days) are paid than the full-time month has."""
        self.ensure_one()
        basic = result_rules['ONSS_BASE_TOTAL']['total'] - result_rules['HolPayRec']['total']
        worked_days_payslip = (self | month_payslips).filtered('worked_days_line_ids')
        if self.env.context.get('salary_simulation') or not worked_days_payslip:
            return basic
        is_full_time, paid_hours, total_hours, paid_days, total_days = self._l10n_be_get_employment_bonus_fractions(worked_days_payslip)
        salary = basic  # S = W
        if is_full_time and paid_days and float_compare(paid_days, total_days, precision_digits=2):
            salary = float_round(float_round(basic / paid_days, precision_digits=2) * total_days, precision_digits=2)  # S = (W/J) x D
        elif not is_full_time and paid_hours and float_compare(paid_hours, total_hours, precision_digits=2):
            salary = float_round(float_round(basic / paid_hours, precision_digits=2) * total_hours, precision_digits=2)  # S = (W/H) x U
        return salary + self._l10n_be_get_work_bonus_year_end_excess(salary, month_payslips)

    def _l10n_be_is_employment_bonus_eligible(self, result_rules, month_payslips):
        self.ensure_one()
        wage = result_rules['ONSS_BASE_TOTAL']['total']
        # the bonus reduces the worker's ONSS: nothing to reduce, nor to carry over, without ONSS (e.g. Dimona DWD)
        if not wage or self.version_id.no_onss or self.version_id.is_student() or self.version_id.is_PFI():
            return False
        # the bound applies to the reference wage, below the pay when more hours are paid than the full-time month has
        high = self._rule_parameter('work_bonus_reference_wage_high')
        return bool(
            wage <= high or month_payslips
            or self._l10n_be_get_work_bonus_reference_salary(result_rules, month_payslips) <= high
        )

    def _get_employment_bonus_employees_volet_A(self, result_rules, explanation_info, month_payslips, month_line_values, prev_month_line_values):
        self._l10n_be_init_work_bonus_explanation(explanation_info)
        worked_days_payslip = (self | month_payslips).filtered('worked_days_line_ids')
        if not worked_days_payslip and not self.env.context.get('salary_simulation') and result_rules['SECTORIAL.BONUS']['total'] == 0:  # in case we want a payslip with only the sectorial bonus
            return {'result': 0, 'remaining_bonus': 0, 'explanation_info': explanation_info}

        # S = (W / H) * U
        # W = salaire brut
        # H = le nombre d'heures de travail déclarées avec un code prestations 1, 3, 4, 5 et 20;
        # U = le nombre maximum d'heures de prestations pour le mois concerné dans le régime de travail concerné
        # J = The number of days declared for the worker with a performance (work) code of 1, 3, 4, 5, and 20
        # D = The maximum number of working (performance) days for the relevant month under the relevant work regime
        is_full_time = self.version_id.work_time_rate >= 1.0
        if self.env.context.get('salary_simulation') or not worked_days_payslip:
            paid_hours = total_hours = paid_days = total_days = 1
        else:
            is_full_time, paid_hours, total_hours, paid_days, total_days = self._l10n_be_get_employment_bonus_fractions(worked_days_payslip)
            if (not is_full_time and not paid_hours) or (is_full_time and not paid_days):
                return {'result': 0, 'remaining_bonus': 0, 'explanation_info': explanation_info}

        # 1. - Détermination du salaire mensuel de référence (S)
        basic = result_rules['ONSS_BASE_TOTAL']['total'] - result_rules['HolPayRec']['total']
        if is_full_time:
            if float_compare(paid_days, total_days, precision_digits=2):
                salary = float_round(float_round(basic / paid_days, precision_digits=2) * total_days, precision_digits=2)  # S = (W/J) x D
            else:
                salary = basic  # S = W
        elif not float_compare(paid_hours, total_hours, precision_digits=2):
            salary = basic  # S = W
        else:
            salary = float_round(float_round(basic / paid_hours, precision_digits=2) * total_hours, precision_digits=2)  # S = (W/H) x U
        if not self.env.context.get('salary_simulation'):
            salary += self._l10n_be_get_work_bonus_year_end_excess(salary, month_payslips)

        # 2. - Détermination du montant de base de la réduction (R)
        key = 'worker' if self.version_id.is_worker() else 'employee'
        bonus_basic_amount_volet_A = self._rule_parameter('work_bonus_basic_amount_volet_A')[key]
        wage_lower_bound = self._rule_parameter('work_bonus_reference_wage_low')
        wage_middle_bound = self._rule_parameter('l10n_be_work_bonus_reference_wage_middle')
        wage_higher_bound = self._rule_parameter('work_bonus_reference_wage_high')

        if salary <= wage_lower_bound:
            result = bonus_basic_amount_volet_A
            base_bonus_formula = self.env._(
                "Reference salary (%(salary)s) <= %(bound)s: full basic amount (%(basic_amount)s)",
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_lower_bound, precision_digits=4),
                basic_amount=float_round(bonus_basic_amount_volet_A, precision_digits=4))
        elif salary <= wage_middle_bound:
            result = bonus_basic_amount_volet_A
            base_bonus_formula = self.env._(
                "Reference salary (%(salary)s) <= %(bound)s: full basic amount (%(basic_amount)s)",
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_middle_bound, precision_digits=4),
                basic_amount=float_round(bonus_basic_amount_volet_A, precision_digits=4))
        elif salary <= wage_higher_bound:
            coeff = self._rule_parameter('work_bonus_coeff')[key]
            result = bonus_basic_amount_volet_A - (coeff * (salary - wage_middle_bound))
            base_bonus_formula = self.env._(
                "Basic amount (%(basic_amount)s) - Coefficient (%(coeff)s) * (Reference salary (%(salary)s) - Threshold (%(bound)s))",
                basic_amount=float_round(bonus_basic_amount_volet_A, precision_digits=4), coeff=coeff,
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_middle_bound, precision_digits=4))
        else:
            result = 0
            base_bonus_formula = self.env._(
                "Reference salary (%(salary)s) > %(bound)s: no bonus",
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_higher_bound, precision_digits=4))

        # R is rounded to the cent before the fraction of the month applies; it is never negative: the published
        # amounts, bounds and coefficients are rounded, so the formula can end a few cents below 0 next to a bound
        result = float_round(max(0.0, result), precision_digits=2)
        self._l10n_be_update_work_bonus_explanation(
            explanation_info, basic, salary, result, base_bonus_formula,
            is_full_time, paid_days, total_days, paid_hours, total_hours)
        # 3. - Détermination du montant de la réduction (P)
        if is_full_time:
            if paid_days < total_days:  # If J=D result will remain same
                result = float_round(paid_days / total_days, precision_digits=2) * result  # P = (J/D) x R
        else:
            result = min(1.0, float_round(paid_hours / total_hours, precision_digits=2)) * result  # P = (H/U) x R, at most R

        already_paid = month_line_values['EmpBonus.A']['sum']['total']
        already_carried_over = month_line_values['EmpBonus.A.CO']['sum']['total']
        carry_over = prev_month_line_values['EmpBonus.A.CO']['sum']['total']
        onss = result_rules['ONSS']['total'] + result_rules['ONSS_BONUS']['total'] + result_rules['ONSSRESTRUCTURING']['total']
        # Only the bonus of the month not covered by its ONSS is carried over, the carry over received is lost if unused.
        # The other payslips of the month already carried over their own share: only the difference is added.
        remaining_bonus = float_round(max(0, result - already_paid + onss) - already_carried_over, precision_digits=2)
        explanation_info.update({
            'onss': -float_round(onss, precision_digits=4) or 0.0,
            'calculated_bonus': float_round(result, precision_digits=4),
            'already_paid': float_round(already_paid, precision_digits=4),
            'carry_over': float_round(carry_over, precision_digits=4),
            'already_carried_over': float_round(already_carried_over, precision_digits=4),
            'remaining_bonus': remaining_bonus,
        })
        result -= already_paid
        return {'result': min(-onss, result + carry_over), 'remaining_bonus': remaining_bonus, 'explanation_info': explanation_info}

    def _get_employment_bonus_employees_volet_B(self, result_rules, explanation_info, month_payslips, month_line_values, prev_month_line_values):
        self._l10n_be_init_work_bonus_explanation(explanation_info)
        worked_days_payslip = (self | month_payslips).filtered('worked_days_line_ids')
        if not worked_days_payslip and not self.env.context.get('salary_simulation') and result_rules['SECTORIAL.BONUS']['total'] == 0:
            return {'result': 0, 'remaining_bonus': 0, 'explanation_info': explanation_info}

        # S = (W / H) * U
        # W = salaire brut
        # H = le nombre d'heures de travail déclarées avec un code prestations 1, 3, 4, 5 et 20;
        # U = le nombre maximum d'heures de prestations pour le mois concerné dans le régime de travail concerné
        # J = The number of days declared for the worker with a performance (work) code of 1, 3, 4, 5, and 20
        # D = The maximum number of working (performance) days for the relevant month under the relevant work regime
        is_full_time = self.version_id.work_time_rate >= 1.0
        if self.env.context.get('salary_simulation') or not worked_days_payslip:
            paid_hours = total_hours = paid_days = total_days = 1
        else:
            is_full_time, paid_hours, total_hours, paid_days, total_days = self._l10n_be_get_employment_bonus_fractions(worked_days_payslip)
            if (not is_full_time and not paid_hours) or (is_full_time and not paid_days):
                return {'result': 0, 'remaining_bonus': 0, 'explanation_info': explanation_info}

        # 1. - Détermination du salaire mensuel de référence (S)
        basic = result_rules['ONSS_BASE_TOTAL']['total'] - result_rules['HolPayRec']['total']
        if is_full_time:
            if float_compare(paid_days, total_days, precision_digits=2):
                salary = float_round(float_round(basic / paid_days, precision_digits=2) * total_days, precision_digits=2)  # S = (W/J) x D
            else:
                salary = basic  # S = W
        elif not float_compare(paid_hours, total_hours, precision_digits=2):
            salary = basic  # S = W
        else:
            salary = float_round(float_round(basic / paid_hours, precision_digits=2) * total_hours, precision_digits=2)  # S = (W/H) x U
        if not self.env.context.get('salary_simulation'):
            salary += self._l10n_be_get_work_bonus_year_end_excess(salary, month_payslips)

        # 2. - Détermination du montant de base de la réduction (R)
        key = 'worker' if self.version_id.is_worker() else 'employee'
        bonus_basic_amount = self._rule_parameter('work_bonus_basic_amount')[key]
        wage_lower_bound = self._rule_parameter('work_bonus_reference_wage_low')
        wage_middle_bound = self._rule_parameter('l10n_be_work_bonus_reference_wage_middle')
        wage_higher_bound = self._rule_parameter('work_bonus_reference_wage_high')

        if salary <= wage_lower_bound:
            result = bonus_basic_amount
            base_bonus_formula = self.env._(
                "Reference salary (%(salary)s) <= %(bound)s: full basic amount (%(basic_amount)s)",
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_lower_bound, precision_digits=4),
                basic_amount=float_round(bonus_basic_amount, precision_digits=4))
        elif salary <= wage_middle_bound:
            coeff = self._rule_parameter('l10n_be_work_bonus_coeff_low')[key]
            result = bonus_basic_amount - (coeff * (salary - wage_lower_bound))
            base_bonus_formula = self.env._(
                "Basic amount (%(basic_amount)s) - Coefficient (%(coeff)s) * (Reference salary (%(salary)s) - Threshold (%(bound)s))",
                basic_amount=float_round(bonus_basic_amount, precision_digits=4), coeff=coeff,
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_lower_bound, precision_digits=4))
        elif salary <= wage_higher_bound:
            result = 0
            base_bonus_formula = self.env._(
                "Reference salary (%(salary)s) > %(bound)s: no bonus",
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_middle_bound, precision_digits=4))
        else:
            result = 0
            base_bonus_formula = self.env._(
                "Reference salary (%(salary)s) > %(bound)s: no bonus",
                salary=float_round(salary, precision_digits=4),
                bound=float_round(wage_higher_bound, precision_digits=4))

        # R is rounded to the cent before the fraction of the month applies; it is never negative: the published
        # amounts, bounds and coefficients are rounded, so the formula can end a few cents below 0 next to a bound
        result = float_round(max(0.0, result), precision_digits=2)
        self._l10n_be_update_work_bonus_explanation(
            explanation_info, basic, salary, result, base_bonus_formula,
            is_full_time, paid_days, total_days, paid_hours, total_hours)
        # 3. - Détermination du montant de la réduction (P)
        if is_full_time:
            if paid_days < total_days:  # If J=D result will remain same
                result = float_round(paid_days / total_days, precision_digits=2) * result  # P = (J/D) x R
        else:
            result = min(1.0, float_round(paid_hours / total_hours, precision_digits=2)) * result  # P = (H/U) x R, at most R

        already_paid = month_line_values['EmpBonus.B']['sum']['total']
        already_carried_over = month_line_values['EmpBonus.B.CO']['sum']['total']
        carry_over = prev_month_line_values['EmpBonus.B.CO']['sum']['total']
        onss = result_rules['ONSS']['total'] + result_rules['ONSS_BONUS']['total'] + result_rules['ONSSRESTRUCTURING']['total'] + result_rules['EmpBonus.A']['total']
        # Only the bonus of the month not covered by its ONSS is carried over, the carry over received is lost if unused.
        # The other payslips of the month already carried over their own share: only the difference is added.
        remaining_bonus = float_round(max(0, result - already_paid + onss) - already_carried_over, precision_digits=2)
        explanation_info.update({
            'onss': -float_round(onss, precision_digits=4) or 0.0,  # not -0.0 without ONSS left
            'calculated_bonus': float_round(result, precision_digits=4),
            'already_paid': float_round(already_paid, precision_digits=4),
            'carry_over': float_round(carry_over, precision_digits=4),
            'already_carried_over': float_round(already_carried_over, precision_digits=4),
            'remaining_bonus': remaining_bonus,
        })
        result -= already_paid
        return {'result': min(-onss, result + carry_over), 'remaining_bonus': remaining_bonus, 'explanation_info': explanation_info}

    # ref: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/workers_reductions/workbonus.html
    def _get_employment_bonus_employees(self, result_rules, month_payslips, month_line_values, prev_month_line_values):
        self.ensure_one()
        if self.date_from >= date(2024, 4, 1):
            bonus_volet_A = result_rules['EmpBonus.A']['total']
            bonus_volet_B = result_rules['EmpBonus.B']['total']
            # since 04/2024 each volet carries over its own unused bonus, the total only sums them up
            carry_over = result_rules['EmpBonus.A.CO']['total'] + result_rules['EmpBonus.B.CO']['total']
            return {'result': bonus_volet_A + bonus_volet_B, 'remaining_bonus': float_round(carry_over, precision_digits=2)}

        worked_days_payslip = (self | month_payslips).filtered('worked_days_line_ids')
        if not worked_days_payslip and not self.env.context.get('salary_simulation') and result_rules['SECTORIAL.BONUS']['total'] == 0:
            return {'result': 0, 'remaining_bonus': 0}

        # S = (W / H) * U
        # W = salaire brut
        # H = le nombre d'heures de travail déclarées avec un code prestations 1, 3, 4, 5 et 20;
        # U = le nombre maximum d'heures de prestations pour le mois concerné dans le régime de travail concerné
        # J = The number of days declared for the worker with a performance (work) code of 1, 3, 4, 5, and 20
        # D = The maximum number of working (performance) days for the relevant month under the relevant work regime
        is_full_time = self.version_id.work_time_rate >= 1.0
        if self.env.context.get('salary_simulation') or not worked_days_payslip:
            paid_hours = 1
            total_hours = 1
            paid_days = 1
            total_days = 1
        else:
            is_full_time, paid_hours, total_hours, paid_days, total_days = self._l10n_be_get_employment_bonus_fractions(worked_days_payslip)
            if (not is_full_time and not paid_hours) or (is_full_time and not paid_days):
                return {'result': 0, 'remaining_bonus': 0}

        # 1. - Détermination du salaire mensuel de référence (S)
        basic = result_rules['ONSS_BASE_TOTAL']['total'] - result_rules['HolPayRec']['total']
        if is_full_time:
            if float_compare(paid_days, total_days, precision_digits=2):
                salary = float_round(float_round(basic / paid_days, precision_digits=2) * total_days, precision_digits=2)  # S = (W/J) x D
            else:
                salary = basic  # S = W
        elif not float_compare(paid_hours, total_hours, precision_digits=2):
            salary = basic  # S = W
        else:
            salary = float_round(float_round(basic / paid_hours, precision_digits=2) * total_hours, precision_digits=2)  # S = (W/H) x U
        if not self.env.context.get('salary_simulation'):
            salary += self._l10n_be_get_work_bonus_year_end_excess(salary, month_payslips)

        # 2. - Détermination du montant de base de la réduction (R)
        key = 'worker' if self.version_id.is_worker() else 'employee'
        bonus_basic_amount = self._rule_parameter('work_bonus_basic_amount')[key]
        wage_lower_bound = self._rule_parameter('work_bonus_reference_wage_low')
        wage_higher_bound = self._rule_parameter('work_bonus_reference_wage_high')

        if self.date_from < date(2023, 7, 1):
            if salary <= wage_lower_bound:
                result = bonus_basic_amount
            elif salary <= wage_higher_bound:
                coeff = self._rule_parameter('work_bonus_coeff')[key]
                result = bonus_basic_amount - (coeff * (salary - wage_lower_bound))
            else:
                result = 0
        else:
            wage_middle_bound = self._rule_parameter('l10n_be_work_bonus_reference_wage_middle')
            if salary <= wage_lower_bound:
                result = bonus_basic_amount
            elif salary <= wage_middle_bound:
                coeff = self._rule_parameter('l10n_be_work_bonus_coeff_low')[key]
                result = bonus_basic_amount - (coeff * (salary - wage_lower_bound))
            elif salary <= wage_higher_bound:
                coeff = self._rule_parameter('work_bonus_coeff')[key]
                result = bonus_basic_amount - (coeff * (salary - wage_lower_bound))
            else:
                result = 0

        # 3. - Détermination du montant de la réduction (P)
        if is_full_time:
            if paid_days < total_days:  # If J=D result will remain same
                result = float_round(paid_days / total_days, precision_digits=2) * result  # P = (J/D) x R
        else:
            result = min(1.0, float_round(paid_hours / total_hours, precision_digits=2)) * result  # P = (H/U) x R, at most R

        already_paid = month_line_values['EmpBonus.1']['sum']['total']
        already_carried_over = month_line_values['EmpBonus.Total.CO']['sum']['total']
        carry_over = prev_month_line_values['EmpBonus.Total.CO']['sum']['total']
        onss = result_rules['ONSS']['total'] + result_rules['ONSS_BONUS']['total'] + result_rules['ONSSRESTRUCTURING']['total']
        # Only the bonus of the month not covered by its ONSS is carried over, the carry over received is lost if unused.
        # The other payslips of the month already carried over their own share: only the difference is added.
        remaining_bonus = float_round(max(0, result - already_paid + onss) - already_carried_over, precision_digits=2)
        result -= already_paid
        return {'result': min(-onss, result + carry_over), 'remaining_bonus': remaining_bonus}

    def _get_termination_children_exoneration(self, children, taxable_reference_salary):
        children_exoneration = self._rule_parameter('holiday_pay_pp_exoneration')
        total = 0
        if children > 0 and taxable_reference_salary <= children_exoneration.get(children, children_exoneration[12]):
            total += children_exoneration.get(children, children_exoneration[12]) - taxable_reference_salary
        return total

    def _get_withholding_taxes_after_child_allowances(self, rates, gross, apply_reduction=True, apply_exoneration=True, get_explanation=False):
        version = self.version_id
        is_termination_fees = self.date_to.year >= 2024 and rates == self._rule_parameter('termination_fees_pp_rates')
        starter_job_deduct_rate = 0.0
        bik_amount = 0.0
        car_atn = 0.0
        base_monthly_revenue = 0.0
        if is_termination_fees:
            yearly_revenue = gross
        else:
            # Annex III n° 53: the yearly normal pay, that of the weekly hours for a worker paid by the hour
            base_monthly_revenue = monthly_revenue = version._l10n_be_get_monthly_wage(self.date_to.year)
            starter_job_deduct_rate = self._get_starterjob_deduction_rate()
            if starter_job_deduct_rate != 0:
                monthly_revenue *= (100 - starter_job_deduct_rate) / 100
            # Count ANT in yearly remuneration
            if version.internet:
                bik_amount += self._rule_parameter('bik_internet_amount')
            if version.mobile:
                bik_amount += self._rule_parameter('bik_phone_sub_amount')
            if version.laptop:
                bik_amount += self._rule_parameter('bik_laptop_amount')
            if version.tablet:
                bik_amount += self._rule_parameter('bik_tablet_amount')
            if version.mobile_amount:
                bik_amount += self._rule_parameter('bik_phone_amount')
            monthly_revenue += bik_amount

            yearly_revenue = monthly_revenue * (1 - 0.1307) * 12.0

            if version.car_id:
                car_atn = self.vehicle_id._get_car_atn(date=self.date_from) if 'vehicle_id' in self else version.car_atn
                yearly_revenue += car_atn
        children_exoneration = self._rule_parameter('holiday_pay_pp_exoneration')
        # Exoneration
        children = version.dependent_children
        exonerated_amount = 0.0
        if apply_exoneration and children > 0 and yearly_revenue <= children_exoneration.get(children, children_exoneration[12]):
            if is_termination_fees:
                yearly_revenue -= children_exoneration.get(children, children_exoneration[12]) - yearly_revenue
                yearly_revenue = max(yearly_revenue, 0)
            else:
                # Annexe III n° 54: the allowance is exempted up to the difference between the limit and the yearly
                # normal pay, the rate and the reduction still follow the yearly normal pay
                exonerated_amount = children_exoneration.get(children, children_exoneration[12]) - yearly_revenue
                gross = max(0, gross - exonerated_amount)

        children_reduction = self._rule_parameter('holiday_pay_pp_rate_reduction')

        rate = self._l10n_be_find_withholding_tax_rates(yearly_revenue, rates)
        withholding_tax_amount = gross * rate
        # Reduction
        reduction_pct = 0.0
        if (apply_reduction and
            children > 0 and
            yearly_revenue <= children_reduction.get(children, children_reduction[5])[1]
        ):
            reduction_pct = children_reduction.get(children, children_reduction[5])[0]
            withholding_tax_amount *= (1 - reduction_pct / 100.0)

        result = - withholding_tax_amount
        if not get_explanation:
            return result

        if is_termination_fees:
            explanation = self.env._(
                "Reference Yearly Remuneration (%(yearly_revenue)s €) = Exceptional Gross (%(gross)s €), as termination fees are taxed on their own annualized amount",
                yearly_revenue=float_round(yearly_revenue, precision_digits=2),
                gross=float_round(gross, precision_digits=2),
            )
        else:
            explanation = self.env._(
                "Reference Yearly Remuneration (%(yearly_revenue)s €) = (Monthly Wage (%(monthly_wage)s €) - Starter Job Deduction (%(starter_job_rate)s %%) + Benefits in Kind (%(bik_amount)s €)) * (1 - 13.07 %% ONSS) * 12 months + Company Car Benefit in Kind (%(car_atn)s €)",
                yearly_revenue=float_round(yearly_revenue, precision_digits=2),
                monthly_wage=float_round(base_monthly_revenue, precision_digits=2),
                starter_job_rate=float_round(starter_job_deduct_rate, precision_digits=2),
                bik_amount=float_round(bik_amount, precision_digits=2),
                car_atn=float_round(car_atn, precision_digits=2),
            )
        explanation += self.env._(
            "\nRate applicable to a Reference Yearly Remuneration of %(yearly_revenue)s €: %(rate)s %%",
            yearly_revenue=float_round(yearly_revenue, precision_digits=2),
            rate=float_round(rate * 100, precision_digits=2),
        )
        if exonerated_amount:
            explanation += self.env._(
                "\nExemption for %(children)s dependent child(ren): Exceptional Gross reduced by %(exonerated_amount)s € as the Reference Yearly Remuneration is below the exemption limit",
                children=children,
                exonerated_amount=float_round(exonerated_amount, precision_digits=2),
            )
        if reduction_pct:
            explanation += self.env._(
                "\nReduction for %(children)s dependent child(ren): -%(reduction_pct)s %%",
                children=children,
                reduction_pct=float_round(reduction_pct, precision_digits=2),
            )
        explanation += self.env._(
            "\nResult = - (Exceptional Gross (%(gross)s €) * Rate (%(rate)s %%)) = %(result)s €",
            gross=float_round(gross, precision_digits=2),
            rate=float_round(rate * 100, precision_digits=2),
            result=float_round(result, precision_digits=2),
        )
        return result, {'explanation': explanation}

    def _get_theoretical_exceptional_monthly_withholding_tax(self, work_entries, exceptional_gross):
        """ Estimate what the monthly professional withholding tax would be on regular contract income topped up by one twelfth of the exceptional gross. """
        version = self.version_id
        # The normal monthly pay, that of the weekly hours for a worker paid by the hour
        monthly_contract_wage = version._l10n_be_get_monthly_wage(self.date_to.year)

        # Add each recurring taxable benefit in kind to the monthly contract wage.
        if version.internet:
            monthly_contract_wage += self._rule_parameter('bik_internet_amount')
        if version.mobile:
            monthly_contract_wage += self._rule_parameter('bik_phone_sub_amount')
        if version.laptop:
            monthly_contract_wage += self._rule_parameter('bik_laptop_amount')
        if version.tablet:
            monthly_contract_wage += self._rule_parameter('bik_tablet_amount')
        if version.mobile_amount:
            monthly_contract_wage += self._rule_parameter('bik_phone_amount')

        # The 13.07 percent personal ONSS contribution is deducted to get the monthly taxable base.
        monthly_taxable = monthly_contract_wage * (1 - 0.1307)
        # The exceptional gross is already net of ONSS at this point, so dividing by 12 gives the monthly share to add.
        monthly_taxable += exceptional_gross / 12.0
        # The bareme brackets work on a yearly basis, so the monthly base is multiplied back up.
        yearly_taxable_gross = monthly_taxable * 12.0

        # The company car ATN is not subject to ONSS, so it is added directly to the yearly taxable base.
        # The version field is used on purpose, as the transport deduction below reads the very same one.
        if version.car_id:
            yearly_taxable_gross += version.car_atn

        # The taxable share of private car kilometre reimbursements is annualised and included here.
        if version.private_car_employee_kilometer:
            car_result, car_result_qty, car_result_rate = self._get_be_private_car_reimbursement_amount(work_entries)
            yearly_taxable_gross += car_result * car_result_qty * car_result_rate / 100 * 12

        # Flat-rate professional fees, same lookup as the F_PROFESSIONAL_FEES rule, are deducted before the bareme
        # applies. This deduction is always granted, so skipping it would overstate the theoretical tax.
        joint_committee_code = self._l10n_be_get_professional_fees_joint_committee_code()
        fees_max = (
            self._rule_parameter(f'flat_rate_professional_fees_max_cp{joint_committee_code}', raise_if_not_found=False)
            or self._rule_parameter('flat_rate_professional_fees_max_cp200', raise_if_not_found=False)
            or 0
        )
        fees_rate = (
            self._rule_parameter(f'flat_rate_professional_fees_rate_cp{joint_committee_code}', raise_if_not_found=False)
            or self._rule_parameter('flat_rate_professional_fees_rate_cp200', raise_if_not_found=False)
            or 0
        )
        # The transport withholding tax exemption offsets car ATN and private car reimbursements, capped at the
        # gross taxable base, same as the TRANSPORT_TAX_DED rule; the fees apply to what remains taxable.
        transport_exemption = min(yearly_taxable_gross, self._get_be_withholding_taxes_transport_deduction(work_entries))
        yearly_net_taxable = yearly_taxable_gross - transport_exemption
        yearly_net_taxable -= min(yearly_net_taxable * fees_rate, fees_max)

        # Run the bareme on the full yearly base, then remove the marital and family charge deductions.
        yearly_theoretical_tax = self._compute_basic_bareme(yearly_net_taxable)
        yearly_theoretical_tax -= self._get_be_withholding_taxes_marital_deduction()
        yearly_theoretical_tax -= self._get_be_withholding_taxes_family_charges_deduction()

        # Floor at zero and divide by twelve, as a negative monthly tax makes no sense.
        return max(0.0, yearly_theoretical_tax) / 12.0

    def _is_exceptional_withholding_tax_exempted(self, year_payslips, work_entries, exceptional_gross):
        """
        Return True when the flat-rate professional withholding tax on double holiday or 13th month pay can be skipped.
        SSCUM for the year and the theoretical monthly tax on regular income must both be zero for the exemption to fire.
        The marital and family charge deductions reused by the theoretical computation cover every scale, so the
        exemption applies to any employee, not only Scale II ones.
        """
        version = self.version_id
        # A CP999 executive can have their monthly tax set as a fixed amount or as a rate on the whole base.
        is_cp999 = version.l10n_be_egov3_code == '999'
        has_fixed_withholding_tax = version.l10n_be_withholding_tax_type == 'fixed' and version.l10n_be_withholding_tax_amount
        has_withholding_tax_rate = version.l10n_be_withholding_tax_type == 'percentage' and version.l10n_be_withholding_tax_percentage
        pays_flat_withholding_tax = is_cp999 and (has_fixed_withholding_tax or has_withholding_tax_rate)

        # Students, PFI employees, interns and those CP999 executives do not pay their monthly tax through the bareme,
        # so the theoretical computation says nothing about them and no exemption is granted.
        if version.is_student() or version._l10n_be_has_internship_withholding_tax_rate() or pays_flat_withholding_tax:
            return False

        # Check that no cumulated professional withholding tax (SSCUM) was paid on BEMONTHLY payslips this year.
        # The year key holds every validated payslip of the year, so the monthly structure is filtered here.
        year_payslips = year_payslips.filtered(
            lambda p: p.struct_id.code == 'BEMONTHLY',
        )
        if year_payslips:
            line_values = year_payslips._get_line_values(['PPTOTAL'], compute_sum=True)
            # PPTOTAL negates the PP category, so it is already the positive amount actually withheld.
            cumulated_professional_withholding_tax = line_values['PPTOTAL']['sum']['total']
            if not float_is_zero(cumulated_professional_withholding_tax, precision_digits=2):
                # Even one monthly payslip with a positive withholding tax is enough to block the exemption.
                return False

        # Simulate what the monthly tax would be on regular income topped up by one twelfth of the exceptional gross.
        theoretical_monthly_tax = self._get_theoretical_exceptional_monthly_withholding_tax(work_entries, exceptional_gross)
        # A zero theoretical tax means the employee genuinely owes nothing on this exceptional payment.
        return theoretical_monthly_tax <= 0

    def _get_be_double_holiday_withholding_taxes(self, categories, year_payslips, work_entries, get_explanation=False):
        self.ensure_one()
        # See: https://www.securex.eu/lex-go.nsf/vwReferencesByCategory_fr/52DA120D5DCDAE78C12584E000721081?OpenDocument

        gross = categories['DH_WITHHOLDING_BASE']
        if gross <= 0:
            explanation_info = {'explanation': self.env._("No withholding tax: the Exceptional Gross is zero.")}
            return (0, explanation_info) if get_explanation else 0
        # Skip the flat-rate tax entirely if the exemption conditions are met.
        if self._is_exceptional_withholding_tax_exempted(year_payslips, work_entries, gross):
            explanation_info = {'explanation': self.env._("No withholding tax: both the cumulated tax of the year and the theoretical tax on regular income are zero.")}
            return (0, explanation_info) if get_explanation else 0
        rates = self._rule_parameter('holiday_pay_pp_rates')

        return self._get_withholding_taxes_after_child_allowances(rates, gross, get_explanation=get_explanation)

    def _get_thirteen_month_withholding_taxes(self, categories, year_payslips, work_entries, get_explanation=False):
        self.ensure_one()
        # See: https://www.securex.eu/lex-go.nsf/vwReferencesByCategory_fr/52DA120D5DCDAE78C12584E000721081?OpenDocument

        gross = categories['BONUS_WITHHOLDING_BASE']
        if gross <= 0:
            explanation_info = {'explanation': self.env._("No withholding tax: the Exceptional Gross is zero.")}
            return (0, explanation_info) if get_explanation else 0
        # Skip the flat-rate tax entirely if the exemption conditions are met.
        if self._is_exceptional_withholding_tax_exempted(year_payslips, work_entries, gross):
            explanation_info = {'explanation': self.env._("No withholding tax: both the cumulated tax of the year and the theoretical tax on regular income are zero.")}
            return (0, explanation_info) if get_explanation else 0
        rates = self._rule_parameter('exceptional_allowances_pp_rates')

        return self._get_withholding_taxes_after_child_allowances(rates, gross, get_explanation=get_explanation)

    def _is_cp200_annual_sectorial_bonus_eligible(self, month_line_values=None):
        self.ensure_one()
        if month_line_values and month_line_values['SECTORIAL.BONUS']['sum']['total'] > 0:
            return False
        EXCLUDED_EMPLOYER_DMFA_CODES = {'024', '026', '044', '054', '114'}
        if (
            self.version_id.l10n_be_reason_code == 355
            or self.version_id.is_flexi()
            or self.version_id.is_student()
            or self.date_to < date(2023, 1, 1)
            or self._l10n_be_get_employer_category_dmfa_code() in EXCLUDED_EMPLOYER_DMFA_CODES
        ):
            return False
        if self.date_to.month == 6:
            return True
        return self._l10n_be_is_last_payslip()

    def _get_cp200_annual_bonus_reference_period(self):
        """
        Reference period of the CP200 Annual Sectorial Bonus: June 1st Y-1 → May 31st Y.

        On a June payslip, the bonus pays the reference period that just ended. On
        a departure payslip, it pays the running reference period the departure
        falls into.
        """
        self.ensure_one()
        year = self.date_to.year if self.date_to.month == 6 else self.date_to.year + 1
        return date(year - 1, 6, 1), date(year, 5, 31)

    def _get_cp200_annual_bonus_prorata(self, work_entries=None):
        """
        Returns the prorata coefficient for the CP200 Annual Sectorial Bonus.

        Computed per version, then summed:
            sum of (ref_calendar_days / C) * (assimilated_hours / H_ref_v)

        Per version:
        - ref_calendar_days: calendar days under that version during reference period (June 1 Y-1 → May 31 Y)
        - total_calendar_days: total calendar days in reference period (365 or 366)
        - assimilated_hours: assimilated hours for that version (paid + maternity/paternity)
        - full_time_hours: reference full-time hours from the version's reference calendar (_get_reference_calendar)
        """
        self.ensure_one()
        ref_start, ref_end = self._get_cp200_annual_bonus_reference_period()

        total_calendar_days = (ref_end - ref_start).days + 1  # 365 or 366

        versions = self.employee_id._get_versions_with_contract_overlap_with_period(ref_start, ref_end)
        if not versions:
            return 0.0

        # https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/fill_in_dmfa/dmfa_fillinrules/servicedatadeclaration/workingtimecodification.html
        excluded = self.env['hr.work.entry.type'].search([('l10n_be_egov3_code', 'not in', ['1101001', '1202001', '1202003', '1203001', '1203002', '1203003',
                                                                                            '1204001', '1204002', '1204003', '1205001', '1205002', '1205003',
                                                                                            '1205005', '1205006', '1206002', '1206003', '1206004', '1209002',
                                                                                            '1298001', '1298004', '1298006', '1298099', '2210002', '2210004',
                                                                                            '2210005', '2210006'])])
        maternity_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity')
        paternity_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_paternity_legal')
        final_excluded_ids = (excluded - maternity_leave - paternity_leave).ids

        prorata = 0.0
        work_entries_vals = work_entries or versions.filtered('resource_calendar_id').generate_work_entries(ref_start, ref_end)
        for v in versions:
            v_start = max(v.date_start, ref_start)
            # date_end ignores departure_date, which is the only end date set until the departure is applied
            v_end = min(v.date_end or self.employee_id.departure_date or ref_end, ref_end)
            if v_end < v_start:
                continue

            ref_calendar_days = (v_end - v_start).days + 1

            ref_calendar = v._get_reference_calendar()
            if not ref_calendar:
                continue
            v_start_dt = datetime.combine(v_start, time.min)
            v_end_dt = datetime.combine(v_end, time.max)

            full_time_hours = ref_calendar.get_work_hours_count(v_start_dt, v_end_dt, compute_leaves=False)
            if not full_time_hours:
                continue

            all_hours = v.get_work_hours(v_start, v_end, work_entries_vals)
            assimilated_hours = sum(
                hours for (work_entry_type_id, _options), hours in all_hours.items()
                if work_entry_type_id.id not in final_excluded_ids)
            if total_calendar_days == 0 or full_time_hours == 0:
                continue
            prorata += (ref_calendar_days / total_calendar_days) * (assimilated_hours / full_time_hours)

        return prorata

    def _get_termination_fees_withholding_taxes(self, result_rules, categories, work_entries):
        # See: https://www.securex.eu/lex-go.nsf/vwReferencesByCategory_fr/52DA120D5DCDAE78C12584E000721081?OpenDocument
        if self.date_from.year >= 2024:
            self.ensure_one()

            rates = self._rule_parameter('termination_fees_pp_rates')
            gross = categories['TERMINATION_WITHHOLDING_BASE']

            return self._get_withholding_taxes_after_child_allowances(rates, gross, apply_reduction=False)

        else:
            yearly_tax_amount = self._get_be_withholding_taxes_basic_bareme(result_rules, work_entries)
            yearly_tax_amount -= self._get_be_withholding_taxes_marital_deduction()
            yearly_tax_amount -= self._get_be_withholding_taxes_family_charges_deduction()
            return -max(0, float_round(yearly_tax_amount / 12.0, precision_rounding=0.01, rounding_method='DOWN'))

    def _get_replacement_revenue_withholding_taxes(self, categories, get_explanation=False):
        self.ensure_one()

        rates = self._rule_parameter('exceptional_allowances_pp_rates')
        gross = categories['TAXABLE_18']
        # Annex III n° 78.1.1: taxed following n° 53 only (the rate of the yearly normal pay), without the exemption
        # (n° 54) and the reduction (n° 55) for dependent children of the exceptional allowances
        return self._get_withholding_taxes_after_child_allowances(rates, gross, apply_reduction=False, apply_exoneration=False, get_explanation=get_explanation)

    def _l10n_be_get_warrant_atn_rate(self, inputs):
        # The optional payslip input overrides the legal percentage (18%)
        atn_percent_input = inputs.get('WARRANT_ATN_PERCENT')
        if atn_percent_input and atn_percent_input.amount:
            return atn_percent_input.amount
        return self._rule_parameter('warrant_atn_percentage')

    def _get_warrant_withholding_taxes(self, categories, get_explanation=False):
        self.ensure_one()

        rates = self._rule_parameter('exceptional_allowances_pp_rates')
        gross = categories['WARRANT_WITHHOLDING_BASE']
        return self._get_withholding_taxes_after_child_allowances(rates, gross, get_explanation=get_explanation)

    def _get_withholding_reduction(self, result_rules, previous_payslips_line_values):
        self.ensure_one()
        reduction_explanation = ''
        # The reductions of the scale reduce the tax of the scale, after its reduction for overtime, and never the
        # exceptional rates of the same payslip: the flat rate on the temporary unemployment supplements (Annex III
        # to the royal decree implementing the ITC 1992, n° 79.2.2: 26.75 % without reduction), the replacement
        # revenue, the premiums or the double holiday pay
        # The reduction is that of the month's work bonus: it is capped by the month's tax, the earlier payslips of
        # the month included (P.P of this payslip is only the increase of the month's tax)
        withholding_tax = result_rules['P.P']['total'] + result_rules['P.P.DEDEH']['total']
        if previous_payslips_line_values:
            withholding_tax += previous_payslips_line_values['P.P']['sum']['total'] + previous_payslips_line_values['P.P.DEDEH']['sum']['total']
        withholding_tax = max(0.0, -withholding_tax)
        if result_rules['EmpBonus.1']:
            bonus_volet_A_rate = self.env['hr.rule.parameter']._get_parameter_from_code('work_bonus_volet_A_rate', date=self.date_to, raise_if_not_found=False) or 0.3314
            if self.date_from >= date(2024, 4, 1):
                bonus_volet_A = result_rules['EmpBonus.A']['total']
                bonus_volet_B = result_rules['EmpBonus.B']['total']
                bonus_volet_B_rate = self.env['hr.rule.parameter']._get_parameter_from_code('work_bonus_volet_B_rate', date=self.date_to, raise_if_not_found=False) or 0.5254
                if previous_payslips_line_values:
                    bonus_volet_A += previous_payslips_line_values['EmpBonus.A']['sum']['total']
                    bonus_volet_B += previous_payslips_line_values['EmpBonus.B']['sum']['total']
                reduction = bonus_volet_A * bonus_volet_A_rate + bonus_volet_B * bonus_volet_B_rate
                reduction_explanation = self.env._(
                    "Reduction (%(value)s) = EmpBonus.A (%(bonus_volet_A)s) * Rate.A (%(bonus_volet_A_rate)s) + EmpBonus.B (%(bonus_volet_B)s) * Rate.B (%(bonus_volet_B_rate)s)\n",
                    value=float_round(reduction, precision_digits=2),
                    bonus_volet_A=float_round(bonus_volet_A, precision_digits=2),
                    bonus_volet_B=float_round(bonus_volet_B, precision_digits=2),
                    bonus_volet_A_rate=float_round(bonus_volet_A_rate, precision_digits=2),
                    bonus_volet_B_rate=float_round(bonus_volet_B_rate, precision_digits=2)
                )
            else:
                bonus = result_rules['EmpBonus.1']['total']
                if previous_payslips_line_values:
                    bonus += previous_payslips_line_values['EmpBonus.1']['sum']['total']
                reduction = bonus * bonus_volet_A_rate
                reduction_explanation = self.env._(
                    "Reduction (%(value)s) = EmpBonus.1 (%(bonus)s) * Rate (%(bonus_volet_A_rate)s)\n",
                    value=float_round(reduction, precision_digits=2),
                    bonus=float_round(bonus, precision_digits=2),
                    bonus_volet_A_rate=float_round(bonus_volet_A_rate, precision_digits=2),
                )

            explanation_info = {'reduction_explanation': reduction_explanation, 'reduction': float_round(reduction, precision_digits=2), 'ded_pp': float_round(withholding_tax, precision_digits=2)}
            return min(withholding_tax, reduction), explanation_info
        return 0.0, {'reduction_explanation': reduction_explanation, 'reduction': 0.0, 'ded_pp': float_round(withholding_tax, precision_digits=2)}

    def _get_fiscal_voluntarism_natures(self):
        # Order in which a fixed fiscal voluntarism amount is spread over the 274 natures
        return ['10', '20', '18', '13', '30']

    def _get_l10n_be_274_nature_values(self, categories, nature):
        """Taxable amount and withholding tax of a 274 nature on the payslip being computed.

        274.10 and 274.20 share a category, the nature follows the contract, as in the 274
        declaration (see `_l10n_be_filter_remuneration_form`): a company director is declared
        on the 274.20 even when flagged for the 281.30.
        """
        self.ensure_one()
        version = self.version_id
        if nature == '10':
            # Employees
            if version.l10n_be_include_employee_in_281_30 or version._l10n_be_is_company_director():
                return 0.0, 0.0
            return categories['TAXABLE_10_20'], -categories['WITHHOLDING_TAX_274_10_20']
        if nature == '20':
            # Company Executives
            if not version._l10n_be_is_company_director():
                return 0.0, 0.0
            return categories['TAXABLE_10_20'], -categories['WITHHOLDING_TAX_274_10_20']
        if nature == '30' and version.l10n_be_include_employee_in_281_30 and not version._l10n_be_is_company_director():
            # Beneficiaries of a 281.30: their salary is declared with their presence tokens on the 274.30
            return categories['TAXABLE_10_20'] + categories['TAXABLE_30'], \
                -categories['WITHHOLDING_TAX_274_10_20'] - categories['WITHHOLDING_TAX_274_30']
        return categories['TAXABLE_%s' % nature], -categories['WITHHOLDING_TAX_274_%s' % nature]

    def _check_fiscal_voluntarism(self, categories, nature):
        version = self.version_id
        if version.fiscal_voluntarism_type == 'percentage':
            is_set = version.fiscal_voluntarism_percentage > 0
        else:
            is_set = version.fiscal_voluntarism_amount > 0
        return is_set and self._get_l10n_be_274_nature_values(categories, nature)[0] > 0

    def _get_fiscal_voluntarism(self, categories, nature):
        """Fiscal voluntarism withheld on the remuneration of a 274 nature.

        A rate applies on the withholding tax of the nature. A fixed amount, or what is missing
        to reach the total amount asked by the employee, is withheld on the first nature of
        `_get_fiscal_voluntarism_natures` and what that nature cannot bear on the next ones.
        In every case the nature cannot withhold more than its taxable amount left.
        """
        self.ensure_one()
        version = self.version_id
        taxable, withholding_tax = self._get_l10n_be_274_nature_values(categories, nature)
        if version.fiscal_voluntarism_type == 'percentage':
            voluntary_amount = withholding_tax * version.fiscal_voluntarism_percentage
        else:
            # The fiscal voluntarism already withheld on the previous natures
            already_withheld = -categories['FISCAL_VOLUNTARISM']
            if version.fiscal_voluntarism_type == 'fixed':
                total_voluntary_amount = version.fiscal_voluntarism_amount
            else:
                total_withholding_tax = -sum(
                    categories['WITHHOLDING_TAX_274_%s' % code]
                    for code in ['10_20', '13', '18', '30']
                ) - already_withheld
                total_voluntary_amount = max(0.0, version.fiscal_voluntarism_amount - total_withholding_tax)
            voluntary_amount = total_voluntary_amount - already_withheld
        limit = max(0.0, min(taxable - withholding_tax, categories['REMUNERATION_BASE']))
        return -max(0.0, min(limit, voluntary_amount))

    def _get_impulsion_plan_amount(self):
        self.ensure_one()
        version = self.version_id
        impulsion_start_date = version._get_l10n_be_impulsion_start_date()
        if not impulsion_start_date or version._get_l10n_be_employee_residence_region() != 'wa':
            return 0, 0
        activation_permitted = self.env['hr.rule.parameter']._get_parameter_from_code('l10n_be_impulsion_activation_permitted', date=impulsion_start_date, raise_if_not_found=False)
        payment_permitted = self.env['hr.rule.parameter']._get_parameter_from_code('l10n_be_impulsion_payment_permitted', date=self.date_from, raise_if_not_found=False)
        if activation_permitted is False or payment_permitted is False:
            return 0, 0
        if version.l10n_be_impulsion_plan == '25yo' and self.employee_id._get_age(impulsion_start_date) >= 25:
            return 0, 0

        brackets = self.env['hr.rule.parameter']._get_parameter_from_code(
            'impulsion25_deduction' if version.l10n_be_impulsion_plan == '25yo' else 'impulsion12_deduction',
            date=impulsion_start_date)
        number_of_months = (self.date_to.year - impulsion_start_date.year) * 12 + (self.date_to.month - impulsion_start_date.month)
        amount = next((amount for max_months, amount in brackets if number_of_months <= max_months), 0)

        paid_hours = sum(self.worked_days_line_ids.filtered('is_paid').mapped('number_of_hours'))
        full_time_hours = version._get_reference_calendar().hours_per_week * 4
        coefficient = min(paid_hours / full_time_hours, 1.0) if full_time_hours else 0
        return amount, coefficient * 100

    def _get_onss_restructuring(self, result_rules):
        self.ensure_one()
        # Source: https://www.onem.be/fr/documentation/feuille-info/t115

        # 1. Grant condition
        # A worker who has been made redundant following a restructuring benefits from a reduction in his personal contributions under certain conditions:
        # - The engagement must take place during the validity period of the reduction card. The reduction card is valid for 9 months, calculated from date to date, following the termination of the employment contract.
        # - The gross monthly reference salary does not exceed
        # o 3.071.90: if the worker is under 30 years of age at the time of entry into service
        # o 4,504.93: if the worker is at least 30 years old at the time of entry into service
        # 2. Amount of reduction
        # Lump sum reduction of € 133.33 per month (full time - full month) in personal social security contributions.
        # If the worker does not work full time for a full month or if he works part time, this amount is reduced proportionally.

        # So the reduction is:
        # 1. Full-time worker: P = (J / D) x 133.33
        # - Full time with full one month benefits: € 133.33

        # Example the worker entered service on 02/01/2021 and worked the whole month
        # - Full time with incomplete services: P = (J / D) x 133.33
        # Example: the worker entered service on February 15 -> (10/20) x 133.33 = € 66.665
        # P = amount of reduction
        # J = the number of worker's days declared with a benefit code 1, 3, 4, 5 and 20 .;
        # D = the maximum number of days of benefits for the month concerned in the work scheme concerned.

        # 2. Part-time worker: P = (H / U) x 133.33
        # Example: the worker starts 02/01/2021 and works 19 hours a week.
        # (76/152) x 133.33 = € 66.665
        # Example: the worker starts 02/15/2021 and works 19 hours a week.
        # (38/155) x 133.33 = 33.335 €

        # P = amount of reduction
        # H = the number of working hours declared with a service code 1, 3, 4, 5 and 20;
        # U = the number of monthly hours corresponding to D.

        # 3. Duration of this reduction
        # The benefit applies to all periods of occupation that fall within the period that:
        # starts to run on the day you start your first occupation during the validity period of the restructuring reduction card;
        # and which ends on the last day of the third quarter following the start date of this first occupation.
        # 4. Formalities to be completed
        # The employer deducts the lump sum from the normal amount of personal contributions when paying the remuneration.
        # The ONEM communicates to the ONSS the data concerning the identification of the worker and the validity date of the card.

        # 5. Point of attention
        # If the worker also benefits from a reduction in his personal contributions for low wages, the cumulation between this reduction and that for restructuring cannot exceed the total amount of personal contributions due.

        # If this is the case, we must first reduce the restructuring reduction.

        # Example:
        # - personal contributions = 200 €
        # - restructuring reduction = € 133.33
        # - low salary reduction = 100 €

        # The total amount of reductions exceeds the contributions due. We must therefore first reduce the restructuring reduction and then the balance of the low wage reduction.
        if not self.worked_days_line_ids:
            return 0, {'restruct_amount': 0.0, 'restruct_ratio': 0.0}

        employee = self.version_id.employee_id
        if employee._get_age(self.version_id.contract_date_start) < 30:
            threshold = self._rule_parameter('onss_restructuring_before_30')
        else:
            threshold = self._rule_parameter('onss_restructuring_after_30')

        salary = result_rules['BASIC']['total']
        if salary > threshold:
            return 0, {'restruct_amount': 0.0, 'restruct_ratio': 0.0}

        amount = self._rule_parameter('onss_restructuring_amount')

        if self.version_id.is_worker():
            amount = amount * self._rule_parameter('worker_onss_calculation_basis_uplift')

        paid_hours = sum(self.worked_days_line_ids.filtered(lambda wd: wd.amount).mapped('number_of_hours'))
        total_hours = sum(self.worked_days_line_ids.mapped('number_of_hours'))
        ratio = paid_hours / total_hours if total_hours else 0

        start = employee.restructuring_reduction_date_start
        end = self.date_to

        quarter_start, _ = date_utils.get_quarter(start)
        expiration_date = quarter_start + relativedelta(months=9)

        if start <= end < expiration_date:
            result = amount * ratio
            return result, {'restruct_amount': float_round(amount, precision_digits=2), 'restruct_ratio': float_round(ratio, precision_digits=2)}

        return 0, {'restruct_amount': float_round(amount, precision_digits=2), 'restruct_ratio': 0.0}

    def _l10n_be_get_onss_rule_parameter(self, code_format):
        """The ONSS rule parameter `code_format` (formatted with the employer category) of the payslip: the one of
        the employer category of the payslip, or of its payroll configuration if not imported (e.g. the rates of
        317 for an occasional worker under a 017 configuration, imported again with the ONSS rates)"""
        self.ensure_one()
        employer_class = self._l10n_be_get_employer_category_dmfa_code()
        value = self._rule_parameter(code_format.format(employer_class=employer_class), self.date_to, raise_if_not_found=False)
        configured_employer_class = self.payroll_config_id.l10n_be_employer_category_id.dmfa_code
        if not value and configured_employer_class and configured_employer_class != employer_class:
            value = self._rule_parameter(code_format.format(employer_class=configured_employer_class), self.date_to, raise_if_not_found=False)
        return value

    def _get_onss_rates(self, worker_code=None, contribution_type='0'):
        self.ensure_one()
        worker_code = worker_code or self.version_id.l10n_be_worker_code_id.dmfa_code
        rates = self._l10n_be_get_onss_rule_parameter(f'l10n_be_onss_rates_{{employer_class}}_{worker_code}_{contribution_type}')
        return rates or {"personal_rate": 0, "employer_rate": 0, "salary_moderation_rate": 0, "total_rate": 0}

    def _get_fse_flat_contribution_type(self):
        """ The contribution type of the flat contribution to the subsistence security fund of the construction workers
        (826): reduced for the workers younger than 25 (type 2), their age at the end of the quarter of the payslip,
        the contribution being quarterly.
        Source: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/other_specialcontributions/subsistenceprotectionfunds.html
        """
        self.ensure_one()
        quarter_end = date_utils.get_quarter(self.date_to)[1]
        return 2 if self.employee_id._get_age(quarter_end) < 25 else 0

    def _get_fse_percentage_contribution_type(self):
        """ The contribution type of the percentage contributions to the subsistence security funds (820 for the
        workers, 830 for the employees). A few sectors have a rate depending on the number of workers of the employer,
        the others have a single rate of type 0.
        Source: ONSS table of the subsistence security funds contributions
        https://www.socialsecurity.be/site_fr/Infos/instructs/documents/xls/FSE_4-2026.xlsx
        and the ONSS rates file (dmfa_rate_2026_3)
        """
        self.ensure_one()
        payroll_config = self.payroll_config_id
        employer_class = payroll_config.l10n_be_employer_category_id.dmfa_code
        # The importance code of the employer: 3 = 10 to 19 workers, 4 = 20 to 49, 5 = 50 to 99. Without it, as a
        # large employer (as before)
        importance_code = int(payroll_config.onss_importance_code or 9)
        if employer_class in ('017', '317', '417'):
            # Hotel industry: type 5 from 50 workers, type 0 below
            return '5' if importance_code >= 5 else '0'
        if employer_class in ('024', '026', '044', '054', '224', '226', '244', '254'):
            # Construction: type 5 from 20 workers, type 0 below
            return '5' if importance_code >= 4 else '0'
        if employer_class == '036':
            # Graphic industry: type 5 from 10 workers, type 0 below
            return '5' if importance_code >= 3 else '0'
        if employer_class == '095':
            # Tourist attractions: type 0 from 20 workers, type 5 below
            return '0' if importance_code >= 4 else '5'
        return '0'

    def _with_salary_moderation(self):
        self.ensure_one()
        contribution_type = '1' if self.version_id.is_worker() else '0'
        return bool(self._get_onss_rates(contribution_type=contribution_type)['salary_moderation_rate'])

    def _get_owedness_codes(self, contribution_worker_code):
        self.ensure_one()
        worker_code = self.version_id.l10n_be_worker_code_id.dmfa_code
        combinations = self._l10n_be_get_onss_rule_parameter(f'l10n_be_onss_combinations_{{employer_class}}_{worker_code}')
        return combinations.get(contribution_worker_code, []) if combinations else []

    def _should_apply_owedness(self, contribution_worker_code, owedness):
        self.ensure_one()
        match owedness:
            case '0':  # apply to everybody
                return True
            case '1':  # do not apply for employee with Dimona Category ALT that are younger than 18 year old
                return (self.employee_id.l10n_be_dimona_category != 'alt' or
                        self.employee_id._get_age(self.date_to + relativedelta(month=1, day=1, days=-1)) >= 18)
            case '2':  # conditional, the condition is specific per rule
                return True
            case '6':  # rule 809 applies only if commercial purpose, 811 applies if no commercial purpose
                return ((contribution_worker_code == '809' and self.payroll_config_id.l10n_be_ffe_employer_type == 'C') or
                        (contribution_worker_code == '811' and self.payroll_config_id.l10n_be_ffe_employer_type == 'B'))
            case '7':  # not for occasional worker (Dimona Category = EXT)
                return self.employee_id.l10n_be_dimona_category != 'ext'
            case '8' | '9':  # public sector, not yet handled
                return False
            case _:
                return False

    def _l10n_be_get_activation_contribution_type(self):
        """ The type of the activation contribution (260/261), its quarterly minimum and whether it is increased (due
        for at least 10% of the workers). The type depends on the age at the start of the exemption from work.
        Source: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/other_specialcontributions/activationcontribution.html
        """
        self.ensure_one()
        version = self.version_id
        quarter_start = date_utils.get_quarter(self.date_to)[0]
        # Only the workers in contract during the quarter, of the employer: the company and all its branches
        all_versions = self.env['hr.version'].sudo().browse([
            versions.sorted('date_version', reverse=True)[0].id
            for _, versions in self.env['hr.version'].sudo()._read_group(
                domain=[
                    ('company_id', 'child_of', self.company_id.root_id.id),
                    ('date_version', '<', self.date_to),
                    ('contract_date_start', '!=', False),
                    '|', ('contract_date_end', '=', False), ('contract_date_end', '>=', quarter_start),
                ],
                groupby=['employee_id'],
                aggregates=['id:recordset'],
            )
        ])
        increased = len(all_versions.filtered(lambda v: v._should_apply_onss_activation())) / len(all_versions) >= 0.1 if all_versions else False
        age = self.employee_id._get_age(version.l10n_be_work_exemption_date or version.date_version)
        if age < 60:
            return ('5' if increased else '0'), 300, increased
        if age < 62:
            return ('6' if increased else '3'), 225.60, increased
        return ('7' if increased else '4'), 225.60, increased

    def _should_apply_onss_contribution(self, contribution_worker_code):
        self.ensure_one()
        if self.version_id.l10n_be_dimona_category == 'dwd':
            # a worker declared without ONSS (Dimona DWD) owes no employer contribution either
            return False
        owedness_codes = self._get_owedness_codes(contribution_worker_code)
        return (bool(owedness_codes) and
                all(self._should_apply_owedness(contribution_worker_code, owedness) for owedness in owedness_codes))

    def _must_contribute_retirement_fund(self):
        self.ensure_one()
        if self._l10n_be_get_employer_category_dmfa_code() in ('017', '317', '417') and (
            self.version_id.l10n_be_dimona_category in ('alt', 'ext')
            or self.version_id.l10n_be_apprenticeship_contract_number
        ):
            # The Horeca pension excludes apprentices and occasional workers.
            return False
        retirement_date = self.version_id.l10n_be_retirement_date
        quarter_start = date_utils.get_quarter(self.date_from)[0]
        return not retirement_date or retirement_date >= quarter_start or self.version_id.l10n_be_contribute_to_fse

    def _l10n_be_get_cct90_threshold_left(self, parameter_code):
        """ The part of the yearly ceiling of the CCT 90 bonuses (per worker and per calendar year, at the
        employer: the company and its branches) the bonus of this payslip can still use: the ceiling minus the part
        used by the other CCT 90 payslips of the year validated before it.

        :param parameter_code: 'cct90_employer_onss_threshold' (ONSS) or 'cct90_employee_pp_threshold' (withholding
            tax)
        """
        self.ensure_one()
        threshold = self._rule_parameter(parameter_code)
        previous_payslips = self.search([
            ('employee_id', '=', self.employee_id.id),
            ('company_id', 'child_of', self.company_id.root_id.id),
            ('struct_id.code', '=', 'BECCT90'),
            ('state', 'in', ['validated', 'paid']),
            ('date_to', '>=', date(self.date_to.year, 1, 1)),
            ('date_to', '<=', date(self.date_to.year, 12, 31)),
            ('id', '!=', self._origin.id or 0),
        ]).filtered(lambda p: (p.date_from, p.id) < (self.date_from, self._origin.id or float('inf')))
        if not previous_payslips:
            return threshold
        # the part of the ceiling used: the bonus base of the solidarity contribution, the withholding tax exemption
        line_code, field = {
            'cct90_employer_onss_threshold': ('ONSS_SOLIDARITY_BONUS', 'amount'),
            'cct90_employee_pp_threshold': ('PP_EXEMP', 'total'),
        }[parameter_code]
        used = abs(previous_payslips._get_line_values([line_code], vals_list=[field], compute_sum=True)[line_code]['sum'][field])
        return max(0.0, threshold - used)

    def _l10n_be_is_excluded_from_employee_retirement_fund(self):
        """ The cases without the sectoral pension contribution of the employees (835), on top of the ones of
        _must_contribute_retirement_fund:
        - the notice indemnity (DmfA wage code 3) for the notaries (employer category 435);
        - the apprentices (worker code 439, or 495 with an apprenticeship) of the construction employers (categories
          024, 026, 044 and 054).
        """
        self.ensure_one()
        employer_category = self._l10n_be_get_employer_category_dmfa_code()
        version = self.version_id
        if employer_category == '435' and self.struct_id.code == 'BETERM':
            return True
        return employer_category in ('024', '026', '044', '054') and (
            version.l10n_be_worker_code_id.dmfa_code == '439'
            or version.l10n_be_dimona_category == 'alt'
            or bool(version.l10n_be_apprenticeship_contract_number)
        )

    def _get_number_repr_fees_units(self, unit, result_rules, worked_days):
        """
        This function is aimed at returning the effective amount of units
        that allow representation fees.

        The unit keyword can be either 'days' or 'hours' and determines
        wether we return how many days or how many hours admit
        representation fees.
        """
        self.ensure_one()
        if unit == 'days':
            field = 'number_of_days'
        elif unit == 'hours':
            field = 'number_of_hours'
        else:
            return 0
        benefit_category = self.env.ref('l10n_be_hr_payroll.REPRESENTATION_FEES')
        result = 0
        # Representation fees aren't paid if there's no basic pay or every day is an absence
        if result_rules['BASIC']['total'] and (not all((days.mapped('work_entry_type_id.count_as') == ['absence']) for days in worked_days.values())):
            def filter(wdl): return benefit_category.id in wdl.work_entry_type_id.category_ids.mapped('id')
            result = sum(self.worked_days_line_ids.filtered(filter).mapped(field))
        return result

    def _get_repr_fees_proration_rate(self, result_rules, worked_days, work_hours_by_calendar_and_period):
        if self.env.context.get('salary_simulation_full_time'):
            return 100

        # The rate is the percentage of the expected work time according to the full-time calendar for the company that is actually being worked
        number_of_hours_worked = self._get_number_repr_fees_units('hours', result_rules, worked_days)
        expected_number_of_hours = work_hours_by_calendar_and_period[self.version_id._get_reference_calendar(), self.date_from, self.date_to]
        return min(((number_of_hours_worked / expected_number_of_hours) * 100), 100)

    def _get_holiday_pay_recovery(self, worked_days):
        """
            See: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/intermediates#intermediate_row_196b32c7-9d98-4233-805d-ca9bf123ff48

            When an employee changes employer, he receives the termination pay and a vacation certificate
            stating his vacation rights. When he subsequently takes vacation with his new employer, the latter
            must, when paying the simple vacation pay, take into account the termination pay that the former
            employer has already paid.

            From an exchange of letters with the SPF ETCS and the Inspectorate responsible for the control of
            social laws, it turned out that when calculating the simple vacation pay, the new employer must
            deduct the exit pay based on the number of vacation days taken. The rule in the ONSS instructions
            according to which the new employer must take into account the exit vacation pay only once when the
            employee takes his main vacation is abolished.

            When the salary of an employee with his new employer is higher than the salary he had with his
            previous employer, his new employer will have, each time he takes vacation days, to make a
            calculation to supplement the nest egg. exit from these days up to the amount of the simple vacation
            pay to which the worker is entitled.

            Concretely:

            2020 vacation certificate (full year):
            - simple allowance 1,917.50 EUR
                - this amounts to 1917.50 / 20 EUR = 95.875 EUR per day of vacation
                - holidays 2021, for example when taking 5 days in April 2021
            - monthly salary with the new employer: 3000.00 EUR / month
                - simple nest egg:
                     - remuneration code 12: 5/20 x 1917.50 = 479.38 EUR
                     - remuneration code 1: (5/22 x 3000.00) - 479.38 = 202.44 EUR
                - ordinary days for the month of April:
                    - remuneration code 1: 17/22 x 3000.00 = 2318.18 EUR
                    - The examples included in the ONSS instructions will be adapted in the next publication.

            We now recover only 90% of the calculated amount.
            Additionally, the recovered amount may exceed the initial amount to recover
            if the employee's current salary is higher than their previous one!
        """
        self.ensure_one()
        explanation_info = {'remaining_day_amount': 0.0, 'holiday_amount': 0.0}
        if '016.00' not in worked_days or not sum(worked_days['016.00'].mapped('amount')):
            return 0, explanation_info

        number_of_days_allocated = sum(
            self.employee_id.l10n_be_holiday_attest_ids
                .filtered(lambda att: att.year == self.date_from.year - 1)
                .mapped("days_to_allocate"),
        )

        all_payslips_during_civil_year = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', date(self.date_from.year, 1, 1)),
            ('date_to', '<=', date(self.date_from.year, 12, 31)),
            ('state', 'in', ['validated', 'paid']),
        ])
        paid_leave_days = all_payslips_during_civil_year._get_worked_days_line_values(['016.00'], ['number_of_days'], True)['016.00']['sum']['number_of_days']
        remaining_days = number_of_days_allocated - paid_leave_days
        if remaining_days <= 0:
            return 0, explanation_info
        if self.wage_type == 'hourly':
            employee_hourly_cost = self.version_id.hourly_wage
        else:
            if self.date_from.year < 2024:
                employee_hourly_cost = self.version_id._get_contract_wage() / self.sum_worked_hours
            else:
                hours_per_week = self.version_id._l10n_be_get_hours_per_week(self.date_from.year)
                if not hours_per_week:
                    return 0, explanation_info
                weekly_wage = self.version_id._get_contract_wage() * 3 / 13
                employee_hourly_cost = weekly_wage / hours_per_week
        remaining_day_amount = remaining_days * employee_hourly_cost * self.version_id.resource_calendar_id.hours_per_day
        paid_leave_data = self._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        holiday_amount = min(paid_leave_data['amount'], employee_hourly_cost * paid_leave_data['number_of_hours'])
        explanation_info.update({'remaining_day_amount': float_round(remaining_day_amount, precision_digits=2), 'holiday_amount': float_round(holiday_amount, precision_digits=2)})
        return - min(remaining_day_amount, holiday_amount) * 0.9, explanation_info

    def _get_termination_n_basic_double(self):
        self.ensure_one()
        result_qty = 1
        result_rate = 6.8
        result = self._get_input_line_amount('GROSS_REF')
        date_from = self.date_from
        if self.struct_id.code == "BEHOLN1":
            existing_double_pay = self.env['hr.payslip'].search([
                ('employee_id', '=', self.employee_id.id),
                ('state', 'in', ['validated', 'paid']),
                ('struct_id', '=', self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id),
                ('date_from', '>=', date(date_from.year, 1, 1)),
                ('date_to', '<=', date(date_from.year, 12, 31)),
            ])
            if existing_double_pay:
                result = 0
        return (result_qty, result_rate, result)

    def _get_upcoming_public_holiday_count(self, public_holidays):
        self.ensure_one()
        if not public_holidays:
            return 0

        version = self.version_id
        end_date = False
        if not version.employee_id.version_ids.filtered(lambda v: v.date_start > (version.date_end or self.employee_id.departure_date)):
            end_date = self.employee_id.departure_date or version.contract_date_end
        if not end_date or not (self.date_from <= end_date <= self.date_to):
            return 0

        # Loi du 4 janvier 1974, art. 14: only when the employer ends the contract, except for a serious misconduct.
        # No right with less than 15 days of service at the end of the contract, the holidays within 14 days of the
        # end with less than one month of service, within 30 days beyond. With an indemnity for the notice not
        # worked, the period starts at the end of the period it covers.
        if self.employee_id.departure_reason_id.l10n_be_reason_code not in EMPLOYER_NOTICE_REASON_CODES:
            return 0
        if (end_date - version.contract_date_start).days + 1 < 15:
            return 0
        upcoming_period = 30 if version.contract_date_start + relativedelta(months=1) <= end_date else 14
        departure = self.employee_id.departure_id
        if departure.l10n_be_notice_respect != 'with' and departure.l10n_be_notice_period_theoretical_end:
            end_date = max(end_date, departure.l10n_be_notice_period_theoretical_end)
        company_tz = ZoneInfo(self.company_id.tz or 'UTC')

        number_of_upcoming_public_holidays = 0
        for public_holiday in public_holidays:
            # the holidays are stored in UTC from midnight in the company's time zone
            holiday_date = public_holiday.date_from.replace(tzinfo=UTC).astimezone(company_tz).date()
            if 0 < (holiday_date - end_date).days <= upcoming_period:
                number_of_upcoming_public_holidays += 1

        return number_of_upcoming_public_holidays

    def _get_double_pay_to_recover(self):
        self.ensure_one()

        attests = self.employee_id.l10n_be_holiday_attest_ids.filtered(lambda a: a.year == self.date_from.year - 1)

        return sum(attest._get_double_holiday_pay_cap(self.date_from) for attest in attests)

    def _get_holiday_pay_regularization(self, result_rules, year_payslips):
        """Compute the annual holiday pay regularization for previous year's holiday attestations (N-1).

        Throughout the year, taking legal leave (`016.00`) deducts 90% of the hourly wage via the
        `HolPayRec` salary rule up to the earned attestation hours. During year-end regularization
        (typically December), this method calculates the final adjustment required to reach 100%
        of the gross leave wage equivalent, capped by the total simple holiday pay attestation limit
        (`amount_to_recover`) prorated to the attestation hours taken.

        Why Ground-Truth Chronological Recomputation:
            Legacy databases may contain payslips that deducted recovery at 100% instead of 90% (or used
            custom rates). Relying on DB line totals (`recovered / 0.9`) on mixed histories distorts the
            100% wage base calculation.

            To solve this cleanly without trusting historical line values:
            1. `actual_recovered_amount` reads what was *actually deducted* from the employee on DB lines.
            2. `total_100_pct_wage` recomputes the true 100% gross leave wage chronologically
               across past payslips using each payslip's contract version wage (`version.wage`) and the
               Belgian hourly wage formula:
                   hourly_cost = (version._get_contract_wage() * 3.0 / 13.0) / hours_per_week

        Formula & Logic Flow:
            - max_recoverable = min(total_100_pct_wage, amount_to_recover * hours taken / attestation hours)
            - regularization_amount = max_recoverable - actual_recovered_amount
            - Return value = -regularization_amount

        Sign Convention & Auto-Correction:
            - Negative return value (-): Deducts the remaining 10% (or missing adjustment) from the employee.
            - Positive return value (+): Refunds over-recovered amounts to the employee if historical
              deductions exceeded `max_recoverable`.

        Args:
            result_rules (dict): Rule results of the current payslip.
            year_payslips (hr.payslip): Validated/paid payslips of the current year.

        Returns:
            tuple:
                - float: Regularization amount (-regularization_amount) for the payslip line.
                - dict: Explanation info breakdown ('recovered', 'total_100_pct_wage',
                        'amount_to_recover', 'max_amount').
        """
        self.ensure_one()

        employee = self.employee_id
        attestations = employee.l10n_be_holiday_attest_ids.filtered(lambda a: a.year == self.date_from.year - 1)
        amount_to_recover = sum(attestations.mapped("simple_holiday_pay_cap"))

        if not amount_to_recover:
            return 0.0, {}

        # the hours the certificates allocate (capped at 4 weeks, converted to the new schedule), as HolPayRec
        hours_to_recover = sum(attestations.mapped("hours_to_allocate"))
        if not hours_to_recover:
            return 0.0, {}

        all_payslips = (year_payslips | self).sorted('date_from')

        # what was recovered so far, the settlement of an earlier payslip included (the last monthly payslip and the
        # termination fees payslip of a departure both settle)
        line_values = year_payslips._get_line_values(['HolPayRec', 'HolPayReg'], compute_sum=True)
        actual_recovered_amount = -line_values['HolPayRec']['sum']['total'] - line_values['HolPayReg']['sum']['total']

        if 'HolPayRec' in result_rules:
            actual_recovered_amount += -result_rules['HolPayRec']['total']

        remaining_attest_hours = hours_to_recover
        total_100_pct_wage = 0.0

        for payslip in all_payslips:
            if remaining_attest_hours <= 0:
                break

            leave_wd = payslip.worked_days_line_ids.filtered(lambda w: w.code == '016.00')
            leave_hours = sum(leave_wd.mapped('number_of_hours'))

            if leave_hours > 0:
                version = payslip.version_id
                if payslip.wage_type == 'hourly':
                    hourly_cost = version.hourly_wage
                else:
                    hours_per_week = version._l10n_be_get_hours_per_week(payslip.date_from.year)
                    if not hours_per_week:
                        continue
                    weekly_wage = version._get_contract_wage() * 3.0 / 13.0
                    hourly_cost = weekly_wage / hours_per_week

                covered_hours = min(leave_hours, remaining_attest_hours)
                total_100_pct_wage += covered_hours * hourly_cost
                remaining_attest_hours -= covered_hours

        # the cap of the certificates is prorated to the hours taken: cap * hours taken / hours of the certificates
        taken_attest_hours = hours_to_recover - max(remaining_attest_hours, 0)
        amount_to_recover = amount_to_recover * taken_attest_hours / hours_to_recover
        max_recoverable = min(total_100_pct_wage, amount_to_recover)
        regularization_amount = max_recoverable - actual_recovered_amount

        explanation_info = {
            k: float_round(v, precision_digits=2)
            for k, v in {
                'recovered': actual_recovered_amount,
                'total_100_pct_wage': total_100_pct_wage,
                'amount_to_recover': amount_to_recover,
                'max_amount': max_recoverable,
            }.items()
        }

        return -regularization_amount, explanation_info

    def add_upcoming_public_holiday_on_termination(self):
        self.ensure_one()
        number_of_public_holidays = self.env.context.get('number_of_public_holidays', 0)
        if number_of_public_holidays <= 0:
            return
        upcomming_public_holiday_type = self.env['hr.work.entry.type'].search([
                ('code', '=', '202.00'),
                ('country_id.code', '=', 'BE')
            ], limit=1)
        days_per_week = self.version_id.resource_calendar_id.days_per_week
        hours_per_day = self.version_id.resource_calendar_id.hours_per_day
        if self.version_id.wage_type == 'hourly':
            # paid by the hour: the hours of a normal day at the hourly wage
            result = self.version_id._get_contract_wage() * hours_per_day
        else:
            result = self.version_id._get_contract_wage() * 3 / 13 / days_per_week
        unlink_records = self.worked_days_line_ids.filtered_domain([('work_entry_type_id', '=', upcomming_public_holiday_type.id)])
        if unlink_records:
            unlink_records.unlink()
        self.env['hr.payslip.worked_days'].create({
            'payslip_id': self.id,
            'version_id': self.version_id.id,
            'number_of_days': number_of_public_holidays,
            'number_of_hours': number_of_public_holidays * hours_per_day,
            'amount': result * number_of_public_holidays,
            'work_entry_type_id': upcomming_public_holiday_type.id,
        })
        self.compute_sheet()

    def _get_current_quarter_sum(
        self, rule_codes, result_rules, quarter_payslips, quarter_totals, include_current_payslip=True, prefetch_rule_codes=(),
    ):
        self.ensure_one()
        missing_rule_codes = {*rule_codes, *prefetch_rule_codes} - quarter_totals.keys()
        if missing_rule_codes:
            # TODO: to keep old behavior, the following line was added but we need make sure this is intended
            #  (for example the termination payslip was not regulating the ONSS with regular payslips,
            #  ~800€ difference in the 'test test_06_declaration_employee_no_notice_period')
            quarter_prev_payslips = quarter_payslips.filtered(lambda p: p.struct_id == self.struct_id)
            line_values = quarter_prev_payslips._get_line_values(missing_rule_codes, compute_sum=True)
            quarter_totals.update({
                rule_code: line_values[rule_code]['sum']['total']
                for rule_code in missing_rule_codes
            })
        total_prev_payslips = sum(quarter_totals[rule_code] for rule_code in rule_codes)
        total_current_payslip = sum(result_rules.get(rule_code, {'total': 0})['total'] for rule_code in rule_codes)
        return total_prev_payslips + (total_current_payslip if include_current_payslip else 0)

    def _l10n_be_get_onss_basis_uplift(self):
        """ The factor of the ONSS contributions basis: 108% for the blue collars, whose holiday pay is paid
        by the holiday fund (a flexi-job's holiday pay is the flexi holiday pay, already in the basis) """
        self.ensure_one()
        employer_category = self._l10n_be_get_employer_category_dmfa_code()
        # the 108% base of blue collars stands for the holiday pay of the holiday fund; a flexi-job's holiday pay
        # is the flexi holiday pay, already in the base
        if self.version_id.is_worker() and not self.version_id.is_flexi() and employer_category not in ['036', '320']:
            return self._rule_parameter('worker_onss_calculation_basis_uplift')
        return 1

    def _get_onss_contribution_amount(self, base_amount, rate, with_uplift=True):
        """ :param with_uplift: False for a flat amount, not a remuneration (e.g. the flat contribution to a
            subsistence security fund): the 108% basis of the blue collars doesn't apply """
        self.ensure_one()
        uplift = self._l10n_be_get_onss_basis_uplift() if with_uplift else 1
        return float_round(base_amount * uplift * rate / 100, 2)

    def _get_regularised_onss_contribution_amount(self, contribution_code, rate, result_rules, quarter_payslips, quarter_totals, base_codes=None, quarter_base=None, with_uplift=True, quarter_minimum=0.0):
        """ The contribution of the quarter, at least quarter_minimum, minus the contribution already paid by the
        other payslips of the quarter """
        self.ensure_one()
        if base_codes is None:
            base_codes = self._get_salary_wage_line_codes() - {'DH_SALARY'}
        if quarter_base is None:
            employer_rule_codes = {
                code for code in self.struct_id.rule_ids.mapped('code') if code.startswith('ONSSEMPLOYER')
            }
            quarter_base = self._get_current_quarter_sum(
                base_codes, result_rules, quarter_payslips, quarter_totals, prefetch_rule_codes=employer_rule_codes,
            )
        quarter_contribution = self._get_onss_contribution_amount(quarter_base, rate, with_uplift=with_uplift)
        if quarter_minimum:
            quarter_contribution = max(quarter_minimum, quarter_contribution)
        already_paid_contribution = self._get_current_quarter_sum([contribution_code], result_rules, quarter_payslips, quarter_totals)
        return quarter_contribution - already_paid_contribution

    def _calculate_dmfa_occupation_fraction(self, quarter_payslips):
        self.ensure_one()
        uu = self.employee_id.version_id._get_reference_calendar().hours_per_week
        employer_category = self._l10n_be_get_employer_category_dmfa_code()
        match employer_category:
            case '024' | '026' | '044' | '054' | '224' | '226' | '244' | '254':
                excluded_codes = {10, 11, 50, 51, 53, 60, 61}
            case '521' | '621' | '721' | '121' | '221' | '421':
                excluded_codes = {13, 21, 22, 24, 25, 26, 30}
            case '036':
                excluded_codes = {4, 21, 22, 25, 26, 30, 72, 73, 74}
            case '320':
                excluded_codes = {21, 25, 30, 72, 73}
            case '083' | '091':
                excluded_codes = {12, 30, 73}
            case '084':
                excluded_codes = {30, 50, 51, 53, 60}
            case _:
                excluded_codes = set()

        zz = sum(
            wl.number_of_hours
            for payslip in quarter_payslips
            for wl in payslip.worked_days_line_ids
            if int(wl.work_entry_type_id.dmfa_code) not in excluded_codes and wl.sequence != 99
        )

        mu_c = zz / (13 * uu)
        return float_round(min(mu_c, 1.0) * 100, precision_digits=2)

    def _get_ffe_contribution_type(self):
        """ The contribution type of the basic Closure Fund contribution of the commercial employers (809): by
        number of workers, with wage moderation, or without it, as the subsidised contracts (ACS).
        Source: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/other_specialcontributions/basiccontributions_closingcompanyfunds.html
        """
        self.ensure_one()
        with_moderation = self._with_salary_moderation() and not self.version_id._l10n_be_is_subsidised_contract()
        if self.payroll_config_id.onss_importance_code in ['1', '2', '3']:
            contribution_type = '0' if with_moderation else '2'
        else:
            contribution_type = '5' if with_moderation else '4'
        return contribution_type

    def _get_ffe_without_headcount_contribution_type(self):
        """ The contribution type of the special Closure Fund contribution (810) and of the basic one of the
        employers without industrial or commercial purpose (811): 0 with wage moderation, 2 without it, as the
        subsidised contracts (ACS), whose ordinary contributions do include the wage moderation.
        Sources: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/other_specialcontributions/specialcontribution_closingcompanyfunds.html
        https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/other_specialcontributions/basiccontributions_closingcompanyfunds.html
        """
        self.ensure_one()
        return '0' if self._with_salary_moderation() and not self.version_id._l10n_be_is_subsidised_contract() else '2'

    def _l10n_be_defer_fiscal_date(self):
        """Attach to the confirmation period the remunerations paid after their own pay period
        has already been declared: they can no longer be added to that declaration."""
        # A refund reverses an already declared period on its own: deferring it would declare a
        # negative amount alone in the fiscal period. It follows its correction instead, if any.
        late_slips = self.filtered(
            lambda p: p.date_to and p.done_date and p.done_date.date() > p.date_to
            and not p.is_refund_payslip)
        if not late_slips:
            return
        declared_sheets = self.env['l10n_be.274_xx'].sudo().search([
            ('company_id', 'in', late_slips.company_id.root_id.ids),
            ('state', 'in', ['ready', 'done']),
            ('date_start', '<=', max(late_slips.mapped('date_from'))),
            ('date_end', '>=', min(late_slips.mapped('date_to'))),
        ])
        for payslip in late_slips:
            pay_period_declared = any(
                sheet.company_id == payslip.company_id.root_id
                and sheet.date_start <= payslip.date_from and payslip.date_to <= sheet.date_end
                for sheet in declared_sheets)
            if payslip.l10n_be_arrear_salary or pay_period_declared:
                payslip.l10n_be_fiscal_date = payslip.done_date.date()
                # A correction resolves its attachment with its refund, see _l10n_be_apply_correction_fiscal_period
                if not payslip.is_correction_payslip:
                    payslip._l10n_be_attach_benefits_to_fiscal_period()

    def _l10n_be_attach_benefits_to_fiscal_period(self):
        """Declare the benefits in kind of a deferred payslip with the rest of it.

        The withholding tax on the benefits in kind is withheld when the payslip is paid, so the
        taxable amount it is withheld on must be declared with it, not in the pay period already
        declared. Only the attachment of the rules: an amount pinned by hand keeps its own.
        """
        self.line_ids.filtered(
            lambda line: line.l10n_be_follow_pay_period
            and line.salary_rule_id.l10n_be_follow_pay_period == 'always'
        ).l10n_be_follow_pay_period = False

    def _l10n_be_apply_correction_fiscal_period(self):
        """Bring a correction back to the period it corrects when it lowers the declared amounts.

        A correction is paid now, so like any late remuneration it is declared now. An amount
        that goes down is the exception: declaring it now would mean a negative amount, which is
        refused, so the correction and its refund stay attached to the period they correct.

        A correction declared now declares its benefits in kind now too, as any deferred payslip
        (see _l10n_be_attach_benefits_to_fiscal_period).
        """
        for correction in self.filtered(lambda p: p.is_correction_payslip and p.origin_payslip_id):
            origin = correction.origin_payslip_id
            lowers_declaration = (
                float_compare(correction.gross_wage, origin.gross_wage, 2) < 0
                or float_compare(correction.l10n_be_withholding_taxes, origin.l10n_be_withholding_taxes, 2) < 0
            )
            refunds = origin.related_payslip_ids.filtered('is_refund_payslip')
            if lowers_declaration:
                (correction | refunds).l10n_be_fiscal_date = correction.date_to
            else:
                refunds.l10n_be_fiscal_date = correction.l10n_be_fiscal_date
                if correction.l10n_be_fiscal_date and correction.l10n_be_fiscal_date > correction.date_to:
                    correction._l10n_be_attach_benefits_to_fiscal_period()
            # A reversal and the correction replacing it are one operation, so both halves of the
            # delta must land in the same declaration: the reversal takes the attachment its
            # counterpart resolved, which it could not resolve itself for lack of a delta.
            attachment = {line.code: line.l10n_be_follow_pay_period for line in correction.line_ids}
            for line in refunds.line_ids:
                if line.code in attachment:
                    line.l10n_be_follow_pay_period = attachment[line.code]

    def _get_l10n_be_arrear_average_tax_rate(self):
        """
        Compute the average withholding tax rate for the arrear salary year.
        average_rate = total withholding tax paid / total taxable salary in the arrear year.
        """
        self.ensure_one()
        arrear_year = self.date_from.year
        year_payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ['validated', 'paid']),
            ('date_from', '>=', date(arrear_year, 1, 1)),
            ('date_to', '<=', date(arrear_year, 12, 31)),
            ('l10n_be_arrear_salary', '=', False),
            ('company_id', '=', self.company_id.id),
        ])
        if not year_payslips:
            return 0.0
        line_values = year_payslips._get_line_values(['PPTOTAL', 'GROSS'], compute_sum=True)
        total_tax = line_values['PPTOTAL']['sum']['total']
        total_gross = line_values['GROSS']['sum']['total']
        if not total_gross:
            return 0.0
        return total_tax / total_gross

    @api.constrains('l10n_be_arrear_salary')
    def _check_l10n_be_arrear_salary(self):
        if self.l10n_be_arrear_salary and self.create_date.year <= self.date_from.year:
            raise ValidationError(self.env._("Arrear salary must be for a prior year."))

    def _l10n_be_get_december_holiday_regularization(self, get_explanation=False):
        """
        compute the regularization for december:
        'what the employee should receive' - 'what was already paid'
        """
        self.ensure_one()
        if (self.struct_id.code == 'BEMONTHLY' and self.l10n_be_is_december) or self.struct_id.code == 'BEHOLN1':
            simple_holiday_due, double_holiday_due = self._l10n_be_get_holiday_pay_due()
            simple_holiday_n, double_holiday_n = self._l10n_be_get_holiday_pay_n()

            simple_december_pay = max(0, simple_holiday_due - simple_holiday_n)
            total_double_december_pay = max(0, double_holiday_due - double_holiday_n)
            explanation_info = {'explanation': self.env._(
                "Result = Max(0, Simple Holiday Due (%(simple_holiday_due)s €) - Simple Holiday Already Paid (%(simple_holiday_n)s €))",
                simple_holiday_due=float_round(simple_holiday_due, precision_digits=2),
                simple_holiday_n=float_round(simple_holiday_n, precision_digits=2)
            )}
            result = {
                'simple': simple_december_pay,
                'double': total_double_december_pay,
            }
            return (result, explanation_info) if get_explanation else result

        return ({}, {}) if get_explanation else {}

    def _l10n_be_get_remuneration_n1(self):
        """
        Remuneration of the previous year:
        gross salary of year N-1 + fictive gross for assimilated periods of absence.

        13th month salary:
        - for 'Departure Holiday Attests': included in the remuneration
        - for 'December Settlement': NOT included in the remuneration
        """
        self.ensure_one()
        if not self.employee_id or (not self.l10n_be_is_december and self.struct_id.code != 'BEHOLN1'):
            return 0
        struct_codes = ['BEMONTHLY']
        if self.struct_id.code == 'BEHOLN1':
            struct_codes.append('BETHIRTEEN')
        payslips_n1 = self.employee_id._get_payslips_for_year(
            self.date_from.year - 1,
            struct_codes
        )
        salary_codes = self._get_salary_wage_line_codes()
        line_values = payslips_n1._get_line_values(salary_codes, compute_sum=True)
        net_n1 = sum(line_values[code]['sum']['total'] for code in salary_codes)
        fictitious_remuneration_n1 = self.employee_id._get_fictitious_remuneration_previous_year(self.date_from, payslips=payslips_n1)
        remuneration_n1 = net_n1 + fictitious_remuneration_n1
        return remuneration_n1

    def _l10n_be_get_holiday_pay_due(self):
        """
        compute Simple Holiday and Double Holiday which the employee should receive.
        Calculation is based on the remuneration of the previous year
        """
        self.ensure_one()
        remuneration_n1 = self._l10n_be_get_remuneration_n1()
        simple_holiday_due = remuneration_n1 * 0.0767
        gross_reference_n1 = self._get_input_line_amount('GROSS_REF') if self.struct_id.code == 'BEHOLN1' else 0
        if gross_reference_n1:
            # The departure passes the gross reference remuneration of the previous year, which can be encoded when
            # that year's payroll is not in Odoo: the simple holiday pay due follows it.
            simple_holiday_due = gross_reference_n1 * 0.0767
        current_year = self.date_from.replace(month=1, day=1)
        dp_date = current_year.replace(month=self._l10n_be_get_theoretical_double_holiday_pay_month())
        # The exit double holiday pay is 7.67% of the gross earned at this employer: the months of the previous
        # employers' certificates were paid by them (no DOUBLERECOVERY on the departure structure)
        double_holiday_due_based_on_main_holiday_month = self._l10n_be_get_paid_double_holiday(
            base_month=dp_date, include_attests=self.struct_id.code != 'BEHOLN1') * 0.92
        double_holiday_due = max(remuneration_n1 * 0.0767, double_holiday_due_based_on_main_holiday_month)
        return simple_holiday_due, double_holiday_due

    def _l10n_be_get_holiday_pay_n(self):
        """
        Compute Simple Holiday and Double Holiday already paid in this year
        """
        self.ensure_one()
        current_year = self.date_from.replace(month=1, day=1)
        structure_monthly_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        structure_double_holiday = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday')
        payslips_n = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', current_year),
            ('date_to', '<=', self.date_to),
            ('state', 'in', ['validated', 'paid']),
            ('struct_id', 'in', (structure_monthly_pay + structure_double_holiday).ids)])
        double_payslip = payslips_n.filtered(lambda p: p.struct_id == structure_double_holiday)
        monthly_payslips = payslips_n - double_payslip

        simple_holiday_n = monthly_payslips._get_worked_days_line_values(
            ['016.00'], ['amount'], True)['016.00']['sum']['amount']
        simple_holiday_n += monthly_payslips._get_line_values(
            ['SIMPLE_DECEMBER'], ['amount'], compute_sum=True)['SIMPLE_DECEMBER']['sum']['amount']
        # the days of the previous employers' holiday certificates are paid by them: the wage paid for them is
        # recovered (HolPayRec, HolPayReg, negative)
        recovery_values = monthly_payslips._get_line_values(['HolPayRec', 'HolPayReg'], compute_sum=True)
        simple_holiday_n += recovery_values['HolPayRec']['sum']['total'] + recovery_values['HolPayReg']['sum']['total']
        simple_holiday_n += monthly_payslips._get_line_values(
            ['COM_LOSS_PTO'], compute_sum=True)['COM_LOSS_PTO']['sum']['total']

        double_holiday_n = payslips_n._get_line_values(
            ['DH_BASIC'], compute_sum=True)['DH_BASIC']['sum']['total']
        if self.struct_id.code == 'BEHOLN1':
            # the double holiday pay of the previous employers' months, paid with DH_BASIC, was recovered
            recovery_codes = ['DOUBLERECOVERYONSS', 'DOUBLERECOVERYNOONSS']
            recovery_values = double_payslip._get_line_values(recovery_codes, compute_sum=True)
            double_holiday_n += sum(recovery_values[code]['sum']['total'] for code in recovery_codes)

        return simple_holiday_n, double_holiday_n

    def _get_unused_legal_leave_at_year_end(self, leave_code, employee, cutoff):
        year_end = cutoff.replace(month=12, day=31)
        leave_type = self.env['hr.work.entry.type'].search([('code', '=', leave_code)], limit=1)
        if leave_type:
            all_leaves_data = leave_type.get_allocation_data(employee, year_end)
            employee_data = all_leaves_data.get(employee, [])
            for name, vals, *_rest in employee_data:
                if name == leave_type.name:
                    return vals.get('virtual_remaining_leaves', 0.0)
        return 0.0

    def _l10n_be_get_legal_leave_days_per_month(self):
        self.ensure_one()
        current_year = self.date_from.replace(month=1, day=1)
        next_year = current_year + relativedelta(years=1)
        monthly_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        payslips_n = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', current_year),
            ('date_to', '<', next_year),
            ('state', 'in', ['validated', 'paid']),
            ('struct_id', '=', monthly_pay.id)])
        return {
            date_to.month: sum(
                slips._get_worked_days_line_values(['016.00'], ['number_of_days'], True)['016.00']['sum']['number_of_days']
                for slips in grouped_slips
            )
            for date_to, grouped_slips in payslips_n.grouped('date_to').items()
        }

    def _l10n_be_get_theoretical_double_holiday_pay_month(self):
        """
        The method returns a month with the maximum days of vacation.
        If there are more than one maximum, returns a months after which is impossible to take a vacation longer than maximum
        (according to the documentation)
        """
        self.ensure_one()
        payslip_month = self.date_to.month
        holidays_dict = self._l10n_be_get_legal_leave_days_per_month()
        if not holidays_dict or not any(holidays_dict.values()):
            return payslip_month

        days_off_left = self._get_unused_legal_leave_at_year_end("016.00", self.employee_id, self.date_from)
        total_taken = sum(holidays_dict.values())
        total_allowance = total_taken + days_off_left
        if days_off_left > total_allowance / 2:
            return payslip_month

        max_value = max(holidays_dict.values())
        remaining_balance = total_allowance
        for month in sorted(holidays_dict.keys()):
            remaining_balance -= holidays_dict[month]
            if holidays_dict[month] == max_value and remaining_balance <= max_value:
                return month
        return payslip_month

    def _l10n_be_get_termination_yearly_salary(self):
        self.ensure_one()
        current_quarter_start = date_utils.get_quarter(self.date_from)[0]
        previous_quarter_end = current_quarter_start - relativedelta(days=1)
        previous_quarter_start = date_utils.get_quarter(previous_quarter_end)[0]

        loop_guard = 0
        max_quarters_lookback = 40  # at most 10 years lookback
        while loop_guard < max_quarters_lookback:
            payslips_previous_quarter = self.env['hr.payslip'].search([
                ('employee_id', '=', self.employee_id.id),
                ('date_from', '>=', previous_quarter_start),
                ('date_to', '<=', previous_quarter_end),
                ('state', 'in', ['validated', 'paid']),
                ('struct_id.code', '=', "BEMONTHLY")
            ])

            eligible_worked_days = payslips_previous_quarter.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id.dmfa_code in ['1', '101']) if payslips_previous_quarter else False
            if eligible_worked_days:
                quarter_basis = payslips_previous_quarter._get_line_values(['SALARY'], compute_sum=True)['SALARY']['sum']['total']
                if quarter_basis > 0:
                    if self.version_id.work_time_rate == 1:
                        total_worked_days = sum(eligible_worked_days.mapped('number_of_days'))
                        day_basis = quarter_basis / total_worked_days
                    else:
                        total_worked_hours = sum(eligible_worked_days.mapped('number_of_hours'))
                        day_basis = quarter_basis / total_worked_hours * self.version_id._get_reference_calendar().hours_per_week / 5
                    # the annual salary of a worker whose holiday pay is paid by a holiday fund is taken at 108%
                    return day_basis * 260 * self._l10n_be_get_onss_basis_uplift()
            previous_quarter_end = previous_quarter_start - relativedelta(days=1)
            previous_quarter_start = date_utils.get_quarter(previous_quarter_end)[0]
            loop_guard += 1
        return 0

    @api.model
    def _l10n_be_get_unemployment_without_complement_codes(self):
        """Temporary unemployment work entry types the employer pays no complement (EUC, EUB) for:

        - the collective closures (annual holidays, compulsory leave, compensatory rest): no lack of work for economic
          reasons (law of 3 July 1978, art. 51);
        - the temporary unemployment refused by the ONEM (020.49) and the public holidays during the temporary
          unemployment (006.11): the employer pays them as salary, no unemployment allowance is due.
        """
        return ('157.00', '157.05', '157.10', '020.49', '006.11')

    @api.model
    def _l10n_be_get_force_majeure_unemployment_codes(self):
        """Temporary unemployment work entry types for force majeure: no additional supplement of the temporary
        unemployment (EUB, from 2024) is due for them, nor are they counted in its 26 days.
        """
        return ('156.50', '156.55')

    def _l10n_be_get_unemployment_supplement_allowances(self):
        """Allowances of the ONEM covering the temporary unemployment of the payslip giving right to the additional
        supplement (EUB): the collective closures included, not the days paid as salary and the force majeure. The ONEM
        converts the hours into days of the 6 days week (hours * 6 / weekly hours, rounded to the half day), half
        allowances for the voluntary part time workers (hours * 12 / full time weekly hours, rounded to the unit).

        :return: the number of allowances and whether they are half allowances
        """
        self.ensure_one()
        without_complement_codes = self._l10n_be_get_unemployment_without_bonus_codes() \
            + self._l10n_be_get_force_majeure_unemployment_codes()
        lines = self.worked_days_line_ids.filtered(
            lambda l: l.work_entry_type_id.l10n_be_economic_unemployment and l.work_entry_type_id.code not in without_complement_codes)
        days = sum(lines.mapped('number_of_days'))
        hours = sum(lines.mapped('number_of_hours'))
        version = self.version_id
        hours_per_week = version.full_time_required_hours
        hours_per_week_reference = version._get_reference_calendar().hours_per_week
        if version._get_reference_calendar().is_fulltime or version.l10n_be_part_time_status == 'with_unemployment_rights_no_agr':
            # rounded to the half day: below .25 down, from .75 up
            return float_round(hours * 6 / (hours_per_week or 1) * 2, precision_digits=0) / 2, False
        if version.l10n_be_part_time_status == 'with_unemployment_rights_agr':
            return float_round(hours * 6 / (hours_per_week_reference or 1) * 2, precision_digits=0) / 2, False
        if version.l10n_be_part_time_status == 'voluntary':
            return round(hours * 12 / (hours_per_week_reference or 1)), True
        return days, False

    @api.model
    def _l10n_be_get_unemployment_without_bonus_codes(self):
        """Temporary unemployment work entry types the employer pays no supplement of the ONEM allowances (EUB) for: the
        days paid as salary (refused by the ONEM, 020.49, public holidays, 006.11). Unlike the economic unemployment
        complement (EUC), the supplement is also due for the collective closures (157.xx): the counter of the days of
        temporary unemployment of the ONEM includes them (all the schemes of temporary unemployment).
        """
        return ('020.49', '006.11')

    def _l10n_be_get_economic_unemployment_compensation(self, year_payslips, work_entries):
        """Compute the economic unemployment compensation for the employee/worker.

        Joint Committee Rules:
            CP200:
                No predefined amount; it's set manually. (handeled by a property_input EUC_CP200)
            CP302:
                - Seniority < 6 months: 2€ per day.
                - Seniority >= 6 months:
                    - Total temporary unemployment days <= 110: max(2€, 0.5187 * daily unemployment hours).
                    - Total temporary unemployment days > 110: 2€ per day.
            Default (Other Joint Committees):
                2€ per day.
        Neither is due on the days of :meth:`_l10n_be_get_unemployment_without_complement_codes`, nor on the days of
        temporary unemployment for force majeure or strike: the complement is due for the temporary unemployment for
        economic reasons, bad weather or technical reasons.
        """
        self.ensure_one()

        payslip_input = self._get_input_line_amount('EUC_CP200')
        employee = self.employee_id
        worked_days = self.worked_days_line_ids
        company_seniority = relativedelta(self.date_from, employee._get_first_contract_date(date_limit=self.date_to))
        company_seniority = company_seniority.years * 12 + company_seniority.months
        joint_committee_code = self.l10n_be_joint_committee_id.egov3_code or "200"
        daily_compensation = self._rule_parameter("economic_unemployment_daily_compensation")
        special_codes = ["152.00", "151.00"]
        without_complement_codes = self._l10n_be_get_unemployment_without_complement_codes() \
            + self._l10n_be_get_force_majeure_unemployment_codes() + ('141.00',)
        days = 0
        days_special = 0

        for line in worked_days.filtered(lambda l: l.work_entry_type_id.l10n_be_economic_unemployment and l.work_entry_type_id.code not in without_complement_codes):
            if line.work_entry_type_id.code in special_codes:
                days_special += line.number_of_days
            else:
                days += line.number_of_days

        result_qty = days + days_special
        result = daily_compensation
        if joint_committee_code == "302" and company_seniority >= 6:
            previous_unemployment_days = 0
            previous_payslips_of_year = year_payslips.filtered_domain([
                ('date_to', '<=', self.date_from),
                ('state', 'in', ['paid', 'validated']),
            ])

            for previous_worked_days in previous_payslips_of_year.worked_days_line_ids.filtered(lambda l: l.work_entry_type_id.l10n_be_economic_unemployment and l.work_entry_type_id.code not in without_complement_codes):
                previous_unemployment_days += previous_worked_days.number_of_days

            if previous_unemployment_days <= 110:
                hourly_compensation = self._rule_parameter("cp302_temp_unemployment_bonus")
                result = 0
                result_qty = 1
                cap_remaining_days = 110 - previous_unemployment_days

                unemployment_entries = [
                    we for we in work_entries
                    if we["work_entry_type_id"].l10n_be_economic_unemployment
                    and we["work_entry_type_id"].code not in without_complement_codes
                ]

                entries_by_date = defaultdict(list)
                for entry in unemployment_entries:
                    entries_by_date[entry["date"]].append(entry)

                # The complement is due per day of unemployment, whatever its length: a partial day
                # (a fraction of a worked day) is a day, so the days beyond the 110 are counted per date too.
                for daily_entries in entries_by_date.values():
                    beyond_cap = cap_remaining_days <= 0
                    cap_remaining_days -= 1

                    if any(we["work_entry_type_id"].code in special_codes for we in daily_entries):
                        continue

                    if beyond_cap:
                        result += daily_compensation
                        continue

                    # an amount per day: each day is paid to the cent
                    daily_hours = sum(we["duration"] for we in daily_entries)
                    result += max(daily_compensation, float_round(daily_hours * hourly_compensation, precision_digits=2))

                result += days_special * daily_compensation
        elif joint_committee_code == "200":
            result = payslip_input

        return (result_qty, result)

    def _get_termination_fees_contribution_basis(self, base_amount):
        # The contribution is only due on the part of the indemnity based on the seniority since 2014: the Part II of
        # the notice, in weeks and days, the Part I being in months (a month is 13 / 3 weeks)
        self.ensure_one()
        weeks_after_2014 = self._get_input_line_amount('ND_WEEK') + self._get_input_line_amount('ND_DAY') / 7
        weeks_before_2014 = self._get_input_line_amount('ND_MONTH') * 13 / 3
        if not weeks_before_2014 + weeks_after_2014:
            return base_amount
        return base_amount * weeks_after_2014 / (weeks_before_2014 + weeks_after_2014)

    def _get_termination_fees_minimum_yearly_salary(self):
        return self._rule_parameter('l10n_be_termination_contribution_type')[0][0]

    def _get_termination_fees_contribution_type(self, yearly_salary):
        self.ensure_one()
        contribution_type_brackets = self._rule_parameter('l10n_be_termination_contribution_type')
        for yearly_salary_threshold, contribution_type in reversed(contribution_type_brackets):
            if yearly_salary >= yearly_salary_threshold:
                return contribution_type
        return '1'

    def _get_pension_fund_contribution_type(self, quarter_payslips=None):
        self.ensure_one()
        employer_category = self._l10n_be_get_employer_category_dmfa_code()

        if not quarter_payslips:
            quarter_payslips = self.env['hr.payslip'].search([
                ('employee_id', '=', self.employee_id.id),
                ('date_from', '>=', date_utils.get_quarter(self.date_from)[0]),
                ('date_to', '<=', date_utils.get_quarter(self.date_from)[1]),
                ('state', 'in', ['validated', 'paid']),
                ('struct_id.code', 'in', ['BEMONTHLY', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1'])
            ])

        occupation_fraction = self._calculate_dmfa_occupation_fraction(quarter_payslips)
        contribution_type = 0
        if employer_category == '320':
            if occupation_fraction >= 80:
                contribution_type = 1
            elif occupation_fraction >= 50:
                contribution_type = 2
            elif occupation_fraction >= 33:
                contribution_type = 3
        return contribution_type, occupation_fraction

    def _l10n_be_get_student_worked_hours(self):
        """
        Hours worked by a student on the payslips of a quarter, declared in the DmfA (zone 01158 StudentHoursNbr)
        and deducted from the yearly quota of the student hours: only the hours actually worked (the attendances,
        the overtime, a worked public holiday), not the paid absences (a public holiday not worked, the guaranteed
        salary, ...). Only whole hours are declared: the total of the quarter is rounded up (100h30 counts 101h).
        Source: DmfA glossary, zone 01158
        """
        hours = sum(
            line.number_of_hours
            for line in self.worked_days_line_ids
            if line.is_paid and line.work_entry_type_id.count_as == 'working_time' and line.number_of_hours > 0
        )
        return int(float_round(round(hours, 2), precision_digits=0, rounding_method='UP'))

    def _get_onss_global_rates(self):
        self.ensure_one()
        contribution_type = '0'
        if self.version_id.is_worker():
            contribution_type = '1'

        # Source: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/students.html
        if self.version_id.is_student():
            worker_code = '840' if self.version_id.is_worker() else '841'
            rates = self._get_onss_rates(worker_code)
        elif self.version_id.l10n_be_dimona_category == 'flx' and self.version_id.l10n_be_refused_flexijob:
            worker_code = '015' if self.version_id.is_worker() else '495'
            rates = self._get_onss_rates(worker_code, contribution_type=contribution_type)
        else:
            rates = self._get_onss_rates(contribution_type=contribution_type)
        return rates

    def _l10n_be_has_mrt_without_valid_worked_days(self):
        # Not used anymore. Drop me in master branch.
        mrts = self.employee_id.resource_calendar_id.l10n_be_reorganisation_measure_ids
        credit_work_entry_types = self.env['hr.work.entry.type'].search([
            '|',
                ("l10n_be_is_time_credit", "=", True),
                ("code", "=", "122.04")
        ])
        worked_days_codes = self.worked_days_line_ids.mapped("code")
        measure_refs = ['l10n_be_reorganisation_measure_009_3', 'l10n_be_reorganisation_measure_009_4', 'l10n_be_reorganisation_measure_005_5']
        if any(self.env.ref(f'l10n_be_hr_payroll.{measure_ref}') in mrts for measure_ref in measure_refs):
            return all(leave.code not in worked_days_codes for leave in credit_work_entry_types)

    @api.model
    def _l10n_be_search_with_missing_credit_time(self):
        measure_xml_ids = [
            'l10n_be_reorganisation_measure_009_3',
            'l10n_be_reorganisation_measure_009_4',
            'l10n_be_reorganisation_measure_005_5',
        ]
        measure_ids = [self.env.ref(f'l10n_be_hr_payroll.{xml_id}').id for xml_id in measure_xml_ids]
        payslips = self.search([
            ('company_id', 'in', self.env.companies.filtered(lambda c: c.country_id.code == 'BE').ids),
            ('employee_id.resource_calendar_id.l10n_be_reorganisation_measure_ids', 'in', measure_ids)
        ])
        credit_work_entry_types = self.env['hr.work.entry.type'].search([
            '|',
                ("l10n_be_is_time_credit", "=", True),
                ("code", "=", "122.04")
        ])
        payslip_ids = []
        for payslip in payslips:
            worked_days_codes = payslip.worked_days_line_ids.mapped("code")
            if all(leave.code not in worked_days_codes for leave in credit_work_entry_types):
                payslip_ids.append(payslip.id)
        return self.browse(payslip_ids)

    def action_l10n_be_edit_time_off(self):
        self.ensure_one()
        return {
            'name': self.env._('Time Off Dashboard'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.leave',
            'view_mode': 'calendar',
            'views': [[self.env.ref('hr_holidays.hr_leave_employee_view_dashboard_month').id, 'calendar']],
            'domain': [('employee_id', 'in', self.employee_id.ids)],
            'context': {
                'default_employee_id': self.employee_id.id,
                'initial_date': self.date_from,
                'employee_id': [self.employee_id.id]
            },
        }

    def _get_category_options_data(self, work_entries=None):
        """
        Compute category option hours from work entry vals, grouping by category and day, then capping daily hours for
        specific categories (Sunday/holiday premium, temporary unemployment) based on their max amount and hourly rate parameters.

        :return: dict mapping category code to total (capped) hours for the payslip period.
        """
        if self.struct_id.country_id.code != 'BE':
            return super()._get_category_options_data(work_entries=work_entries)

        category_options = defaultdict(float)
        if not work_entries:
            return category_options

        category_options_params_by_code = {
            'PREMIUM_PAY_SUN': [self._rule_parameter('cp_200_premium_pay_sunday_max'), self._rule_parameter('cp_200_premium_pay_sunday_hourly_rate')],
            'PREMIUM_PAY_HOLIDAY': [self._rule_parameter('cp_200_premium_pay_holiday_max'), self._rule_parameter('cp_200_premium_pay_holiday_hourly_rate')],
            'TEMP_UNEMP': [self._rule_parameter('cp_200_temporary_unemployment_max'), self._rule_parameter('cp_200_temporary_unemployment_hourly_rate')],
        }

        # {category_code: {days: hours}}
        # A category option implies its ancestors: hours carrying a child option (e.g. a custom
        # premium pay) are also credited to each parent category code, once per work entry.
        hours_per_day_per_category_option = defaultdict(lambda: defaultdict(float))
        for work_entry_vals in work_entries:
            for code in work_entry_vals['category_options_ids']._get_codes_with_ancestors():
                hours_per_day_per_category_option[code][work_entry_vals['date']] += work_entry_vals['duration']

        for code, dates in hours_per_day_per_category_option.items():
            if code not in category_options_params_by_code:
                category_options[code] = sum(dates.values())
                continue
            max_amount_per_day, hourly_rate = category_options_params_by_code[code]
            max_hours_per_day = max_amount_per_day / hourly_rate if hourly_rate else 0
            for _date, hours in dates.items():
                category_options[code] += min(hours, max_hours_per_day)

        return category_options

    def _get_flxwage_amounts(self):
        """Split the flexi gross into the eGov FLXWAGE remuneration (0001001000) and
        bonus (0002001000) buckets.
        Lines are bucketed by their DmfA remuneration code (``1`` = remuneration,
        ``2`` = prime/bonus), the same field DMFA reporting uses. ``SALARY`` (code 1)
        is the ONSS gross and already contains the code-2 lines and the flexi-pécule;
        on a dedicated bonus slip there is no ``SALARY`` line, so ``remuneration_base``
        falls back to 0. eGov declares the flexi holiday pay (``FLEXI_PECULE``) with the
        pay it was computed on, so the single pécule line is split pro rata between the
        two bases.
        """
        self.ensure_one()
        lines = self.line_ids
        # the commissions (code 1 in the DmfA, in SALARY) go with the bonus of the FLXWAGE
        salary = sum(lines.filtered(
            lambda l: l.salary_rule_id.l10n_be_remuneration_code == '1' and l.code != 'COMMISSION').mapped('total'))
        bonus_base = sum(lines.filtered(
            lambda l: l.salary_rule_id.l10n_be_remuneration_code == '2' or l.code == 'COMMISSION').mapped('total'))
        pecule = sum(lines.filtered(lambda l: l.salary_rule_id.code == 'FLEXI_PECULE').mapped('total'))
        remuneration_base = max(salary - bonus_base - pecule, 0.0)
        base = remuneration_base + bonus_base
        if not base:
            return 0.0, 0.0
        remuneration = remuneration_base + pecule * remuneration_base / base
        bonus = bonus_base + pecule * bonus_base / base
        return remuneration, bonus

    def _create_flxwage_declarations(self):
        payslips = self or self.search(self.env.context.get('active_domain', []))
        flexi_payslips = payslips.filtered(lambda p:
            p.l10n_be_needs_flxwage_declaration and p.state in ('validated', 'paid') and not p.l10n_be_flexi_declaration_id)
        return self.env['l10n.be.flexi.at.work'].create([{'payslip_id': payslip.id} for payslip in flexi_payslips])

    def action_create_flxwage_declaration(self):
        payslips = self or self.search(self.env.context.get('active_domain', []))
        flexi_payslips = payslips.filtered(lambda p: p.l10n_be_needs_flxwage_declaration and p.state in ('validated', 'paid'))
        flexi_payslips_to_create = flexi_payslips.filtered(lambda p: not p.l10n_be_flexi_declaration_id)
        if not flexi_payslips_to_create and flexi_payslips:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': self.env._("All selected payslips already have a Flexi@Work declaration."),
                },
            }

        flexis = self.env['l10n.be.flexi.at.work'].create([{'payslip_id': payslip.id} for payslip in flexi_payslips_to_create])
        if not flexis:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': self.env._("No Flexi@Work declarations were created."),
                },
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': self.env._("%(count)s Flexi@Work declaration(s) created successfully.", count=len(flexis)),
            },
        }

    def action_create_and_show_flxwage_declaration(self):
        action = self.action_create_flxwage_declaration()
        if 'params' in action and not 'next' in action['params']:
            flexis = self.l10n_be_flexi_declaration_id
            if len(flexis) == 1:
                action['params']['next'] = {
                    'type': 'ir.actions.act_window',
                    'res_model': 'l10n.be.flexi.at.work',
                    'res_id': flexis.id,
                    'view_mode': 'form',
                    'views': [[False, 'form']],
                }
            elif flexis:
                action['params']['next'] = {
                    'type': 'ir.actions.act_window',
                    'res_model': 'l10n.be.flexi.at.work',
                    'view_mode': 'list,form',
                    'domain': [('payslip_id', 'in', self.ids)],
                }
        return action

    def action_create_flxwage_declaration_and_reload(self):
        action = self.action_create_flxwage_declaration()
        if 'params' in action and action['params']['type'] == 'success' and not 'next' in action['params']:
            action['params']['next'] = {'type': 'ir.actions.client', 'tag': 'reload'}
        return action

    def action_show_flxwage_declaration(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'l10n.be.flexi.at.work',
            'res_id': self.l10n_be_flexi_declaration_id.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
        }

    def action_postpone_paid_time_off(self, paid_time_off_to_postpone_n1=0, paid_time_off_to_postpone_n2=0):
        self.ensure_one()

        existing_amounts = {
            code: sum(self.input_line_ids.filtered(lambda line: line.code == code).mapped('amount'))
            for code in ('PPTO1', 'PPTO2')
        }

        if paid_time_off_to_postpone_n1 > 0:
            self._set_input_value('PPTO1', existing_amounts['PPTO1'] + paid_time_off_to_postpone_n1)

        if paid_time_off_to_postpone_n2 > 0:
            self._set_input_value('PPTO2', existing_amounts['PPTO2'] + paid_time_off_to_postpone_n2)

    def _get_net_to_recover_amount(self, categories, year_payslips):
        self.ensure_one()

        current_net = categories['REMUNERATION_BASE']

        if current_net < 0:
            return abs(current_net)

        past_payslips = year_payslips.filtered_domain([
            ('date_to', '<', self.date_to),
            ('state', 'in', ['paid', 'validated']),
        ])

        line_values = past_payslips._get_line_values(['NET_TO_RECOVER'], compute_sum=True)
        accumulated_debt = line_values['NET_TO_RECOVER']['sum']['total']
        # The correction of a paid payslip pays its net delta: a negative delta is owed by the employee
        accumulated_debt += sum(past_payslips.filtered(
            lambda p: p.is_correction_payslip and p.has_negative_net_to_report
        ).mapped('negative_net_to_report'))

        if current_net > 0 and accumulated_debt > 0:
            return -min(current_net, accumulated_debt)

        return 0.0

    def _get_cp200_sectorial_bonus_compensation(self):
        self.ensure_one()
        benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_sectorial_bonus_comp', raise_if_not_found=False)
        if not benefit or not benefit.active:
            return 0.0
        return self.version_id.l10n_be_sectorial_bonus_compensatory_amount

    def _get_starterjob_deduction_rate(self):
        self.ensure_one()
        version = self.version_id
        if version.l10n_be_is_starterjob \
                and version.l10n_be_joint_committee_id.egov3_code != '999' \
                and not self.env.context.get('without_starterjob'):
            last_day_of_the_month = self.date_to + relativedelta(day=31)
            age = self.employee_id._get_age(last_day_of_the_month)
            if age >= 18 and age <= 20:
                return self._rule_parameter('starterjob_gross_reduction').get(age)
        return 0

    def _l10n_be_get_reached_departures(self, documents_generated):
        """
        Departures whose departure date is reached by one of these regular payslips, and whose
        termination documents are already generated or not.
        """
        return self.filtered(lambda p: p.struct_id.code == 'BEMONTHLY'
            and p.employee_id.departure_id.departure_date
            and p.date_to >= p.employee_id.departure_id.departure_date
            and p.employee_id.departure_id.l10n_be_termination_documents_generated == documents_generated,
        ).employee_id.departure_id

    def _l10n_be_generate_termination_documents(self, payslip_run=None):
        for departure in self._l10n_be_get_reached_departures(documents_generated=False):
            generated_payslips = self.browse()
            if departure.l10n_be_notice_respect != 'with' and departure.l10n_be_reason_code not in RESIGNATION_REASON_CODES:
                generated_payslips += departure._generate_termination_payslip()
            generated_payslips += departure._generate_termination_holidays()
            if departure.l10n_be_thirteen_month_eligible:
                generated_payslips += departure._generate_termination_thirteen_month()
            if payslip_run:
                generated_payslips.payslip_run_id = payslip_run.id
            departure.employee_id.action_report_employment_certificate()
            departure.l10n_be_termination_documents_generated = True

    def _l10n_be_refresh_termination_holidays(self):
        """
        Termination documents generated from a pay run are created while the departure-month
        payslip is still a draft, so the N holiday attest misses that month in its gross reference.
        Recompute it once that payslip is validated.
        """
        departures = self._l10n_be_get_reached_departures(documents_generated=True)
        if not departures:
            return
        holiday_payslips = self.search([
            ("employee_id", "in", departures.employee_id.ids),
            ("struct_id", "=", self.env.ref("l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays").id),
            ("date_from", "in", [departure.departure_date + relativedelta(day=1) for departure in departures]),
            ("state", "=", "draft"),
        ]).filtered(lambda p: p.date_from == p.employee_id.departure_id.departure_date + relativedelta(day=1))
        if not holiday_payslips:
            return
        holiday_payslips.employee_id.departure_id._compute_net()
        for holiday_payslip in holiday_payslips:
            holiday_payslip._set_input_values({
                "GROSS_REF": holiday_payslip.employee_id.departure_id.l10n_be_gross_reference_remuneration_n,
            })
        holiday_payslips.compute_sheet()

    def _get_payroll_translation(self, text, **kwargs):
        # Please order alphabetically to easily spot duplicates
        if text == "No double holiday pay, so no simple holiday pay":
            return self.env._("No double holiday pay, so no simple holiday pay")
        if text == "Result = Gross Reference Remuneration (%(result)s €) * 7.67%%":
            return self.env._("Result = Gross Reference Remuneration (%(result)s €) * 7.67%%", **kwargs)
        return super()._get_payroll_translation(text, **kwargs)

    def _get_l10n_be_mobility_amounts(self):
        monthly_slips = self.filtered(
            lambda slip:
            slip.struct_id.code == 'BEMONTHLY'
            and slip.state == 'draft'
            and slip.employee_id
            and slip.date_from
            and slip.country_code == 'BE'
            and (slip.version_id.l10n_be_mobility_budget or slip.l10n_be_is_december or slip._is_last_monthly_payslip())
        )
        if not monthly_slips:
            return {}

        # 1. Compute the prorated yearly mobility budget
        employees_by_year = defaultdict(lambda: self.env['hr.employee'])
        for slip in monthly_slips:
            employees_by_year[slip.date_from.year] |= slip.employee_id

        prorated_budgets = {}
        for year, employees in employees_by_year.items():
            amounts = employees._get_l10n_be_mobility_budget_amount_prorated(
                reference_date=date(year, 12, 31),
                year=year,
            )
            for employee_id, amount in amounts.items():
                prorated_budgets[employee_id, year] = amount

        # Keep December/last payslips without MB only if the employee was entitled to a mobility budget earlier in the year.
        monthly_slips = monthly_slips.filtered(lambda s:
            s.version_id.l10n_be_mobility_budget or
            ((s.l10n_be_is_december or s._is_last_monthly_payslip()) and prorated_budgets.get((s.employee_id.id, s.date_from.year), 0.0) > 0)
        )

        # 2. Compute already paid mobility amounts.
        # For the yearly amount, include all validated and done payslips of the same year.
        # For the monthly amount, only consider the current month (normally, this only includes expenses from l10n_be_hr_payroll_expense).
        employees_by_year = defaultdict(lambda: self.env['hr.employee'])

        for slip in monthly_slips:
            employees_by_year[slip.date_from.year] |= slip.employee_id

        paid_amounts_by_year = {}
        for year, employees in employees_by_year.items():
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            yearly_paid, monthly_paid = employees._get_l10n_be_paid_mobility_amounts(date_start=year_start, date_end=year_end)
            paid_amounts_by_year[year] = (yearly_paid, monthly_paid)

        # 3.  Build mobility input values for each payslip.
        values_by_slip = {}
        for slip in monthly_slips:
            employee_id = slip.employee_id.id
            year = slip.date_from.year
            month = slip.date_from.month
            prorated_yearly_budget = prorated_budgets.get((employee_id, year), 0.0)

            yearly_paid, monthly_paid = paid_amounts_by_year[year]
            already_paid_year = yearly_paid.get((employee_id, year), 0.0)
            already_paid_month = monthly_paid.get((employee_id, year, month), 0.0)
            values_by_slip[slip] = {
                'MOBILITY_PAID_MONTH': already_paid_month,
                'MOBILITY_PAID_YEAR': already_paid_year,
                'MOBILITY_REMAINING': round(max(0.0, prorated_yearly_budget - already_paid_year), 2),
            }

        return values_by_slip

    def _get_l10n_be_mobility_budget_termination_fee_amount(self):
        # Deprecated: the mobility budget is already part of the reference salary of the
        # termination fees (MOBILITY_BUDGET_ANNUAL in TERMINATION_BASE). Kept so that the
        # MOBILITY_PAYMENT_TERM rule of a database not yet updated doesn't crash nor count
        # the mobility budget twice. To remove in master.
        self.ensure_one()
        return 0, 0

    def _is_last_monthly_payslip(self):
        self.ensure_one()
        departure_date = self.employee_id.departure_date
        return departure_date and self.date_from <= departure_date <= self.date_to

    def _l10n_be_show_mobility_budget_rules(self):
        self.ensure_one()
        return self.version_id.l10n_be_mobility_budget or self.l10n_be_is_december or self._is_last_monthly_payslip()

    def _get_special_wage_moderation_contribution(self):
        """
        Formule: (Partie_A + Partie_B) / 2
            - Partie A = (Salaire de ref. indexé - [4000 * (1 + chiffre d'index)]) * fraction de prestation * chiffre d'index limité à 2%
            - Partie B = Partie A * taux ONSS global (employeur + modération salariale)
        The reference wage is a full-time one: a part-time wage is converted with the work time rate (Q/S).
        Source: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/pennyindex_wagemoderationcontribution.html
        """
        self.ensure_one()
        # the contribution is due from the first indexation of the period of the measure, that starts on 1 June 2026:
        # an earlier indexation (as the one of January 2026) isn't moderated
        indexation_date = date(self.date_from.year, 1, 1)
        legal_index = self.env['hr.rule.parameter.value'].sudo().search([
            ('rule_parameter_id.code', '=', 'l10n_be_legal_index'),
            ('date_from', '<=', indexation_date),
        ], order='date_from desc', limit=1)
        if not legal_index or legal_index.date_from < date(2026, 6, 1):
            return 0
        version = self.version_id
        rates = self._get_onss_global_rates()
        onss_pat_global_rate = rates['employer_rate'] + rates['salary_moderation_rate']
        reference_salary = version._l10n_be_get_monthly_wage(int(self.date_from.year))
        rule_parameter = self.env["hr.rule.parameter"]._get_parameter_from_code(
                    "l10n_be_legal_index", date=indexation_date, raise_if_not_found=False,
                ).get(version.l10n_be_egov3_code, False)
        if not rule_parameter:
            return 0
        rate, cap = rule_parameter
        # only the part of the full-time wage above the capped reference wage is concerned, nothing is due at or below
        # it; the fraction of performance (against a full-time worker) prorates that part, so nothing is due without
        # any performance either. With the work time rate Q/S: (wage x S/Q - cap) x (attendance x Q/S)
        work_time_rate = version.work_time_rate or 1.0
        part_A = max(0.0, reference_salary - cap * (1 + rate) * work_time_rate) * self._get_attendance_rate() * min(rate, 0.02)
        part_B = part_A * onss_pat_global_rate / 100
        return (part_A + part_B) / 2

    def _get_attendance_rate(self):
        self.ensure_one()
        # DMFA prestation codes 1, 3, 4, 5, 20, 38
        PRESTATION_DMFA_CODES = {'1', '3', '4', '5', '20', '38'}
        wd_lines = self.worked_days_line_ids.filtered(lambda wd: wd.code != '000.00')
        prestation_lines = wd_lines.filtered(lambda wd: wd.work_entry_type_id.dmfa_code in PRESTATION_DMFA_CODES)
        is_part_time = self.version_id.work_time_rate < 1.0
        if is_part_time:
            # attendance_rate = H / U  (hours with prestation codes / total theoretical monthly hours)
            H = sum(prestation_lines.mapped('number_of_hours'))
            U = sum(wd_lines.mapped('number_of_hours'))
            attendance_rate = H / U if U else 0
        else:
            # attendance_rate = J / D  (days with prestation codes / total theoretical monthly days)
            J = sum(prestation_lines.mapped('number_of_days'))
            D = sum(wd_lines.mapped('number_of_days'))
            attendance_rate = J / D if D else 0
        return attendance_rate

    def _l10n_be_get_employer_category_dmfa_code(self):
        """The employer category of the payslip: the one of its payroll configuration, or its dedicated code for
        the occasional workers (e.g. 317 for a Horeca occasional worker under a 017 configuration), see
        hr.version._l10n_be_get_employer_category_dmfa_code()"""
        self.ensure_one()
        return self.version_id._l10n_be_get_employer_category_dmfa_code(self.payroll_config_id.l10n_be_employer_category_id)

    def _l10n_be_is_horeca_occasional(self):
        """A Horeca occasional worker (an extra): DIMONA category EXT, declared under the employer category 317
        (whether on a dedicated payroll configuration, or derived from a 017 one, see
        l10n.be.employer.category._get_occasional_worker_dmfa_code())."""
        self.ensure_one()
        return (self.version_id.l10n_be_dimona_category == 'ext'
                and self._l10n_be_get_employer_category_dmfa_code() == '317')

    def _l10n_be_get_horeca_occasional_days(self, work_entries):
        """The flat-rate regime of Horeca occasional workers: their contributions are computed on a flat wage per
        started hour, 6 hours a day at most, and a flat withholding tax applies, for the first days of work of the
        calendar year (the worker's contingent).

        :param work_entries: the work entries of the payslip (the rules' localdict)
        :return: ({date: flat hours} of the payslip's days under the regime, {date: worked hours} of all its days)
        Source: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/socialsecuritycontributions/calculationbase/occasionals_horeca.html
        """
        self.ensure_one()

        def worked_hours(entries):
            hours = defaultdict(float)
            for vals in entries:
                if vals['work_entry_type_id'].count_as == 'working_time' and vals.get('duration'):
                    hours[vals['date']] += vals['duration']
            return hours

        worked = worked_hours(work_entries)
        # the days of work as an occasional worker earlier in the year use the contingent up
        year_start = self.date_from.replace(month=1, day=1)
        used = 0
        if self.date_from > year_start:
            before = self.date_from - timedelta(days=1)
            versions = self.employee_id._get_versions_with_contract_overlap_with_period(year_start, before).filtered(
                lambda v: v.l10n_be_dimona_category == 'ext')
            used = len(worked_hours(versions.generate_work_entries(year_start, before)))
        left = max(0, self._rule_parameter('horeca_occasional_days') - used)
        flat = {day: min(math.ceil(round(worked[day], 4)), 6) for day in sorted(worked)[:left]}
        return flat, worked

    def _l10n_be_get_horeca_occasional_flat_days(self):
        """The days of the payslip under the flat-rate regime of Horeca occasional workers (within the worker's
        yearly contingent), from the work entries of its occasional versions."""
        self.ensure_one()
        versions = (self.worked_days_line_ids.version_id | self.version_id).filtered(
            lambda v: v.l10n_be_dimona_category == 'ext')
        if not versions:
            return set()
        work_entries = [
            vals for vals in versions.generate_work_entries(self.date_from, self.date_to)
            if self.date_from <= vals['date'] <= self.date_to]
        return set(self._l10n_be_get_horeca_occasional_days(work_entries)[0])

    def _l10n_be_get_horeca_occasional_share(self, work_entries):
        """The share of the pay of the payslip earned on the days of the flat-rate regime of Horeca occasional
        workers (their worked hours over all the worked hours)."""
        self.ensure_one()
        flat, worked = self._l10n_be_get_horeca_occasional_days(work_entries)
        total = sum(worked.values())
        return sum(worked[day] for day in flat) / total if total else 0.0

    def action_open_employee_calendar(self):
        """Encoding worked time needs the wider list of time types, absences only is not enough.
        The regular time off gantt keeps the employee facing one."""
        action = super().action_open_employee_calendar()
        if self.struct_id.country_id.code != 'BE':
            return action
        gantt = self.env.ref('hr_payroll.hr_leave_gantt_view_payroll_encoding')
        action['views'] = [
            (gantt.id, view_type) if view_type == 'gantt' else (view_id, view_type)
            for view_id, view_type in action['views']
        ]
        return action

    def _l10n_be_get_meal_vouchers_yearly_estimated_quantity(self):
        self.ensure_one()
        days_per_week = self.version_id.resource_calendar_id.days_per_week
        pto_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_legal_leave')
        extra_legal_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_extra_legal')
        allocations = self.env['hr.leave.allocation'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('work_entry_type_id', 'in', (pto_work_entry_type + extra_legal_work_entry_type).ids),
            ('date_from', '>=', self.date_from.replace(month=1, day=1)),
            '|',
            ('date_to', '<=', self.date_from.replace(month=12, day=31)),
            ('date_to', '=', False),
        ])
        number_of_days_off = sum(allocations.mapped('number_of_days'))
        return (days_per_week * 52) - 10 - number_of_days_off

    @api.model
    def _l10n_be_find_withholding_tax_rates(self, x, rates):
        low_bound, high_bound = rates[0][0], rates[-1][1]
        x = min(max(low_bound, x), high_bound)
        rounded_x = float_round(x, precision_digits=2)
        for low, high, rate in rates:
            if low <= rounded_x <= high:
                return rate / 100.0

    def _check_create_wech006(self):
        """ The part-time work of the workers with a declaration of the start of their part-time occupation
        (WECH003) is declared monthly to compute their income guarantee allowance """
        wech003_risk = self.env.ref('l10n_be_hr_payroll.drs_risk_wech003_001', raise_if_not_found=False)
        wech006_risk = self.env.ref('l10n_be_hr_payroll.drs_risk_wech006_001', raise_if_not_found=False)
        payslips_to_declare = self.filtered(
            lambda payslip: payslip.country_code == 'BE'
            and payslip.struct_id.code == 'BEMONTHLY'
            and payslip.version_id.resource_calendar_id.hours_per_week < payslip.version_id._get_reference_calendar().hours_per_week)
        if not payslips_to_declare or not wech003_risk or not wech006_risk:
            return
        employees_with_wech003 = self.env['l10n.be.drs'].search([
            ('risk_id', '=', wech003_risk.id),
            ('employee_id', 'in', payslips_to_declare.employee_id.ids),
        ]).employee_id
        self.env['l10n.be.drs']._create_missing_declarations([{
            'employee_id': payslip.employee_id.id,
            'sector': 'unemployment',
            'risk_id': wech006_risk.id,
            'month': payslip.date_from.month,
            'year': payslip.date_from.year,
        } for payslip in payslips_to_declare if payslip.employee_id in employees_with_wech003])

    def _check_create_wech007(self):
        """ The work in a sheltered workshop is declared monthly, once declared for the employee (the ONEM still
        compensates the workers of the sheltered workshops employed before July 2004) """
        risk = self.env.ref('l10n_be_hr_payroll.drs_risk_wech007_001', raise_if_not_found=False)
        payslips_to_declare = self.filtered(lambda payslip: payslip.country_code == 'BE' and payslip.struct_id.code == 'BEMONTHLY')
        if not payslips_to_declare or not risk:
            return
        declared_employees = self.env['l10n.be.drs'].search([
            ('risk_id', '=', risk.id),
            ('employee_id', 'in', payslips_to_declare.employee_id.ids),
        ]).employee_id
        self.env['l10n.be.drs']._create_missing_declarations([{
            'employee_id': payslip.employee_id.id,
            'sector': 'unemployment',
            'risk_id': risk.id,
            'month': payslip.date_from.month,
            'year': payslip.date_from.year,
        } for payslip in payslips_to_declare if payslip.employee_id in declared_employees])

    def _check_create_wech008(self):
        """ The Walloon Impulsion plans are declared monthly to compute the work allowance """
        risk_010 = self.env.ref('l10n_be_hr_payroll.drs_risk_wech008_010', raise_if_not_found=False)
        risk_011 = self.env.ref('l10n_be_hr_payroll.drs_risk_wech008_011', raise_if_not_found=False)
        payslips_to_declare = self.filtered(
            lambda payslip: payslip.country_code == 'BE'
            and payslip.struct_id.code == 'BEMONTHLY'
            and payslip.version_id.l10n_be_impulsion_plan
            and payslip.version_id._get_l10n_be_employee_residence_region() == 'wa')
        if not payslips_to_declare or not risk_010 or not risk_011:
            return
        self.env['l10n.be.drs']._create_missing_declarations([{
            'employee_id': payslip.employee_id.id,
            'sector': 'unemployment',
            'risk_id': risk_010.id if payslip.version_id.l10n_be_impulsion_plan == '12mo' else risk_011.id,
            'month': payslip.date_from.month,
            'year': payslip.date_from.year,
        } for payslip in payslips_to_declare])

    def _check_create_zima002(self):
        """ The adapted work during an incapacity (medical part-time) or as a maternity protection measure is
        declared monthly to the health insurance """
        risk_001 = self.env.ref('l10n_be_hr_payroll.drs_risk_zima002_001', raise_if_not_found=False)
        risk_002 = self.env.ref('l10n_be_hr_payroll.drs_risk_zima002_002', raise_if_not_found=False)
        if not risk_001 or not risk_002:
            return
        vals_list = []
        for payslip in self.filtered(lambda payslip: payslip.country_code == 'BE' and payslip.struct_id.code == 'BEMONTHLY'):
            worked_days = payslip.worked_days_line_ids.filtered(lambda line: line.number_of_hours > 0)
            risks = worked_days.work_entry_type_id.l10n_be_drs_risk_ids
            if risk_001 in risks:
                risk = risk_001
            # A partial removal from work, with worked hours
            elif risk_002 in risks and any(line.work_entry_type_id.count_as == 'working_time' for line in worked_days):
                risk = risk_002
            else:
                continue
            vals_list.append({
                'employee_id': payslip.employee_id.id,
                'sector': 'compensation',
                'risk_id': risk.id,
                'month': payslip.date_from.month,
                'year': payslip.date_from.year,
            })
        self.env['l10n.be.drs']._create_missing_declarations(vals_list)

    def _check_create_zima003(self):
        """ The breastfeeding pauses are declared monthly to the health insurance """
        risk = self.env.ref('l10n_be_hr_payroll.drs_risk_zima003_001', raise_if_not_found=False)
        if not risk:
            return
        self.env['l10n.be.drs']._create_missing_declarations([{
            'employee_id': payslip.employee_id.id,
            'sector': 'compensation',
            'risk_id': risk.id,
            'month': payslip.date_from.month,
            'year': payslip.date_from.year,
        } for payslip in self.filtered(lambda payslip: payslip.country_code == 'BE' and payslip.struct_id.code == 'BEMONTHLY' and any(
            risk in line.work_entry_type_id.l10n_be_drs_risk_ids for line in payslip.worked_days_line_ids if line.number_of_hours > 0))])
