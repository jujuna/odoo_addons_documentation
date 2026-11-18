# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from odoo import Command
from odoo.addons.hr_payroll.tests.common import TestPayrollBase
from odoo.addons.l10n_be_hr_payroll.models.hr_dmfa import DMFAWorkerContribution
from odoo.addons.l10n_be_hr_payroll.models.utils import format_amount
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install', 'onss_contributions')
class TestPayrollOnssContributions(TestPayrollBase, TestBelgiumCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.be_employee_emp_type = cls.env.ref('hr.contract_type_employee')
        cls.be_worker_emp_type = cls.env.ref('l10n_be_hr_payroll.l10n_be_contract_type_be_worker')
        cls.be_apprent_emp_type = cls.env.ref('hr.contract_type_apprenticeship')

        cls.be_employee = cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495')
        cls.be_worker = cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015')
        cls.be_acs = cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00484')
        cls.be_employee_no_salary_moderation = cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00439')
        cls.be_worker_no_salary_moderation = cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00027')

        cls.category_employee = cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010')
        cls.category_horeca = cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00017')
        cls.category_food_industry = cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00048')

        worker_codes = (
            cls.be_employee |
            cls.be_worker |
            cls.be_acs |
            cls.be_employee_no_salary_moderation |
            cls.be_worker_no_salary_moderation
        )

        categories = (
            cls.category_employee |
            cls.category_horeca |
            cls.category_food_industry
        )

        categories.write({
            'allowed_worker_code_ids': [Command.set(worker_codes.ids)]
        })

        cls.cp_200 = cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200')
        cls.cp_302 = cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')

        cls.struct = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        cls.salary_rule = cls.env.ref('l10n_be_hr_payroll.cp200_employees_salary_gross_salary')

        cls.economic_unemployment = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment')

        cls.construction_sector = cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_124')

        cls.company = cls.env['res.company'].create([{
            'name': 'BE Company',
            'country_id': cls.env.ref('base.be').id,
        }])
        cls.payroll_config = cls.company.current_payroll_config_id
        cls.payroll_config.write({
            'l10n_be_employer_category_id': cls.category_employee.id,
        })

        cls.env.user.company_id = cls.company
        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.struct,
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            version_fields={
                'name': 'Employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'wage': 1000,
                'l10n_be_flexi_monthly_wage': 1000,
                'employee_type_id': cls.be_employee_emp_type.id,
                'l10n_be_worker_code_id': cls.be_employee.id,
                'l10n_be_joint_committee_id': cls.cp_200.id,
                'resource_calendar_id': cls.env.ref('l10n_be_hr_payroll.resource_calendar_std_38h').id,
            }
        )

        cls.quarter_payslips = cls.env['hr.payslip'].create([
            {
                'name': 'Payslip January',
                'date_from': '2026-01-01',
                'employee_id': cls.employee.id,
                'company_id': cls.company.id,
                'struct_id': cls.struct.id,
            },
            {
                'name': 'Payslip February',
                'date_from': '2026-02-01',
                'employee_id': cls.employee.id,
                'company_id': cls.company.id,
                'struct_id': cls.struct.id,
            },
            {
                'name': 'Payslip March',
                'date_from': '2026-03-01',
                'employee_id': cls.employee.id,
                'company_id': cls.company.id,
                'struct_id': cls.struct.id,
            },
        ])
        cls.payslip = cls.quarter_payslips[0]
        cls.extra_payslip = cls.env['hr.payslip'].create({
            'name': '2nd Payslip March',
            'date_from': '2026-03-01',
            'employee_id': cls.employee.id,
            'company_id': cls.company.id,
            'struct_id': cls.struct.id,
        })

    def get_total(self, payslip, rule_code):
        payslip.compute_sheet()
        return payslip._get_line_values([rule_code], compute_sum=True)[rule_code]['sum']['total']

    def check_total(self, payslip, rule_code, total):
        payslip.compute_sheet()
        self._validate_payslip(payslip, {rule_code: total}, True)

    def check_quarter_total(self, rule_code, totals, quarter_total):
        self.quarter_payslips.action_payslip_draft()
        q_total = 0.0
        for i in range(len(self.quarter_payslips)):
            if totals[i] is None:
                continue
            self.check_total(self.quarter_payslips[i], rule_code, totals[i])
            self.quarter_payslips[i].action_payslip_done()
            q_total += self.get_total(self.quarter_payslips[i], rule_code)
        self.assertAlmostEqual(q_total, quarter_total, 2)

    def check_condition(self, rule_code, expected):
        self.payslip.compute_sheet()
        self._validate_rule_computed(self.payslip, rule_code, expected)

    def check_condition_dimona_categories(self, rule_code, categories, expected):
        original_category = self.version.l10n_be_dimona_category
        self.version.contract_date_start = date(2026, 1, 1)
        self.version.contract_date_end = date(2026, 3, 31)
        for category in categories:
            self.version.l10n_be_dimona_category = category
            self.payslip.compute_sheet()
            self._validate_rule_computed(self.payslip, rule_code, expected)
        self.version.l10n_be_dimona_category = original_category

    def test_onss_employee_condition(self):
        """
        ONSS
        Social contribution
        """
        self.check_condition('ONSS', True)
        self.check_condition_dimona_categories('ONSS', ['dwd', 'o17', 's17', 't17', 'stg', 'tri', 'ivt'], False)

    def test_internship_withholding_tax_rate(self):
        """ The allowance of the transition internships (Dimona STG and TRI), without ONSS, bears the flat
        withholding tax rate of 11.11%, as the professional immersion contracts """
        self.version.contract_date_start = date(2026, 1, 1)
        self.version.contract_date_end = date(2026, 3, 31)
        for category in ('stg', 'tri', 'ivt'):
            self.version.l10n_be_dimona_category = category
            self.payslip.compute_sheet()
            values = self.payslip._get_line_values(['ONSS', 'P.P'])
            self.assertFalse(values['ONSS'][self.payslip.id]['total'], category)
            self.assertAlmostEqual(values['P.P'][self.payslip.id]['total'], -1000 * 11.11 / 100, 2, msg=category)

    def test_wijninckx_contribution_rate(self):
        """ The Wijninckx contribution (867) is 3% from 2018 to 2025, 12.5% from the contribution year 2026 """
        rule = self.env.ref('l10n_be_hr_payroll.l10n_be_employees_salary_onss_employer_867')
        for date_from, rate in [(date(2025, 12, 1), 3.0), (date(2026, 12, 1), 12.5)]:
            payslip = self.env['hr.payslip'].create({
                'name': f'Payslip {date_from}',
                'date_from': date_from,
                'employee_id': self.employee.id,
                'company_id': self.company.id,
                'struct_id': self.struct.id,
                'input_line_ids': [Command.create({'salary_rule_id': rule.id, 'amount': 10000})],
            })
            payslip.compute_sheet()
            self.assertAlmostEqual(payslip._get_line_values(['ONSSEMPLOYER_867'])['ONSSEMPLOYER_867'][payslip.id]['total'], 100 * rate, 2)

    def test_cct90_yearly_ceilings(self):
        """ The ceilings of the CCT 90 bonuses (ONSS: 4255 EUR, withholding tax: 3701 EUR in 2026) are per worker and
        per calendar year: a second bonus of the year only uses what the first one left """
        cct90_struct = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90')
        payslips = self.env['hr.payslip']
        for month in (3, 9):
            payslip = self.env['hr.payslip'].create({
                'name': f'CCT90 2026-{month}',
                'date_from': date(2026, month, 1),
                'date_to': date(2026, month, 1) + relativedelta(day=31),
                'employee_id': self.employee.id,
                'company_id': self.company.id,
                'struct_id': cct90_struct.id,
            })
            payslip._set_input_value('CCT90BONUSPLAN', 3000)
            payslip.compute_sheet()
            payslip.action_payslip_done()
            payslips |= payslip
        line_values = payslips._get_line_values(
            ['ONSS_SOLIDARITY_BONUS', 'ONSS_BONUS', 'PP_EXEMP', 'ONSSEMPLOYER_888'], vals_list=['amount', 'total'])
        first, second = payslips.ids
        # first bonus: within the ceilings
        self.assertAlmostEqual(line_values['ONSS_SOLIDARITY_BONUS'][first]['amount'], 3000, 2)
        self.assertFalse(line_values['ONSS_BONUS'][first]['amount'])
        self.assertAlmostEqual(line_values['ONSSEMPLOYER_888'][first]['amount'], 3000, 2)
        # second bonus: 4255 - 3000 = 1255 left below the ONSS ceiling, the rest is remuneration
        self.assertAlmostEqual(line_values['ONSS_SOLIDARITY_BONUS'][second]['amount'], 1255, 2)
        self.assertAlmostEqual(line_values['ONSS_BONUS'][second]['amount'], 1745, 2)
        self.assertAlmostEqual(line_values['ONSSEMPLOYER_888'][second]['amount'], 1255, 2)
        # the withholding tax exemption of the year is at most 3701
        first_exemption = -line_values['PP_EXEMP'][first]['total']
        self.assertLess(first_exemption, 3701)
        self.assertAlmostEqual(first_exemption - line_values['PP_EXEMP'][second]['total'], 3701, 2)

    def test_restructuring_cap_before_30_follows_s0(self):
        """ The monthly wage cap of the restructuring reduction for the workers under 30 years is a third of the low
        wage threshold S0 (category 1) of the structural reduction, at each of its indexations """
        get_parameter = self.env['hr.rule.parameter']._get_parameter_from_code
        for date_ref in (date(2024, 7, 1), date(2025, 4, 1), date(2026, 1, 1), date(2026, 7, 1)):
            self.assertAlmostEqual(
                get_parameter('onss_restructuring_before_30', date_ref),
                round(get_parameter('cp200_occupation_deduction_3000_s0', date_ref) / 3, 2),
                2, msg=str(date_ref))

    def test_onss_employee_computation(self):
        """
        ONSS
        Social contribution
        """
        # Employee
        self.check_quarter_total('ONSS', [-130.7] * 3, 3000 * -13.07 / 100)

        # Worker (-0.01 because regularization is on the onss employer basic)
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSS', [-141.16] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * -13.07 / 100 - 0.01)

        # Student Employee
        self.version.l10n_be_worker_code_id = self.be_employee
        self.version.l10n_be_dimona_category = 'stu'
        self.check_quarter_total('ONSS', [-27.1] * 3, 3000 * -2.71 / 100)

        # Student Worker (-0.01 because regularization is on the onss employer basic)
        self.version.l10n_be_worker_code_id = self.be_worker
        self.version.l10n_be_dimona_category = 'stu'
        self.check_quarter_total('ONSS', [-29.27] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * -2.71 / 100 - 0.01)

    def test_onss_basic_condition(self):
        """
        ONSSEMPLOYERBASIC
        Accounting: ONSS Basic (Employer)
        """
        self.check_condition('ONSSEMPLOYERBASIC', True)
        self.check_condition_dimona_categories('ONSSEMPLOYERBASIC', ['ivt', 'flx'], False)

    def test_onss_basic_computation(self):
        """
        ONSSEMPLOYERBASIC
        Accounting: ONSS Basic (Employer)
        """
        # Employee
        self.check_quarter_total('ONSSEMPLOYERBASIC', [250] * 3, 3000 * 25 / 100)

        # Worker (-0.01 because regularization is not done on the employee onss)
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYERBASIC', [270, 269.99, 270], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 25 / 100 - 0.01)

        # Student Employee
        self.version.l10n_be_worker_code_id = self.be_employee
        self.version.l10n_be_dimona_category = 'stu'
        self.check_quarter_total('ONSSEMPLOYERBASIC', [54.3] * 3, 3000 * 5.43 / 100)

        # Student Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.version.l10n_be_dimona_category = 'stu'
        self.check_quarter_total('ONSSEMPLOYERBASIC', [58.64, 58.64, 58.65], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 5.43 / 100)

    def _validate_onss_employer_basic_deductions(self, totals):
        self.quarter_payslips.action_payslip_draft()
        for i in range(len(self.quarter_payslips)):
            if totals[i] is None:
                self.quarter_payslips[i].compute_sheet()
                self.assertNotIn('ONSSEMPLOYERBASICDEDUC', self.quarter_payslips[i].line_ids.mapped('code'))
            else:
                self.check_total(self.quarter_payslips[i], 'ONSSEMPLOYERBASICDEDUC', totals[i])
            self.quarter_payslips[i].action_payslip_done()

    def _setup_onss_employer_basic_deduction(self):
        self.version.wage = 50000
        self.quarter_payslips |= self.extra_payslip

    def test_onss_employer_basic_deduction(self):
        self._setup_onss_employer_basic_deduction()
        # cap_amount: 86700 -> 86700/4 = 21675, wage=50000, ONSSBASICEMPLOYER=50000/4=12500 per month
        # 1st month, no deduction because 21675 > 12500
        # 2nd month, -3325 deduction because of 25000-21675
        # 3rd month, we already reached to cap amount, 12500 should be deducted directly, no more contribution should be paid
        # Same for 4th month.
        totals = [None, -3325, -12500, -12500]
        self._validate_onss_employer_basic_deductions(totals)

        self.version.wage = 30000
        totals = [None, None, -825, -7500]
        self._validate_onss_employer_basic_deductions(totals)

        self.version.wage = 50000
        # cap_amount: 85000 since 2025-07-01
        for slip in self.quarter_payslips:
            slip.date_from = '2025-07-01'
        totals = [None, -3750, -12500, -12500]
        self._validate_onss_employer_basic_deductions(totals)

        # cap_amount: 88434 since 2026-07-01
        for slip in self.quarter_payslips:
            slip.date_from = '2026-07-01'
        totals = [None, -2891.5, -12500, -12500]
        self._validate_onss_employer_basic_deductions(totals)

    def test_onss_employer_basic_deduction_before_capping(self):
        self._setup_onss_employer_basic_deduction()
        # First cap amount starts in 2025-07-01, before that there is no deduction for capping
        for i in range(len(self.quarter_payslips)):
            self.quarter_payslips[i].date_from = '2025-01-01'
        totals = [None, None, None, None]
        self._validate_onss_employer_basic_deductions(totals)

    def test_onss_employer_basic_deduction_category_exception(self):
        self._setup_onss_employer_basic_deduction()
        # No deduction for flx and stu categories
        self.version.contract_date_start = date(2026, 1, 1)
        self.version.contract_date_end = date(2026, 3, 31)
        self.version.l10n_be_dimona_category = 'flx'
        totals = [None, None, None, None]
        self._validate_onss_employer_basic_deductions(totals)

        self.version.l10n_be_dimona_category = 'stu'
        self.version.contract_date_end = False
        totals = [None, None, None, None]
        self._validate_onss_employer_basic_deductions(totals)

        self.version.l10n_be_dimona_category = 's17'
        # on the remuneration code 1, as for the other workers
        totals = [None, -3325, -12500, -12500]
        self._validate_onss_employer_basic_deductions(totals)

        for slip in self.quarter_payslips:
            slip.date_from = '2026-07-01'
        totals = [None, None, None, None]
        # There will be no deduction for s17 (sports) dimona category since 2026-07-01
        self._validate_onss_employer_basic_deductions(totals)

    def test_onss_253_condition(self):
        """
        ONSSEMPLOYER_253
        Accounting: ONSS Annual Vacations Contribution (Employer)
        """
        # This rule doesn't apply for employer category 10 and worker code 495
        self.assertFalse(self.payslip._should_apply_onss_contribution('253'))
        self.check_condition('ONSSEMPLOYER_253', False)

        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.assertTrue(self.payslip._should_apply_onss_contribution('253'))
        self.check_condition('ONSSEMPLOYER_253', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_253', ['stu', 'ivt', 'flx'], False)

    def test_onss_253_computation(self):
        """
        ONSSEMPLOYER_253
        Accounting: ONSS Annual Vacations Contribution (Employer)
        """
        # Worker
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.payslip.compute_sheet()
        self.check_quarter_total('ONSSEMPLOYER_253', [60.16, 60.15, 60.16], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 5.57 / 100)

    def test_onss_255_condition(self):
        """
        ONSSEMPLOYER_255
        Accounting: ONSS Work Accident Contribution (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('255'))
        self.check_condition('ONSSEMPLOYER_255', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_255', ['stu', 'ivt', 'flx'], False)

    def test_onss_255_computation(self):
        """
        ONSSEMPLOYER_255
        Accounting: ONSS Work Accident Contribution (Employer)
        """
        # Employee
        self.check_quarter_total('ONSSEMPLOYER_255', [0.2] * 3, 3000 * 0.02 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_255', [0.22, 0.21, 0.22], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.02 / 100)

    def test_onss_256_condition(self):
        """
        ONSSEMPLOYER_256
        Accounting: ONSS Asbestos Contribution (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('256'))
        self.check_condition('ONSSEMPLOYER_256', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_256', ['stu', 'ivt', 'flx'], False)

        # the quarters due come from the ONSS combinations of the quarter, not from the month
        self.payslip.write({'date_from': date(2026, 7, 1), 'date_to': date(2026, 7, 31)})
        self.check_condition('ONSSEMPLOYER_256', True)
        employer_class = self.payslip.payroll_config_id.l10n_be_employer_category_id.dmfa_code
        code = f'l10n_be_onss_combinations_{employer_class}_{self.version.l10n_be_worker_code_id.dmfa_code}'
        combinations = self.payslip._rule_parameter(code)
        self.env['hr.rule.parameter.value'].sudo().create({
            'rule_parameter_id': self.env['hr.rule.parameter'].sudo().search([('code', '=', code)]).id,
            'parameter_value': str({key: value for key, value in combinations.items() if key != '256'}),
            'date_from': date(2026, 7, 1),
        })
        self.check_condition('ONSSEMPLOYER_256', False)

    def _enable_onss_804(self):
        employer_class = self.payslip.payroll_config_id.l10n_be_employer_category_id.dmfa_code
        code = f'l10n_be_onss_combinations_{employer_class}_{self.version.l10n_be_worker_code_id.dmfa_code}'
        combinations = self.payslip._rule_parameter(code)
        # the ONSS lists the contribution from the second quarter of 2026
        self.env['hr.rule.parameter.value'].sudo().create({
            'rule_parameter_id': self.env['hr.rule.parameter'].sudo().search([('code', '=', code)]).id,
            'parameter_value': str({**combinations, '804': ['0']}),
            'date_from': date(2026, 4, 1),
        })
        # the first moderated indexation of the JC 200: 1 January 2027
        self.env['hr.rule.parameter.value'].sudo().create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_l10n_be_legal_index').id,
            'parameter_value': str({'200': (0.0185, 4000.0)}),
            'date_from': date(2027, 1, 1),
        })

    def test_onss_804_wage_moderation_on_the_index(self):
        """
        ONSSEMPLOYER_804
        Special wage moderation contribution on the index: from the first indexation from 1 June 2026, on the part of the indexed reference
        wage above the capped one (4,000 EUR), never negative, prorated by the fraction of performance.
        """
        self._enable_onss_804()
        # a full-time worker: the 38 hours week is the reference (the company's calendar has 40 hours)
        self.version.resource_calendar_id.reference_calendar_id = self.version.resource_calendar_id
        self.version.generate_work_entries(date(2026, 6, 1), date(2026, 6, 30))
        self.version.generate_work_entries(date(2027, 6, 1), date(2027, 6, 30))
        self.payslip.write({'date_from': date(2027, 6, 1), 'date_to': date(2027, 6, 30)})
        self.check_condition('ONSSEMPLOYER_804', True)
        self.assertEqual(self.get_total(self.payslip, 'ONSSEMPLOYER_804'), 0.0, "A wage below the cap owes nothing")

        self.version.wage = 5000
        rate = self.payslip._rule_parameter('l10n_be_legal_index')['200'][0]
        part_a = (5000 - 4000 * (1 + rate)) * min(rate, 0.02)
        self.assertAlmostEqual(self.get_total(self.payslip, 'ONSSEMPLOYER_804'), (part_a + part_a * 0.25) / 2, delta=0.01)

        self.payslip.write({'date_from': date(2026, 6, 1), 'date_to': date(2026, 6, 30)})
        self.assertEqual(self.get_total(self.payslip, 'ONSSEMPLOYER_804'), 0.0,
                         "The indexation of January 2026 is before the measure: nothing is due in 2026")

        # The fraction of performance (J / D) prorates the part above the cap: temporary unemployment (no performance,
        # DmfA code 76) from 15 to 30 June leaves 10 of the 22 days of June 2027
        self.payslip.write({'date_from': date(2027, 6, 1), 'date_to': date(2027, 6, 30)})
        unemployment = self.env.ref('hr_work_entry.l10n_be_work_entry_type_temporary_economic_unemployement_employee')
        self._generate_leave(self.employee, date(2027, 6, 15), date(2027, 6, 30), unemployment)
        self.assertAlmostEqual(
            self.get_total(self.payslip, 'ONSSEMPLOYER_804'), (part_a + part_a * 0.25) / 2 * 10 / 22, delta=0.01)
        self._generate_leave(self.employee, date(2027, 6, 1), date(2027, 6, 14), unemployment)
        self.assertEqual(self.get_total(self.payslip, 'ONSSEMPLOYER_804'), 0.0, "Nothing is due without performance")

    def test_onss_804_wage_moderation_part_time(self):
        """
        ONSSEMPLOYER_804
        A part-time wage is converted to a full-time one (Q/S) and the fraction of performance is the part-time
        worker's against a full-time worker: half-time at 3,000 EUR is 6,000 EUR full-time, performed at 50%.
        """
        self._enable_onss_804()
        self.version.resource_calendar_id = self.env['resource.calendar'].create({
            'name': 'Half-time 19 hours',
            'company_id': self.company.id,
            'reference_calendar_id': self.version.resource_calendar_id.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': 8.0,
                'hour_to': 11.8,
            }) for dayofweek in ['0', '1', '2', '3', '4']],
        })
        self.version.wage = 3000
        self.assertAlmostEqual(self.version.work_time_rate, 0.5, places=2)
        self.version.generate_work_entries(date(2027, 6, 1), date(2027, 6, 30))
        self.payslip.write({'date_from': date(2027, 6, 1), 'date_to': date(2027, 6, 30)})
        rate = self.payslip._rule_parameter('l10n_be_legal_index')['200'][0]
        part_a = (3000 / 0.5 - 4000 * (1 + rate)) * 0.5 * min(rate, 0.02)
        self.assertAlmostEqual(self.get_total(self.payslip, 'ONSSEMPLOYER_804'), (part_a + part_a * 0.25) / 2, delta=0.01)

    def test_horeca_occasional_flat_wage(self):
        """
        HORECA_OCC_FLAT, HORECA_OCC_TAXABLE, HORECA_OCC_PP
        Horeca occasional workers (DIMONA EXT, employer category 317): the contributions of their first 50 days of
        work of the year are computed on a flat wage per started hour, 6 hours a day at most, and the pay of those
        days is taxed at a flat rate apart from the scale; the days after follow the ordinary regime.
        """
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00317')
        self.version.write({
            'contract_date_start': date(2026, 4, 1),
            'l10n_be_dimona_category': 'ext',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00011').id,
            'l10n_be_joint_committee_id': self.cp_302.id,
            'wage_type': 'hourly',
            'hourly_wage': 15.0,
        })
        self.version.generate_work_entries(date(2026, 4, 1), date(2026, 6, 30))
        payslips = self.env['hr.payslip'].create([{
            'name': f'Extra {month}',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'struct_id': self.struct.id,
            'date_from': date(2026, month, 1),
        } for month in (4, 5, 6)])
        payslips.compute_sheet()
        flat_hourly_wage = self.payslip._rule_parameter('horeca_occasional_hourly_wage', date(2026, 4, 1))
        used = 0
        for payslip in payslips:
            worked = payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id.count_as == 'working_time')
            days = round(sum(worked.mapped('number_of_days')))
            flat_days = max(0, min(days, 50 - used))
            used += days
            values = payslip._get_line_values([
                'BASIC', 'SALARY', 'GROSS', 'P.P', 'EmpBonus.1', 'P.P.DED', 'PPTOTAL', 'HORECA_OCC_TAXABLE', 'HORECA_OCC_PP',
            ])
            values = {code: values[code][payslip.id]['total'] for code in values}
            # the 7.6 hours of a day count 8 started hours, capped at 6; the other days keep their pay
            expected = flat_days * 6 * flat_hourly_wage + values['BASIC'] * (days - flat_days) / days
            self.assertAlmostEqual(values['SALARY'], expected, 2, payslip.name)
            if flat_days == days:
                # the whole taxable pay is taxed at the flat rate, the scale gets none of it
                self.assertTrue(values['HORECA_OCC_TAXABLE'], payslip.name)
                self.assertAlmostEqual(values['HORECA_OCC_PP'], -values['HORECA_OCC_TAXABLE'] * 0.3331, delta=0.01,
                                       msg=payslip.name)
                self.assertFalse(values['GROSS'], payslip.name)
                self.assertFalse(values['P.P'], payslip.name)
                # the fiscal work bonus only reduces the tax of the scale, never the flat rate
                self.assertTrue(values['EmpBonus.1'], payslip.name)
                self.assertFalse(values['P.P.DED'], payslip.name)
                self.assertAlmostEqual(values['PPTOTAL'], -values['HORECA_OCC_PP'], 2, payslip.name)
        self.assertGreater(used, 50, "The third month goes past the worker's contingent")

    def test_horeca_occasional_scale_premium(self):
        """
        HORECA_OCC_SCALE_PREMIUM, HORECA_OCC_SCALE_PREMIUM_FLAT
        The premiums of a Horeca occasional worker taxed at the scale: covered by the flat wage on the days of the
        worker's contingent, out of the flat rate of withholding tax
        """
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00317')
        self.version.write({
            'contract_date_start': date(2026, 4, 1),
            'l10n_be_dimona_category': 'ext',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00011').id,
            'l10n_be_joint_committee_id': self.cp_302.id,
            'wage_type': 'hourly',
            'hourly_wage': 15.0,
        })
        self.version.generate_work_entries(date(2026, 4, 1), date(2026, 4, 30))
        payslips = self.env['hr.payslip'].create([{
            'name': f'Extra April {premium}',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'struct_id': self.struct.id,
            'date_from': date(2026, 4, 1),
        } for premium in (0, 24)])
        payslips[1]._set_input_value('HORECA_OCC_SCALE_PREMIUM', 24)
        payslips.compute_sheet()
        codes = ['BASIC', 'SALARY', 'GROSS', 'HORECA_OCC_TAXABLE', 'HORECA_OCC_PP', 'HORECA_OCC_SCALE_PREMIUM',
                 'HORECA_OCC_SCALE_PREMIUM_FLAT']
        values = payslips._get_line_values(codes)
        without, with_premium = ({code: values[code][payslip.id]['total'] for code in codes} for payslip in payslips)
        self.assertEqual(with_premium['HORECA_OCC_SCALE_PREMIUM'], 24)
        # all the days of the month are flat wage days: the whole premium is covered by the flat wage
        self.assertEqual(with_premium['HORECA_OCC_SCALE_PREMIUM_FLAT'], 24)
        self.assertAlmostEqual(with_premium['SALARY'], without['SALARY'], 2)
        # the flat rate taxes the same pay, the scale taxes the premium
        self.assertAlmostEqual(with_premium['HORECA_OCC_TAXABLE'], without['HORECA_OCC_TAXABLE'], 2)
        self.assertAlmostEqual(with_premium['HORECA_OCC_PP'], without['HORECA_OCC_PP'], 2)
        self.assertFalse(without['GROSS'])
        self.assertAlmostEqual(with_premium['GROSS'], 24, 2)

    def test_horeca_occasional_no_withholding_taxes(self):
        # an occasional Horeca worker without withholding taxes (a cross-border worker) pays neither the flat rate nor
        # the scale
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00317')
        self.version.write({
            'contract_date_start': date(2026, 4, 1),
            'l10n_be_dimona_category': 'ext',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00011').id,
            'l10n_be_joint_committee_id': self.cp_302.id,
            'wage_type': 'hourly',
            'hourly_wage': 15.0,
            'no_withholding_taxes': True,
        })
        self.version.generate_work_entries(date(2026, 4, 1), date(2026, 4, 30))
        payslip = self.env['hr.payslip'].create({
            'name': 'Extra April',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'struct_id': self.struct.id,
            'date_from': date(2026, 4, 1),
        })
        payslip.compute_sheet()
        values = payslip._get_line_values(['SALARY', 'HORECA_OCC_PP', 'P.P', 'PPTOTAL'])
        self.assertTrue(values['SALARY'][payslip.id]['total'])
        self.assertFalse(values['HORECA_OCC_PP'][payslip.id]['total'])
        self.assertFalse(values['P.P'][payslip.id]['total'])
        self.assertFalse(values['PPTOTAL'][payslip.id]['total'])

    def test_onss_256_computation(self):
        """
        ONSSEMPLOYER_256
        Accounting: ONSS Asbestos Contribution (Employer)
        """
        # Employee
        self.check_quarter_total('ONSSEMPLOYER_256', [0.1] * 3, 3000 * 0.01 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_256', [0.11, 0.11, 0.1], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.01 / 100)

    def test_onss_260_condition(self):
        """
        ONSSEMPLOYER_260
        Accounting: ONSS Activation Contribution (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('260'))
        self.check_condition('ONSSEMPLOYER_260', False)

        self.version.l10n_be_work_exemption = '2'
        self.check_condition('ONSSEMPLOYER_260', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_260', ['stu', 'ivt', 'flx'], False)

    def test_onss_260_computation(self):
        """
        ONSSEMPLOYER_260
        Accounting: ONSS Activation Contribution (Employer)
        """
        # == Employees with Activation >= 10% ==
        # Age < 60 years
        # Employee
        self.employee.birthday = date(2025 - 59, 1, 1)
        self.version.l10n_be_work_exemption = '2'
        self.check_quarter_total('ONSSEMPLOYER_260', [625] * 3, 3000 * 62.5 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_260', [675] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 62.5 / 100)

        # 60 years <= Age < 62 years
        # Employee
        self.employee.birthday = date(2025 - 61, 1, 1)
        self.version.l10n_be_worker_code_id = self.be_employee
        self.check_quarter_total('ONSSEMPLOYER_260', [562.5] * 3, 3000 * 56.25 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_260', [607.5] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 56.25 / 100)

        # 62 years <= Age
        # Employee
        self.employee.birthday = date(2025 - 63, 1, 1)
        self.version.l10n_be_worker_code_id = self.be_employee
        self.check_quarter_total('ONSSEMPLOYER_260', [500] * 3, 3000 * 50 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_260', [540] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 50 / 100)

        # == Employees with Activation < 10% ==
        # Age < 60 years
        # Employee
        for i in range(10):
            self.env['hr.employee'].create({
                'name': f'Employee {i}',
                'company_id': self.company.id,
                'date_version': '2025-01-01',
                'contract_date_start': '2025-01-01',
            })
        self.employee.birthday = date(2025 - 59, 1, 1)
        self.version.l10n_be_worker_code_id = self.be_employee
        self.check_quarter_total('ONSSEMPLOYER_260', [500] * 3, 3000 * 50 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_260', [540] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 50 / 100)

        # 60 years <= Age < 62 years
        # Employee
        self.employee.birthday = date(2025 - 61, 1, 1)
        self.version.l10n_be_worker_code_id = self.be_employee
        self.check_quarter_total('ONSSEMPLOYER_260', [450] * 3, 3000 * 45 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_260', [486] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 45 / 100)

        # 62 years <= Age
        # Employee
        self.employee.birthday = date(2025 - 63, 1, 1)
        self.version.l10n_be_worker_code_id = self.be_employee
        self.check_quarter_total('ONSSEMPLOYER_260', [400] * 3, 3000 * 40 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_260', [432] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 40 / 100)

    def test_onss_260_quarterly_minimum(self):
        """
        ONSSEMPLOYER_260
        The minimum of the activation contribution (300 EUR under 60 years) is a quarterly one: due once on the
        quarter, not on each payslip, as in the DmfA
        """
        self.employee.birthday = date(2025 - 59, 1, 1)
        self.version.write({'l10n_be_work_exemption': '2', 'wage': 150})
        # 150 x 62.5% = 93.75 a month, 281.25 on the quarter: raised to the minimum of 300
        self.check_quarter_total('ONSSEMPLOYER_260', [300, 0, 0], 300)
        # 400 x 62.5% = 250 a month, 750 on the quarter: no minimum
        self.version.wage = 400
        self.check_quarter_total('ONSSEMPLOYER_260', [300, 200, 250], 750)

    def test_onss_450_condition(self):
        """
        ONSSEMPLOYER_450
        Accounting: ONSS Flexi-Job (Employer)
        """
        self.check_condition('ONSSEMPLOYER_450', False)
        self.check_condition_dimona_categories('ONSSEMPLOYER_450', ['flx'], True)

    def test_flexi_holiday_pay_benefits_in_kind(self):
        """
        FLEXI_PECULE
        The flexi holiday pay is 7.67% of the whole flexi wage, its benefits in kind included
        """
        self.version.write({
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 3, 31),
            'l10n_be_dimona_category': 'flx',
            'mobile': 30.0,
        })
        self.payslip.compute_sheet()
        lines = self.payslip._get_line_values(['BASIC', 'ATN.MOB', 'FLEXI_PECULE'])
        basic, mobile, holiday_pay = (lines[code][self.payslip.id]['total'] for code in ('BASIC', 'ATN.MOB', 'FLEXI_PECULE'))
        self.assertTrue(mobile)
        self.assertAlmostEqual(holiday_pay, (basic + mobile) * 7.67 / 100, delta=0.005)

        # a benefit in kind without ONSS is no flexi wage: no flexi holiday pay on it
        self.payslip._set_input_value('ATN_MISC_NO_ONSS', 20)
        self.payslip.compute_sheet()
        lines = self.payslip._get_line_values(['ATN_MISC_NO_ONSS', 'FLEXI_PECULE'])
        self.assertAlmostEqual(lines['ATN_MISC_NO_ONSS'][self.payslip.id]['total'], 20, places=2)
        self.assertAlmostEqual(lines['FLEXI_PECULE'][self.payslip.id]['total'], holiday_pay, places=2)

    def test_flexi_exemption_cap(self):
        """
        FLEXI_EXEMPTION
        The flexi remuneration is tax exempt up to a yearly cap (18,440 EUR in 2026), without any
        cap for the legal pensioners. The early retirement status has nothing to do with it.
        """
        self.version.write({
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 3, 31),
            'l10n_be_dimona_category': 'flx',
        })

        def flexi_exemption(wage, **version_values):
            self.version.write({'l10n_be_flexi_monthly_wage': wage, **version_values})
            payslip = self.env['hr.payslip'].create({
                'name': 'Flexi Payslip',
                'date_from': '2026-01-01',
                'employee_id': self.employee.id,
                'company_id': self.company.id,
                'struct_id': self.struct.id,
            })
            return self.get_total(payslip, 'FLEXI_EXEMPTION'), self.get_total(payslip, 'P.P')

        # Standard cap
        self.assertAlmostEqual(flexi_exemption(20000)[0], -18440, 2)
        # Legal pensioner: no cap
        exemption, withholding_tax = flexi_exemption(20000, l10n_be_is_retired=True)
        self.assertAlmostEqual(exemption, -21534, 2)
        self.assertAlmostEqual(withholding_tax, 0, 2)
        # Early retirement status, not retired: standard cap
        self.assertAlmostEqual(flexi_exemption(9000, l10n_be_is_retired=False, l10n_be_early_retirement_status=True)[0], -9690.3, 2)

    def test_flexi_exemption_no_cap_before_2024(self):
        """
        FLEXI_EXEMPTION
        The yearly cap of the exemption applies from the income of 2024.
        """
        self.version.write({
            'date_version': date(2023, 1, 1),
            'contract_date_start': date(2023, 1, 1),
            'contract_date_end': date(2023, 3, 31),
            'l10n_be_dimona_category': 'flx',
            'l10n_be_flexi_monthly_wage': 20000,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Flexi Payslip 2023',
            'date_from': '2023-01-01',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'struct_id': self.struct.id,
        })
        self.assertAlmostEqual(self.get_total(payslip, 'FLEXI_EXEMPTION'), -21534, 2)

    def test_flexi_exemption_cap_same_period(self):
        """
        FLEXI_EXEMPTION
        A validated flexi payslip ending the same day as the computed one consumes the yearly cap.
        """
        self.version.write({
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 3, 31),
            'l10n_be_dimona_category': 'flx',
            'l10n_be_flexi_monthly_wage': 10000,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': 'Flexi Payslip %s' % i,
            'date_from': '2026-01-01',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'struct_id': self.struct.id,
        } for i in range(2)])
        self.assertAlmostEqual(self.get_total(payslips[0], 'FLEXI_EXEMPTION'), -10767, 2)
        payslips[0].action_payslip_done()
        self.assertAlmostEqual(self.get_total(payslips[1], 'FLEXI_EXEMPTION'), -(18440 - 10767), 2)

    def test_flexi_hourly_wage_four_decimals(self):
        # the flexi hourly wage keeps the four decimals of the hourly scale: the hours are paid at that exact rate, the
        # pay of every day rounded to the cent (22 days of 7.6 hours: 22 x 113.12, not 167.2 x 14.8839 = 2488.59)
        self.version.write({
            'contract_date_start': date(2026, 4, 1),
            'contract_date_end': date(2026, 4, 30),
            'l10n_be_dimona_category': 'flx',
            'wage_type': 'hourly',
            'l10n_be_flexi_hourly_wage': 14.8839,
        })
        self.assertEqual(self.version.l10n_be_flexi_hourly_wage, 14.8839)
        self.version.generate_work_entries(date(2026, 4, 1), date(2026, 4, 30))
        payslip = self.env['hr.payslip'].create({
            'name': 'Flexi April',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'struct_id': self.struct.id,
            'date_from': date(2026, 4, 1),
        })
        payslip.compute_sheet()
        attendance = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00')
        self.assertTrue(attendance.number_of_hours)
        self.assertAlmostEqual(attendance.number_of_hours, 167.2, places=2)
        self.assertAlmostEqual(attendance.amount, 2488.64, places=2)

    def test_onss_450_computation(self):
        """
        ONSSEMPLOYER_450
        Accounting: ONSS Flexi-Job (Employer)
        """
        # Employee
        # SALARY = BASIC + FLEXI_PECULE = 3000€ + 3000€ * 7.67 / 100 = 3000€ + 230.1€ = 3230.1€
        self.version.contract_date_start = date(2026, 1, 1)
        self.version.contract_date_end = date(2026, 3, 31)
        self.version.l10n_be_dimona_category = 'flx'
        self.check_quarter_total('ONSSEMPLOYER_450', [301.48, 301.47, 301.48], 3230.1 * 28 / 100)

        # Worker: no 108% base, the flexi holiday pay replaces the holiday fund
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_450', [301.48, 301.47, 301.48], 3230.1 * 28 / 100)

    def test_onss_800_condition(self):
        """
        ONSSEMPLOYER_800
        Accounting: ONSS Economic Unemployment Contribution (Employer)
        """
        # This rule doesn't apply for employer category 10 and worker code 495
        self.assertFalse(self.payslip._should_apply_onss_contribution('800'))
        self.check_condition('ONSSEMPLOYER_800', False)

        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.assertTrue(self.payslip._should_apply_onss_contribution('800'))
        self.check_condition('ONSSEMPLOYER_800', False)

        self._generate_leave(self.employee, '2026-01-01', '2026-01-02', self.economic_unemployment)
        self.check_condition('ONSSEMPLOYER_800', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_800', ['stu', 'ivt', 'flx'], False)

    def test_onss_800_two_versions(self):
        """
        ONSSEMPLOYER_800
        The days of economic unemployment of every line of the month count: a new version in the month gives a second
        137.00 line
        """
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.version.copy({'date_version': date(2026, 1, 15)})
        self._generate_leave(self.employee, '2026-01-05', '2026-01-06', self.economic_unemployment)
        self._generate_leave(self.employee, '2026-01-19', '2026-01-20', self.economic_unemployment)
        self.payslip.compute_sheet()
        self.assertEqual(len(self.payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '137.00')), 2)
        self._validate_rule_computed(self.payslip, 'ONSSEMPLOYER_800', True)

    def test_onss_800_computation(self):
        """
        ONSSEMPLOYER_800
        Accounting: ONSS Economic Unemployment Contribution (Employer)
        """
        # Worker
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker

        # 10 days total
        self._generate_leave(self.employee, '2026-01-01', '2026-01-14', self.economic_unemployment)
        self.check_total(self.payslip, 'ONSSEMPLOYER_800', 0)

        # 120 days last 3 quarters (01/04/2025 -> 31/12/2025)
        self._generate_leave(self.employee, '2025-07-17', '2025-12-31', self.economic_unemployment)
        for month in range(4, 13):
            date_from = date(2025, month, 1)
            date_to = date_from + relativedelta(day=31)
            self._generate_payslip(date_from, date_to).action_payslip_done()

        self.check_total(self.payslip, 'ONSSEMPLOYER_800', 200)
        self.payroll_config.l10n_be_in_difficulty = True
        self.check_total(self.payslip, 'ONSSEMPLOYER_800', 100)
        self.payroll_config.l10n_be_in_difficulty = False

        # 120 + 10 = 130 days total
        # => 20€ per day
        # quarter total = economic unemployment days in quarter * flat-rate per day
        # total = quarter total - already paid this quarter
        # => 10 * 20€ - 0€ = 200€
        self.check_total(self.quarter_payslips[0], 'ONSSEMPLOYER_800', 200)
        self.quarter_payslips[0].action_payslip_done()

        # 120 + 10 + 10 = 140 days total
        # => 40€ per day
        # quarter total = economic unemployment days in quarter * flat-rate per day
        # total = quarter total - already paid this quarter
        # => 20 * 40€ - 200€ = 800€ - 200€ = 600€
        self._generate_leave(self.employee, '2026-02-01', '2026-02-13', self.economic_unemployment)
        self.check_total(self.quarter_payslips[1], 'ONSSEMPLOYER_800', 600)
        self.quarter_payslips[1].action_payslip_done()

        # 120 + 10 + 10 + 10 = 150 days total
        # => 40€ per day
        # quarter total = economic unemployment days in quarter * flat-rate per day
        # total = quarter total - already paid this quarter
        # => 30 * 40€ - 800€ = 1200€ - 800€ = 400€
        self._generate_leave(self.employee, '2026-03-01', '2026-03-13', self.economic_unemployment)
        self.check_total(self.quarter_payslips[2], 'ONSSEMPLOYER_800', 400)

        # 30 days economic unemployment in this quarter
        # 150 days in the reference period so 40€ per day
        # quarter total = economic unemployment days in quarter * flat-rate per day
        # quarter total = 30 * 40€ = 1200€ = 200€ + 600€ + 400€
        quarter_total = 0
        for payslip in self.quarter_payslips:
            quarter_total += self.get_total(payslip, 'ONSSEMPLOYER_800')
        self.assertEqual(quarter_total, 30 * 40)

    def test_onss_809_condition(self):
        """
        ONSSEMPLOYER_809
        Accounting: ONSS Commercial Sector FFE (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('809'))
        self.check_condition('ONSSEMPLOYER_809', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_809', ['stu', 'ivt', 'flx'], False)

    def test_onss_809_computation(self):
        """
        ONSSEMPLOYER_809
        Accounting: ONSS Commercial Sector FFE (Employer)
        """
        # Employee - Small Commercial Company
        self.payroll_config.onss_importance_code = '3'
        self.check_quarter_total('ONSSEMPLOYER_809', [3.4] * 3, 3000 * 0.34 / 100)

        # ACS - Small Commercial Company
        self.version.l10n_be_worker_code_id = self.be_acs
        self.check_quarter_total('ONSSEMPLOYER_809', [3.2] * 3, 3000 * 0.32 / 100)

        # Worker - Small Commercial Company
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_809', [3.67, 3.67, 3.68], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.34 / 100)

        # Employee No Salary Moderation - Small Commercial Company
        self.version.l10n_be_worker_code_id = self.be_employee_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_809', [3.2] * 3, 3000 * 0.32 / 100)

        # Worker No Salary Moderation - Small Commercial Company
        self.version.l10n_be_worker_code_id = self.be_worker_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_809', [3.46, 3.45, 3.46], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.32 / 100)

        # Employee - Large Commercial Company
        self.payroll_config.onss_importance_code = '4'
        self.version.l10n_be_worker_code_id = self.be_employee
        self.check_quarter_total('ONSSEMPLOYER_809', [3.9] * 3, 3000 * 0.39 / 100)

        # ACS - Large Commercial Company
        self.version.l10n_be_worker_code_id = self.be_acs
        self.check_quarter_total('ONSSEMPLOYER_809', [3.7] * 3, 3000 * 0.37 / 100)

        # Worker - Large Commercial Company
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_809', [4.21, 4.21, 4.22], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.39 / 100)

        # Employee No Salary Moderation - Large Commercial Company
        self.version.l10n_be_worker_code_id = self.be_employee_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_809', [3.7] * 3, 3000 * 0.37 / 100)

        # Worker No Salary Moderation - Large Commercial Company
        self.version.l10n_be_worker_code_id = self.be_worker_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_809', [4, 3.99, 4], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.37 / 100)

    def test_onss_810_condition(self):
        """
        ONSSEMPLOYER_810
        Accounting: ONSS Special FFE (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('810'))
        self.check_condition('ONSSEMPLOYER_810', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_810', ['stu', 'ivt', 'flx'], False)

    def test_onss_810_computation(self):
        """
        ONSSEMPLOYER_810
        Accounting: ONSS Special FFE (Employer)
        """
        # Employee
        self.check_quarter_total('ONSSEMPLOYER_810', [1.0] * 3, 3000 * 0.1 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_810', [self.payslip._rule_parameter('worker_onss_calculation_basis_uplift')] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.1 / 100)

    def test_onss_811_condition(self):
        """
        ONSSEMPLOYER_811
        Accounting: ONSS Non-Commercial Sector FFE (Employer)
        """
        # This rule doesn't apply for commercial sector employer
        self.assertFalse(self.payslip._should_apply_onss_contribution('811'))
        self.check_condition('ONSSEMPLOYER_811', False)

        self.payroll_config.l10n_be_ffe_employer_type = 'B'
        self.assertTrue(self.payslip._should_apply_onss_contribution('811'))
        self.check_condition('ONSSEMPLOYER_811', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_811', ['stu', 'ivt', 'flx'], False)

    def test_onss_811_computation(self):
        """
        ONSSEMPLOYER_811
        Accounting: ONSS Non-Commercial Sector FFE (Employer)
        """
        # Employee - Non-Commercial Sector
        self.payroll_config.l10n_be_ffe_employer_type = 'B'
        self.check_quarter_total('ONSSEMPLOYER_811', [0.1] * 3, 3000 * 0.01 / 100)

        # Worker - Non-Commercial Sector
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_811', [0.11, 0.11, 0.1], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.01 / 100)

        # Employee No Salary Moderation - Non-Commercial Sector
        self.version.l10n_be_worker_code_id = self.be_employee_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_811', [0.1] * 3, 3000 * 0.01 / 100)

        # Worker No Salary Moderation - Non-Commercial Sector
        self.version.l10n_be_worker_code_id = self.be_worker_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_811', [0.11, 0.11, 0.1], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.01 / 100)

    def test_onss_820_condition(self):
        """
        ONSSEMPLOYER_820
        Accounting: ONSS Workers Existence Security Funds (Employer)
        """
        self.assertFalse(self.payslip._should_apply_onss_contribution('820'))

        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.assertTrue(self.payslip._should_apply_onss_contribution('820'))
        self.check_condition('ONSSEMPLOYER_820', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_820', ['stu', 'ivt', 'flx'], False)

    def test_onss_820_computation(self):
        """
        ONSSEMPLOYER_820
        Accounting: ONSS Workers Existence Security Funds (Employer)
        """
        # Worker - Small Company
        self.payroll_config.onss_importance_code = '4'
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_820', [15.12] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 1.4 / 100)

        # Worker - Large Company
        self.payroll_config.onss_importance_code = '5'
        self.check_quarter_total('ONSSEMPLOYER_820', [15.66] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 1.45 / 100)

    def test_onss_820_auxiliary_committee_workers(self):
        """
        ONSSEMPLOYER_820
        The workers of category 210 (auxiliary committee 100) pay the training fund of their committee: 0.15 % from
        1 April 2026, a single rate of type 0 whatever the size of the employer (ONSS dmfa_rate_2026_2)
        """
        for code, value in (
            ('l10n_be_onss_combinations_210_015', {'820': ['1']}),
            ('l10n_be_onss_rates_210_820_0', {'personal_rate': 0.0, 'employer_rate': 0.15, 'salary_moderation_rate': 0.0, 'total_rate': 0.15}),
        ):
            parameter = self.env['hr.rule.parameter'].sudo().search([('code', '=', code)]) or self.env['hr.rule.parameter'].sudo().create({
                'name': code,
                'code': code,
                'country_id': self.env.ref('base.be').id,
            })
            self.env['hr.rule.parameter.value'].sudo().create({
                'rule_parameter_id': parameter.id,
                'parameter_value': str(value),
                'date_from': date(2000, 1, 1),
            })
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00210')
        self.payroll_config.onss_importance_code = '2'
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_condition('ONSSEMPLOYER_820', True)
        self.check_quarter_total('ONSSEMPLOYER_820', [1.62] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.15 / 100)

        self.payroll_config.onss_importance_code = '5'
        self.check_quarter_total('ONSSEMPLOYER_820', [1.62] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.15 / 100)

    def test_onss_820_construction(self):
        """
        ONSSEMPLOYER_820
        The workers of the construction (category 024) pay the subsistence security fund in percentage: 14.77 % for the
        employers of less than 20 workers (type 0), 13.27 % from 20 workers (type 5), on the gross remuneration at 108 %
        """
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00024')
        self.payroll_config.onss_importance_code = '3'  # 10 to 19 workers
        self.version.write({
            'l10n_be_worker_code_id': self.be_worker.id,
            'l10n_be_joint_committee_id': self.construction_sector.id,
        })
        self.assertTrue(self.payslip._should_apply_onss_contribution('820'))
        self.check_condition('ONSSEMPLOYER_820', True)
        uplift = self.payslip._rule_parameter('worker_onss_calculation_basis_uplift')
        self.assertEqual(self.payslip._get_fse_percentage_contribution_type(), '0')
        self.check_quarter_total('ONSSEMPLOYER_820', [159.52, 159.51, 159.52], 3000 * uplift * 14.77 / 100)

        self.payroll_config.onss_importance_code = '4'  # 20 to 49 workers
        self.assertEqual(self.payslip._get_fse_percentage_contribution_type(), '5')
        self.check_quarter_total('ONSSEMPLOYER_820', [143.32, 143.31, 143.32], 3000 * uplift * 13.27 / 100)

        # The DmfA declares the contribution with the same type and rate
        contribution = DMFAWorkerContribution(self.quarter_payslips, 3000 * uplift, date(2026, 1, 1), 820)
        self.assertEqual(contribution.contribution_type, '5')
        self.assertEqual(contribution.amount, format_amount(round(3000 * uplift * 13.27 / 100, 2)))

        # The hotel industry keeps its threshold of 50 workers
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.assertEqual(self.payslip._get_fse_percentage_contribution_type(), '0')
        self.payroll_config.onss_importance_code = '5'
        self.assertEqual(self.payslip._get_fse_percentage_contribution_type(), '5')

    def test_onss_826_construction_flat_amount(self):
        """
        ONSSEMPLOYER_826
        The contribution to the subsistence security fund of the construction workers (category 024) is a flat amount
        by quarter (644 euros) prorated on the occupation fraction μ(c): not a remuneration, without the 108% basis of
        the blue collars
        """
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00024')
        self.version.write({
            'l10n_be_worker_code_id': self.be_worker.id,
            'l10n_be_joint_committee_id': self.construction_sector.id,
        })
        self.employee.birthday = date(1990, 1, 1)
        self.check_condition('ONSSEMPLOYER_826', True)
        self.quarter_payslips.action_payslip_draft()
        quarter_total = 0
        for payslip in self.quarter_payslips:
            quarter_total += self.get_total(payslip, 'ONSSEMPLOYER_826')
            payslip.action_payslip_done()
        mu = self.payslip._calculate_dmfa_occupation_fraction(self.quarter_payslips)
        self.assertTrue(mu)
        self.assertAlmostEqual(quarter_total, round(644 * mu / 100, 2), 2)

    @freeze_time('2026-10-27')
    def test_onss_826_young_worker_age_at_quarter_end(self):
        """
        ONSSEMPLOYER_826
        The flat contribution to the subsistence security fund of the construction workers (category 024) is reduced
        for the workers younger than 25 (type 2): their age at the end of the quarter of the payslip, not today
        """
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00024')
        self.version.write({
            'l10n_be_worker_code_id': self.be_worker.id,
            'l10n_be_joint_committee_id': self.construction_sector.id,
        })
        # 24 years old at the end of the first quarter of 2026, 25 today
        self.employee.birthday = date(2001, 5, 15)
        self.check_condition('ONSSEMPLOYER_826', True)
        self.quarter_payslips.action_payslip_draft()
        quarter_total = 0
        for payslip in self.quarter_payslips:
            quarter_total += self.get_total(payslip, 'ONSSEMPLOYER_826')
            payslip.action_payslip_done()
        mu = self.payslip._calculate_dmfa_occupation_fraction(self.quarter_payslips)
        self.assertTrue(mu)
        self.assertAlmostEqual(quarter_total, round(444 * mu / 100, 2), 2)
        self.assertEqual(self.payslip._get_fse_flat_contribution_type(), 2)
        # The DmfA declares the reduced type
        contribution = DMFAWorkerContribution(self.quarter_payslips, 3000, date(2026, 1, 1), 826)
        self.assertEqual(contribution.contribution_type, 2)

        # 25 years old at the end of the quarter
        self.employee.birthday = date(2001, 3, 31)
        self.assertEqual(self.payslip._get_fse_flat_contribution_type(), 0)

    def test_l10n_be_employer_category_occasional_worker_merge(self):
        """
        Horeca companies no longer need a dedicated payroll configuration for category 317:
        an employee declared as an occasional worker (DIMONA category "ext") is automatically
        reported under 317 even though the company is only configured with 017.
        """
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.assertEqual(self.version._l10n_be_get_employer_category_dmfa_code(), '017')

        self.version.l10n_be_dimona_category = 'ext'
        self.assertEqual(self.version._l10n_be_get_employer_category_dmfa_code(), '317')

        # The merge only applies to employer categories that define an occasional counterpart
        self.payroll_config.l10n_be_employer_category_id = self.category_employee
        self.assertEqual(self.version._l10n_be_get_employer_category_dmfa_code(), self.category_employee.dmfa_code)

        # The Existence Security Fund contribution (820) applies to both regular (017) and
        # occasional (317) Horeca workers, whether the occasional one is declared under a merged
        # 017 payroll configuration or a dedicated 317 one
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.version.l10n_be_dimona_category = False
        self.assertTrue(self.payslip._should_apply_onss_contribution('820'))
        self.check_condition('ONSSEMPLOYER_820', True)

        # Occasional workers are declared under their own worker code (011), for which the ONSS
        # rates/combinations of category 317 are loaded (see common.py)
        self.version.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00011')
        self.version.l10n_be_dimona_category = 'ext'
        self.assertTrue(self.payslip._l10n_be_is_horeca_occasional())
        self.check_condition('ONSSEMPLOYER_820', True)
        self.assertEqual(self.payslip._get_onss_rates(contribution_type='1'), self.payslip._rule_parameter(
            'l10n_be_onss_rates_317_011_1', self.payslip.date_to))

        # Without the imported rates of 317 for its worker code, an occasional worker keeps the ones of 017
        self.version.l10n_be_worker_code_id = self.be_worker
        self.assertEqual(self.payslip._get_onss_rates(contribution_type='1'), self.payslip._rule_parameter(
            'l10n_be_onss_rates_017_015_1', self.payslip.date_to))
        combinations_017 = self.payslip._rule_parameter('l10n_be_onss_combinations_017_015', self.payslip.date_to)
        self.assertTrue(combinations_017.get('820'))
        self.assertEqual(self.payslip._get_owedness_codes('820'), combinations_017['820'])

        # The employer category of a payslip is the one of its own payroll configuration (e.g. set manually)
        self.payslip.payroll_config_id = self.env['payroll.config.settings'].create({
            'company_id': self.payslip.company_id.id,
            'date_version': date(2100, 1, 1),
            'l10n_be_employer_category_id': self.category_employee.id,
        })
        self.assertEqual(self.payslip._l10n_be_get_employer_category_dmfa_code(), self.category_employee.dmfa_code)
        self.assertEqual(self.version._l10n_be_get_employer_category_dmfa_code(), '317')

        # Without employer category
        self.assertFalse(self.version._l10n_be_get_employer_category_dmfa_code(self.env['l10n.be.employer.category']))

        # The salary scales of the occasional workers (317) can be chosen with a 017 configuration
        category_317 = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00317')
        self.assertEqual(category_317.regular_category_id, self.category_horeca)
        self.assertFalse(self.category_horeca.regular_category_id)
        occasional_scales = self.env['l10n_be.salary.scale'].search([('employer_category_id', '=', category_317.id)])
        self.assertTrue(occasional_scales)
        self.assertEqual(self.env['l10n_be.salary.scale'].search([
            ('employer_category_id.regular_category_id', '=', self.category_horeca.id),
        ]), occasional_scales)
        self.assertFalse(self.env['l10n_be.salary.scale'].search([('employer_category_id.regular_category_id', '=', False)]))
        self.assertFalse(self.env['l10n_be.salary.scale'].search([
            ('employer_category_id.regular_category_id', '=', self.category_employee.id),
        ]))

        # The DmfA worker records of the occasional workers are kept apart from the regular ones of the same worker code
        state_model = self.env['l10n_be.dmfa.natural_person.state']
        self.assertEqual(state_model._get_worker_record_key('317', '015', '017'), '317-015')
        self.assertEqual(state_model._get_worker_record_key('317', '015', '317'), '015')
        self.assertEqual(state_model._get_worker_record_key('017', '015', '017'), '015')

    def test_onss_825_condition(self):
        """
        ONSSEMPLOYER_825
        Accounting: ONSS Workers Retirement Funds (Employer)
        """
        self.assertFalse(self.payslip._should_apply_onss_contribution('825'))

        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.employee_type_id = self.be_worker_emp_type
        self.version.l10n_be_worker_code_id = self.be_worker
        self.assertTrue(self.payslip._should_apply_onss_contribution('825'))
        self.check_condition('ONSSEMPLOYER_825', False)

        for retirement_fund in ['0', '8']:
            self.payroll_config.l10n_be_worker_retirement_fund = retirement_fund
            self.check_condition('ONSSEMPLOYER_825', True)

        self.payroll_config.l10n_be_employer_category_id = self.category_food_industry
        for retirement_fund in ['1', '2']:
            self.payroll_config.l10n_be_worker_retirement_fund = retirement_fund
            self.check_condition('ONSSEMPLOYER_825', True)

        self.employee.birthday = date(2026 - 61, 1, 1)
        retired_version = self.employee.create_version({
            'date_version': date(2025, 12, 1),
            'l10n_be_is_retired': True,
        })
        self.check_condition('ONSSEMPLOYER_825', False)

        retired_version.date_version = date(2026, 1, 1)
        self.check_condition('ONSSEMPLOYER_825', True)

        self.check_condition_dimona_categories('ONSSEMPLOYER_825', ['stu', 'ivt', 'flx'], False)

    def test_horeca_pension_apprentices_and_extras(self):
        self.payroll_config.write({
            'l10n_be_employer_category_id': self.category_horeca.id,
            'l10n_be_worker_retirement_fund': '0',
            'l10n_be_employee_retirement_fund': '0',
        })
        self.version.l10n_be_joint_committee_id = self.cp_302
        # The exclusion still applies after the apprentice enters ordinary
        # social security in January of the year of their nineteenth birthday.
        self.employee.birthday = date(2007, 12, 1)
        for worker_code, rule_code in [(self.be_worker, 'ONSSEMPLOYER_825'), (self.be_employee, 'ONSSEMPLOYER_835')]:
            with self.subTest(rule_code=rule_code):
                self.version.write({
                    'l10n_be_worker_code_id': worker_code.id,
                    'l10n_be_dimona_category': 'oth',
                    'l10n_be_apprenticeship_contract_number': False,
                })
                self.assertGreater(self.get_total(self.payslip, rule_code), 0)
                self.version.l10n_be_dimona_category = 'alt'
                self.assertAlmostEqual(self.get_total(self.payslip, rule_code), 0, places=2)
                self.version.l10n_be_dimona_category = 'ext'
                self.assertAlmostEqual(self.get_total(self.payslip, rule_code), 0, places=2)
                self.version.write({
                    'l10n_be_dimona_category': 'oth',
                    'l10n_be_apprenticeship_contract_number': 'TEST-APPRENTICE',
                })
                self.assertAlmostEqual(self.get_total(self.payslip, rule_code), 0, places=2)

        # Same exclusion of the extras with a payroll configuration dedicated to the occasional workers (317)
        self.version.write({
            'l10n_be_worker_code_id': self.be_worker.id,
            'l10n_be_dimona_category': 'oth',
            'l10n_be_apprenticeship_contract_number': False,
        })
        self.assertTrue(self.payslip._must_contribute_retirement_fund())
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00317')
        self.version.l10n_be_dimona_category = 'ext'
        self.assertFalse(self.payslip._must_contribute_retirement_fund())

    def test_onss_825_computation(self):
        """
        ONSSEMPLOYER_825
        Accounting: ONSS Workers Retirement Funds (Employer)
        """
        # Worker - Contribution Due
        self.payroll_config.l10n_be_worker_retirement_fund = '0'
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.employee_type_id = self.be_worker_emp_type
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_825', [11.88] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 1.1 / 100)

        # Worker - Contribution Not Due
        self.payroll_config.l10n_be_worker_retirement_fund = '8'
        self.check_quarter_total('ONSSEMPLOYER_825', [0] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0 / 100)

        # Worker - Increased Contribution
        self.payroll_config.l10n_be_worker_retirement_fund = '1'
        self.payroll_config.l10n_be_employer_category_id = self.category_food_industry
        self.check_quarter_total('ONSSEMPLOYER_825', [self.payslip._rule_parameter('worker_onss_calculation_basis_uplift')] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.1 / 100)

        # Worker - Solidarity Contribution
        self.payroll_config.l10n_be_worker_retirement_fund = '2'
        self.check_quarter_total('ONSSEMPLOYER_825', [0.65, 0.65, 0.64], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.06 / 100)

    def test_onss_830_condition(self):
        """
        ONSSEMPLOYER_830
        Accounting: ONSS Employees Existence Security Funds (Employer)
        """
        self.assertFalse(self.payslip._should_apply_onss_contribution('830'))

        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_acs
        self.version.l10n_be_joint_committee_id = self.cp_302
        self.check_condition('ONSSEMPLOYER_830', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_830', ['stu', 'ivt', 'flx'], False)

    def test_onss_830_computation(self):
        """
        ONSSEMPLOYER_830
        Accounting: ONSS Employees Existence Security Funds (Employer)
        """
        # ACS - Small Company
        self.payroll_config.onss_importance_code = '4'
        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_acs
        self.version.l10n_be_joint_committee_id = self.cp_302
        self.check_quarter_total('ONSSEMPLOYER_830', [14] * 3, 3000 * 1.4 / 100)

        # ACS - Large Company
        self.payroll_config.onss_importance_code = '5'
        self.check_quarter_total('ONSSEMPLOYER_830', [14.5] * 3, 3000 * 1.45 / 100)

    def test_onss_subsistence_funds_adult_apprentice(self):
        """
        ONSSEMPLOYER_820 / 830 / 831
        No subsistence fund contribution for an apprentice in alternance training, for the whole of its contract,
        whatever its age (the generic owedness of the ONSS combinations only spares the apprentices under 18)
        """
        self.employee.birthday = date(2000, 1, 1)
        self.check_condition('ONSSEMPLOYER_831', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_831', ['alt'], False)

        self.payroll_config.l10n_be_employer_category_id = self.category_horeca
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_condition('ONSSEMPLOYER_820', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_820', ['alt'], False)

    def test_onss_831_condition(self):
        """
        ONSSEMPLOYER_831
        Accounting: ONSS Employees Social Funds CPAE (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('831'))
        self.check_condition('ONSSEMPLOYER_831', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_831', ['stu', 'ivt', 'flx'], False)

    def test_onss_831_computation(self):
        """
        ONSSEMPLOYER_831
        Accounting: ONSS Employees Social Funds CPAE (Employer)
        """
        # Employee
        self.check_quarter_total('ONSSEMPLOYER_831', [2.3] * 3, 3000 * 0.23 / 100)

    def test_onss_835_condition(self):
        """
        ONSSEMPLOYER_835
        Accounting: ONSS Employees Retirement Funds (Employer)
        """
        self.assertFalse(self.payslip._should_apply_onss_contribution('835'))

        self.payroll_config.l10n_be_employer_category_id = self.category_food_industry
        self.version.l10n_be_worker_code_id = self.be_acs
        self.assertTrue(self.payslip._should_apply_onss_contribution('835'))
        self.check_condition('ONSSEMPLOYER_835', False)

        for retirement_fund in ['0', '1', '8']:
            self.payroll_config.l10n_be_employee_retirement_fund = retirement_fund
            self.check_condition('ONSSEMPLOYER_835', True)

        self.employee.birthday = date(2026 - 61, 1, 1)
        retired_version = self.employee.create_version({
            'date_version': date(2025, 12, 1),
            'l10n_be_is_retired': True,
        })
        self.check_condition('ONSSEMPLOYER_835', False)

        retired_version.date_version = date(2026, 1, 1)
        self.check_condition('ONSSEMPLOYER_835', True)

        self.check_condition_dimona_categories('ONSSEMPLOYER_835', ['stu', 'ivt', 'flx'], False)

    def test_onss_835_exclusions(self):
        """
        ONSSEMPLOYER_835
        No contribution on the notice indemnity of the notaries (employer category 435), nor for the apprentices of
        the construction employers (worker code 439, or 495 with an apprenticeship)
        """
        self.assertFalse(self.payslip._l10n_be_is_excluded_from_employee_retirement_fund())
        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00435')
        self.assertFalse(self.payslip._l10n_be_is_excluded_from_employee_retirement_fund())
        termination_payslip = self.env['hr.payslip'].create({
            'name': 'Termination Fees',
            'date_from': '2026-03-01',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees').id,
        })
        self.assertTrue(termination_payslip._l10n_be_is_excluded_from_employee_retirement_fund())

        self.payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00024')
        self.assertFalse(self.payslip._l10n_be_is_excluded_from_employee_retirement_fund())
        self.assertFalse(termination_payslip._l10n_be_is_excluded_from_employee_retirement_fund())
        self.version.l10n_be_worker_code_id = self.be_employee_no_salary_moderation  # 439
        self.assertTrue(self.payslip._l10n_be_is_excluded_from_employee_retirement_fund())
        self.version.write({'l10n_be_worker_code_id': self.be_employee.id, 'l10n_be_apprenticeship_contract_number': 'A123'})
        self.assertTrue(self.payslip._l10n_be_is_excluded_from_employee_retirement_fund())
        self.payroll_config.l10n_be_employer_category_id = self.category_food_industry
        self.assertFalse(self.payslip._l10n_be_is_excluded_from_employee_retirement_fund())

    def test_onss_835_computation(self):
        """
        ONSSEMPLOYER_835
        Accounting: ONSS Employees Retirement Funds (Employer)
        """
        # ACS - Contribution Due
        self.payroll_config.l10n_be_employee_retirement_fund = '0'
        self.payroll_config.l10n_be_employer_category_id = self.category_food_industry
        self.version.l10n_be_worker_code_id = self.be_acs
        self.check_quarter_total('ONSSEMPLOYER_835', [12.5] * 3, 3000 * 1.25 / 100)

        # ACS - Increased Contribution
        self.payroll_config.l10n_be_employee_retirement_fund = '1'
        self.check_quarter_total('ONSSEMPLOYER_835', [16.5] * 3, 3000 * 1.65 / 100)

        # ACS - Contribution Not Due
        self.payroll_config.l10n_be_employee_retirement_fund = '8'
        self.check_quarter_total('ONSSEMPLOYER_835', [0] * 3, 3000 * 0 / 100)

    def test_onss_852_condition(self):
        """
        ONSSEMPLOYER_852
        Accounting: ONSS Risk Groups Contribution (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('852'))
        self.check_condition('ONSSEMPLOYER_852', False)

        self.payroll_config.l10n_be_at_risk_groups_contribution = True
        self.check_condition('ONSSEMPLOYER_852', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_852', ['stu', 'ivt', 'flx'], False)

    def test_onss_852_computation(self):
        """
        ONSSEMPLOYER_852
        Accounting: ONSS Risk Groups Contribution (Employer)
        """
        # Employee
        self.payroll_config.l10n_be_at_risk_groups_contribution = True
        self.check_quarter_total('ONSSEMPLOYER_852', [1] * 3, 3000 * 0.1 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_852', [self.payslip._rule_parameter('worker_onss_calculation_basis_uplift')] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.1 / 100)

    def test_onss_855_condition(self):
        """
        ONSSEMPLOYER_855
        Accounting: ONSS Special Contribution with Salary Moderation (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('855'))
        self.check_condition('ONSSEMPLOYER_855', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_855', ['stu', 'ivt', 'flx'], False)

        self.payroll_config.onss_importance_code = '2'
        self.check_condition('ONSSEMPLOYER_855', False)

        self.payroll_config.onss_importance_code = '3'
        self.check_condition('ONSSEMPLOYER_855', True)

        self.version.l10n_be_worker_code_id = self.be_employee_no_salary_moderation
        self.check_condition('ONSSEMPLOYER_855', False)

    def test_onss_855_computation(self):
        """
        ONSSEMPLOYER_855
        Accounting: ONSS Special Contribution with Salary Moderation (Employer)
        """
        # Employee
        self.check_quarter_total('ONSSEMPLOYER_855', [16.9] * 3, 3000 * 1.69 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_855', [18.25, 18.25, 18.26], 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 1.69 / 100)

    def test_onss_857_condition(self):
        """
        ONSSEMPLOYER_857
        Accounting: ONSS Special Contribution without Salary Moderation (Employer)
        """
        self.assertFalse(self.payslip._should_apply_onss_contribution('857'))

        self.version.employee_type_id = self.be_apprent_emp_type
        self.version.l10n_be_worker_code_id = self.be_employee_no_salary_moderation
        self.assertTrue(self.payslip._should_apply_onss_contribution('857'))
        self.check_condition('ONSSEMPLOYER_857', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_857', ['stu', 'ivt', 'flx'], False)

        self.payroll_config.onss_importance_code = '2'
        self.check_condition('ONSSEMPLOYER_857', False)

        self.payroll_config.onss_importance_code = '3'
        self.check_condition('ONSSEMPLOYER_857', True)

    def test_onss_857_computation(self):
        """
        ONSSEMPLOYER_857
        Accounting: ONSS Special Contribution without Salary Moderation (Employer)
        """
        # Employee No Salary Moderation
        self.version.l10n_be_worker_code_id = self.be_employee_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_857', [16] * 3, 3000 * 1.6 / 100)

        # Worker No Salary Moderation
        self.version.l10n_be_worker_code_id = self.be_worker_no_salary_moderation
        self.check_quarter_total('ONSSEMPLOYER_857', [17.28] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 1.6 / 100)

    def test_onss_859_condition(self):
        """
        ONSSEMPLOYER_859
        Accounting: ONSS Temporary Unemployment (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('859'))
        self.check_condition('ONSSEMPLOYER_859', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_859', ['stu', 'ivt', 'flx'], False)

    def test_onss_859_computation(self):
        """
        ONSSEMPLOYER_859
        Accounting: ONSS Temporary Unemployment (Employer)
        """
        # Employee
        self.check_quarter_total('ONSSEMPLOYER_859', [1] * 3, 3000 * 0.1 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_859', [self.payslip._rule_parameter('worker_onss_calculation_basis_uplift')] * 3, 3000 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 0.1 / 100)

    def test_onss_865_condition(self):
        """
        ONSSEMPLOYER_865
        Accounting: ONSS Group Insurance (Employer)
        """
        self.check_condition('ONSSEMPLOYER_865', False)

        self.version.l10n_be_group_insurance_company_contribution = 0.5
        self.check_condition('ONSSEMPLOYER_865', True)

    def test_onss_865_computation(self):
        """
        ONSSEMPLOYER_865
        Accounting: ONSS Group Insurance (Employer)
        """
        # Employee
        # GI.COMP.CONT = ONSS_BASE * COMPANY_CONTRIBUTION = 3000€ * 50% = 1500€
        self.version.l10n_be_group_insurance_company_contribution = 0.5
        self.check_quarter_total('ONSSEMPLOYER_865', [44.3] * 3, 1500 * 8.86 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_865', [47.84, 47.85, 47.84], 1500 * self.payslip._rule_parameter('worker_onss_calculation_basis_uplift') * 8.86 / 100)

    def test_onss_878_condition(self):
        """
        ONSSEMPLOYER_878
        Accounting: ONSS Journalist Pension Fund (Employer)
        """
        self.check_condition('ONSSEMPLOYER_878', False)

        self.version.l10n_be_worker_status = 'PJ'
        self.check_condition('ONSSEMPLOYER_878', True)

    def test_onss_878_computation(self):
        """
        ONSSEMPLOYER_878
        Accounting: ONSS Journalist Pension Fund (Employer)
        """
        self.version.l10n_be_worker_status = 'PJ'

        rate = 20
        percentage = 2.0  # 2.0%

        self.check_quarter_total('ONSSEMPLOYER_878', [rate] * 3, 3000 * percentage / 100)

    def test_onss_889_condition(self):
        """
        ONSSEMPLOYER_889
        Accounting: ONSS Traffic Fines Contribution (Employer)
        """
        self.assertTrue(self.payslip._should_apply_onss_contribution('889'))
        self.check_condition('ONSSEMPLOYER_889', False)

        self.payslip._set_input_value('TRAFFIC_FINES', 200)
        self.check_condition('ONSSEMPLOYER_889', True)
        self.check_condition_dimona_categories('ONSSEMPLOYER_889', ['stu', 'ivt', 'flx'], False)

    def test_onss_889_computation(self):
        """
        ONSSEMPLOYER_889
        Accounting: ONSS Traffic Fines Contribution (Employer)
        """
        # Employee
        self.payslip._set_input_value('TRAFFIC_FINES', 200)
        self.check_quarter_total('ONSSEMPLOYER_889', [66, None, None], 200 * 33 / 100)

        # Worker
        self.version.l10n_be_worker_code_id = self.be_worker
        self.check_quarter_total('ONSSEMPLOYER_889', [66, None, None], 200 * 33 / 100)
