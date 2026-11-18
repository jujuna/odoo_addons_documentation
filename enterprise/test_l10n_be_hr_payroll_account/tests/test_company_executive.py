from datetime import date, datetime

from odoo import Command
from odoo.tests import tagged
from .common import TestPayrollAccountCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestCompanyExecutive(TestPayrollAccountCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        attendance_work_entry_type = cls.env['hr.work.entry.type'].search([('code', '=', '002.00'), ('country_code', '=', 'BE')], limit=1)
        be_resource_calendar = cls.env['resource.calendar'].create({
            'name': 'BE Calendar',
            'company_id': cls.company_id.id,
            'hours_per_day': 7.6,
            'hours_per_week': 38,
            'full_time_required_hours': 38,
            'attendance_ids': [
                (0, 0, {'dayofweek': str(weekday),
                        'hour_from': hour,
                        'hour_to': hour + 4,
                        'work_entry_type_id': attendance_work_entry_type.id,
                       })
                for weekday in range(5)
                for hour in [8, 13]
            ],
        })
        cls.employee = cls.create_employee({
            'name': 'Karim',
            'date_version': date(2020, 1, 1),
            'contract_date_start': date(2020, 1, 1),
            'contract_date_end': False,
            'resource_calendar_id': be_resource_calendar.id,
            'employee_type_id': cls.env.ref("hr.contract_type_company_executive").id,
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
        })
        # Made a company executive by the tests, to compare with what an ordinary employee gets
        cls.ordinary_employee = cls.create_employee({
            'name': 'Sofia',
            'date_version': date(2020, 1, 1),
            'contract_date_start': date(2020, 1, 1),
            'contract_date_end': False,
            'resource_calendar_id': be_resource_calendar.id,
        })

    def test_meal_vouchers_company_executive(self):
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'date_from': date(date.today().year, 1, 1),
            'date_to': date(date.today().year, 1, 31),
            'struct_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
        })
        payslip.compute_sheet()
        number_of_attendances = payslip.worked_days_line_ids.filtered(lambda line: line.code == '002.00').number_of_days
        number_of_meal_vouchers = payslip.line_ids.filtered(lambda line: line.salary_rule_id.code == 'MEAL_V_EMP').quantity
        self.assertEqual(number_of_meal_vouchers, number_of_attendances)

        self.employee.version_id.fixed_meal_voucher_days = 30
        payslip.compute_sheet()
        number_of_attendances = payslip.worked_days_line_ids.filtered(lambda line: line.code == '002.00').number_of_days
        number_of_meal_vouchers = payslip.line_ids.filtered(lambda line: line.salary_rule_id.code == 'MEAL_V_EMP').quantity
        self.assertNotEqual(number_of_meal_vouchers, number_of_attendances)
        self.assertEqual(number_of_meal_vouchers, 30)

    def test_company_executive_no_structural_reduction_nor_co2_fee(self):
        """A company director pays no ONSS: no structural reduction on a low remuneration, no CO2 contribution on its
        company car."""
        car = self.env['fleet.vehicle'].create({
            'model_id': self.model_a3.id,
            'license_plate': '1-DIR-999',
            'co2': 110,
            'car_value': 38000,
            'fuel_type': 'diesel',
            'acquisition_date': date(2025, 1, 1),
            'company_id': self.company_id.id,
        })
        self.employee.version_id.write({
            'wage': 900,
            'transport_mode_car': True,
            'car_id': car.id,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
        })
        payslip.compute_sheet()
        self.assertEqual(payslip.vehicle_id, car)
        self.assertFalse(payslip.line_ids.filtered(lambda line: line.code in ('ONSS_STRUCTURAL', 'CO2FEE')))

    def test_withholding_tax_on_custom_non_periodic_rule(self):
        # Withholding tax on non-periodic remuneration is computed on the yearly withholding base
        # Any rule in that category is taxed, not only N_P_BASIC
        monthly_structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        non_periodic_rule = self.env.ref('l10n_be_hr_payroll.l10n_be_monthly_cp999_non_periodic_revenue')
        self.env['hr.salary.rule'].create({
            'name': 'Custom Non-periodic Salary',
            'code': 'CUSTOM_N_P',
            'sequence': non_periodic_rule.sequence,
            'category_ids': [Command.set(non_periodic_rule.category_ids.ids)],
            'condition_select': 'property_input',
            'input_usage_payslip': True,
            'input_usage_employee': False,
            'struct_ids': [Command.link(monthly_structure.id)],
            'country_id': self.env.ref('base.be').id,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': monthly_structure.id,
        })

        def compute_non_periodic_withholding_tax(input_values):
            payslip._set_input_values(input_values)
            payslip.compute_sheet()
            return payslip.line_ids.filtered(lambda line: line.code == 'P.P.NP').total

        tax_on_n_p_basic = compute_non_periodic_withholding_tax({'N_P_BASIC': 6000, 'CUSTOM_N_P': 0})
        # Check for there is non-periodic withholding tax, the value is negative
        self.assertLess(tax_on_n_p_basic, 0)
        # Non-periodic withholding tax amount does not change because it uses category "YEARLY_WITHHOLDING_BASE"
        self.assertAlmostEqual(compute_non_periodic_withholding_tax({'N_P_BASIC': 0, 'CUSTOM_N_P': 6000}), tax_on_n_p_basic, places=2)
        self.assertAlmostEqual(compute_non_periodic_withholding_tax({'N_P_BASIC': 3000, 'CUSTOM_N_P': 3000}), tax_on_n_p_basic, places=2)

    def test_company_executive_no_fiscal_voluntarism(self):
        """Company executives get no FISC_VOL line from a fiscal voluntarism amount"""
        self.ordinary_employee.fiscal_voluntarism_amount = 100
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.ordinary_employee.id,
            'date_from': date(2026, 1, 1),
        })
        payslip.compute_sheet()
        self.assertIn('FISC_VOL', payslip.line_ids.mapped('code'))

        self.ordinary_employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999')
        payslip.compute_sheet()
        self.assertNotIn('FISC_VOL', payslip.line_ids.mapped('code'))

    def test_company_executive_no_starterjob(self):
        """Company executives get no starterjob salary reduction"""
        self.ordinary_employee.write({
            'birthday': date(2006, 1, 1),
            'l10n_be_is_starterjob': True,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.ordinary_employee.id,
            'date_from': date(2026, 1, 1),
        })
        payslip.compute_sheet()
        self.assertTrue(payslip.line_ids.filtered(lambda line: 'STARTERJOB' in line.code or line.code in ('COMPSUPP', 'WITHHOLDING_TAX_EX_274_62')))
        self.assertGreater(payslip._get_starterjob_deduction_rate(), 0)

        self.ordinary_employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999')
        payslip.compute_sheet()
        self.assertFalse(payslip.line_ids.filtered(lambda line: 'STARTERJOB' in line.code or line.code in ('COMPSUPP', 'WITHHOLDING_TAX_EX_274_62')))
        self.assertEqual(payslip._get_starterjob_deduction_rate(), 0)

    def test_company_executive_no_rd_exemption(self):
        """Company executives get no 274.32 withholding tax exemption"""
        self.ordinary_employee.write({
            'certificate': 'doctor',
            'rd_percentage': 1.0,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.ordinary_employee.id,
            'date_from': date(2026, 1, 1),
        })
        payslip.compute_sheet()
        self.assertIn('WITHHOLDING_TAX_EX_274_32', payslip.line_ids.mapped('code'))
        self.assertEqual(self.env['l10n_be.274_xx']._get_valid_274_32_payslips(payslip), payslip)

        self.ordinary_employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999')
        payslip.compute_sheet()
        self.assertNotIn('WITHHOLDING_TAX_EX_274_32', payslip.line_ids.mapped('code'))
        self.assertFalse(self.env['l10n_be.274_xx']._get_valid_274_32_payslips(payslip))

    def test_company_executive_no_aid_zone_exemption(self):
        """Company executives get no 274.81 withholding tax exemption from the aid zone"""
        self.company_id.current_payroll_config_id.write({
            'l10n_be_company_number': '0897223670',
            'l10n_be_revenue_code': '1293',
        })
        # Aid zone employee from January, company executive from February
        self.ordinary_employee.l10n_be_is_aid_zone = True
        self.ordinary_employee.create_version({
            'date_version': date(2026, 2, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
        })
        payslips = self.env['hr.payslip'].create([
            {'employee_id': self.ordinary_employee.id, 'date_from': date(2026, month, 1)} for month in (1, 2)
        ])
        payslips.compute_sheet()
        aid_zone_lines = payslips.line_ids.filtered(lambda line: line.code == 'WITHHOLDING_TAX_EX_274_81')
        self.assertEqual(aid_zone_lines.mapped('slip_id.date_from'), [date(2026, 1, 1)])
        payslips.action_payslip_done()

        # Only January's declares the aid zone exemption
        january, february = self.env['l10n_be.274_xx'].with_company(self.company_id).create([
            {'year': 2026, 'month': month} for month in ('1', '2')
        ])
        self.assertTrue(january.line_274_81_ids)
        self.assertFalse(february.line_274_81_ids)

    def test_company_executive_attendance_based(self):
        """Attendance Based has no effect on company executives"""
        def start_payrun_warnings():
            warnings = self.env['hr.payslip.run']._get_start_payrun_warnings(self.ordinary_employee.version_id, date(2026, 1, 1), date(2026, 1, 31))
            return [warning['title'] for warning in warnings]

        self.ordinary_employee.attendance_based = True
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.ordinary_employee.id,
            'date_from': date(2026, 1, 1),
        })
        payslip.compute_sheet()
        self.assertFalse(payslip.worked_days_line_ids)
        self.assertIn('No Attendance', start_payrun_warnings())

        self.ordinary_employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999')
        payslip.action_refresh_from_work_entries()
        self.assertTrue(self.ordinary_employee.attendance_based)
        self.assertTrue(payslip.worked_days_line_ids)
        self.assertNotIn('No Attendance', start_payrun_warnings())

    def test_company_executive_not_subject_to_onss(self):
        """Company executives get the 000 sub-type (not subject to ONSS), and lose it when they stop being one"""
        not_subject_to_onss = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00000')
        joint_committee_999 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999')
        sub_type = self.ordinary_employee.l10n_be_worker_code_id
        self.assertNotEqual(sub_type, not_subject_to_onss)

        self.ordinary_employee.l10n_be_joint_committee_id = joint_committee_999
        self.assertEqual(self.ordinary_employee.l10n_be_worker_code_id, not_subject_to_onss)

        self.ordinary_employee.l10n_be_joint_committee_id = self.cp200
        self.assertEqual(self.ordinary_employee.l10n_be_worker_code_id, sub_type)

        executive = self.create_employee({'name': 'Executive', 'l10n_be_joint_committee_id': joint_committee_999.id})
        self.assertEqual(executive.l10n_be_worker_code_id, not_subject_to_onss)

    def test_company_executive_no_public_holiday_compensation(self):
        """Company executives get no public holiday compensation, though their sub-type is set"""
        public_holiday = self.env['resource.calendar.leaves'].create({
            'name': 'Public Holiday on Sunday',
            'date_from': datetime(2026, 1, 4),
            'date_to': datetime(2026, 1, 4, 23, 59, 59),
            'company_id': self.company_id.id,
        })
        action = public_holiday.action_open_multi_allocations_wizard()
        wizard = self.env['hr.leave.allocation.generate.multi.wizard'].with_context(**action['context']).create({})
        self.assertIn(self.ordinary_employee, self.env['hr.employee'].search(wizard._get_employee_domain()))

        self.ordinary_employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999')
        self.assertNotIn(self.ordinary_employee, self.env['hr.employee'].search(wizard._get_employee_domain()))
