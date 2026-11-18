# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import date, datetime, time, UTC
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from odoo.tests import tagged
from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestDashboardWarnings(TestPayrollCommon):

    def check_warnings(self, warning_ids, warning_name, expected_employees):
        self.assertTrue(all(isinstance(warning_id, int) for warning_id in warning_ids), "There should be warnings to check")
        warnings = self.env['hr.payroll.warning'].get_payroll_dashboard_warning_cards(warning_ids)
        applicable_warnings = [warning for warning in warnings if warning['name'] == warning_name]
        if not expected_employees:
            self.assertEqual(applicable_warnings, [])
        else:
            self.assertTrue(applicable_warnings, f"Warning '{warning_name}' should be present in the dashboard warnings")
            self.assertEqual(expected_employees, applicable_warnings[0]['warning_records'])

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.new_employee = cls.create_employee({
            'name': 'Test Employee',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 3, 31),
            'fixed_term': True,
        })
        cls.second_version = cls.new_employee.create_version({
            'date_version': date(2025, 4, 1),
            'contract_date_start': date(2025, 4, 1),
            'contract_date_end': date(2025, 6, 30),
        })
        cls.third_version = cls.new_employee.create_version({
            'date_version': date(2025, 7, 1),
            'contract_date_start': date(2025, 7, 1),
            'contract_date_end': date(2025, 9, 30),
        })
        cls.fourth_version = cls.new_employee.create_version({
            'date_version': date(2025, 10, 1),
            'contract_date_start': date(2025, 10, 1),
            'contract_date_end': date(2025, 12, 31),
        })

    @freeze_time("2025-11-01")
    def test_4th_cdd_warning_4_cdd(self):
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.new_employee)

    @freeze_time("2025-11-01")
    def test_4th_cdd_warning_3_cdd_1_cdi(self):
        self.fourth_version.write({
            'date_version': date(2025, 10, 1),
            'contract_date_start': date(2025, 10, 1),
            'contract_date_end': False,
            'fixed_term': False,
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.env['hr.employee'])

    @freeze_time("2025-11-01")
    def test_4th_cdd_warning_less_three_months(self):
        self.second_version.write({
            'date_version': date(2025, 4, 1),
            'contract_date_start': date(2025, 4, 1),
            'contract_date_end': date(2025, 4, 30),
        })
        self.third_version.write({
            'date_version': date(2025, 5, 1),
            'contract_date_start': date(2025, 5, 1),
            'contract_date_end': date(2025, 9, 30),
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.env['hr.employee'])

    @freeze_time("2025-08-01")
    def test_4th_cdd_warning_3_cdd(self):
        self.fourth_version.unlink()
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.env['hr.employee'])

    @freeze_time("2025-12-01")
    def test_4th_cdd_warning_more_two_years(self):
        self.new_employee.version_ids[0].write({
            'date_version': date(2023, 1, 1),
            'contract_date_start': date(2023, 1, 1),
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.env['hr.employee'])

    @freeze_time("2025-12-01")
    def test_4th_cdd_warning_cdd_then_cdi(self):
        self.fourth_version.write({
            'contract_date_end': date(2025, 12, 10),
        })
        self.new_employee.create_version({
            'date_version': date(2025, 12, 11),
            'contract_date_start': date(2025, 12, 11),
            'contract_date_end': False,
            'fixed_term': False,
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.env['hr.employee'])

    @freeze_time("2025-12-01")
    def test_4th_cdd_one_less_3_months(self):
        self.third_version.write({
            'contract_date_end': date(2025, 9, 20),
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.env['hr.employee'])

    @freeze_time("2025-12-01")
    def test_4th_cdd_warning_more_two_years_span(self):
        self.fourth_version.write({
            'contract_date_end': date(2027, 1, 10),
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, '4th consecutive fixed-term contract', self.env['hr.employee'])

    @freeze_time("2026-01-01")
    def test_sales_rep_wrong_salary_scale(self):
        sales_rep_employee = self.create_employee({
            'name': 'Sales Rep',
            'date_version': date(2025, 12, 1),
            'contract_date_start': date(2025, 12, 1),
            'contract_date_end': False,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_a').id,
            'l10n_be_is_sale_representative': True,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id
        })

        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Invalid Salary Scale for Sales Representatives', self.env['hr.employee'])

        # 6 months < seniority < 4 years
        sales_rep_employee.write({
            'date_version': date(2025, 7, 1),
            'contract_date_start': date(2025, 7, 1),
            'l10n_be_fictive_hire_date': date(2025, 7, 1),
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Invalid Salary Scale for Sales Representatives', sales_rep_employee)
        sales_rep_employee.write({
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_c').id,
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Invalid Salary Scale for Sales Representatives', self.env['hr.employee'])

        # 4 years < seniority
        sales_rep_employee.write({
            'date_version': date(2019, 7, 1),
            'contract_date_start': date(2019, 7, 1),
            'l10n_be_fictive_hire_date': date(2019, 7, 1),
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Invalid Salary Scale for Sales Representatives', sales_rep_employee)
        sales_rep_employee.write({
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_d').id,
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Invalid Salary Scale for Sales Representatives', self.env['hr.employee'])

        # No contract, no warning
        sales_rep_employee.write({
            'contract_date_start': False,
            'l10n_be_fictive_hire_date': False,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_a').id,
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Invalid Salary Scale for Sales Representatives', self.env['hr.employee'])

    def test_unknown_salary_scale_warning(self):
        def unknown_scale_employees():
            warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
            cards = self.env['hr.payroll.warning'].get_payroll_dashboard_warning_cards(warning_ids)
            return next((card['warning_records'] for card in cards if card['name'] == 'Unknown Salary Scale'), self.env['hr.employee'])

        employee = self.create_employee({'l10n_be_salary_scale_id': False})
        self.assertIn(employee, unknown_scale_employees())

        employee.l10n_be_salary_scale_id = self.env.ref('l10n_be_hr_payroll.salary_scale_na')
        self.assertNotIn(employee, unknown_scale_employees())

        # Only employees with a contract running in the pay period are listed
        employee.company_id.payroll_closing_date = '25'
        departed_employee = self.create_employee({
            'l10n_be_salary_scale_id': False,
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'contract_date_end': date(2024, 12, 31),
        })
        self.assertNotIn(departed_employee, unknown_scale_employees())
        employee_without_contract = self.create_employee({'l10n_be_salary_scale_id': False, 'contract_date_start': False})
        self.assertNotIn(employee_without_contract, unknown_scale_employees())

    def test_unknown_salary_scale_payslip_report(self):
        employee = self.create_employee({'l10n_be_salary_scale_id': False})
        payslip = self.env['hr.payslip'].create({
            'name': 'Unknown scale payslip',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'company_id': employee.company_id.id,
        })
        html = self.env['ir.actions.report'].with_context(lang='en_US')._render_qweb_html(
            'l10n_be_hr_payroll.report_belgium_payslip_lang', payslip.ids)[0].decode()
        self.assertIn('Salary Scale:', html)
        self.assertIn('Unknown', html)

    def test_non_matching_birthday_warning(self):
        """
        Set NISS -> birthday becomes date(1988, 1, 1) -> change birthday -> check warning is raised
        """
        self.new_employee.write({
            'niss': 88010119776,
        })
        self.new_employee.write({
            'birthday': date(1988, 1, 2),
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees with inconsistent birthday', self.new_employee)

    @freeze_time("2026-06-01")
    def test_min_wage_warning_student_non_existent_category(self):
        self.create_employee({
            'name': 'Student',
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': False,
            'birthday': date(2008, 1, 1),
            'l10n_be_dimona_category': 'stu',
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp302_cat_22').id,
        })
        # Must not raise:
        self.env['hr.employee']._get_l10n_be_min_wage_invalid_employees()

    def test_mobility_budget_and_not_eco_vehicle_warning(self):
        brand = self.env['fleet.vehicle.model.brand'].sudo().create({'name': "Test Brand"})
        model = self.env['fleet.vehicle.model'].sudo().create({'name': "Test Model", 'brand_id': brand.id})
        car = self.env['fleet.vehicle'].sudo().create({
            'name': "Not Eco-Friendly Car",
            'license_plate': "Test Car",
            'company_id': self.belgian_company.id,
            'model_id': model.id,
            'contract_date_start': date(2020, 10, 8),
            'co2': 90.0,
            'car_value': 38000.0,
            'fuel_type': "diesel",
            'acquisition_date': date(2020, 1, 1)
        })
        self.new_employee.write({
            'car_id': car.id,
            'transport_mode_car': True,
            'l10n_be_mobility_budget': True,
        })

        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees with mobility budget and company car with CO2 > 0', self.new_employee)

    def test_missing_employer_category_warning(self):
        """ Ensure that a missing employer category is flagged both on the dashboard and on the payslip. """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.belgian_company.payroll_config_ids.l10n_be_employer_category_id = False
        config = self.belgian_company.current_payroll_config_id
        config.onss_importance_code = False
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Missing Employer Category', config)
        payslip_vals = {
            'employee_id': self.new_employee.id,
            'version_id': self.fourth_version.id,
            'date_from': date(2025, 12, 1),
            'date_to': date(2025, 12, 31),
        }
        # An unsaved payslip (form onchange) must not crash: without saved payslip, the warning answers for the dashboard
        self.env['hr.payslip'].new(payslip_vals).issues
        payslip = self.env['hr.payslip'].create(payslip_vals)
        issue_messages = [issue['message'] for issue in payslip.issues.values()]
        self.assertIn('Employer category required to import ONSS rates.', issue_messages, "The payslip should carry the warning")
        # The button action goes straight to doAction, so it must list its views
        issue = next(i for i in payslip.issues.values() if i['message'] == 'Employer category required to import ONSS rates.')
        self.assertEqual(issue['action']['views'], [[False, 'form']], "The warning action should open the config form")
        self.assertEqual(issue['action']['res_id'], payslip.payroll_config_id.id)
        # Building the action has no side effect (payroll officers only read the configuration)
        self.assertFalse(payslip.payroll_config_id.onss_importance_code)

    def test_missing_employer_category_warning_exemptions(self):
        """ Ensure that the employer category warning skips lone executive companies and old config versions. """
        exempt_company = self.env['res.company'].create({
            'name': 'Exempt Company',
            'country_id': self.env.ref('base.be').id,
        })
        companies = self.belgian_company | exempt_company
        self.env.user.company_ids |= exempt_company
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=companies.ids, hr_payroll_force_compute_issue=True))
        exec_employee = self.env['hr.employee'].create({
            'name': 'Lone Executive',
            'company_id': exempt_company.id,
            'employee_type_id': self.env.ref('hr.contract_type_company_executive').id,
        })
        # An old 2020 version is added so the company has a past config too
        self.belgian_company.create_payroll_config(date(2020, 1, 1))
        companies.payroll_config_ids.l10n_be_employer_category_id = False
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Missing Employer Category', self.belgian_company.current_payroll_config_id)
        # The lone executive payslip is ONSS exempt, so it must stay clean
        exempt_payslip = self.env['hr.payslip'].with_company(exempt_company).create({
            'employee_id': exec_employee.id, 'date_from': date(2025, 12, 1), 'date_to': date(2025, 12, 31),
        })
        issue_messages = [issue['message'] for issue in (exempt_payslip.issues or {}).values()]
        self.assertNotIn(
            'Employer category required to import ONSS rates.', issue_messages,
            "The ONSS exempt payslip should not carry the warning",
        )
        # Once the current version is set, the old empty one must not show on the dashboard
        category = self.env['l10n.be.employer.category'].search([], limit=1)
        self.belgian_company.current_payroll_config_id.l10n_be_employer_category_id = category
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Missing Employer Category', self.env['payroll.config.settings'])

    @freeze_time("2026-11-03")
    def test_missing_employer_category_warning_ended_configuration(self):
        """ The payslips are checked on the configuration of their period, even once it ended: the dashboard only
        shows the current and future configurations. """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        old_config = self.belgian_company._get_payroll_config(date(2026, 10, 1))
        old_config.copy({'date_version': date(2026, 11, 1)})
        old_config.l10n_be_employer_category_id = False
        self.assertEqual(old_config.date_end, date(2026, 10, 31))
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.new_employee.id,
            'version_id': self.fourth_version.id,
            'date_from': date(2026, 10, 1),
            'date_to': date(2026, 10, 31),
        })
        self.assertEqual(payslip.payroll_config_id, old_config)
        issue_messages = [issue['message'] for issue in payslip.issues.values()]
        self.assertIn('Employer category required to import ONSS rates.', issue_messages)
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Missing Employer Category', self.env['payroll.config.settings'])

    def _get_dmfa_submission_cards(self):
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        warnings = self.env['hr.payroll.warning'].get_payroll_dashboard_warning_cards(warning_ids)
        return [warning for warning in warnings if warning['name'].startswith('DMFA Submission')]

    @freeze_time("2026-03-20")
    def test_dmfa_submission_warning_current_quarter(self):
        # The current quarter can't be declared yet
        self.env.company.first_payrun_date = date(2026, 1, 15)
        self.assertEqual(self._get_dmfa_submission_cards(), [])

    @freeze_time("2026-04-10")
    def test_dmfa_submission_warning_ended_quarter(self):
        # An ended quarter is declared until the last day of the following month
        self.env.company.first_payrun_date = date(2026, 3, 15)
        cards = self._get_dmfa_submission_cards()
        self.assertEqual([card['name'] for card in cards], ['DMFA Submission 2026 Q1'])
        self.assertEqual(str(cards[0]['warning_date']), '2026-04-30')

    def test_public_holidays_after_end_of_contract(self):
        """
        Public holidays after the end of the contract (loi du 4 janvier 1974, art. 14): only when the employer ends
        the contract, except for a serious misconduct. Nothing with less than 15 days of service at the end of the
        contract, those within 14 days with less than one month, within 30 days beyond, from the end of the period
        covered by the indemnity for the notice not worked. The holidays are stored in UTC from midnight in Brussels.
        """
        self.belgian_company.tz = 'Europe/Brussels'

        def public_holiday(day):
            def to_utc(local_datetime):
                return local_datetime.replace(tzinfo=ZoneInfo('Europe/Brussels')).astimezone(UTC).replace(tzinfo=None)
            return self.env['resource.calendar.leaves'].create({
                'name': f'Public holiday {day}',
                'company_id': self.belgian_company.id,
                'calendar_id': self.belgian_company.resource_calendar_id.id,
                'date_from': to_utc(datetime.combine(day, time(0, 0))),
                'date_to': to_utc(datetime.combine(day, time(23, 59, 59))),
                'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
            })

        def upcoming_count(contract_start, contract_end, holidays, reason='hr.departure_fired'):
            employee = self.create_employee({
                'name': 'Short contract',
                'date_version': contract_start,
                'contract_date_start': contract_start,
                'contract_date_end': contract_end,
                'fixed_term': True,
            })
            employee.departure_reason_id = self.env.ref(reason)
            payslip = self.env['hr.payslip'].create({
                'employee_id': employee.id,
                'date_from': contract_end.replace(day=1),
                'date_to': contract_end + relativedelta(day=31),
            })
            return payslip._get_upcoming_public_holiday_count(holidays)

        # 10 days of service: no right, even 20 days after the hire
        self.assertEqual(upcoming_count(date(2026, 7, 1), date(2026, 7, 10), public_holiday(date(2026, 7, 21))), 0)
        # 20 days of service: the holidays within 14 days of the end
        self.assertEqual(upcoming_count(date(2026, 10, 1), date(2026, 10, 20), public_holiday(date(2026, 11, 4))), 0)
        self.assertEqual(upcoming_count(date(2026, 10, 1), date(2026, 10, 20), public_holiday(date(2026, 11, 3))), 1)
        # more than one month of service: the holidays within 30 days of the end
        self.assertEqual(upcoming_count(date(2026, 9, 1), date(2026, 10, 20), public_holiday(date(2026, 11, 19))), 1)
        self.assertEqual(upcoming_count(date(2026, 9, 1), date(2026, 10, 20), public_holiday(date(2026, 11, 20))), 0)
        # the day after the end, in Brussels time
        self.assertEqual(upcoming_count(date(2026, 9, 1), date(2026, 10, 20), public_holiday(date(2026, 10, 21))), 1)
        # no right after a resignation, a dismissal for serious misconduct or the end of a fixed term
        holiday = public_holiday(date(2026, 10, 22))
        for reason in (
            'hr.departure_resigned',
            'l10n_be_hr_payroll.departure_fired_serious_misconduct',
            'l10n_be_hr_payroll.departure_contract_end_fixed_term',
        ):
            self.assertEqual(upcoming_count(date(2026, 9, 1), date(2026, 10, 20), holiday, reason=reason), 0, reason)

        # dismissal with an indemnity for the notice not worked: the 30 days follow the period covered by it
        employee = self.create_employee({
            'name': 'Dismissed',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
        })
        departure = self.env['hr.employee.departure'].create({
            'departure_description': 'Dismissed',
            'employee_id': employee.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': date(2026, 9, 30),
        })
        departure.l10n_be_notice_respect = 'without'
        departure.action_register()
        notice_end = departure.l10n_be_notice_period_theoretical_end
        self.assertGreater(notice_end, employee.departure_date + relativedelta(days=30))
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': employee.departure_date.replace(day=1),
            'date_to': employee.departure_date + relativedelta(day=31),
        })
        holidays = public_holiday(notice_end + relativedelta(days=10)) | public_holiday(notice_end + relativedelta(days=40))
        self.assertEqual(payslip._get_upcoming_public_holiday_count(holidays), 1)

    def _get_report_cards(self, company, prefix):
        warning_model = self.env['hr.payroll.warning'].with_company(company)
        warning_ids = warning_model.get_payroll_dashboard_data()['warning_ids']
        warnings = warning_model.get_payroll_dashboard_warning_cards(warning_ids)
        return [warning for warning in warnings if warning['name'].startswith(prefix)]

    @freeze_time("2026-02-10")
    def test_274_warning_with_branches(self):
        # The 274 of the employees of the branches is declared by the root company
        root, branch = self.multibranch_company[:2]
        self.env.user.company_ids |= self.multibranch_company
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=self.multibranch_company.ids))
        root.first_payrun_date = date(2026, 1, 1)
        employee = self.create_employee({
            'company_id': branch.id,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
        })
        self.create_and_validate_payslips(employee, 2026, 1)

        for company in (root, branch):
            with self.subTest(company=company.name):
                cards = self._get_report_cards(company, 'Withholding taxes:')
                self.assertEqual([card['name'] for card in cards], ['Withholding taxes: Jan 2026'])

        # Starting the declaration from the branch creates the one of the root company
        card = self._get_report_cards(branch, 'Withholding taxes:')[0]
        action = self.env['hr.payroll.warning'].with_company(branch).with_context(
            **card['button_action']['context'],
        ).action_l10n_be_report_warning()
        report = self.env['l10n_be.274_xx'].browse(action['params']['report_id'])
        self.assertEqual(report.company_id, root)
        self.assertEqual((report.month, report.year), ('1', 2026))

    @freeze_time("2026-02-10")
    def test_274_warning_first_payrun_date_on_branch(self):
        # The first payrun date can be set on a branch only
        root, branch = self.multibranch_company[:2]
        self.env.user.company_ids |= self.multibranch_company
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=self.multibranch_company.ids))
        root.first_payrun_date = False
        branch.first_payrun_date = date(2026, 1, 1)
        self.assertFalse(root.first_payrun_date)
        employee = self.create_employee({
            'company_id': branch.id,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
        })
        self.create_and_validate_payslips(employee, 2026, 1)

        for company in (root, branch):
            with self.subTest(company=company.name):
                cards = self._get_report_cards(company, 'Withholding taxes:')
                self.assertEqual([card['name'] for card in cards], ['Withholding taxes: Jan 2026'])

    @freeze_time("2026-02-10")
    def test_payslips_without_dimona_refused_declaration(self):
        # A Dimona refused by the ONSS doesn't declare the employment
        employee = self.create_employee({
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
        })
        self.create_and_validate_payslips(employee, 2026, 1)
        declaration = self.env['l10n.be.dimona.declaration'].create({
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'content': {'dimonaIn': {'startDate': '2026-01-01'}, 'declarationStatus': {'result': 'B'}},
        })
        self.assertEqual((declaration.state, declaration.date_start), ('B', date(2026, 1, 1)))

        def flagged_employees():
            cards = self._get_report_cards(self.belgian_company, 'Payslips Without Dimona')
            return cards[0]['warning_records'] if cards else self.env['hr.employee']

        self.assertIn(employee, flagged_employees())
        declaration.content = {'dimonaIn': {'startDate': '2026-01-01'}, 'declarationStatus': {'result': 'A'}}
        self.assertEqual(declaration.state, 'A')
        self.assertNotIn(employee, flagged_employees())

    def test_paid_time_off_allocation_warning_after_new_year(self):
        # The allocations of the new year are due once the December payrun is closed, and are still
        # missing at the beginning of January
        employee = self.create_employee({
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
        })
        self.env['hr.payslip.run'].create({
            'name': 'December 2026',
            'company_id': self.belgian_company.id,
            'date_start': date(2026, 12, 1),
            'date_end': date(2026, 12, 31),
        }).state = '02_close'

        for today in ('2026-12-28', '2027-01-05'):
            with self.subTest(today=today), freeze_time(today):
                cards = self._get_report_cards(self.belgian_company, 'Employees require paid time off allocation')
                self.assertEqual([card['name'] for card in cards], ['Employees require paid time off allocation for 2027'])
                self.assertIn(employee, cards[0]['warning_records'])

    @freeze_time("2026-10-10")
    def test_company_configuration_warnings_ignore_ended_configurations(self):
        # Only the current and future configurations of the company are checked
        company = self.belgian_company
        old_config = company._get_payroll_config(date(2026, 1, 1))
        new_config = old_config.copy({'date_version': date(2026, 6, 1)})
        old_config.l10n_be_employer_category_id = False
        self.assertEqual(old_config.date_end, date(2026, 5, 31))
        self.assertTrue(new_config.l10n_be_employer_category_id)

        for warning_name in ('Configure your company', 'Missing Employer Category'):
            with self.subTest(warning=warning_name):
                cards = [card for card in self._get_report_cards(company, warning_name) if card['name'] == warning_name]
                records = cards[0]['warning_records'] if cards else self.env['payroll.config.settings']
                self.assertNotIn(old_config, records)

    def _get_employees_without_allocation_warning_records(self):
        self.env.invalidate_all()  # allocations_count is not stored: as in a new request
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        cards = self.env['hr.payroll.warning'].get_payroll_dashboard_warning_cards(warning_ids)
        return self.env['hr.employee'].union(
            card['warning_records'] for card in cards
            if card['name'] == 'Employees Without Time Off Allocation'
        )

    @freeze_time("2026-06-01")
    def test_employee_without_time_off_allocation_warning(self):
        employee = self.create_employee({
            'name': 'No Allocation',
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': False,
        })
        self.assertIn(employee, self._get_employees_without_allocation_warning_records())

        # an expired or a future allocation does not count
        allocations = self.env['hr.leave.allocation'].create([{
            'name': 'Allocation',
            'employee_id': employee.id,
            'work_entry_type_id': self.holiday_work_entry_types.id,
            'number_of_days': 20,
            'date_from': date_from,
            'date_to': date_to,
        } for date_from, date_to in [(date(2025, 1, 1), date(2025, 12, 31)), (date(2027, 1, 1), date(2027, 12, 31))]])
        allocations.action_approve()
        self.assertIn(employee, self._get_employees_without_allocation_warning_records())

        self.env['hr.leave.allocation'].create({
            'name': 'Allocation',
            'employee_id': employee.id,
            'work_entry_type_id': self.holiday_work_entry_types.id,
            'number_of_days': 20,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 12, 31),
        }).action_approve()
        self.assertNotIn(employee, self._get_employees_without_allocation_warning_records())

    @freeze_time("2026-06-01")
    def test_employee_without_time_off_allocation_warning_accrual(self):
        """ An accrual allocation that has not accrued any day yet is still an allocation. """
        employee = self.create_employee({
            'name': 'Accrual Allocation',
            'date_version': date(2026, 5, 1),
            'contract_date_start': date(2026, 5, 1),
            'contract_date_end': False,
        })
        accrual_plan = self.env['hr.leave.accrual.plan'].create({
            'name': 'Yearly accrual',
            'work_entry_type_id': self.holiday_work_entry_types.id,
            'accrued_gain_time': 'end',
            'level_ids': [(0, 0, {
                'added_value': 20,
                'added_value_type': 'day',
                'frequency': 'yearly',
            })],
        })
        allocation = self.env['hr.leave.allocation'].create({
            'name': 'Accrual Allocation',
            'employee_id': employee.id,
            'work_entry_type_id': self.holiday_work_entry_types.id,
            'accrual_plan_id': accrual_plan.id,
            'number_of_days': 0,
            'date_from': date(2026, 5, 1),
        })
        allocation.action_approve()
        self.assertEqual(allocation.state, 'validate')
        self.assertEqual(employee.allocation_display, '0')
        self.assertNotIn(employee, self._get_employees_without_allocation_warning_records())

    @freeze_time("2026-06-01")
    def test_employee_without_time_off_allocation_warning_not_applicable(self):
        no_contract_employee, director, ended_contract_employee, future_employee = self.create_employee([
            {
                'name': 'No Contract Yet',
                'contract_date_start': False,
            },
            {
                'name': 'Director',
                'date_version': date(2026, 1, 1),
                'contract_date_start': date(2026, 1, 1),
                'contract_date_end': False,
                'employee_type_id': self.env.ref("hr.contract_type_company_executive").id,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            },
            {
                'name': 'Ended Contract',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': date(2026, 3, 31),
            },
            {
                'name': 'Future Employee',
                'date_version': date(2026, 7, 1),
                'contract_date_start': date(2026, 7, 1),
                'contract_date_end': False,
            },
        ])
        warning_records = self._get_employees_without_allocation_warning_records()
        self.assertFalse(warning_records & (no_contract_employee | director | ended_contract_employee | future_employee))

    def test_extra_legal_leave_with_available_paid_time_off_warning(self):
        """ The extra legal time off of an employee who still has paid time off are flagged, with one balance
        computation per start date whatever the number of time off """
        legal = self.env.ref('hr_work_entry.be_work_entry_type_legal_leave')
        extra_legal = self.env.ref('hr_work_entry.l10n_be_work_entry_type_extra_legal')
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_work_entry_type_change')
        employees = self.create_employee([{
            'name': f'Extra Legal {i}', 'date_version': date(2026, 1, 1), 'contract_date_start': date(2026, 1, 1),
        } for i in range(4)])
        for employee, days in zip(employees, (20, 20, 20, 0), strict=True):
            for work_entry_type, number_of_days in ((legal, days), (extra_legal, 10)):
                if number_of_days:
                    self.env['hr.leave.allocation'].create({
                        'employee_id': employee.id, 'work_entry_type_id': work_entry_type.id,
                        'number_of_days': number_of_days,
                        'date_from': date(2026, 1, 1), 'date_to': date(2026, 12, 31),
                    }).action_approve()
        leaves = self.env['hr.leave'].create([{
            'employee_id': employee.id, 'work_entry_type_id': extra_legal.id,
            'request_date_from': day, 'request_date_to': day,
        } for employee in employees for day in (date(2026, 10, 2), date(2026, 10, 5))])
        self.env.flush_all()
        self.env.invalidate_all()

        with self.assertQueryCount(__system__=58):
            records = warning._get_warning_python_records(localdict={'active_ids': leaves.ids, 'records': leaves})[0]
        self.assertEqual(records, leaves.filtered(lambda leave: leave.employee_id != employees[3]))

    def test_configure_company_warning_missing_sector(self):
        """The "Configure your company" warning reports a configuration without sector."""
        company = self.create_belgian_company()
        config = company.payroll_config_ids
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_missing_company_setting')
        PayrollWarning = self.env['hr.payroll.warning'].with_company(company)

        cards = PayrollWarning.get_payroll_dashboard_warning_cards(warning.ids)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['warning_records'], config)

        config.l10n_be_sector = 'private'
        self.assertFalse(PayrollWarning.get_payroll_dashboard_warning_cards(warning.ids))

    def test_configure_company_warning_on_branch(self):
        """A branch is not warned about the fields it takes from its head office."""
        head_office, branch = self.create_multibranch_company(depth=2)
        # The main joint committee is only checked once the branch has employees.
        self.env['hr.employee'].with_company(branch).create({'name': 'Branch Employee', 'company_id': branch.id})
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_missing_company_setting')
        PayrollWarning = self.env['hr.payroll.warning']

        cards = PayrollWarning.with_company(head_office).get_payroll_dashboard_warning_cards(warning.ids)
        self.assertEqual(cards[0]['warning_records'], head_office.payroll_config_ids)
        self.assertFalse(PayrollWarning.with_company(branch).get_payroll_dashboard_warning_cards(warning.ids))

        branch.payroll_config_ids.l10n_be_main_joint_committee = False
        cards = PayrollWarning.with_company(branch).get_payroll_dashboard_warning_cards(warning.ids)
        self.assertEqual(cards[0]['warning_records'], branch.payroll_config_ids)
