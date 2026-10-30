from datetime import date

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
        })

    def test_meal_vouchers_company_executive(self):
        self.employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id
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
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
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
        self.employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id
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
