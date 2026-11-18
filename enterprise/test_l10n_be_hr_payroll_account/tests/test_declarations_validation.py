# Part of Odoo. See LICENSE file for full copyright and licensing details.

import datetime
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon
from odoo.tests.common import tagged, freeze_time
from odoo.addons.hr_payroll_account.tests.common import TestPayslipValidationCommon
from odoo.tools.float_utils import float_compare


@tagged('post_install', '-at_install', 'declarations_validation')
class TestDeclarationsValidation(TestPayslipValidationCommon, TestBelgiumCommon):

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    @TestPayslipValidationCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.group_ids |= cls.env.ref('hr.group_hr_manager') | cls.env.ref("hr_payroll.group_hr_payroll_officer")
        cls.company_data['company'].write({
            'vat': 'BE0897223670',
            'phone': '0471098765',
            'street': 'Test street',
            'city': 'Test city',
            'zip': '8292',
        })
        cls.company_data['company'].current_payroll_config_id.write({
            'l10n_be_company_number': '0123456749',
            'l10n_be_revenue_code': '1234',
            'l10n_be_employer_category_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010').id,
        })

        cls.env.user.tz = 'Europe/Brussels'

        cls.EMPLOYEES_COUNT = 5

        cls.resource_calendar_38_hours_per_week = cls.env['resource.calendar'].sudo().create([{
            'name': "Test Calendar : 38 Hours/Week",
            'company_id': cls.env.company.id,
            'hours_per_day': 7.6,
            'hours_per_week': 38.0,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id

            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0),
                ("0", 13.0, 16.6),
                ("1", 8.0, 12.0),
                ("1", 13.0, 16.6),
                ("2", 8.0, 12.0),
                ("2", 13.0, 16.6),
                ("3", 8.0, 12.0),
                ("3", 13.0, 16.6),
                ("4", 8.0, 12.0),
                ("4", 13.0, 16.6),
            ]],
        }])

        cls.work_contacts = cls.env['res.partner'].create([{
            'name': f"Test Work Contact {i}",
        } for i in range(cls.EMPLOYEES_COUNT)])

        brand = cls.env['fleet.vehicle.model.brand'].sudo().create([{
            'name': "Test Brand"
        }])

        model = cls.env['fleet.vehicle.model'].sudo().create([{
            'name': "Test Model",
            'brand_id': brand.id
        }])

        with freeze_time('2020-10-08'):
            cars = cls.env['fleet.vehicle'].sudo().create([{
                'name': f"Test Car {i}",
                'license_plate': f"TEST{i}",
                'driver_id': cls.work_contacts[i].id,
                'company_id': cls.env.company.id,
                'model_id': model.id,
                'contract_date_start': datetime.date(2020, 10, 8),
                'co2': 88.0,
                'car_value': 38000.0,
                'fuel_type': "diesel",
                'acquisition_date': datetime.date(2020, 1, 1)
            } for i in range(cls.EMPLOYEES_COUNT)])

        cls.env['fleet.vehicle.log.contract'].sudo().create([{
            'name': f"Test Contract {i}",
            'vehicle_id': cars[i].id,
            'company_id': cls.env.company.id,
            'start_date': datetime.date(2020, 10, 8),
            'expiration_date': datetime.date(2021, 10, 8),
            'state': "open",
            'cost_generated': 0.0,
            'cost_frequency': "monthly",
            'recurring_cost_amount_depreciated': 450.0
        } for i in range(cls.EMPLOYEES_COUNT)])

        cls.employees = cls.env['hr.employee'].create([{
            'name': f"Test Employee {i}",
            'work_contact_id': cls.work_contacts[i].id,
            'private_street': 'Employee Street %s' % i,
            'private_zip': f'100{i}',
            'private_city': f'Employee City {i}',
            'private_country_id': cls.env.ref('base.be').id,
            'resource_calendar_id': cls.resource_calendar_38_hours_per_week.id,
            'company_id': cls.env.company.id,
            'distance_home_work': 75,
            'certificate': 'master',
            'niss': '91072800%s' % i + str(97 - int('91072800%s' % i) % 97),
            'car_id': cars[i].id,
            'structure_type_id': cls.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': datetime.date(2018, 12, 31),
            'date_version': datetime.date(2018, 12, 31),
            'wage': 2650.0 + i * 100,
            'transport_mode_car': True,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'ip_wage_rate': 0.25,
            'rd_percentage': 1.0,
            'l10n_be_lsa_monthly_misc_base_amount': 150,
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        } for i in range(cls.EMPLOYEES_COUNT)])

        cls.company_executive_employee = cls.env['hr.employee'].create([{
            'name': "Company Executive",
            'private_street': 'Employee Street',
            'private_zip': '100',
            'private_city': 'Employee City',
            'private_country_id': cls.env.ref('base.be').id,
            'resource_calendar_id': cls.resource_calendar_38_hours_per_week.id,
            'company_id': cls.env.company.id,
            'certificate': 'master',
            'niss': '91072800%s' % 5 + str(97 - int('91072800%s' % 5) % 97),
            'structure_type_id': cls.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': datetime.date(2018, 12, 31),
            'date_version': datetime.date(2018, 12, 31),
            'wage': 5000,
            'employee_type_id': cls.env.ref("hr.contract_type_company_executive").id,
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            'lang': 'fr_BE',
        }])

        cls.contracts = cls.employees.version_id

        cls.batch = cls.env['hr.payslip.run'].create({
            'name': 'History Batch',
            'date_start': datetime.date(2021, 1, 1),
            'date_end': datetime.date(2021, 12, 31),
            'company_id': cls.env.company.id,
            'structure_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
        })

        # Janvier 2021: Salary + Commissions
        # Février 2021: Salary
        # Mars 2021: Salary (10 unpaid days)
        # Avril 2021: Salary + Warrants (2 payslips)
        # Mai 2021: Salary (20 legal days)
        # Juin 2021: Salary + Double Holiday Pay (2 payslips)
        # Juillet 2021: Salary + Commissions
        # Aout 2021: Salary
        # Septembre 2021: Salary
        # Octobre 2021: Salary + Commissions
        # Novembre 2021: Salary
        # Décembre 2021: Salary (recup de decembre) + 13eme mois (2 payslips)
        cls.journal = cls.env['account.journal'].search([('type', '=', 'general')], limit=1)

        # Janvier 2021: Salary + Commissions
        cls.january_2021 = cls.env['hr.payslip'].create([{
            'name': f'Payslip Jan 2021 {i}',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 1, 1),
            'date_to': datetime.datetime(2021, 1, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])
        for payslip in cls.january_2021:
            payslip._set_input_value('COMMISSION', 2000)

        # Février 2021: Salary
        cls.february_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Feb 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 2, 1),
            'date_to': datetime.datetime(2021, 2, 28),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        # Mars 2021: Salary (10 unpaid days)
        cls.march_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Mar 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 3, 1),
            'date_to': datetime.datetime(2021, 3, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        # Avril 2021: Salary + Warrants (2 payslips)
        cls.april_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Apr 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 4, 1),
            'date_to': datetime.datetime(2021, 4, 30),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        cls.warrant_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Warrant 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 4, 1),
            'date_to': datetime.datetime(2021, 4, 30),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])
        for payslip in cls.warrant_2021:
            payslip._set_input_value('WARRANT_WITHOUT_ONSS', 2000)

        # Mai 2021: Salary (20 legal days)
        cls.may_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip May 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 5, 1),
            'date_to': datetime.datetime(2021, 5, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        # Juin 2021: Salary + Double Holiday Pay (2 payslips)
        cls.june_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Jun 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 6, 1),
            'date_to': datetime.datetime(2021, 6, 30),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        cls.double_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Double 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 6, 1),
            'date_to': datetime.datetime(2021, 6, 30),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        # Juillet 2021: Salary + Commissions
        cls.july_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Jul 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 7, 1),
            'date_to': datetime.datetime(2021, 7, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])
        for payslip in cls.july_2021:
            payslip._set_input_value('COMMISSION', 2000)

        # Aout 2021: Salary
        cls.august_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Aug 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 8, 1),
            'date_to': datetime.datetime(2021, 8, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        # Septembre 2021: Salary
        cls.september_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Sep 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 9, 1),
            'date_to': datetime.datetime(2021, 9, 30),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        # Octobre 2021: Salary + Commissions
        cls.october_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Oct 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 10, 1),
            'date_to': datetime.datetime(2021, 10, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])
        for payslip in cls.october_2021:
            payslip._set_input_value('COMMISSION', 2000)

        # Novembre 2021: Salary
        cls.november_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Nov 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 11, 1),
            'date_to': datetime.datetime(2021, 11, 30),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        # Décembre 2021: Salary + 13eme mois (2 payslips)
        cls.december_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Dec 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 12, 1),
            'date_to': datetime.datetime(2021, 12, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])
        for payslip in cls.december_2021:
            payslip._set_input_values({
                'SIMPLE_DECEMBER': 150,
                'DOUBLE_DECEMBER_BASIC': 100,
            })
            payslip.compute_sheet()

        cls.thirteen_2021 = cls.env['hr.payslip'].create([{
            'name': 'Payslip Thirteen Month 2021',
            'version_id': cls.contracts[i].id,
            'date_from': datetime.datetime(2021, 12, 1),
            'date_to': datetime.datetime(2021, 12, 31),
            'employee_id': cls.employees[i].id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        } for i in range(cls.EMPLOYEES_COUNT)])

        cls.company_executive_payslips = cls.env['hr.payslip'].create([{
            'name': f'Payslip CE {i}',
            'date_from': datetime.datetime(2025, i, 1),
            'date_to': datetime.datetime(2025, i, 1) + relativedelta(day=31),
            'employee_id': cls.company_executive_employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
        } for i in range(1, 13)])

        all_payslips = cls.january_2021 + cls.february_2021 + cls.march_2021 + cls.april_2021 + \
                       cls.warrant_2021 + cls.may_2021 + cls.june_2021 + cls.double_2021 + \
                       cls.july_2021 + cls.august_2021 + cls.september_2021 + cls.october_2021 + \
                       cls.november_2021 + cls.december_2021 + cls.thirteen_2021 + cls.company_executive_payslips
        all_payslips.action_refresh_from_work_entries()
        # Clear review state before validation (simulates payroll officer approval)
        cls.employees.write({'review_state': '1_reviewed'})
        all_payslips.action_payslip_done()

        # Activate the benefit
        cls.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_misc_base_amount')]).active = True

        cls.exemption_rate = cls.env['hr.rule.parameter']._get_parameter_from_code('l10n_be_extra_hours_exemption_rate', raise_if_not_found=True)
        cls.extra_hours_employee = cls.env['hr.employee'].create({
            'name': 'Extra Normal',
            'company_id': cls.env.company.id,
            'contract_date_start': datetime.date(2026, 1, 1),
            'date_version': datetime.date(2026, 1, 1),
            'hourly_wage': 30,
            'wage_type': 'hourly',
            'lang': 'fr_BE',
        })
        cls.volo150_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_voluntary_overtime_150')
        cls.volo200_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_voluntary_overtime_200')
        cls.overtime_type = cls.env.ref('hr_work_entry.be_work_entry_type_overtime')
        cls.overtime_type.write({
            'requires_allocation': False,
            'is_extra_hours': True,
            'amount_rate': 1.5,
        })
        cls.be_attendance_type = cls.env.ref('hr_work_entry.be_work_entry_type_attendance')

    def validate_results(self, declaration, results):
        fields_to_validate = [
            'pp_amount_10',
            'pp_amount_13',
            'pp_amount_18',
            'pp_amount_20',
            'pp_amount_30',
            'pp_amount_32',
            'pp_amount_33',
            'pp_amount_34',
            'pp_amount_44',
            'pp_amount_55',
            'taxable_amount_10',
            'taxable_amount_13',
            'taxable_amount_18',
            'taxable_amount_20',
            'taxable_amount_30',
            'taxable_amount_32',
            'taxable_amount_33',
            'taxable_amount_34',
            'taxable_amount_44',
            'taxable_amount_55',
            'deducted_amount',
            'deducted_amount_32',
            'deducted_amount_33',
            'deducted_amount_34',
            'deducted_amount_44',
            'deducted_amount_55',
            'capped_amount_34',
        ]
        error = []
        for field_name in fields_to_validate:
            declaration_value = declaration[field_name]
            if field_name not in results:
                error.append("Missing Checked Line: '%s' - %s," % (field_name, declaration_value))
                continue
            value = results[field_name]
            if float_compare(declaration_value, value, 2):
                error.append("Code: %s - Expected: %s - Reality: %s" % (field_name, value, declaration_value))
        if error:
            error.append("Declaration Actual Values: ")
            error.append("{")
            for field_name in fields_to_validate:
                error.append("    '%s': %s," % (field_name, declaration[field_name]))
            error.append("}")
        self.assertEqual(len(error), 0, '\n' + '\n'.join(error))

    def _validate_281_report(self, actual_report, expected_report):
        """
        Check the totals of reports against the expected results.
        """
        error = []
        for code, value in expected_report.items():
            if code not in actual_report:
                error.append(f"{'FIELD NOT COMPUTED':>20} │ {code:<50} │ {value:>15} |")
            elif actual_report[code] != value:
                error.append(f"{'WRONG CALCULATION':>20} │ {code:<50} │ {value:>15} │ {actual_report[code]:>15} |")
        for code, value in actual_report.items():
            if code not in expected_report:
                error.append(f"{'MISSING FIELD':>20} │ {code:<50} │ {'/':>15} │")
        if error:
            error.insert(
                0,
                f"{'ERROR':>20} │ {'CODE':<50} │ {'EXPECTED':>15} │ {'REALITY':>15} │\n"
                f"{'':>20} │ {'':<50} │ {'':>15} │ {'':>15} │")
            error.append("Report Actual Values: ")
            error.append("        actual_report = {")
            error.extend(f"            '{code}': {value}," for code, value in actual_report.items())
            error.append("        }")
        self.assertEqual(len(error), 0, '\n\n' + '\n'.join(error))
        return expected_report

    def test_274_declaration(self):
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '1',
        })
        declaration_results = {
            'pp_amount_10': 5749.46,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 5749.46,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 18789.87,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 18789.87,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 4599.56,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 4599.56,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }
        self.validate_results(declaration, declaration_results)

    def test_274_declaration_account_entries(self):
        # The withholding tax exemptions booked by the payslips (their exemption total rule has accounts) are not
        # booked again by the declaration, which books what the payslips could not
        declaration = self.env['l10n_be.274_xx'].create({'year': 2021, 'month': '1'})
        exemption_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_274_exemption_total')
        withholding_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_withholding_taxes_total')
        withholding_account = self.env['account.account'].create({
            'name': 'Taxes Withheld', 'code': '453999', 'account_type': 'liability_current'})
        exemption_account = self.env['account.account'].create({
            'name': 'Withholding Taxes Exemptions', 'code': '620299', 'account_type': 'expense'})
        withholding_rule.account_credit = withholding_account
        self.env.company.exemption_journal_id = self.journal
        self.journal.default_account_id = exemption_account

        # Payslips without accounts on their exemptions: the declaration books all of them (on the default account of
        # its journal), against the withholding taxes the payslips credited in full
        exemption_rule.write({'account_debit': False, 'account_credit': False})
        self.assertEqual(declaration._get_exemptions_to_book(), {'274.33': 4599.56})
        declaration.action_post_account_entries()
        move_lines = declaration.move_id.line_ids
        self.assertEqual(sum(move_lines.filtered(lambda l: l.account_id == withholding_account).mapped('balance')), 4599.56)
        self.assertEqual(sum(move_lines.filtered(lambda l: l.account_id == exemption_account).mapped('balance')), -4599.56)

        # Payslips booking their exemptions (debit of the withholding taxes, credit of the exemptions): nothing left
        exemption_rule.write({'account_debit': withholding_account.id, 'account_credit': exemption_account.id})
        self.assertEqual(declaration._get_exemptions_to_book(), {})
        payslip = self.january_2021[0].copy()
        payslip.compute_sheet()
        payslip.action_payslip_done()
        payslip.move_id.action_post()
        exemption = payslip.line_ids.filtered(lambda l: l.code == 'WITHHOLDING_TAX_EX_TOT').total
        self.assertTrue(exemption)
        payslip_lines = payslip.move_id.line_ids
        self.assertAlmostEqual(sum(payslip_lines.filtered(lambda l: l.account_id == exemption_account).mapped('balance')), -exemption)

    def test_274_56_base_without_cct90_bonus(self):
        # The CCT 90 bonus is exempted from the withholding tax: neither it nor its ONSS is in the base of the 0.12 %
        # exemption (274.56)
        employee = self.employees[0]
        payslip = self.env['hr.payslip'].create({
            'name': 'CCT90',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90').id,
            'date_from': datetime.date(2025, 5, 1),
            'date_to': datetime.date(2025, 5, 31),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })
        payslip._set_input_value('CCT90BONUSPLAN', 3496)
        payslip.compute_sheet()
        self.assertTrue(payslip.line_ids.filtered(lambda line: line.code == 'BONUS_SALARY').total)
        declaration = self.env['l10n_be.274_xx'].create({'year': 2025, 'month': '5'})
        taxable, exemption = declaration._get_274_56_values(payslip)[employee]
        self.assertEqual((taxable, exemption), (0.0, 0.0))

    def test_274_declaration_warrant(self):
        # Check warrants are included, in the research exemption too
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '4',
        })
        declaration_results = {
            'pp_amount_10': 2412.92,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 2412.92,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 11872.12,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 11872.12,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 1930.34,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 1930.34,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }
        self.validate_results(declaration, declaration_results)

    def test_274_declaration_cap(self):
        # Check bachelors are capped based on other employees
        self.employees[:3].write({'certificate': 'bachelor'})
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '1',
        })
        declaration_results = {
            'pp_amount_10': 5749.46,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 2393.68,
            'pp_amount_34': 3355.78,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 18789.87,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 7711.54,
            'taxable_amount_34': 11078.33,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 2393.68,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 1914.94,
            'deducted_amount_34': 2684.62,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 478.74,
        }
        self.validate_results(declaration, declaration_results)

    def test_274_declaration_december(self):
        # Check december pay recuperation
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '12',
        })
        declaration_results = {
            'pp_amount_10': 7825.62,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 7825.62,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 23575.92,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 23575.92,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 6260.51,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 6260.51,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        self.validate_results(declaration, declaration_results)

    def test_274_rd_exemption_DHP(self):
        emp_rd = self.employees[0]
        emp_rd.contract_date_end = datetime.date(2021, 12, 31)
        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'date_version': datetime.date(2022, 1, 1),
            'contract_date_start': datetime.date(2022, 1, 1),
            'contract_date_end': datetime.date(2022, 6, 30),
            'wage': 3500.0,
            'rd_percentage': 0.2,
        })
        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'date_version': datetime.date(2022, 7, 1),
            'contract_date_start': datetime.date(2022, 7, 1),
            'contract_date_end': datetime.date(2022, 12, 31),
            'wage': 3500.0,
            'rd_percentage': 0.8,
        })
        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'contract_date_start': datetime.date(2023, 1, 1),
            'wage': 3500.0,
            'rd_percentage': 1.0,
        })

        dhp_payslip = self.env['hr.payslip'].create({
            'name': 'R&D DHP Payslip Jun 2023',
            'version_id': emp_rd.version_id.id,
            'date_from': datetime.datetime(2023, 6, 1),
            'date_to': datetime.datetime(2023, 6, 30),
            'employee_id': emp_rd.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': self.env.company.id,
        })
        self.assertAlmostEqual(emp_rd._get_average_rd_percentage("BEDOUBLE", datetime.datetime(2023, 6, 1)), 0.502, 3)

        dhp_payslip.compute_sheet()
        dhp_payslip.action_payslip_done()

        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2023,
            'month': '6',
        })

        expected_declaration_results = {
            'pp_amount_10': 1200.13,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 1200.13,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 2831.17,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 2831.17,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 482.42,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 482.42,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        self.validate_results(declaration, expected_declaration_results)

    def test_274_rd_exemption_13_months(self):
        emp_rd = self.employees[0]
        emp_rd.contract_date_end = datetime.date(2021, 12, 31)

        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'date_version': datetime.date(2022, 1, 1),
            'contract_date_start': datetime.date(2022, 1, 1),
            'contract_date_end': datetime.date(2022, 6, 30),
            'wage': 3500.0,
            'rd_percentage': 0.4,
        })
        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'date_version': datetime.date(2022, 7, 1),
            'contract_date_start': datetime.date(2022, 7, 1),
            'contract_date_end': datetime.date(2022, 12, 31),
            'wage': 3500.0,
            'rd_percentage': 1.0,
        })

        thirteen_payslip = self.env['hr.payslip'].create({
            'name': 'R&D 13th Month Payslip Dec 2022',
            'version_id': emp_rd.version_id.id,
            'date_from': datetime.datetime(2022, 12, 1),
            'date_to': datetime.datetime(2022, 12, 31),
            'employee_id': emp_rd.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
            'company_id': self.env.company.id,
        })

        structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month')
        self.assertAlmostEqual(emp_rd._get_average_rd_percentage(structure.code, datetime.date(2022, 12, 1)), 0.702, 3)

        thirteen_payslip.compute_sheet()
        thirteen_payslip.action_payslip_done()

        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2022,
            'month': '12',
        })

        expected_declaration_results = {
            'pp_amount_10': 1412.96,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 1412.96,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 3042.55,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 3042.55,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 794.04,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 794.04,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        self.validate_results(declaration, expected_declaration_results)

    def test_274_rd_exemption_term_holidays(self):
        emp_rd = self.env['hr.employee'].create({
            'name': "R&D Employee",
            'work_contact_id': self.work_contacts[1].id,
            'private_street': 'foo',
            'private_zip': '100',
            'private_country_id': self.env.ref('base.be').id,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'distance_home_work': 75,
            'certificate': 'master',
            'niss': '85073003328',
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': datetime.date(2020, 1, 1),
            'date_version': datetime.date(2020, 1, 1),
            'wage': 5000,
            'rd_percentage': 0.7,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })

        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'date_version': datetime.date(2020, 6, 1),
            'wage': 5000.0,
            'rd_percentage': 0.5,
        })

        self.env['hr.leave.allocation'].create({
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id,
            'number_of_days': 20,
            'employee_id': emp_rd.id,
            'date_from': datetime.date(2021, 1, 1),
            'date_to': datetime.date(2021, 12, 31),
        }).action_approve()

        departure = self.env['hr.employee.departure'].create({
            'employee_id': emp_rd.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.datetime(2021, 9, 1),
            'l10n_be_notice_respect': 'without'
        })
        departure._generate_termination_holidays()

        struct_n_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')
        struct_n1_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays')

        self.assertAlmostEqual(emp_rd._get_average_rd_percentage(struct_n_id.code, datetime.datetime(2021, 9, 1)), 0.5, 3)
        self.assertAlmostEqual(emp_rd._get_average_rd_percentage(struct_n1_id.code, datetime.datetime(2021, 9, 1)), 0.583, 3)

        departure_payslip_n = self.env['hr.payslip'].search([
            ('employee_id', '=', emp_rd.id),
            ('struct_id', '=', struct_n_id.id),
        ])
        departure_payslip_n1 = self.env['hr.payslip'].search([
            ('employee_id', '=', emp_rd.id),
            ('struct_id', '=', struct_n1_id.id),
        ])

        departure_payslip_n.compute_sheet()
        departure_payslip_n1.compute_sheet()
        departure_payslip_n.action_payslip_done()
        departure_payslip_n1.action_payslip_done()

        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '9',
        })

        expected_declaration_results = {
            'pp_amount_10': 2478.24,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 2478.24,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 11758.44,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 11758.44,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 1681.86,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 1681.86,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        self.validate_results(declaration, expected_declaration_results)

    def test_274_rd_exemption_term_fees(self):
        emp_rd = self.employees[0]
        emp_rd.contract_date_end = datetime.date(2021, 12, 31)

        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'date_version': datetime.date(2022, 1, 1),
            'contract_date_start': datetime.date(2022, 1, 1),
            'contract_date_end': datetime.date(2022, 3, 31),
            'wage': 3500.0,
            'rd_percentage': 0.2,
        })
        self.env['hr.version'].create({
            'employee_id': emp_rd.id,
            'date_version': datetime.date(2022, 4, 1),
            'contract_date_start': datetime.date(2022, 4, 1),
            'wage': 3500.0,
            'rd_percentage': 0.8,
        })
        departure = self.env['hr.employee.departure'].create({
            'employee_id': emp_rd.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.datetime(2022, 9, 1),
            'l10n_be_notice_respect': 'without'
        })
        departure._generate_termination_payslip()

        structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        term_payslip = self.env['hr.payslip'].search([
            ('employee_id', '=', emp_rd.id),
            ('struct_id', '=', structure.id),
        ])
        # the twelve months before the departure (02/09/2021 - 01/09/2022)
        self.assertAlmostEqual(emp_rd._get_average_rd_percentage(structure.code, datetime.date(2022, 9, 1)), 0.718, 3)

        term_payslip.compute_sheet()
        term_payslip.action_payslip_done()

        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2022,
            'month': '9',
        })

        expected_declaration_results = {
            'pp_amount_10': 1326.78,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 1326.78,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 11089.4,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 11089.4,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 762.48,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 762.48,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        self.validate_results(declaration, expected_declaration_results)

    def test_274_56_base_with_termination_fees(self):
        # The base of the 0.12 % exemption holds the termination indemnities: the gross amounts of the termination
        # fees payslip, without the ONSS
        employee = self.employees[0]
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.datetime(2022, 9, 1),
            'l10n_be_notice_respect': 'without'
        })
        departure._generate_termination_payslip()
        structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        term_payslip = self.env['hr.payslip'].search([('employee_id', '=', employee.id), ('struct_id', '=', structure.id)])
        term_payslip.compute_sheet()
        term_payslip.action_payslip_done()
        indemnities = term_payslip.line_ids.filtered(
            lambda line: 'TERMINATION_WITHHOLDING_BASE' in line.salary_rule_id.category_ids.mapped('code')
            and line.code != 'ONSS_TERM')
        self.assertTrue(indemnities.filtered(lambda line: line.code == 'TOTALFEES').total)

        declaration = self.env['l10n_be.274_xx'].create({'year': 2022, 'month': '9'})
        self.assertEqual(declaration.payslip_ids, term_payslip)
        line_274_56 = declaration.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, sum(indemnities.mapped('total')), places=2)

    def test_274_declaration_export(self):
        # Check exported data are the same than the computed fields
        def _to_eurocent(amount):
            return '%s' % int(amount * 100)

        self.employees[:3].write({'certificate': 'bachelor'})
        self.employees[3].write({'certificate': 'doctor'})

        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '1',
        })
        declaration_results = {
            'pp_amount_10': 5749.46,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 1178.78,
            'pp_amount_33': 1214.9,
            'pp_amount_34': 3355.78,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 18789.87,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 3823.17,
            'taxable_amount_33': 3888.37,
            'taxable_amount_34': 11078.33,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 2393.68,
            'deducted_amount_32': 943.02,
            'deducted_amount_33': 971.92,
            'deducted_amount_34': 2684.62,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 478.74,
        }
        self.validate_results(declaration, declaration_results)

        declaration_data = declaration._get_rendering_data()
        for data in declaration_data['declarations']:
            declaration_type = data['revenue_nature']
            suffix = '_%s' % (declaration_type)

            xml_taxable = data['taxable_revenue']
            if declaration_type == 56:
                field_taxable = declaration.sme_taxable_amount
            elif declaration_type in (60, 61):
                field_taxable = declaration.startup_taxable_amount
            else:
                field_taxable = declaration['taxable_amount' + suffix]
            self.assertEqual(xml_taxable, _to_eurocent(field_taxable))

            xml_pp = data['prepayment']
            if declaration_type in [10, 13, 18, 20, 30]:
                field_pp = declaration['pp_amount' + suffix]
                self.assertEqual(xml_pp, _to_eurocent(field_pp))
            elif declaration_type == 34:
                field_pp = -declaration.capped_amount_34
                self.assertTrue(int(xml_pp) / 100.0 - field_pp <= 0.01)
            elif declaration_type == 56:
                field_pp = -declaration.sme_exempted_amount
                self.assertEqual(xml_pp, _to_eurocent(field_pp))
            elif declaration_type in (60, 61):
                field_pp = -declaration.startup_exempted_amount
                self.assertEqual(xml_pp, _to_eurocent(field_pp))
            else:
                field_pp = -declaration['deducted_amount' + suffix]
                self.assertEqual(xml_pp, _to_eurocent(field_pp))

    def test_declarations_equivalence(self):
        # Check that the sum of all the 274.10 sheets over the year = 281.10
        declarations_274 = self.env['l10n_be.274_xx'].create([{
            'year': 2021,
            'month': str(i),
        } for i in range(1, 13)])
        total_declared_pp = sum(declarations_274.mapped('pp_amount_10'))

        declaration_281_xx = self.env['l10n_be.281_xx'].create({
            'year': '2021',
        })
        declaration_281 = declaration_281_xx.l10n_be_281_10_ids
        data_281 = declaration_281._get_rendering_data(self.employees)
        declared_pp = data_281['sum_withholding']
        self.assertAlmostEqual(total_declared_pp, declared_pp, places=2)

    def test_281_10_comeback(self):
        # Check that we use the old first_version_date instead of
        # the new one
        self.assertEqual(self.employees[0]._get_first_version_date(), datetime.date(2018, 12, 31))
        self.contracts[0].write({
            'contract_date_end': datetime.date(2021, 12, 31),
        })
        self.contracts[0].copy({
            'name': "New Contract For Payslip Test 0",
            'date_version': datetime.date(2022, 3, 1),
            'contract_date_start': datetime.date(2022, 3, 1),
            'contract_date_end': False,
        })
        self.assertEqual(self.employees[0]._get_first_version_date(), datetime.date(2022, 3, 1))
        declaration_281_xx = self.env['l10n_be.281_xx'].create({
            'year': '2021',
        })
        declaration_281 = declaration_281_xx.l10n_be_281_10_ids
        data_281 = declaration_281._get_rendering_data(self.employees)

        for employee_data in data_281['employees_data']:
            if employee_data['f2011_nationaalnr'] == self.employees[0].niss:
                # Employed since 2018: no entry date in 2021, and not the one of the comeback in 2022
                self.assertEqual(employee_data['f10_2055_datumvanindienstt'], '')

    def test_281_10_departure(self):
        departure_notice = self.env['hr.employee.departure'].create({
            'employee_id': self.employees[0].id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.date(2021, 12, 30),
            'l10n_be_notice_respect': 'without',
            'departure_description': 'foo',
            'action_date': datetime.date(2021, 12, 31),
        })
        departure_notice.action_register()
        departure_payslips = departure_notice._generate_termination_payslip()
        departure_payslips += departure_notice._generate_termination_holidays()

        # Termination Fees
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees = departure_payslips.filtered(lambda dep: dep.struct_id == struct_id)
        termination_fees.compute_sheet()
        termination_fees.employee_id.write({'review_state': '1_reviewed'})
        termination_fees.action_payslip_done()

        # Holiday Attests
        holiday_pays = departure_payslips - termination_fees
        holiday_pays.employee_id.write({'review_state': '1_reviewed'})
        holiday_pays.action_payslip_done()

        # 281.10 Declaration
        declaration_281_xx = self.env['l10n_be.281_xx'].create({
            'year': '2021',
        })
        declaration_281 = declaration_281_xx.l10n_be_281_10_ids
        data_281 = declaration_281._get_rendering_data(self.employees)
        for employee_data in data_281['employees_data']:
            if employee_data['f2011_nationaalnr'] == self.employees[0].niss:
                self.assertEqual(
                    employee_data['f10_2063_vervroegdvakantieg'],
                    holiday_pays._get_line_values(['HOLIDAY_TERM_GROSS'], compute_sum=True)['HOLIDAY_TERM_GROSS']['sum']['total'])
                self.assertEqual(
                    employee_data['f10_2065_opzeggingsreclasseringsverg'],
                    termination_fees._get_line_values(['TERM_GROSS'], compute_sum=True)['TERM_GROSS']['sum']['total'])

    def test_notice_duration_fired(self):
        self.contracts[0].contract_date_start = datetime.date(2014, 1, 1)
        departure_notice = self.env['hr.employee.departure'].create({
            'employee_id': self.employees[0].id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.date(2044, 6, 1),
            'l10n_be_notice_respect': 'with',
            'departure_description': 'foo',
        })

        self.assertEqual(departure_notice.l10n_be_notice_period_start, datetime.date(2044, 6, 6))
        # Seniority is 30 years and 5 months
        # Duration should be 72 weeks
        self.assertEqual(departure_notice.departure_date, datetime.date(2045, 10, 22))

    def test_startup_exemption_calculation(self):
        self.company_data['company'].current_payroll_config_id.exemption_sme_status = 'startup'
        self.company_data['company'].write({
            'l10n_be_cbe_inscription': datetime.date(2020, 1, 1)
        })
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '1',
        })

        # an exemption of each worker, rounded to the cent
        startup_lines = declaration.line_ids.filtered(lambda line: line.nature_code == '274.60')
        self.assertAlmostEqual(
            sum(startup_lines.mapped('withholding_amount')), declaration.pp_amount_10 + declaration.pp_amount_18, places=2)
        for line in startup_lines:
            self.assertAlmostEqual(line.amount, round(line.withholding_amount * 0.10, 2), places=2)
        self.assertAlmostEqual(declaration.startup_exempted_amount, sum(startup_lines.mapped('amount')), places=2)

        data = declaration._get_rendering_data()
        revenues = [d['revenue_nature'] for d in data['declarations']]
        self.assertIn(60, revenues, "Revenue nature 60 (Startup) must be present in XML data")

    def test_micro_enterprise_exemption_calculation(self):
        self.company_data['company'].current_payroll_config_id.exemption_sme_status = 'micro'
        self.company_data['company'].write({
            'l10n_be_cbe_inscription': datetime.date(2020, 1, 1)
        })
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '1',
        })

        # an exemption of each worker, rounded to the cent
        startup_lines = declaration.line_ids.filtered(lambda line: line.nature_code == '274.61')
        self.assertAlmostEqual(
            sum(startup_lines.mapped('withholding_amount')), declaration.pp_amount_10 + declaration.pp_amount_18, places=2)
        for line in startup_lines:
            self.assertAlmostEqual(line.amount, round(line.withholding_amount * 0.20, 2), places=2)
        self.assertAlmostEqual(declaration.startup_exempted_amount, sum(startup_lines.mapped('amount')), places=2)

        data = declaration._get_rendering_data()
        revenues = [d['revenue_nature'] for d in data['declarations']]
        self.assertIn(61, revenues, "Revenue nature 61 (Micro-enterprise) must be present in XML data")

    def test_startup_exemption_expired(self):
        self.company_data['company'].current_payroll_config_id.exemption_sme_status = 'startup'
        self.company_data['company'].write({
            'l10n_be_cbe_inscription': datetime.date(2010, 1, 1)
        })
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '1',
        })

        self.assertTrue(declaration.is_cbe_expired)
        self.assertEqual(declaration.startup_exempted_amount, 0.0, "Exempted amount must be 0 after 48 months")
        self.assertEqual(declaration.startup_amount_to_pay, 0.0)

        data = declaration._get_rendering_data()
        revenues = [d['revenue_nature'] for d in data['declarations']]
        self.assertNotIn(60, revenues)
        self.assertNotIn(61, revenues)

    @freeze_time('2026-11-05')
    def test_startup_exemption_quarterly_declaration(self):
        # The 48 months are counted up to the declared quarter, not up to the current month
        company = self.company_data['company']
        company.current_payroll_config_id.write({
            'exemption_sme_status': 'startup',
            'l10n_be_declaration_frequency': 'quarterly',
        })
        company.l10n_be_cbe_inscription = datetime.date(2022, 3, 15)  # Exemption until March 2026
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2026,
            'quarter': '1',
        })
        self.assertEqual(declaration.declaration_frequency, 'quarterly')
        self.assertEqual(declaration.date_start, datetime.date(2026, 1, 1))
        self.assertFalse(declaration.is_cbe_expired)
        declaration.quarter = '2'
        self.assertTrue(declaration.is_cbe_expired)

    def test_startup_exemption_48_months_from_inscription_month(self):
        # The 48 months start with the month of the inscription when it is on the 1st, else with the next month
        company = self.company_data['company']
        company.current_payroll_config_id.exemption_sme_status = 'startup'
        for inscription_date, last_month in (
            (datetime.date(2022, 3, 1), datetime.date(2026, 2, 1)),
            (datetime.date(2022, 3, 15), datetime.date(2026, 3, 1)),
        ):
            with self.subTest(inscription_date=inscription_date):
                company.l10n_be_cbe_inscription = inscription_date
                declarations = self.env['l10n_be.274_xx'].create([
                    {'year': month.year, 'month': str(month.month)}
                    for month in (last_month, last_month + relativedelta(months=1))
                ])
                self.assertEqual(declarations.mapped('is_cbe_expired'), [False, True])

    def test_no_exemption_when_no_status_configured(self):
        self.company_data['company'].current_payroll_config_id.exemption_sme_status = False
        self.company_data['company'].write({
            'l10n_be_cbe_inscription': datetime.date(2020, 1, 1)
        })
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2021,
            'month': '1',
        })

        self.assertFalse(declaration.is_cbe_expired, "Company should be active (under 48 months)")
        self.assertEqual(declaration.startup_exempted_amount, 0.0, "Exempted amount must be 0 if no status is set")
        self.assertEqual(declaration.startup_amount_to_pay, 0.0)

        data = declaration._get_rendering_data()
        revenues = [d['revenue_nature'] for d in data['declarations']]
        self.assertNotIn(60, revenues, "Nature 60 should not be present without startup status")
        self.assertNotIn(61, revenues, "Nature 61 should not be present without micro status")

    def test_company_executive_declaration(self):
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2025,
            'month': '1',
        })
        declaration_results = {
            'pp_amount_10': 0.0,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 1209.5,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 0.0,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 0.0,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 5000.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 0.0,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 0.0,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 0.0,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }
        self.validate_results(declaration, declaration_results)

    def test_13_declarations(self):
        unemployment_calendar = self.env['resource.calendar'].sudo().create([{
            'name': "Test Calendar : Economic Unemployment Partial",
            'company_id': self.env.company.id,
            'hours_per_day': 7.6,
            'hours_per_week': 38.0,
            'days_per_week': 5.0,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0),
                ("0", 13.0, 16.6),
                ("1", 8.0, 12.0),
                ("1", 13.0, 16.6),
                ("2", 8.0, 12.0),
                ("2", 13.0, 16.6),
            ]] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id
            }) for dayofweek, hour_from, hour_to in [
                ("3", 8.0, 12.0),
                ("3", 13.0, 16.6),
                ("4", 8.0, 12.0),
                ("4", 13.0, 16.6),
            ]],
        }])
        unemployment_employee = self.env['hr.employee'].create([{
            'name': "unemployment employee",
            'private_street': 'Employee Street',
            'private_zip': '100',
            'private_city': 'Employee City',
            'private_country_id': self.env.ref('base.be').id,
            'resource_calendar_id': unemployment_calendar.id,
            'company_id': self.env.company.id,
            'niss': '85073003328',
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': datetime.date(2025, 12, 31),
            'date_version': datetime.date(2025, 12, 31),
            'wage': 5000,
            'lang': 'fr_BE',
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        }])
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip Unemployment {i}',
            'date_from': datetime.datetime(2026, i, 1),
            'date_to': datetime.datetime(2026, i, 1) + relativedelta(day=31),
            'employee_id': unemployment_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
            # 'journal_id': self.journal.id,
        } for i in range(1, 13)])

        for p in payslips:
            p._set_input_value('EUC_CP200', 5)
        payslips.compute_sheet()
        payslips.action_payslip_done()

        unemployment_days = sum(p.worked_days_line_ids.filtered(lambda l: l.work_entry_type_id.l10n_be_economic_unemployment).number_of_days for p in payslips)
        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2026,
            'month': '1',
        })
        declaration_results = {
            'pp_amount_10': 169.61,
            'pp_amount_13': 16.05,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 0.0,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 2006.07,
            'taxable_amount_13': 60.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 0.0,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 0.0,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 0.0,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }
        self.validate_results(declaration, declaration_results)

        declaration = self.env['l10n_be.281_xx'].create({
            'year': 2026,
        })
        declaration = declaration.l10n_be_281_13_ids
        data_281 = declaration._get_rendering_data(unemployment_employee)
        self.assertIn(unemployment_employee.niss, {emp_data['f2011_nationaalnr'] for emp_data in data_281['employees_data']})
        for employee_data in data_281['employees_data']:
            if employee_data['f2011_nationaalnr'] == unemployment_employee.niss:
                self.assertAlmostEqual(employee_data['f13_2060_bedrag'], 780)  # allocations
                self.assertAlmostEqual(employee_data['f13_2078_bedrijfsvoorheffing'], 208.68)  # tax
                self.assertAlmostEqual(employee_data['f13_2089_werkloosheidzonder'], unemployment_days)  # number of days

    def _run_extra_hours_payslip(self, name, rule_vals_list, attendance_periods, date_from, date_to):
        employee_domain = f"[('id', '=', {self.extra_hours_employee.id})]"
        rules = self.env['hr.time.rule'].sudo().create([
            dict(rule_vals, employee_domain=employee_domain)
            for rule_vals in rule_vals_list
        ])
        # attendance_periods is a list of (check_in, check_out) pairs in the employee's
        # local timezone.
        tz = ZoneInfo(self.extra_hours_employee.sudo()._get_tz())
        for check_in_local, check_out_local in attendance_periods:
            check_in = check_in_local.replace(tzinfo=tz).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
            check_out = check_out_local.replace(tzinfo=tz).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
            self.env['hr.attendance'].sudo().create({
                'employee_id': self.extra_hours_employee.id,
                'check_in': check_in,
                'check_out': check_out,
            })
        payslip = self.env['hr.payslip'].create([{
            'name': name,
            'version_id': self.extra_hours_employee.version_id.id,
            'date_from': date_from,
            'date_to': date_to,
            'employee_id': self.extra_hours_employee.id,
            'company_id': self.env.company.id,
        }])
        payslip.compute_sheet()
        payslip.action_payslip_done()
        return payslip, rules

    def test_extra_hours_44_CP_200(self):
        self.env.ref('l10n_be_hr_payroll.l10n_be_time_rule_sunday').sudo().write({'active': False})

        self.extra_hours_employee.l10n_be_joint_committee_id = self.env.ref(
            'l10n_be_hr_payroll.l10n_be_joint_committee_200')

        # First period: voluntary + overtime hours on working days only (Mon-Fri, no weekends).
        _, jan_rules = self._run_extra_hours_payslip(
            name="Payslip Jan 2026",
            rule_vals_list=[
                {
                    'name': 'Voluntary hours',
                    'working_hours_mode': 'day',
                    'work_entry_type_id': self.volo200_type.id,
                    'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
                    'timing_start': 0,
                    'timing_stop': 12,
                    'apply_saturday': False,
                    'apply_sunday': False,
                },
                {
                    'name': 'Overtime hours',
                    'working_hours_mode': 'day',
                    'work_entry_type_id': self.overtime_type.id,
                    'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
                    'timing_start': 12,
                    'timing_stop': 24,
                    'apply_saturday': False,
                    'apply_sunday': False,
                },
            ],
            # working days Jan 1(Thu),2(Fri),5-9(Mon-Fri): 7 days x 24h local each
            attendance_periods=[
                (datetime.datetime(2026, 1, 1, 0, 0), datetime.datetime(2026, 1, 2, 0, 0)),   # Jan 1 Thu
                (datetime.datetime(2026, 1, 2, 0, 0), datetime.datetime(2026, 1, 3, 0, 0)),   # Jan 2 Fri
                (datetime.datetime(2026, 1, 5, 0, 0), datetime.datetime(2026, 1, 6, 0, 0)),   # Jan 5 Mon
                (datetime.datetime(2026, 1, 6, 0, 0), datetime.datetime(2026, 1, 7, 0, 0)),   # Jan 6 Tue
                (datetime.datetime(2026, 1, 7, 0, 0), datetime.datetime(2026, 1, 8, 0, 0)),   # Jan 7 Wed
                (datetime.datetime(2026, 1, 8, 0, 0), datetime.datetime(2026, 1, 9, 0, 0)),   # Jan 8 Thu
                (datetime.datetime(2026, 1, 9, 0, 0), datetime.datetime(2026, 1, 10, 0, 0)),  # Jan 9 Fri
            ],
            date_from=datetime.datetime(2026, 1, 1),
            date_to=datetime.datetime(2026, 1, 31),
        )
        declaration = self.env['l10n_be.274_xx'].create({'year': 2026, 'month': '1'})
        # Rules fire Mon-Fri only. 7 working days, each full local day:
        # Jan 1,2,5,6,7,8,9:
        #   VOLOT200 (timing 0-12h): 12h per day -> 7x12 = 84h   amount = 84x30x2.0 = 5040€
        #   040.00 (timing 12-24h): 12h per day -> 7x12 = 84h   amount = 84x30x1.5 = 3780€
        #
        # calendar 002.00:
        #   Jan 12-30 Mon-Fri (15 days): 15x7.6 = 114h   amount = 114x30 = 3420€
        # BASIC  = categories['REMUNERATION_BASE'] = 002.00(3420) + 040.00(3780) = 7200€
        # VOLOT200 salary rule = 5040€
        # SALARY = 7200 + 5040 = 12240€
        # ONSS   = 12240 x 13.07% = 1599.77€
        # taxable_amount_10 = GROSS = 12240 - 1599.77 = 10640.23€
        # GROSS.Y = 10640.23 x 12 = 127682.76; after forfait (6070): 121612.76€
        # annual tax (Y.P.P) = 58071.34; marital deduction = 2987.98
        # PPTOTAL (before P.P.DEDEH) = (58071.34 - 2987.98) / 12 = 4590.28€
        # P.P.DEDEH (P.P.DEDEH withholding reduction for extra hours):
        #   VOLOT200 (84h, 200% rate -> premium rate 100% >= 50% -> tier2 57.75%):
        #     base = 84 x 30 = 2520€; deduction = 2520 x 0.5775 = 1455.30€
        #   040.00 (84h, 150% rate -> premium rate 50% >= 50% -> tier2 57.75%):
        #     base = 84 x 30 = 2520€; deduction = 2520 x 0.5775 = 1455.30€
        #   total P.P.DEDEH = 2910.60€
        # pp_amount_10 = PPTOTAL = 4590.28 - 2910.60 = 1679.68€
        #
        # taxable_amount_44 (274_44 overtime exemption):
        #   VOLOT200: 84h x 30€ = 2520€; 040.00: 84h x 30€ = 2520€
        #   total = 5040€  (168h < 180h annual cap)
        # 5040 x 41.25% = 2079.0€, at most the withholding tax of the employee: deducted_amount_44 = 1679.68€
        declaration_results = {
            'pp_amount_10': 1679.69,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 0.0,
            'pp_amount_34': 0.0,
            'pp_amount_44': 1679.69,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 10640.23,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 0.0,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 5040.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 1679.69,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 0.0,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 1679.69,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        self.validate_results(declaration, declaration_results)

        # Jan used 84h VOLOT200 + 84h 040.00 = 168h -> 12h remain under the 180h annual cap
        jan_rules.unlink()
        self._run_extra_hours_payslip(
            name="Payslip Feb 2026",
            rule_vals_list=[
                {
                    'name': 'Free Rule',
                    'working_hours_mode': 'day',
                    'work_entry_type_id': self.volo150_type.id,
                    'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
                    'timing_start': 0,
                    'timing_stop': 12,
                    'apply_saturday': False,
                    'apply_sunday': False,
                },
                {
                    'name': 'Paid Rule',
                    'working_hours_mode': 'day',
                    'work_entry_type_id': self.overtime_type.id,
                    'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
                    'timing_start': 12,
                    'timing_stop': 24,
                    'apply_saturday': False,
                    'apply_sunday': False,
                },
            ],
            # working days Feb 2-6, 9-13, 16-20 (Mon-Fri): 15 days x 24h local each
            attendance_periods=[
                (datetime.datetime(2026, 2, 2, 0, 0), datetime.datetime(2026, 2, 3, 0, 0)),   # Feb 2 Mon
                (datetime.datetime(2026, 2, 3, 0, 0), datetime.datetime(2026, 2, 4, 0, 0)),   # Feb 3 Tue
                (datetime.datetime(2026, 2, 4, 0, 0), datetime.datetime(2026, 2, 5, 0, 0)),   # Feb 4 Wed
                (datetime.datetime(2026, 2, 5, 0, 0), datetime.datetime(2026, 2, 6, 0, 0)),   # Feb 5 Thu
                (datetime.datetime(2026, 2, 6, 0, 0), datetime.datetime(2026, 2, 7, 0, 0)),   # Feb 6 Fri
                (datetime.datetime(2026, 2, 9, 0, 0), datetime.datetime(2026, 2, 10, 0, 0)),  # Feb 9 Mon
                (datetime.datetime(2026, 2, 10, 0, 0), datetime.datetime(2026, 2, 11, 0, 0)),  # Feb 10 Tue
                (datetime.datetime(2026, 2, 11, 0, 0), datetime.datetime(2026, 2, 12, 0, 0)),  # Feb 11 Wed
                (datetime.datetime(2026, 2, 12, 0, 0), datetime.datetime(2026, 2, 13, 0, 0)),  # Feb 12 Thu
                (datetime.datetime(2026, 2, 13, 0, 0), datetime.datetime(2026, 2, 14, 0, 0)),  # Feb 13 Fri
                (datetime.datetime(2026, 2, 16, 0, 0), datetime.datetime(2026, 2, 17, 0, 0)),  # Feb 16 Mon
                (datetime.datetime(2026, 2, 17, 0, 0), datetime.datetime(2026, 2, 18, 0, 0)),  # Feb 17 Tue
                (datetime.datetime(2026, 2, 18, 0, 0), datetime.datetime(2026, 2, 19, 0, 0)),  # Feb 18 Wed
                (datetime.datetime(2026, 2, 19, 0, 0), datetime.datetime(2026, 2, 20, 0, 0)),  # Feb 19 Thu
                (datetime.datetime(2026, 2, 20, 0, 0), datetime.datetime(2026, 2, 21, 0, 0)),  # Feb 20 Fri
            ],
            date_from=datetime.datetime(2026, 2, 1),
            date_to=datetime.datetime(2026, 2, 28),
        )
        declaration = self.env['l10n_be.274_xx'].create({'year': 2026, 'month': '2'})
        # Each attendance spans 00:00-24:00 CET local. Rules fire Mon-Fri only.
        # 15 working days Feb 2-20, each full local day:
        #   VOLOT150 (timing 0-12h): 12h per day -> 15x12 = 180h   amount = 180x30x1.5 = 8100€
        #   040.00 (timing 12-24h): 12h per day -> 15x12 = 180h   amount = 180x30x1.5 = 8100€
        #
        # 002.00 (no weekend attendance -> 0h; calendar for unattended Mon-Fri):
        #   Feb 23-27 Mon-Fri (5 days): 5x7.6 = 38h   amount = 38x30 = 1140€
        #
        # BASIC  = 002.00(1140) + 040.00(8100) = 9240€
        # VOLOT150 salary rule = 8100€
        # SALARY = 9240 + 8100 = 17340€
        # ONSS   = 17340 x 13.07% = 2266.34€
        # taxable_amount_10 = GROSS = 17340 - 2266.34 = 15073.66€
        # GROSS.Y = 15073.66 x 12 = 180883.92; after forfait (6070): 174813.92€
        # annual tax (Y.P.P) = 86526.00; marital deduction = 2987.98
        # PPTOTAL (before P.P.DEDEH) = (86526.00 - 2987.98) / 12 = 6962.17€
        # P.P.DEDEH (annual cap=180h for CP200, as the 274.44 exemption; Jan consumed 168h -> 12h remaining):
        #   VOLOT150 (min(180, 12 remaining cap) = 12h, tier2 57.75%): base = 12 x 30 = 360€; deduction = 207.90€
        #   040.00: cap reached
        #   total P.P.DEDEH = 207.90€
        # pp_amount_10 = PPTOTAL = 6962.17 - 207.90 = 6754.27€
        #
        # taxable_amount_44: annual cap = 180h; Jan used 84+84=168h -> 12h remain
        #   Feb exempt hours capped at 12h -> 12x30 = 360€
        # deducted_amount_44 = 360 x 41.25% = 148.5€
        declaration_results = {
            'pp_amount_10': 6754.28,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 0.0,
            'pp_amount_34': 0.0,
            'pp_amount_44': 6754.28,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 15073.66,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 0.0,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 360.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 148.5,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 0.0,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 148.5,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        self.validate_results(declaration, declaration_results)

    def test_extra_hours_55_CP_302(self):
        self.env.ref('l10n_be_hr_payroll.l10n_be_time_rule_sunday').sudo().write({'active': False})
        self.env.ref('l10n_be_hr_payroll.l10n_be_time_rule_night_cp302').sudo().write({'active': False})

        self.extra_hours_employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        payslip, _ = self._run_extra_hours_payslip(
            name="Payslip Jan 2026",
            rule_vals_list=[
                {
                    'name': 'Overtime hours',
                    'working_hours_mode': 'day',
                    'work_entry_type_id': self.overtime_type.id,
                    'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
                    'timing_start': 0,
                    'timing_stop': 12,
                    'apply_saturday': False,
                    'apply_sunday': False,
                },
            ],
            # working days Jan 1(Thu),2(Fri),5-9,12-16,19(Mon): 13 days x 24h local each
            attendance_periods=[
                (datetime.datetime(2026, 1, 1, 0, 0), datetime.datetime(2026, 1, 2, 0, 0)),   # Jan 1 Thu
                (datetime.datetime(2026, 1, 2, 0, 0), datetime.datetime(2026, 1, 3, 0, 0)),   # Jan 2 Fri
                (datetime.datetime(2026, 1, 5, 0, 0), datetime.datetime(2026, 1, 6, 0, 0)),   # Jan 5 Mon
                (datetime.datetime(2026, 1, 6, 0, 0), datetime.datetime(2026, 1, 7, 0, 0)),   # Jan 6 Tue
                (datetime.datetime(2026, 1, 7, 0, 0), datetime.datetime(2026, 1, 8, 0, 0)),   # Jan 7 Wed
                (datetime.datetime(2026, 1, 8, 0, 0), datetime.datetime(2026, 1, 9, 0, 0)),   # Jan 8 Thu
                (datetime.datetime(2026, 1, 9, 0, 0), datetime.datetime(2026, 1, 10, 0, 0)),  # Jan 9 Fri
                (datetime.datetime(2026, 1, 12, 0, 0), datetime.datetime(2026, 1, 13, 0, 0)),  # Jan 12 Mon
                (datetime.datetime(2026, 1, 13, 0, 0), datetime.datetime(2026, 1, 14, 0, 0)),  # Jan 13 Tue
                (datetime.datetime(2026, 1, 14, 0, 0), datetime.datetime(2026, 1, 15, 0, 0)),  # Jan 14 Wed
                (datetime.datetime(2026, 1, 15, 0, 0), datetime.datetime(2026, 1, 16, 0, 0)),  # Jan 15 Thu
                (datetime.datetime(2026, 1, 16, 0, 0), datetime.datetime(2026, 1, 17, 0, 0)),  # Jan 16 Fri
                (datetime.datetime(2026, 1, 19, 0, 0), datetime.datetime(2026, 1, 20, 0, 0)),  # Jan 19 Mon
            ],
            date_from=datetime.datetime(2026, 1, 1),
            date_to=datetime.datetime(2026, 1, 31),
        )

        # Each attendance spans 00:00-24:00 CET local. Rule fires Mon-Fri (0-12h only).
        # 13 working days Jan 1,2,5-9,12-16,19, each full local day:
        #   040.00 (timing 0-12h): 12h per day -> 13x12 = 156h   amount = 156x30x1.5 = 7020€
        #   (afternoon 12-24h unmatched -> stays as 002.00 from attendance)
        #
        # 002.00:
        #   attended PM (12-24h, 13 working days): 13x12 = 156h
        #   calendar Mon-Fri with no attendance: Jan 21-30 Mon-Fri (8 days, not 9):
        #     Jan 19 attendance check_out = Jan 19 23:00 UTC = Jan 20 00:00 CET touches Jan 20,
        #     so the payslip treats Jan 20 as "covered" -> only Jan 21-30 Mon-Fri contribute.
        #     Jan 21(Wed), 22, 23(Fri), 26(Mon), 27, 28, 29, 30(Fri) = 8x7.6 = 60.8h
        #   002.00 = 156 + 60.8 = 216.8h   amount = 216.8x30 = 6504€
        #   (no weekend attendance -> 0h from weekends)
        #
        # BASIC  = SALARY = 002.00(6504) + 040.00(7020) = 13524€
        # ONSS   = 13524 x 13.07% = 1767.59€
        # taxable_amount_10 = GROSS = 13524 - 1767.59 = 11756.41€
        # GROSS.Y = 11756.41 x 12 = 141076.92; after forfait (6070): 135006.92€
        # annual tax (Y.P.P) = 65237.32; marital deduction = 2987.98
        # PPTOTAL (before P.P.DEDEH) = (65237.32 - 2987.98) / 12 = 5187.44€
        # P.P.DEDEH (040.00 156h, tier2 57.75%, cap=360h no prior validated payslips):
        #   base = 156 x 30 = 4680€; deduction = 4680 x 0.5775 = 2702.70€
        # pp_amount_10 = PPTOTAL = 5187.44 - 2702.70 = 2484.74€
        #
        # taxable_amount_44 (274_44 overtime exemption):
        #   040.00 = 156h; cap = 360h for the hotel industry, with or without a white cash register, the first 180h
        #   declared under 274.44, the next ones under 274.55
        #   156h x 30€ = 4680€; deducted = 4680 x 41.25% = 1930.5€
        base_results = {
            'pp_amount_10': 2484.75,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 0.0,
            'pp_amount_32': 0.0,
            'pp_amount_33': 0.0,
            'pp_amount_34': 0.0,
            'pp_amount_44': 2484.75,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 11756.41,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 0.0,
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 0.0,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 4680.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 1930.5,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 0.0,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 1930.5,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }

        # The 360h/year exemption limit holds with or without a white cash register
        for white_cash_register in (False, True):
            self.env.company.l10n_be_has_white_cash_register = white_cash_register
            declaration = self.env['l10n_be.274_xx'].create({'year': 2026, 'month': '1'})
            self.validate_results(declaration, base_results)

        # The payslip's withholding tax (2484.74€) covers the whole exemption
        line_values = payslip._get_line_values(['WITHHOLDING_TAX_EX_274_44', 'WITHHOLDING_TAX_EX_TOT'])
        for code in ('WITHHOLDING_TAX_EX_274_44', 'WITHHOLDING_TAX_EX_TOT'):
            self.assertAlmostEqual(line_values[code][payslip.id]['total'], 1930.5, 2, code)

        # The hours above the general cap (lowered to 100h here) are declared under 274.55:
        #   274.44: 100h x 30 = 3000 EUR, deducted 1237.5 EUR; 274.55: 56h x 30 = 1680 EUR, deducted 693 EUR
        #   the withholding tax shared between them as the taxable amounts: 1592.79 EUR and 891.96 EUR
        self.env['hr.rule.parameter.value'].create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_l10n_be_overtime_threshold_cp200').id,
            'date_from': datetime.date(2026, 1, 1),
            'parameter_value': '100',
        })
        declaration = self.env['l10n_be.274_xx'].create({'year': 2026, 'month': '1'})
        self.validate_results(declaration, dict(
            base_results,
            pp_amount_44=1592.79, pp_amount_55=891.96,
            taxable_amount_44=3000.0, taxable_amount_55=1680.0,
            deducted_amount_44=1237.5, deducted_amount_55=693.0,
        ))

    def test_extra_hours_55_CP_302_voluntary(self):
        self.env.ref('l10n_be_hr_payroll.l10n_be_time_rule_sunday').sudo().write({'active': False})
        self.env.ref('l10n_be_hr_payroll.l10n_be_time_rule_night_cp302').sudo().write({'active': False})

        self.extra_hours_employee.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        payslip, _ = self._run_extra_hours_payslip(
            name="Payslip Jan 2026",
            rule_vals_list=[
                {
                    'name': 'Voluntary hours',
                    'working_hours_mode': 'day',
                    'work_entry_type_id': self.volo150_type.id,
                    'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
                    'timing_start': 0,
                    'timing_stop': 12,
                    'apply_saturday': False,
                    'apply_sunday': False,
                },
            ],
            # working days Jan 1(Thu),2(Fri),5-9(Mon-Fri): 7 days x 24h local each
            attendance_periods=[
                (datetime.datetime(2026, 1, 1, 0, 0), datetime.datetime(2026, 1, 2, 0, 0)),   # Jan 1 Thu
                (datetime.datetime(2026, 1, 2, 0, 0), datetime.datetime(2026, 1, 3, 0, 0)),   # Jan 2 Fri
                (datetime.datetime(2026, 1, 5, 0, 0), datetime.datetime(2026, 1, 6, 0, 0)),   # Jan 5 Mon
                (datetime.datetime(2026, 1, 6, 0, 0), datetime.datetime(2026, 1, 7, 0, 0)),   # Jan 6 Tue
                (datetime.datetime(2026, 1, 7, 0, 0), datetime.datetime(2026, 1, 8, 0, 0)),   # Jan 7 Wed
                (datetime.datetime(2026, 1, 8, 0, 0), datetime.datetime(2026, 1, 9, 0, 0)),   # Jan 8 Thu
                (datetime.datetime(2026, 1, 9, 0, 0), datetime.datetime(2026, 1, 10, 0, 0)),  # Jan 9 Fri
            ],
            date_from=datetime.datetime(2026, 1, 1),
            date_to=datetime.datetime(2026, 1, 31),
        )
        # 040.27 (timing 0-12h): 12h per day -> 7x12 = 84h, voluntary overtime with its legal 50% premium:
        #   84 x 30 x 1.5 = 3780€; the exemption is on the hours' pay: 84 x 30 = 2520€; 2520 x 41.25% = 1039.5€
        # within the first 180h: 274.44
        declaration = self.env['l10n_be.274_xx'].create({'year': 2026, 'month': '1'})
        self.assertAlmostEqual(declaration.taxable_amount_44, 2520, 2)
        self.assertAlmostEqual(declaration.deducted_amount_44, 1039.5, 2)
        self.assertFalse(declaration.taxable_amount_55)

        # The payslip's withholding tax (1963€) covers the whole exemption
        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_44'])
        self.assertAlmostEqual(line_values['PPTOTAL'][payslip.id]['total'], 1963, 2)
        self.assertAlmostEqual(line_values['WITHHOLDING_TAX_EX_274_44'][payslip.id]['total'], 1039.5, 2)

    def test_extra_hours_44_recoverable_payslip(self):
        self.env.ref('l10n_be_hr_payroll.l10n_be_time_rule_sunday').sudo().write({'active': False})

        self.extra_hours_employee.l10n_be_joint_committee_id = self.env.ref(
            'l10n_be_hr_payroll.l10n_be_joint_committee_200')
        recoverable_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_overtime_recoverable')
        payslip, _ = self._run_extra_hours_payslip(
            name="Payslip Jan 2026",
            rule_vals_list=[
                {
                    'name': 'Overtime hours to recover',
                    'working_hours_mode': 'day',
                    'work_entry_type_id': recoverable_type.id,
                    'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
                    'timing_start': 0,
                    'timing_stop': 12,
                    'apply_saturday': False,
                    'apply_sunday': False,
                },
            ],
            # working days Jan 1(Thu),2(Fri),5-9(Mon-Fri): 7 days x 24h local each
            attendance_periods=[
                (datetime.datetime(2026, 1, 1, 0, 0), datetime.datetime(2026, 1, 2, 0, 0)),   # Jan 1 Thu
                (datetime.datetime(2026, 1, 2, 0, 0), datetime.datetime(2026, 1, 3, 0, 0)),   # Jan 2 Fri
                (datetime.datetime(2026, 1, 5, 0, 0), datetime.datetime(2026, 1, 6, 0, 0)),   # Jan 5 Mon
                (datetime.datetime(2026, 1, 6, 0, 0), datetime.datetime(2026, 1, 7, 0, 0)),   # Jan 6 Tue
                (datetime.datetime(2026, 1, 7, 0, 0), datetime.datetime(2026, 1, 8, 0, 0)),   # Jan 7 Wed
                (datetime.datetime(2026, 1, 8, 0, 0), datetime.datetime(2026, 1, 9, 0, 0)),   # Jan 8 Thu
                (datetime.datetime(2026, 1, 9, 0, 0), datetime.datetime(2026, 1, 10, 0, 0)),  # Jan 9 Fri
            ],
            date_from=datetime.datetime(2026, 1, 1),
            date_to=datetime.datetime(2026, 1, 31),
        )
        # 026.00 (timing 0-12h): 12h per day -> 7x12 = 84h, paid now for their 50% premium alone:
        #   84 x 30 x 0.5 = 1260€ (the hours themselves are paid when they are recovered)
        recoverable_line = payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == recoverable_type)
        self.assertAlmostEqual(recoverable_line.number_of_hours, 84, 2)
        self.assertAlmostEqual(recoverable_line.amount, 1260, 2)

        # The exemption is on the whole pay of the hours: 84 x 30 = 2520€; 2520 x 41.25% = 1039.5€, at most the
        # withholding tax of the employee (791.01€ once the employee's overtime tax reduction is applied), as the payslip
        declaration = self.env['l10n_be.274_xx'].create({'year': 2026, 'month': '1'})
        self.assertAlmostEqual(declaration.taxable_amount_44, 2520, 2)
        self.assertAlmostEqual(declaration.deducted_amount_44, 791.01, 2)

        # The payslip keeps at most its own withholding tax
        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_44', 'WITHHOLDING_TAX_EX_TOT'])
        for code, amount in [('PPTOTAL', 791.01), ('WITHHOLDING_TAX_EX_274_44', 791.01), ('WITHHOLDING_TAX_EX_TOT', 791.01)]:
            self.assertAlmostEqual(line_values[code][payslip.id]['total'], amount, 2, code)

    def test_extra_hours_44_part_time_additional_hours_150(self):
        # A part-timer's additional hours paid at 150% (003.12) are overtime of the exemption, on their base pay
        self.env.ref('l10n_be_hr_payroll.l10n_be_time_rule_sunday').sudo().write({'active': False})

        self.extra_hours_employee.l10n_be_joint_committee_id = self.env.ref(
            'l10n_be_hr_payroll.l10n_be_joint_committee_200')
        additional_hours_type = self.env.ref('hr_work_entry.be_work_entry_type_additional_hours_50')
        self.env['hr.time.rule'].sudo().create({
            'name': 'Additional hours 150%',
            'working_hours_mode': 'day',
            'work_entry_type_id': additional_hours_type.id,
            'condition_work_entry_type_ids': [(4, self.be_attendance_type.id)],
            'timing_start': 0,
            'timing_stop': 2,
            'apply_saturday': False,
            'apply_sunday': False,
            'employee_domain': f"[('id', '=', {self.extra_hours_employee.id})]",
        })
        tz = ZoneInfo(self.extra_hours_employee.sudo()._get_tz())
        # working days Jan 1(Thu),2(Fri),5-9(Mon-Fri): 7 days x 24h local each
        for day in (1, 2, 5, 6, 7, 8, 9):
            check_in = datetime.datetime(2026, 1, day).replace(tzinfo=tz).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
            self.env['hr.attendance'].sudo().create({
                'employee_id': self.extra_hours_employee.id,
                'check_in': check_in,
                'check_out': check_in + datetime.timedelta(days=1),
            })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2026',
            'version_id': self.extra_hours_employee.version_id.id,
            'date_from': datetime.date(2026, 1, 1),
            'date_to': datetime.date(2026, 1, 31),
            'employee_id': self.extra_hours_employee.id,
            'company_id': self.env.company.id,
        })
        payslip.compute_sheet()

        # 003.12 (timing 0-2h): 2h per day -> 7x2 = 14h at 150%: 14 x 30 x 1.5 = 630€
        additional_line = payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == additional_hours_type)
        self.assertAlmostEqual(additional_line.number_of_hours, 14, 2)
        self.assertAlmostEqual(additional_line.amount, 630, 2)

        # The exemption is on the pay of the hours without the premium: 14 x 30 = 420€; 420 x 41.25% = 173.25€
        line_values = payslip._get_line_values(['WITHHOLDING_TAX_EX_274_44', 'P.P.DEDEH'])
        self.assertAlmostEqual(line_values['WITHHOLDING_TAX_EX_274_44'][payslip.id]['total'], 173.25, 2)
        self.assertTrue(line_values['P.P.DEDEH'][payslip.id]['total'])

    def test_30_declarations(self):
        employee_tokens = self.employees[0]
        employee_tokens.write({'l10n_be_include_employee_in_281_30': True})
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip Tokens {i}',
            'date_from': datetime.datetime(2026, i, 1),
            'date_to': datetime.datetime(2026, i, 1) + relativedelta(day=31),
            'employee_id': employee_tokens.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
        } for i in range(1, 13)])

        for p in payslips:
            p._set_input_value('PRESENCE_TOKEN', 2000)
        payslips.compute_sheet()
        payslips.action_payslip_done()

        declaration = self.env['l10n_be.274_xx'].create({
            'year': 2026,
            'month': '1',
        })
        declaration_results = {
            'pp_amount_10': 0.0,
            'pp_amount_13': 0.0,
            'pp_amount_18': 0.0,
            'pp_amount_20': 0.0,
            'pp_amount_30': 860.73,  # the withholding taxes of the presence tokens and of the salary
            'pp_amount_32': 0.0,
            'pp_amount_33': 113.73,
            'pp_amount_34': 0.0,
            'pp_amount_44': 0.0,
            'pp_amount_55': 0.0,
            'taxable_amount_10': 0.0,
            'taxable_amount_13': 0.0,
            'taxable_amount_18': 0.0,
            'taxable_amount_20': 0.0,
            'taxable_amount_30': 4070.2,  # the presence tokens and the taxable salary
            'taxable_amount_32': 0.0,
            'taxable_amount_33': 2070.2,
            'taxable_amount_34': 0.0,
            'taxable_amount_44': 0.0,
            'taxable_amount_55': 0.0,
            'deducted_amount': 90.98,
            'deducted_amount_32': 0.0,
            'deducted_amount_33': 90.98,
            'deducted_amount_34': 0.0,
            'deducted_amount_44': 0.0,
            'deducted_amount_55': 0.0,
            'capped_amount_34': 0.0,
        }
        self.validate_results(declaration, declaration_results)

        declaration = self.env['l10n_be.281_xx'].create({
            'year': 2026,
        })
        declaration = declaration.l10n_be_281_30_ids
        data_281 = declaration._get_rendering_data(self.employees[0])
        self.assertIn(self.employees[0].niss, {emp_data['f2011_nationaalnr'] for emp_data in data_281['employees_data']})
        for employee_data in data_281['employees_data']:
            if employee_data['f2011_nationaalnr'] == self.employees[0].niss:
                self.assertAlmostEqual(employee_data['f30_2063_bedrijfsvoorheffing'], 11140.27, places=2)
                # The presence tokens with the taxable salary (benefits in kind included) and the representation fees
                self.assertAlmostEqual(employee_data['f30_2064_presentiegelden'], 24000.0 + 27394.72 + 1800.0, places=2)
                # Box 9: the representation fees, not the benefits in kind
                self.assertAlmostEqual(employee_data['f30_2086_bedrag'], 1800.0, places=2)
                self.assertEqual(employee_data['f30_2099_aard'], 'divers')

        # A non-resident beneficiary: the same income in box 7f
        self.employees[0].l10n_be_resident_situation = 'non_resident'
        employee_data = declaration._get_rendering_data(self.employees[0])['employees_data'][0]
        self.assertEqual(employee_data['f30_2064_presentiegelden'], 0)
        self.assertAlmostEqual(employee_data['f30_2081_retributies'], 24000.0 + 27394.72 + 1800.0, places=2)

    @freeze_time("2025-12-31")
    def test_281_10_all_fields(self):
        """
        Test that all fields for the 281.10 declaration are correctly mapped and validated.
        """
        brand = self.env['fleet.vehicle.model.brand'].sudo().create({'name': "Test Brand"})
        model = self.env['fleet.vehicle.model'].sudo().create({'name': "Test Model", 'brand_id': brand.id})

        test_car = self.env['fleet.vehicle'].sudo().create({
            'name': "Test Car",
            'model_id': model.id,
            'brand_id': brand.id,
            'company_id': self.env.company.id,
            'car_value': 40000.0,
            'co2': 88.0,
            'fuel_type': 'diesel',
            'acquisition_date': datetime.date(2025, 1, 1),
        })
        self.env['fleet.vehicle.log.contract'].sudo().create({
            'name': "Test Contract",
            'vehicle_id': test_car.id,
            'company_id': self.env.company.id,
            'start_date': datetime.date(2025, 10, 8),
            'expiration_date': datetime.date(2026, 10, 8),
            'state': "open",
            'cost_generated': 0.0,
            'cost_frequency': "monthly",
            'recurring_cost_amount_depreciated': 450.0
        })

        emp = self.env['hr.employee'].create({
            'name': "Complete Employee",
            'private_street': 'Employee Street',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'private_country_id': self.env.ref('base.be').id,
            'company_id': self.env.company.id,
            'niss': '91072845880',
            'certificate': 'master',
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'date_version': datetime.date(2025, 1, 1),
            'wage': 4000.0,
            'laptop': True,
            'internet': 38.0,
            'mobile_amount': 30.0,
            'transport_mode_car': True,
            'car_id': test_car.id,
            'housing_fiscal_amount': 1200.0,
            'housing_onss_amount': 300.0,
            'heating_amount': 300.0,
            'electricity_amount': 200.0,
            'mobile': 50.0,
            'rent_amount': 800.0,
            'train_transport_employee_kilometer': 50,
            'private_car_employee_kilometer': 20,
            'has_bicycle': True,
            'km_home_work': 15,
            'fuel_card': 100,
            'l10n_be_lsa_homeworking_amount': 150.0,
            'l10n_be_has_group_insurance': True,
            'l10n_be_group_insurance_employee_contribution': 0.50,
            'l10n_be_group_insurance_employee_voluntary': 0.25,
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': 500.0,
            'bike_transport_employee_kilometer': 15,
            'l10n_be_lsa_daily_misc_other_amount': 75.0,
            'l10n_be_lsa_monthly_misc_other_amount': 100,
            'bus_transport_employee_amount': 25.0,
            'bus_transport_employee_kilometer': 5,
        })

        departure_notice = self.env['hr.employee.departure'].create({
            'employee_id': emp.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.date(2025, 12, 30),
            'l10n_be_notice_respect': 'without',
            'departure_description': 'foo',
            'action_date': datetime.date(2025, 12, 31),
        })
        departure_notice.action_register()
        departure_payslips = departure_notice._generate_termination_payslip()
        departure_payslips += departure_notice._generate_termination_holidays()

        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees = departure_payslips.filtered(lambda dep: dep.struct_id == struct_id)
        termination_fees.compute_sheet()
        termination_fees.employee_id.write({'review_state': '1_reviewed'})
        termination_fees.action_payslip_done()

        holiday_pays = departure_payslips - termination_fees
        holiday_pays.employee_id.write({'review_state': '1_reviewed'})
        holiday_pays.action_payslip_done()

        payslip_regular = self.env['hr.payslip'].create({
            'name': 'Regular Month',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2025, 1, 1),
            'date_to': datetime.date(2025, 1, 31),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })
        payslip_regular._set_input_value('CYCLE', 10)
        payslip_regular._set_input_value('EXPENSE_MANUAL', 75)

        payslip_arrear = self.env['hr.payslip'].create({
            'name': 'Arrear Month',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2025, 2, 1),
            'date_to': datetime.date(2025, 2, 28),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
            'l10n_be_arrear_salary': True,
        })

        payslip_warrant = self.env['hr.payslip'].create({
            'name': 'Warrant',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant').id,
            'date_from': datetime.date(2025, 3, 1),
            'date_to': datetime.date(2025, 3, 31),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })
        payslip_warrant._set_input_value('WARRANT_WITHOUT_ONSS', 1000)

        payslip_cct90 = self.env['hr.payslip'].create({
            'name': 'CCT90',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90').id,
            'date_from': datetime.date(2025, 4, 1),
            'date_to': datetime.date(2025, 4, 30),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })
        payslip_cct90._set_input_value('CCT90_GROSS', 500)

        all_payslips = payslip_regular | payslip_arrear | payslip_warrant | payslip_cct90 | termination_fees | holiday_pays
        all_payslips.compute_sheet()
        emp.write({'review_state': '1_reviewed'})
        # The termination payslips are already validated
        all_payslips.filtered(lambda p: p.state == 'draft').action_payslip_done()

        all_payslips.write({'state': 'validated'})

        declaration_281_xx = self.env['l10n_be.281_xx'].create({'year': 2025})
        sheet = declaration_281_xx.l10n_be_281_10_ids

        data_281 = sheet.with_context(round_281=True)._get_rendering_data(emp)
        emp_data = {key: value for key, value in data_281['employees_data'][0].items() if key.startswith('f10_')}

        EXPECTED_RESULTS = {
            'f10_2031_associationactivity': 0,
            'f10_2035_verantwoordingsstukken': 0,
            'f10_2036_inwonersdeenfr': 0,
            'f10_2037_vergoedingkosten': 0,
            'f10_2038_seasonalworker': 0,
            'f10_2039_optiebuitvennoots': '0',
            'f10_2040_individualconvention': 0,
            'f10_2041_overheidspersoneel': 0,
            'f10_2042_sailorcode': 0,
            'f10_2045_code': 0,
            'f10_2055_datumvanindienstt': '01-01-2025',
            'f10_2056_datumvanvertrek': '30-12-2025',
            'f10_2060_gewonebezoldiginge': 337029,
            'f10_2061_bedragoveruren300horeca': 0,
            'f10_2063_vervroegdvakantieg': 0,
            'f10_2064_afzbelachterstall': 530922,
            'f10_2065_opzeggingsreclasseringsverg': 939326,
            'f10_2066_impulsfund': 0,
            'f10_2067_rechtvermindering66_81': 0,
            'f10_2068_rechtvermindering57_75': 0,
            'f10_2069_fidelitystamps': 0,
            'f10_2070_decemberremuneration': 0,
            'f10_2072_pensioentoezetting': 0,
            'f10_2073_tipamount': 0,
            'f10_2074_bedrijfsvoorheffing': 409260,
            'f10_2075_bijzonderbijdrage': 16910,
            'f10_2076_voordelenaardbedrag': 171800,
            'f10_2078_compensationamountwithoutstandards': 0,
            'f10_2079_covidovertimeremuneration2023': 0,
            'f10_2081_gewonebijdragenenpremies': 481850,
            'f10_2082_bedrag': 18000,
            'f10_2083_bedrag': 0,
            'f10_2084_mobiliteitsvergoedi': 0,
            'f10_2085_forfbezoldiging': 0,
            'f10_2086_openbaargemeenschap': 35110,
            'f10_2087_bedrag': 0,
            'f10_2088_andervervoermiddel': 35010,
            'f10_2090_outborderdays': 0,
            'f10_2092_othercode1': 0,
            'f10_2094_othercode2': 0,
            'f10_2095_aantaluren': 0,
            'f10_2096_othercode3': 0,
            'f10_2097_aantaluren': 0,
            'f10_2098_othercode4': 0,
            'f10_2099_aard': 'BCDHIJK',
            'f10_2102_kas': 0,
            'f10_2103_kasvrijaanvullendpensioen': 0,
            'f10_2106_percentages': '00,00',
            'f10_2109_fiscaalidentificat': '',
            'f10_2110_aantaloveruren360': 0,
            'f10_2111_achterstalloveruren300horeca': 0,
            'f10_2113_forfaitrsz': 0,
            'f10_2115_bonus': 0,
            'f10_2116_badweatherstamps': 0,
            'f10_2117_nonrecurrentadvantages': 0,
            'f10_2118_overtimehours180': 0,
            'f10_2119_sportremuneration': 0,
            'f10_2120_sportvacancysavings': 0,
            'f10_2121_sportoutdated': 0,
            'f10_2122_sportindemnificationofretraction': 0,
            'f10_2123_managerremuneration': 0,
            'f10_2124_managervacancysavings': 0,
            'f10_2125_manageroutdated': 0,
            'f10_2126_managerindemnificationofretraction': 0,
            'f10_2127_nonrecurrentadvantagesoutdated': 0,
            'f10_2128_vrijaanvullendpensioenwerknemers': 0,
            'f10_2129_exemptincomesubjecttoprogressivity': 0,
            'f10_2130_privatepc': 0,
            'f10_2131_bedrijfsvoorheffingvanwerkgever': 409260,
            'f10_2132_horeca': 0,
            'f10_2133_bedrijfsvoorheffingbuitenlvenverbondenwerkgever': 0,
            'f10_2134_totaalbedragmobiliteitsbudget': 49863,
            'f10_2136_amountcontractofstudent': 0,
            'f10_2137_amountstudentspecificperiod': 0,
            'f10_2138_covidovertimehours2023': 0,
            'f10_2141_total': 0,
            'f10_2142_totalovertimehours180': 0,
            'f10_2143_bedragoveruren360horeca': 0,
            'f10_2165_achterstalloveruren360horeca': 0,
            'f10_2166_flexi_job': 0,
            'f10_2167_aantaloveruren300horeca': 0,
            'f10_2168_achterstallaantaloveruren300horeca': 0,
            'f10_2169_aantaloveruren360horeca': 0,
            'f10_2170_achterstallaantaloveruren360horeca': 0,
            'f10_2176_overtimehours180': 0,
            'f10_2177_winstpremies': 0,
            'f10_2178_pensioner': 0,
            'f10_2179_startersjob': 0,
            'f10_2180_onkostenbrandweerenambulanciers': 0,
            'f10_2181_remunerationetrang': 0,
            'f10_2182_aandelenetrang': 0,
            'f10_2183_bonuspremieoaandelenoptiesetrang': 0,
            'f10_2184_anderevaaetrang': 0,
            'f10_2185_amountother1': 0,
            'f10_2186_amountother2': 0,
            'f10_2187_amountother3': 0,
            'f10_2188_amountother4': 0,
            'f10_2195_relanceovertimeremuneration': 0,
            'f10_2196_relanceovertimehours': 0,
            'f10_2198_flexijobnotpension': 0,
            'f10_2200_compensationwithstandards': 0,
            'f10_2201_compensationwithdocuments': 7500,
            'f10_2202_amount': 0,
            'f10_2203_amount': 0,
            'f10_2204_repaidsums': 0,
            'f10_2206_grossamountremuneration': 0,
            'f10_2207_travelbicycleorspeedpedelec': 34400,
            'f10_2208_benefitprovisionbicycleorspeedpedelec': 0,
            'f10_2209_overtimehours': 0,
            'f10_2210_workbonus5254': 0,
            'f10_2226_kmzone2207': 1290,
            'f10_2227_relanceovertimeremuneration2025': 0,
            'f10_2228_relanceovertimehours2025': 0,
            'f10_2062_totaal': 526829,
            'f10_2077_totaal': 104520,
            'f10_2059_totaalcontrole': 3606566,
            'f10_2257_employeecontribution': 481800,
        }
        self._validate_281_report(emp_data, EXPECTED_RESULTS)

    @freeze_time("2025-12-31")
    def test_281_20_all_fields(self):
        """
        Test that all fields for the 281.20 declaration are correctly mapped and validated.
        """
        brand = self.env['fleet.vehicle.model.brand'].sudo().create({'name': "Test Brand"})
        model = self.env['fleet.vehicle.model'].sudo().create({'name': "Test Model", 'brand_id': brand.id})

        test_car = self.env['fleet.vehicle'].sudo().create({
            'name': "Test Car",
            'model_id': model.id,
            'brand_id': brand.id,
            'company_id': self.env.company.id,
            'car_value': 40000.0,
            'co2': 88.0,
            'fuel_type': 'diesel',
            'acquisition_date': datetime.date(2025, 1, 1),
        })
        self.env['fleet.vehicle.log.contract'].sudo().create({
            'name': "Test Contract",
            'vehicle_id': test_car.id,
            'company_id': self.env.company.id,
            'start_date': datetime.date(2025, 10, 8),
            'expiration_date': datetime.date(2026, 10, 8),
            'state': "open",
            'cost_generated': 0.0,
            'cost_frequency': "monthly",
            'recurring_cost_amount_depreciated': 450.0
        })

        jc_999 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999')
        emp = self.env['hr.employee'].create({
            'name': "Complete Executive Employee",
            'private_street': 'Director Street',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'private_country_id': self.env.ref('base.be').id,
            'company_id': self.env.company.id,
            'niss': '91072845880',
            'certificate': 'master',
            'employee_type_id': self.env.ref("hr.contract_type_company_executive").id,
            'l10n_be_joint_committee_id': jc_999.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'date_version': datetime.date(2025, 1, 1),
            'rent_amount': 1200.0,
            'wage': 5000.0,
            'laptop': 200,
            'internet': 38.0,
            'mobile_amount': 30.0,
            'transport_mode_car': True,
            'car_id': test_car.id,
            'has_bicycle': True,
            'km_home_work': 15,
            'l10n_be_has_group_insurance': True,
            'l10n_be_group_insurance_employee_contribution': 0.5,
            'l10n_be_group_insurance_employee_voluntary': 0.25,
            'bike_transport_employee_kilometer': 15,
        })

        self.env['hr.employee.departure'].create({
            'employee_id': emp.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.date(2025, 12, 31),
            'l10n_be_notice_respect': 'without',
        })

        payslip_regular = self.env['hr.payslip'].create({
            'name': 'Regular Month',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2025, 1, 1),
            'date_to': datetime.date(2025, 1, 31),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })

        payslip_regular._set_input_value('CYCLE', 10)

        payslip_warrant = self.env['hr.payslip'].create({
            'name': 'Warrant',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant').id,
            'date_from': datetime.date(2025, 3, 1),
            'date_to': datetime.date(2025, 3, 31),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })

        payslip_warrant._set_input_value('WARRANT_WITHOUT_ONSS', 1000)

        payslip_cct90 = self.env['hr.payslip'].create({
            'name': 'CCT90',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90').id,
            'date_from': datetime.date(2025, 4, 1),
            'date_to': datetime.date(2025, 4, 30),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })

        payslip_cct90._set_input_value('CCT90_GROSS', 500)

        payslip_holiday = self.env['hr.payslip'].create({
            'name': 'Holiday',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays').id,
            'date_from': datetime.date(2025, 6, 1),
            'date_to': datetime.date(2025, 6, 30),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        })

        all_payslips = payslip_regular | payslip_warrant | payslip_cct90 | payslip_holiday
        all_payslips.compute_sheet()
        emp.write({'review_state': '1_reviewed'})
        all_payslips.action_payslip_done()

        all_payslips.write({'state': 'validated'})

        declaration_281_xx = self.env['l10n_be.281_xx'].create({'year': 2025})

        sheet = self.env['l10n_be.281_20'].create({
            'declaration_id': declaration_281_xx.id
        })

        data_281 = sheet.with_context(round_281=True)._get_rendering_data(emp)
        emp_data = {key: value for key, value in data_281['employees_data'][0].items() if key.startswith('f20_')}

        EXPECTED_RESULTS = {
            'f20_2031_stopzettingexploitatie': 0,
            'f20_2033_optiebuitvennoots': '0',
            'f20_2035_verantwoordingsstukken': 0,
            'f20_2045_rsz': 0,
            'f20_2055_datumvanindienstt': '',  # box 2: only for a director under an employment contract
            'f20_2056_datumvanvertrek': '',
            'f20_2060_periodieke': 500000,
            'f20_2061_covidovertimeremuneration2023': 0,
            'f20_2062_anderebezoldiginge': 0,
            'f20_2064_vervroegdvakantieg': 0,
            'f20_2065_opzeggingsreclasseringsverg': 0,
            'f20_2067_bijzonderbijdrage': 0,
            'f20_2069_compensationamountwithoutstandards': 0,
            'f20_2071_pensioengewonebijdragen': 310725,
            'f20_2073_periodieke': 120000,
            'f20_2074_anderen': 0,
            'f20_2076_nonrecurrentadvantages': 0,
            'f20_2078_pensioentoezegging': 0,
            'f20_2079_bedrag': 18000,
            'f20_2080_bedrag': 0,
            'f20_2081_bezoldigingen': 0,
            'f20_2082_occasionalworkhoreca': 0,
            'f20_2083_bonus': 0,
            'f20_2084_bonus5254': 0,
            'f20_2087_code420': 0,
            'f20_2088_impulsfund': 0,
            'f20_2092_othercode1': '',
            'f20_2094_othercode2': '',
            'f20_2096_othercode3': '',
            'f20_2098_othercode4': '',
            'f20_2102_kas': '',
            'f20_2103_kasvrijaanvullendpensioen': '',
            'f20_2106_percentages': '00,00',
            'f20_2109_fiscaalidentificat': 0,
            'f20_2128_vrijaanvullendpensioenwerknemers': 0,
            'f20_2131_bedrijfsvoorheffingvanwerkgever': 94916,
            'f20_2133_bedrijfsvoorheffingbuitenlvenverbondenwerkgever': 0,
            'f20_2134_totaalbedragmobiliteitsbudget': 0,
            'f20_2138_covidovertimehours2023': 0,
            'f20_2181_remunerationetrang': 0,
            'f20_2182_aandelenetrang': 0,
            'f20_2183_bonuspremieoaandelenoptiesetrang': 0,
            'f20_2184_anderevaaetrang': 0,
            'f20_2185_amountother1': 0,
            'f20_2186_amountother2': 0,
            'f20_2187_amountother3': 0,
            'f20_2188_amountother4': 0,
            'f20_2195_relanceovertimeremuneration': 0,
            'f20_2196_relanceovertimehours': 0,
            'f20_2200_compensationwithstandards': 0,
            'f20_2201_compensationwithdocuments': 0,
            'f20_2202_amount': 0,
            'f20_2203_amount': 0,
            'f20_2204_repaidsums': 0,
            'f20_2205_recuperation': 0,
            'f20_2206_grossamountremuneration': 0,
            'f20_2207_travelbicycleorspeedpedelec': 18630,
            'f20_2208_benefitprovisionbicycleorspeedpedelec': 0,
            'f20_2209_totalcontributiontravelexpenses': 18630,
            'f20_2226_kmzone2207': '690',
            'f20_2227_relanceovertimeremuneration2025': 0,
            'f20_2228_relanceovertimehours2025': 0,
            'f20_2068_bedrag': 25860,
            'f20_2099_aard': 'FHIJ',
            'f20_2063_totaal': 543860,
            'f20_2075_totaal': 120000,
            'f20_2066_totaalbedrijfsvoorheffing': 94916,
            'f20_2059_totaalcontrole': 1733361,
        }

        self._validate_281_report(emp_data, EXPECTED_RESULTS)

    @freeze_time("2025-12-31")
    def test_281_30_all_fields(self):
        """
        Test that all fields for the 281.30 declaration are correctly mapped and validated.
        """
        emp = self.env['hr.employee'].create({
            'name': "Complete Board Member",
            'private_street': 'Board Street',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'private_country_id': self.env.ref('base.be').id,
            'company_id': self.env.company.id,
            'niss': '91072845880',
            'certificate': 'master',
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'date_version': datetime.date(2025, 1, 1),
            'wage': 4000.0,
            'l10n_be_include_employee_in_281_30': True,
            'l10n_be_resident_situation': 'resident',
            'laptop': True,
            'internet': 38.0,
            'mobile_amount': 30.0,
            'transport_mode_car': True,
            'heating_amount': 300.0,
            'electricity_amount': 200.0,
            'mobile': 50.0,
        })

        car_brand = self.env['fleet.vehicle.model.brand'].sudo().create({'name': "Test Brand"})
        car_model = self.env['fleet.vehicle.model'].sudo().create({'name': "Test Model", 'brand_id': car_brand.id})
        test_car = self.env['fleet.vehicle'].sudo().create({
            'name': "Test Car",
            'model_id': car_model.id,
            'brand_id': car_brand.id,
            'company_id': self.env.company.id,
            'car_value': 40000.0,
            'co2': 88.0,
            'fuel_type': 'diesel',
            'acquisition_date': datetime.date(2025, 1, 1),
        })
        emp.car_id = test_car.id

        payslips = self.env['hr.payslip'].create([{
            'name': f'Board Fees {i}',
            'employee_id': emp.id,
            'version_id': emp.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2025, i, 1),
            'date_to': datetime.date(2025, i, 1) + relativedelta(day=31),
            'company_id': self.env.company.id,
            'journal_id': self.journal.id,
        } for i in range(1, 13)])
        for payslip in payslips:
            payslip._set_input_value('PRESENCE_TOKEN', 2000)
        payslips.compute_sheet()
        emp.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()
        payslips.write({'state': 'validated'})

        declaration_281_xx = self.env['l10n_be.281_xx'].create({'year': 2025})
        sheet = declaration_281_xx.l10n_be_281_30_ids

        data_281 = sheet.with_context(round_281=True)._get_rendering_data(emp)
        emp_data = {key: value for key, value in data_281['employees_data'][0].items() if key.startswith('f30_')}

        EXPECTED_RESULTS = {
            'f30_2030_beneficiarynature': 1,
            'f30_2035_verantwoordingsstukken': 0,
            'f30_2059_totaalcontrole': 9705428,
            'f30_2060_toegekendbedrag': 0,
            'f30_2061_vrijstelling': 0,
            'f30_2062_bedrag': 0,
            'f30_2063_bedrijfsvoorheffing': 2292790,
            # The presence tokens and the taxable salary, benefits in kind (car, laptop, internet, phone...) included
            'f30_2064_presentiegelden': 7412638,
            'f30_2065_toegekendbedrag': 0,
            'f30_2066_vrijstelling': 0,
            'f30_2067_bedrag': 0,
            'f30_2068_zonderberoepskarak': 0,
            'f30_2069_bijzonderbijdrage': 0,
            'f30_2070_toegekendbedrag': 0,
            'f30_2071_vrijstelling': 0,
            'f30_2072_bedrag': 0,
            'f30_2073_toegekendbedrag': 0,
            'f30_2074_vrijstelling': 0,
            'f30_2075_bedrag': 0,
            'f30_2076_peronderhoudsuitke': 0,
            'f30_2077_onderhoudsuitkering': 0,
            'f30_2078_olympicbonus': 0,
            'f30_2079_totalamount': 0,
            'f30_2080_winstofbaten': 0,
            'f30_2081_retributies': 0,
            'f30_2082_buitverrichtingen': 0,
            'f30_2083_podiumkunstenaars': 0,
            'f30_2084_winst': 0,
            'f30_2085_art2283': 0,
            # Box 9 holds the reimbursed expenses included in the taxable income, not the benefits in kind
            'f30_2086_bedrag': 0,
            'f30_2087_bedrag': 0,
            'f30_2088_bedrag': 0,
            'f30_2089_numberpeople': 0,
            'f30_2090_numberdays': 0,
            'f30_2095_foreignolympicbonus': 0,
            'f30_2097_totalamount': 0,
            'f30_2099_aard': '',
            'f30_2109_fiscaalidentificat': 0,
            'f30_2113_sportlimitedremuneration': 0,
            'f30_2115_sportunlimitedotherremuneration': 0,
            'f30_2116_sportmorethan30daysprofit': 0,
            'f30_2117_managerprofit': 0,
            'f30_2205_recuperation': 0,
        }
        self._validate_281_report(emp_data, EXPECTED_RESULTS)
