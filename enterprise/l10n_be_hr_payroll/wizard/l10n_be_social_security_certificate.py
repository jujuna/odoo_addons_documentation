# Part of Odoo. See LICENSE file for full copyright and licensing details.

import collections
import re
from io import BytesIO

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes
from odoo.tools.misc import format_date, format_time


class L10nBeSocialSecurityCertificate(models.TransientModel):
    _name = 'l10n.be.social.security.certificate'
    _description = 'Belgium: Social Security Certificate'

    @api.model
    def default_get(self, fields):
        if self.env.company.country_id.code != "BE":
            raise UserError(self.env._('This feature seems to be as exclusive as Belgian chocolates. You must be logged in to a Belgian company to use it.'))
        return super().default_get(fields)

    date_from = fields.Date(default=lambda s: fields.Date.context_today(s) + relativedelta(day=1, month=1, years=-1))
    date_to = fields.Date(default=lambda s: fields.Date.context_today(s) + relativedelta(day=31, month=12, years=-1))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], default='draft')
    state_xlsx = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], default='draft')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    social_security_sheet = fields.Binary('Social Security Certificate', readonly=True, attachment=False)
    social_security_filename = fields.Char()
    social_security_xlsx = fields.Binary('Social Security Certificate Spreadsheet', readonly=True, attachment=False)
    social_security_filename_xlsx = fields.Char()
    aggregation_level = fields.Selection([
        ('company', 'Whole Company'),
        ('department', 'By Department'),
        ('employee', 'By Employee')], default='company', required=True)

    def _get_joint_committees(self):
        """ The joint committees of the employees paid in the period """
        self.ensure_one()
        payslips = self.env['hr.payslip'].search([
            ('state', 'in', ['validated', 'paid']),
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', self.date_from + relativedelta(day=1)),
            ('date_to', '<=', self.date_to + relativedelta(day=31)),
        ])
        return sorted(set(filter(None, payslips.version_id.l10n_be_joint_committee_id.mapped('egov3_code'))) - {'999'})

    def _get_report_data(self):
        def _get_total(payslips, all_values, codes):
            return sum(all_values[code][p.id]['total'] for p in payslips for code in codes)

        self.ensure_one()

        date_from = self.date_from + relativedelta(day=1)
        date_to = self.date_to + relativedelta(day=31)

        monthly_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        termination_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        holiday_pay_n = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')
        holiday_pay_n1 = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays')
        double_holiday_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday')
        thirteen_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month')
        warrant_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant')
        salary_advance_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_salary_advance')
        cct90_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90')
        profit_sharing_pay = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_profit_sharing_bonus')

        all_payslips = self.env['hr.payslip'].search([
            ('state', 'in', ['validated', 'paid']),
            # the company and its branches
            ('company_id', 'child_of', self.company_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
            '|', ('version_id.l10n_be_joint_committee_id', '=', False), ('version_id.l10n_be_joint_committee_id.egov3_code', '!=', '999')])

        if self.aggregation_level == 'company':
            grouped_payslips = [(self.company_id.name, all_payslips)]
        elif self.aggregation_level == 'department':
            # The department of the employee at the time of the payslip, the employees without department included
            grouped_payslips = [
                (department.complete_name or self.env._('Without Department'), payslips)
                for department, payslips in all_payslips.grouped(lambda p: p.version_id.department_id).items()
            ]
        else:
            grouped_payslips = [
                (employee.legal_name, payslips)
                for employee, payslips in all_payslips.grouped('employee_id').items()
            ]

        # The benefits in kind, subject to the ONSS or not, from the categories of their salary rules
        bik_rules = self.env['hr.salary.rule'].with_context(active_test=False).search([
            ('category_ids', 'in', self.env.ref('l10n_be_hr_payroll.BIK').ids)])
        onss_base = self.env.ref('l10n_be_hr_payroll.ONSS_BASE')
        onss_bik_rules = bik_rules.filtered(lambda r: onss_base in r.category_ids)
        atn_codes = set(onss_bik_rules.mapped('code')) | {'ATN_HOUSING_ONSS'}
        atn_without_onss_codes = set((bik_rules - onss_bik_rules).mapped('code')) | {'ATN_HOUSING_FISCAL'}

        code_list = [
            *atn_codes, *atn_without_onss_codes,
            'BASIC', 'BONUS_BASIC', 'VOLOTNOONSS', 'IP.EXEMPT', 'WARRANT_ATN', 'TERM_BASIC', 'DH_BASIC', 'ATN.CAR',
            'PAY_SIMPLE', 'PAY_DOUBLE', 'PAY_DOUBLE_COMPLEMENTARY', 'PUB.TRANS', 'TRAIN', 'SALARY', 'BONUS_SALARY',
            'DH_SALARY', 'WARRANT_SALARY', 'ONSSTOTAL', 'ONSS_HOLIDAY_TERM_SIMPLE', 'ONSS_HOLIDAY_TERM_DOUBLE',
            'ONSS_BONUS', 'ONSS_SOLIDARITY_BONUS', 'BEPROFITSHARING_BASIC', 'REP.FEES', 'REP.FEES.VOLATILE', 'CAR.PRIV',
            'CYCLE', 'CANTEEN', 'M.ONSS', 'ATTACH_SALARY', 'ATN_DED', 'WARRANT_ATN_DED', 'MEAL_V_EMP', 'IMPULSION25',
            'IMPULSION12', 'ASSIG_SALARY', 'SALARYADVREC', 'NET', 'PPTOTAL', 'P.P.DED', 'ONSSEMPLOYER',
            'ONSSEMPLOYER_809', 'ONSSEMPLOYER_810', 'CO2FEE', 'ONSS_STRUCTURAL', 'MEAL_VOUCHER_EMPLOYER']
        all_values = all_payslips._get_line_values(code_list)

        # The withholding tax exemptions of the 274 declarations of the period, computed once per month for the
        # company and split by employee. The capping of the exemption of the bachelors (274.34), for the company, is
        # split according to their exemption.
        exemptions_32 = collections.defaultdict(float)
        exemptions_33 = collections.defaultdict(float)
        exemptions_34 = collections.defaultdict(float)
        denied_exemptions_34 = collections.defaultdict(float)
        month_start = date_from
        while month_start <= date_to:
            wizard_274 = self.env['l10n_be.274_xx'].new({
                'company_id': self.company_id,
                'date_start': month_start,
                'date_end': month_start + relativedelta(day=31),
            })
            for line in wizard_274.line_274_32_ids:
                exemptions_32[line.employee_id] += line.amount
            for line in wizard_274.line_274_33_ids:
                exemptions_33[line.employee_id] += line.amount
            # deducted_amount_34 is the raw (uncapped) bachelor total; capped_amount_34 is what is actually granted.
            denied_exemption = wizard_274.deducted_amount_34 - wizard_274.capped_amount_34
            for line in wizard_274.line_274_34_ids:
                exemptions_34[line.employee_id] += line.raw_amount
                if denied_exemption and wizard_274.deducted_amount_34:
                    denied_exemptions_34[line.employee_id] += denied_exemption * line.raw_amount / wizard_274.deducted_amount_34
            month_start += relativedelta(months=1)

        def _get_values(aggregate_payslips):
            monthly_slips = aggregate_payslips.filtered(lambda p: p.struct_id == monthly_pay)
            termination_slips = aggregate_payslips.filtered(lambda p: p.struct_id in termination_pay)
            holiday_slips = aggregate_payslips.filtered(lambda p: p.struct_id in [holiday_pay_n, holiday_pay_n1])
            double_slips = aggregate_payslips.filtered(lambda p: p.struct_id == double_holiday_pay)
            thirteen_slips = aggregate_payslips.filtered(lambda p: p.struct_id == thirteen_pay)
            # The students are paid with the monthly salary structure
            student_slips = monthly_slips.filtered(lambda p: p.version_id.is_student())
            monthly_slips -= student_slips
            salary_advance_slips = aggregate_payslips.filtered(lambda p: p.struct_id == salary_advance_pay)
            warrant_slips = aggregate_payslips.filtered(lambda p: p.struct_id == warrant_pay)
            cct90_slips = aggregate_payslips.filtered(lambda p: p.struct_id == cct90_pay)
            profit_sharing_slips = aggregate_payslips.filtered(lambda p: p.struct_id == profit_sharing_pay)
            unclassified_slips = (
                aggregate_payslips - monthly_slips - termination_slips - holiday_slips - double_slips - thirteen_slips
                - student_slips - warrant_slips - salary_advance_slips - cct90_slips - profit_sharing_slips)
            monthly_slips += unclassified_slips

            # The ONSS base of the monthly payslips, and their bonuses (sectorial bonus...), without the benefits in kind
            atn = _get_total(monthly_slips, all_values, atn_codes)
            gross_before_onss = _get_total(monthly_slips, all_values, ['SALARY', 'BONUS_SALARY']) - atn
            termination_fees = _get_total(termination_slips, all_values, ['TERM_BASIC'])
            student = _get_total(student_slips, all_values, ['BASIC'])
            thirteen_month = _get_total(thirteen_slips, all_values, ['BONUS_BASIC'])
            # The double holiday pay, paid with its own structure or with the December salary: the part subject to
            # the ONSS and the rest
            double_pay = _get_total(double_slips | monthly_slips, all_values, ['DH_SALARY'])
            warrant_with_onss = _get_total(warrant_slips, all_values, ['WARRANT_SALARY'])
            # The non-recurring bonuses (CCT 90) and the profit sharing bonuses, subject to the solidarity contribution
            cct90_bonus = _get_total(cct90_slips, all_values, ['BONUS_BASIC'])
            profit_sharing = _get_total(profit_sharing_slips, all_values, ['BEPROFITSHARING_BASIC'])
            total_gross_before_onss = (
                gross_before_onss + atn + termination_fees + student + thirteen_month + double_pay + warrant_with_onss
                + cct90_bonus + profit_sharing)
            atn_without_onss = _get_total(monthly_slips, all_values, atn_without_onss_codes)
            warrant_without_onss = _get_total(warrant_slips, all_values, ['WARRANT_ATN']) - warrant_with_onss
            early_holiday_pay = _get_total(holiday_slips, all_values, ['PAY_SIMPLE'])
            holiday_pay_supplement = _get_total(holiday_slips, all_values, ['PAY_DOUBLE'])
            other_exempted_amount = (
                _get_total(holiday_slips, all_values, ['PAY_DOUBLE_COMPLEMENTARY'])
                # The overtime without ONSS and the author rights exempted from the ONSS, out of the ONSS base
                + _get_total(monthly_slips, all_values, ['VOLOTNOONSS'])
                - _get_total(monthly_slips, all_values, ['IP.EXEMPT']))
            double_gross = _get_total(double_slips | monthly_slips, all_values, ['DH_BASIC']) - double_pay
            subtotal_gross = total_gross_before_onss + atn_without_onss + warrant_without_onss + early_holiday_pay + holiday_pay_supplement + other_exempted_amount + double_gross
            # The deductions of the workers are negative, as on the payslips
            onss_cotisation = -_get_total(monthly_slips, all_values, ['ONSSTOTAL'])
            onss_cotisation_termination_fees = -_get_total(termination_slips, all_values, ['ONSSTOTAL'])
            anticipated_holiday_pay_retenue = _get_total(holiday_slips, all_values, ['ONSS_HOLIDAY_TERM_SIMPLE'])
            holiday_pay_supplement_retenue = _get_total(holiday_slips, all_values, ['ONSS_HOLIDAY_TERM_DOUBLE'])
            onss_thirteen_month = -_get_total(thirteen_slips, all_values, ['ONSSTOTAL'])
            onss_double = -_get_total(double_slips, all_values, ['ONSSTOTAL'])
            onss_student = -_get_total(student_slips, all_values, ['ONSSTOTAL'])
            onss_warrant = -_get_total(warrant_slips, all_values, ['ONSSTOTAL'])
            # No ONSS total on the CCT 90 structure
            onss_cct90 = _get_total(cct90_slips, all_values, ['ONSS_BONUS', 'ONSS_SOLIDARITY_BONUS'])
            onss_profit_sharing = -_get_total(profit_sharing_slips, all_values, ['ONSSTOTAL'])
            representation_fees = _get_total(monthly_slips, all_values, ['REP.FEES', 'REP.FEES.VOLATILE'])
            private_car = _get_total(monthly_slips | student_slips, all_values, ['CAR.PRIV'])
            public_transport = _get_total(monthly_slips | student_slips, all_values, ['PUB.TRANS', 'TRAIN'])
            cycle_allowance = _get_total(monthly_slips | student_slips, all_values, ['CYCLE'])
            canteen_costs = _get_total(monthly_slips, all_values, ['CANTEEN'])
            atn_car = _get_total(monthly_slips, all_values, ['ATN.CAR'])
            # All the withholding taxes, of all the structures (double holiday, 13th month, termination...)
            withholding_taxes = -_get_total(aggregate_payslips, all_values, ['PPTOTAL'])
            misc_onss = _get_total(aggregate_payslips, all_values, ['M.ONSS'])
            salary_attachment = _get_total(aggregate_payslips, all_values, ['ATTACH_SALARY'])
            atn_deduction = _get_total(monthly_slips, all_values, ['ATN_DED'])
            warrant_deduction = _get_total(warrant_slips, all_values, ['WARRANT_ATN_DED'])
            meal_voucher_employee = _get_total(monthly_slips | student_slips, all_values, ['MEAL_V_EMP'])
            net_third_party = _get_total(monthly_slips, all_values, ['IMPULSION25', 'IMPULSION12'])
            salary_assignment = _get_total(aggregate_payslips, all_values, ['ASSIG_SALARY'])
            salary_advance = _get_total(salary_advance_slips, all_values, ['NET'])
            salary_advance_recovery = _get_total(monthly_slips, all_values, ['SALARYADVREC'])
            net = _get_total(aggregate_payslips, all_values, ['NET']) - salary_advance + (-salary_advance_recovery)
            total_net = net + salary_advance - (-salary_advance_recovery)

            # Cotisation patronnale de base =
            # Global Rate (without employee part) + FFE + Special FFE + CPAE + Modération Salariale + Chomage temporaire
            # global_rate = 0.3810 + 0.0023 + (0.0169 if worker_count >= 10 else 0) + 0.0010 - 0.1307
            emp_onss = _get_total(monthly_slips + thirteen_slips + holiday_slips + warrant_slips + cct90_slips, all_values, ['ONSSEMPLOYER'])
            emp_termination_onss = _get_total(termination_slips, all_values, ['ONSSEMPLOYER'])
            # Details of the employer contributions, already in them
            closure_fund = _get_total(aggregate_payslips, all_values, ['ONSSEMPLOYER_809', 'ONSSEMPLOYER_810'])
            charges_redistribution = 0

            # Already in the employer contributions
            co2_fees = _get_total(aggregate_payslips, all_values, ['CO2FEE'])
            structural_reductions = _get_total(aggregate_payslips, all_values, ['ONSS_STRUCTURAL'])
            # As paid: the current amount of the version is not the one of the past payslips, and a refund cancels it
            meal_voucher_employer = _get_total(monthly_slips | student_slips, all_values, ['MEAL_VOUCHER_EMPLOYER'])
            withholding_taxes_deduction = _get_total(monthly_slips, all_values, ['P.P.DED'])
            # The withholding tax reduction (P.P.DED) is the one of the worker
            total_employer_cost = emp_onss + emp_termination_onss + charges_redistribution + meal_voucher_employer
            holiday_pay_provision = 0

            aggregate_employees = aggregate_payslips.employee_id
            withholding_taxes_exemption_32 = sum(exemptions_32[employee] for employee in aggregate_employees)
            withholding_taxes_exemption_33 = sum(exemptions_33[employee] for employee in aggregate_employees)
            withholding_taxes_exemption_34 = sum(exemptions_34[employee] for employee in aggregate_employees)
            withholding_taxes_capping = -sum(denied_exemptions_34[employee] for employee in aggregate_employees)

            aggregate_data = {
                'gross_before_onss': gross_before_onss,
                'atn': atn,
                'termination_fees': termination_fees,
                'student': student,
                'thirteen_month': thirteen_month,
                'double_pay': double_pay,
                'warrant_with_onss': warrant_with_onss,
                'cct90_bonus': cct90_bonus,
                'profit_sharing': profit_sharing,
                'total_gross_before_onss': total_gross_before_onss,
                'atn_without_onss': atn_without_onss,
                'warrant_without_onss': warrant_without_onss,
                'early_holiday_pay': early_holiday_pay,
                'holiday_pay_supplement': holiday_pay_supplement,
                'other_exempted_amount': other_exempted_amount,
                'double_gross': double_gross,
                'subtotal_gross': subtotal_gross,
                'onss_cotisation': onss_cotisation,
                'onss_cotisation_termination_fees': onss_cotisation_termination_fees,
                'anticipated_holiday_pay_retenue': anticipated_holiday_pay_retenue,
                'holiday_pay_supplement_retenue': holiday_pay_supplement_retenue,
                'onss_student': onss_student,
                'onss_thirteen_month': onss_thirteen_month,
                'onss_double': onss_double,
                'onss_warrant': onss_warrant,
                'onss_cct90': onss_cct90,
                'onss_profit_sharing': onss_profit_sharing,
                'taxable_adaptation': 0,
                'taxable_325': 0,
                'gift_in_kind': 0,
                'representation_fees': representation_fees,
                'private_car': private_car,
                'public_transport': public_transport,
                'cycle_allowance': cycle_allowance,
                'atn_car': atn_car,
                'canteen_costs': canteen_costs,
                'withholding_taxes': withholding_taxes,
                'misc_onss': misc_onss,
                'salary_attachment': salary_attachment,
                'atn_deduction': atn_deduction,
                'warrant_deduction': warrant_deduction,
                'meal_voucher_employee': meal_voucher_employee,
                'net_third_party': net_third_party,
                'salary_assignment': salary_assignment,
                'salary_advance': salary_advance,
                'salary_advance_recovery': salary_advance_recovery,
                'net': net,
                'total_net': total_net,
                'emp_onss': emp_onss,
                'emp_termination_onss': emp_termination_onss,
                'closure_fund': closure_fund,
                'charges_redistribution': charges_redistribution,
                'co2_fees': co2_fees,
                'structural_reductions': structural_reductions,
                'meal_voucher_employer': meal_voucher_employer,
                'withholding_taxes_deduction': withholding_taxes_deduction,
                'total_employer_cost': total_employer_cost,
                'holiday_pay_provision': holiday_pay_provision,
                'withholding_taxes_exemption_32': withholding_taxes_exemption_32,
                'withholding_taxes_exemption_33': withholding_taxes_exemption_33,
                'withholding_taxes_exemption_34': withholding_taxes_exemption_34,
                'withholding_taxes_capping': withholding_taxes_capping,
            }
            return aggregate_data

        # The values of all the payslips, of the employees and of the workers (blue collars)
        report_data = []
        for aggregate_name, aggregate_payslips in grouped_payslips:
            worker_payslips = aggregate_payslips.filtered(lambda p: p.version_id.is_worker())
            values = [_get_values(payslips) for payslips in (aggregate_payslips, aggregate_payslips - worker_payslips, worker_payslips)]
            report_data.append((aggregate_name, {key: tuple(value[key] for value in values) for key in values[0]}))

        return report_data

    def _get_report_lines(self):
        """ The lines of the certificate, for the PDF and the XLSX files: [(title, [(key, label)])] """
        return [
            (self.env._('Workers'), [
                ('gross_before_onss', self.env._('Gross salary before ONSS')),
                ('atn', self.env._('Benefits in kind submitted to ONSS')),
                ('termination_fees', self.env._('Termination fees')),
                ('thirteen_month', self.env._('Thirteen Month')),
                ('double_pay', self.env._('Double Holiday')),
                ('student', self.env._('Students')),
                ('warrant_with_onss', self.env._('Warrants subject to ONSS')),
                ('cct90_bonus', self.env._('Non-recurring bonuses (CCT 90)')),
                ('profit_sharing', self.env._('Profit Sharing Bonuses')),
                ('total_gross_before_onss', self.env._('Total Basic before ONSS')),
                ('atn_without_onss', self.env._('Benefits in kind without ONSS')),
                ('warrant_without_onss', self.env._('Warrants exempted from ONSS')),
                ('early_holiday_pay', self.env._('Early holiday pay')),
                ('holiday_pay_supplement', self.env._('Holiday pay supplement')),
                ('other_exempted_amount', self.env._('Other exempted amount from ONSS')),
                ('double_gross', self.env._('Double Holiday Gross')),
                ('subtotal_gross', self.env._('Sub-total Gross')),
                ('onss_cotisation', self.env._('ONSS Cotisation')),
                ('onss_cotisation_termination_fees', self.env._('ONSS Cotisation on termination fees')),
                ('anticipated_holiday_pay_retenue', self.env._('Anticipated Holiday Pay Retenue')),
                ('holiday_pay_supplement_retenue', self.env._('Holiday Pay Supplement Retenue')),
                ('onss_thirteen_month', self.env._('ONSS Thirteen Month')),
                ('onss_double', self.env._('ONSS Double Holiday')),
                ('onss_student', self.env._('ONSS Student')),
                ('onss_warrant', self.env._('ONSS Warrants')),
                ('onss_cct90', self.env._('ONSS Non-recurring bonuses (CCT 90)')),
                ('onss_profit_sharing', self.env._('ONSS Profit Sharing Bonuses')),
                ('taxable_adaptation', self.env._('Taxable Adaptation')),
                ('taxable_325', self.env._('Taxable Amounts (325)')),
                ('gift_in_kind', self.env._('Gifts in kind')),
                ('representation_fees', self.env._('Reimbursed Expenses (Representation Fees)')),
                ('private_car', self.env._('Private Car')),
                ('public_transport', self.env._('Public Transportation')),
                ('cycle_allowance', self.env._('Cycle Allowance')),
                ('atn_car', self.env._('Benefits in kind (Company Car)')),
                ('canteen_costs', self.env._('Canteen Costs')),
                ('withholding_taxes', self.env._('Withholding Taxes')),
                ('misc_onss', self.env._('Special Social Contribution')),
                ('salary_attachment', self.env._('Payslip Adjustments')),
                ('atn_deduction', self.env._('Benefit in kind deduction')),
                ('warrant_deduction', self.env._('Warrants deduction')),
                ('meal_voucher_employee', self.env._('Meal Vouchers (Employee Part)')),
                ('net_third_party', self.env._('Net salary paid by third party')),
                ('salary_assignment', self.env._('Salary Assignment')),
                ('net', self.env._('Net Salary')),
                ('salary_advance', self.env._('Salary Advance')),
                ('salary_advance_recovery', self.env._('Salary Advance Recovery')),
                ('total_net', self.env._('Total Net (Advance included)')),
            ]),
            (self.env._('Employer'), [
                ('emp_onss', self.env._('ONSS cotisation')),
                ('emp_termination_onss', self.env._('ONSS termination fees cotisation')),
                ('closure_fund', self.env._('Business closure fund cotisation')),
                ('charges_redistribution', self.env._('ONSS Cotisation: Charges redistribution')),
                ('co2_fees', self.env._('Solidarity Cotisation: Company Cars')),
                ('structural_reductions', self.env._('Structural reductions')),
                ('meal_voucher_employer', self.env._('Meal Vouchers (Employer Part)')),
                ('withholding_taxes_deduction', self.env._('Retenue de versement: précompte professionnel (salaires)')),
                ('total_employer_cost', self.env._('Total Employer Cost')),
                ('holiday_pay_provision', self.env._('Holiday Pay Provision')),
                ('withholding_taxes_exemption_32', self.env._('Withholding Taxes Exemption (Scientific Research) - Doctors / Civil Engineers')),
                ('withholding_taxes_exemption_33', self.env._('Withholding Taxes Exemption (Scientific Research) - Masters')),
                ('withholding_taxes_exemption_34', self.env._('Withholding Taxes Exemption (Scientific Research) - Bachelors')),
                ('withholding_taxes_capping', self.env._('Withholding Taxes Capping (Bachelors)')),
            ]),
        ]

    def print_report(self):
        report_data = self._get_report_data()
        filename = self.env._(
            'SocialSecurityCertificate-%(date_from)s-%(date_to)s.pdf',
            date_from=format_date(self.env, self.date_from),
            date_to=format_date(self.env, self.date_to))
        certificate_pdf = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            self.env.ref('l10n_be_hr_payroll.action_report_social_security_certificate').id,
            res_ids=self.ids, data={'report_data': report_data})[0]

        self.social_security_filename = filename
        self.social_security_sheet = BinaryBytes(certificate_pdf)

        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Social Security Certificate'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
        }

    def export_report_xlsx(self):
        reports_data = self._get_report_data()
        output = BytesIO()
        import xlsxwriter  # noqa: PLC0415
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet_names = set()

        def _get_sheet_name(name):
            # Unique (case insensitive), at most 31 characters, without []:*?/\ (two employees may have the same name)
            name = re.sub(r'[\[\]:*?/\\]', '', name or '')[:31] or '-'
            unique_name, index = name, 1
            while unique_name.lower() in sheet_names:
                index += 1
                suffix = f' ({index})'
                unique_name = name[:31 - len(suffix)] + suffix
            sheet_names.add(unique_name.lower())
            return unique_name

        company_worksheet = workbook.add_worksheet(_get_sheet_name(self.env._('Identification Of The Company And Infos')))

        # styling
        style_header = workbook.add_format({'bold': True, 'pattern': 1, 'bg_color': '#E0E0E0', 'align': 'center', 'bottom': 1})
        style_vertical_header = workbook.add_format({'bold': True, 'pattern': 1, 'bg_color': '#E0E0E0', 'align': 'center', 'bottom': 1, 'right': 1})
        style_normal = workbook.add_format({'align': 'center'})
        column_width = 25
        double_column_width = 50
        triple_column_width = 75

        # company worksheet
        current_line = 0
        company_header = self.env._('Identification of the company')
        company_worksheet.set_column(0, 0, double_column_width)
        company_worksheet.set_column(1, 1, double_column_width)
        company_worksheet.write(0, 0, company_header, style_header)
        company_worksheet.write(0, 1, '', style_vertical_header)
        company_data = {
            'name': {
                'header': self.env._('Name'),
                'value': self.company_id.name,
            },
            'vat': {
                'header': self.env._('VAT Number'),
                'value': self.company_id.vat,
            },
            'onss': {
                'header': self.env._('ONSS Number'),
                'value': self.company_id._get_payroll_config(self.date_from).onss_registration_number,
            },
            'established': {
                'header': self.env._('Established on'),
                'value': self.env._(
                    "%(established_date)s at %(established_time)s",
                    established_date=format_date(self.env, self.create_date, date_format='long'),
                    established_time=format_time(self.env, self.create_date),
                )
            },
            'joint_committees': {
                'header': self.env._('Number of joint committees'),
                'value': ', '.join(self._get_joint_committees()),
            },
            'period': {
                'header': self.env._('Period'),
                'value': self.env._(
                    "%(date_from)s to %(date_to)s",
                    date_from=format_date(self.env, self.date_from, date_format="long"),
                    date_to=format_date(self.env, self.date_to, date_format="long"),
                ),
            },
            'currency': {
                'header': self.env._('Currency'),
                'value': self.company_id.currency_id.name,
            },
        }

        for data in company_data.values():
            current_line += 1
            company_worksheet.write(current_line, 0, data['header'], style_vertical_header)
            company_worksheet.write(current_line, 1, data['value'], style_normal)

        current_line += 2
        aggregation_header = self.env._('Aggregation Level:')
        if self.aggregation_level == 'company':
            aggregation_data = self.env._('Whole Company')
            company_worksheet.write(current_line, 0, aggregation_header, style_vertical_header)
            current_line += 1
            company_worksheet.write(current_line, 0, aggregation_data, style_vertical_header)
        elif self.aggregation_level == 'department':
            aggregation_data = self.env._('departments:')
            company_worksheet.write(current_line, 0, aggregation_header, style_vertical_header)
            current_line += 1
            company_worksheet.write(current_line, 0, aggregation_data, style_vertical_header)
            for department, _dummy in reports_data:
                current_line += 1
                company_worksheet.write(current_line, 0, department, style_normal)
        else:
            aggregation_data = self.env._('Employees:')
            company_worksheet.write(current_line, 0, aggregation_header, style_vertical_header)
            current_line += 1
            company_worksheet.write(current_line, 0, aggregation_data, style_vertical_header)
            for employee, _dummy in reports_data:
                current_line += 1
                company_worksheet.write(current_line, 0, employee, style_normal)

        for aggregation_data, report_data in reports_data:
            current_worksheet = workbook.add_worksheet(_get_sheet_name(aggregation_data))
            current_worksheet.set_column(0, 0, triple_column_width)
            current_worksheet.set_column(1, 3, column_width)
            current_worksheet.write(0, 0, aggregation_data, style_header)

            current_line = 2
            for title, lines in self._get_report_lines():
                current_line += 1
                for column, header in enumerate([title, self.env._('Total'), self.env._('Employee'), self.env._('Worker')]):
                    current_worksheet.write(current_line, column, header, style_vertical_header)
                for key, label in lines:
                    current_line += 1
                    current_worksheet.write(current_line, 0, label, style_vertical_header)
                    for column, value in enumerate(report_data[key], start=1):
                        current_worksheet.write(current_line, column, round(value, 2), style_normal)
                current_line += 1

        workbook.close()

        base64_xlsx = BinaryBytes(output.getvalue())
        filename = self.env._(
            'SocialSecurityCertificate-%(date_from)s-%(date_to)s.xlsx',
            date_from=format_date(self.env, self.date_from),
            date_to=format_date(self.env, self.date_to))
        self.social_security_filename_xlsx = filename
        self.social_security_xlsx = base64_xlsx
        self.state_xlsx = 'done'

        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Social Security Certificate'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_validate(self):
        self.ensure_one()
        if self.social_security_sheet:
            self._post_process_generated_file(self.social_security_sheet, self.social_security_filename)
        if self.social_security_xlsx:
            self._post_process_generated_file(self.social_security_xlsx, self.social_security_filename_xlsx)
        return {'type': 'ir.actions.act_window_close'}

    # To be overwritten in documents_l10n_be_hr_payroll to create a document.document
    def _post_process_generated_file(self, data, filename):
        return
