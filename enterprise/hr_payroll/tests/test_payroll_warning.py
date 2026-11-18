# Part of Odoo. See LICENSE file for full copyright and licensing details.

import ast
import re
from datetime import date
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.tests import tagged, TransactionCase


@tagged('-at_install', 'post_install')
class TestPayrollWarning(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.test_company = self.env['res.company'].create({
            'name': 'Test Company',
            'first_payrun_date': date(2025, 1, 1),
            'payroll_closing_date': '25',
        })
        self.monthly_structure_type = self.env['hr.payroll.structure.type'].create({
            'name': 'Monthly Structure Type',
            'default_schedule_pay': 'monthly',
        })
        self.will_byers = self.env['hr.employee'].create({
            'name': 'Will Byers',
            'company_id': self.test_company.id,
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': False,
            'structure_type_id': self.monthly_structure_type.id
        })
        self.Warning = self.env['hr.payroll.warning']

    @freeze_time('2025-11-14')
    def test_company_monthly_closing_date(self):
        closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        self.assertEqual(closing_date, date(2025, 11, 25), "Computed monthly closing date should match payroll_closing_date")

    @freeze_time('2025-11-26')
    def test_company_monthly_closing_date_rollover(self):
        closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        self.assertEqual(closing_date, date(2025, 12, 25), "Closing date should roll to next month when today is past the closing date")

    @freeze_time('2025-11-14')
    def test_company_monthly_closing_date_for_next_month(self):
        self.test_company.write({'payroll_closing_date': '5'})
        closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        self.assertEqual(closing_date, date(2025, 12, 5), "Closing date should be computed in the next month for early closing days")

    @freeze_time('2026-4-3')
    def test_company_monthly_closing_date_for_next_month_date(self):
        self.test_company.write({'payroll_closing_date': '5'})
        closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        self.assertEqual(closing_date, date(2026, 4, 5), "Closing date should be computed in the same month if today < closing day")

    @freeze_time('2025-11-14')
    def test_warning_date_before_next_payslip(self):
        warning = self.Warning.create({
            'name': 'Test Warning',
            'warning_type': 'domain',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_domain': "[('id', '=', %d)]" % self.will_byers.id,
            'closing_on': 'next_payslip',
            'warning_offset_days': -5,
        })
        monthly_closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        warning_date = warning._get_warning_date(self.will_byers, monthly_closing_date)
        self.assertEqual(warning_date, date(2025, 11, 20), "Warning date should be 5 days before the closing date")

    @freeze_time('2025-11-14')
    def test_warning_date_after_next_payslip(self):
        warning = self.Warning.create({
            'name': 'After Payslip Warning',
            'warning_type': 'domain',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_domain': "[('id', '=', %d)]" % self.will_byers.id,
            'closing_on': 'next_payslip',
            'warning_offset_days': 3,
        })
        monthly_closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        warning_date = warning._get_warning_date(self.will_byers, monthly_closing_date)
        self.assertEqual(warning_date, date(2025, 11, 28), "Warning date should be 3 days after the closing date")

    @freeze_time('2025-11-14')
    def test_warning_date_before_contract_start(self):
        warning = self.Warning.create({
            'name': 'Before Contract Start Warning',
            'warning_type': 'domain',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_domain': "[('id', '=', %d)]" % self.will_byers.id,
            'closing_on': 'contract_start',
            'warning_offset_days': -7,
        })
        monthly_closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        warning_date = warning._get_warning_date(self.will_byers, monthly_closing_date)
        self.assertEqual(warning_date, date(2024, 12, 25), "Warning date should be 7 days before the contract start date")

    @freeze_time('2025-11-14')
    def test_warning_date_before_contract_end(self):
        self.will_byers.write({'contract_date_end': date(2025, 12, 31)})
        warning = self.Warning.create({
            'name': 'Before Contract End Warning',
            'warning_type': 'domain',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_domain': "[('id', '=', %d)]" % self.will_byers.id,
            'closing_on': 'contract_end',
            'warning_offset_days': -5,
        })
        monthly_closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        warning_date = warning._get_warning_date(self.will_byers, monthly_closing_date)
        self.assertEqual(warning_date, date(2025, 12, 26), "Warning date should be 5 days before the contract end date")

    def test_filter_warning_records_by_contract_period(self):
        ended_employee, rehired_employee = self.env['hr.employee'].create([{
            'name': 'Jim Hopper',
            'company_id': self.test_company.id,
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'contract_date_end': date(2025, 6, 30),
            'structure_type_id': self.monthly_structure_type.id,
        }, {
            'name': 'Joyce Byers',
            'company_id': self.test_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 12, 31),
            'structure_type_id': self.monthly_structure_type.id,
        }])
        running_version = rehired_employee.version_id
        rehired_employee.create_version({
            'date_version': date(2026, 3, 1),
            'contract_date_start': date(2026, 3, 1),
            'contract_date_end': False,
        })
        employees = self.will_byers | ended_employee
        self.assertEqual(
            self.Warning._filter_warning_records_by_contract_period(employees, date(2025, 10, 26), date(2025, 11, 25)),
            self.will_byers,
            "Only the employees with a running contract during the period should be kept",
        )
        self.assertEqual(
            self.Warning._filter_warning_records_by_contract_period(rehired_employee.version_ids, date(2025, 10, 26), date(2025, 11, 25)),
            running_version,
            "Only the versions with a running contract during the period should be kept",
        )

    def test_warning_domain_records_active_ids_restriction(self):
        eleven = self.env['hr.employee'].create({
            'name': 'Eleven',
            'company_id': self.test_company.id,
        })
        warning = self.Warning.create({
            'name': 'Active Ids Warning',
            'warning_type': 'domain',
            'country_id': self.test_company.country_id.id,
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_domain': [('id', 'in', [self.will_byers.id, eleven.id])],
        })
        self.assertEqual(
            warning._get_warning_domain_records(self.test_company),
            self.will_byers | eleven,
            "Without active_ids, every record matching the domain should be returned",
        )
        with self.assertQueryCount(0):  # If we pass records to check, no additional query should be made
            self.assertEqual(
                warning._get_warning_domain_records(self.test_company, records_to_check=self.will_byers),
                self.will_byers,
                "With active_ids, only the records within that restriction should be returned",
            )

    @freeze_time('2025-11-07')
    def test_other_schedule_closing_dates(self):
        monthly_closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        weekly_closing_date = self.Warning._get_schedule_closing_date('weekly', monthly_closing_date)
        bi_weekly_closing_date = self.Warning._get_schedule_closing_date('bi-weekly', monthly_closing_date)
        semi_monthly_closing_date = self.Warning._get_schedule_closing_date('semi-monthly', monthly_closing_date)

        self.assertEqual(weekly_closing_date, date(2025, 11, 10), "Weekly schedule should close on the next Monday")
        self.assertEqual(bi_weekly_closing_date, date(2025, 11, 17), "Bi-weekly schedule should close on the next bi-weekly Monday")
        self.assertEqual(semi_monthly_closing_date, date(2025, 11, 15), "Semi-monthly schedule should close on the 15th")

    @freeze_time('2025-11-14')
    def test_payroll_dashboard_basic_structure(self):
        warning = self.Warning.with_company(self.test_company).create({
            'name': 'Dashboard Warning',
            'warning_type': 'domain',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_domain': "[('id', '=', %d)]" % self.will_byers.id,
            'closing_on': 'next_payslip',
            'warning_offset_days': 0,
            'warning_color_class': 'warning',
        })

        monthly_closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        warning_date = warning._get_warning_date(self.will_byers, monthly_closing_date)
        dashboard_data = self.Warning.with_company(self.test_company).get_payroll_dashboard_data()
        self.assertIn(warning.id, dashboard_data['warning_ids'])

        warning_entry = self.Warning.with_company(self.test_company).get_payroll_dashboard_warning_cards([warning.id])[0]

        self.assertEqual(warning_entry['key'], f"monthly_{warning.id}", "Dashboard warning key should use the schedule prefix")
        self.assertEqual(warning_entry['warning_date'], warning_date, "Dashboard warning date should match the computed warning date")
        self.assertEqual(warning_entry['count'], 1, "Dashboard warning count should have the matching records")
        self.assertEqual(warning_entry['structure_type_suffix'], '', "Monthly schedule should not display a structure type suffix")
        self.assertEqual(warning_entry['color_class'], 'warning', "Dashboard warning color should match the warning configuration")
        self.assertIn(self.will_byers, warning_entry['warning_records'], "Dashboard warning records should include the employee")
        self.assertEqual(
            warning_entry['button_action']['res_id'],
            self.will_byers.id,
            "Dashboard warning action should target the matching record",
        )

        second_employee = self.env['hr.employee'].create({
            'name': 'Second Employee',
            'company_id': self.test_company.id,
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': False,
            'structure_type_id': self.monthly_structure_type.id
        })
        warning.warning_domain = f"[('id', 'in', {self.will_byers.id, second_employee.id})]"
        monthly_closing_date = self.test_company._get_monthly_payroll_next_closing_date()
        warning_date = warning._get_warning_date(self.will_byers, monthly_closing_date)
        dashboard_data = self.Warning.with_company(self.test_company).get_payroll_dashboard_data()
        self.assertIn(warning.id, dashboard_data['warning_ids'])

        warning_entry = self.Warning.with_company(self.test_company).get_payroll_dashboard_warning_cards([warning.id])[0]

        self.assertEqual(warning_entry['key'], f"monthly_{warning.id}", "Dashboard warning key should use the schedule prefix")
        self.assertEqual(warning_entry['warning_date'], warning_date, "Dashboard warning date should match the computed warning date")
        self.assertEqual(warning_entry['count'], 2, "Dashboard warning count should have the matching records")
        self.assertEqual(warning_entry['structure_type_suffix'], '', "Monthly schedule should not display a structure type suffix")
        self.assertEqual(warning_entry['color_class'], 'warning', "Dashboard warning color should match the warning configuration")
        self.assertIn(self.will_byers, warning_entry['warning_records'], "Dashboard warning records should include the employee")
        self.assertIn(second_employee, warning_entry['warning_records'], "Dashboard warning records should include the employee")
        self.assertEqual(
            warning_entry['button_action']['domain'],
            [('id', 'in', [second_employee.id, self.will_byers.id])],
            "Dashboard warning action should target the matching records",
        )

    @freeze_time("2025-02-01")
    def test_payrun_employee_type(self):
        def _has_warning(name, warning_date):
            warnings_data = self.env['hr.payroll.warning'].with_company(self.will_byers.company_id).get_payroll_dashboard_warning_cards([])
            return any(
                warning_data['name'] == name and warning_data['warning_date'] == warning_date
                for warning_data in warnings_data
            )

        # 1. Employee type without payroll closing date
        self.will_byers.company_id.payroll_closing_date = 25
        employee_type = self.env.ref('hr.contract_type_employee')
        employee_type.payroll_closing_date = False
        self.will_byers.employee_type_id = employee_type.id
        self.assertTrue(_has_warning('Payrun: Jan 2025', date(2025, 1, 25)))

        # 2. Employee type with payroll closing date
        employee_type.payroll_closing_date = 28
        self.assertTrue(_has_warning('Start Pay run - Jan 2025 (Employee)', date(2025, 1, 28)))

    @freeze_time('2025-11-14')
    def test_payroll_dashboard_with_falsy_schedule_pay(self):
        self.monthly_structure_type.write({
            'default_schedule_pay': False,
            'country_id': False,
        })
        self.monthly_structure_type.default_schedule_pay = False
        warning = self.Warning.with_company(self.test_company).create({
            'name': 'Dashboard Warning',
            'warning_type': 'domain',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_domain': [('id', '=', self.will_byers.id)],
            'closing_on': 'next_payslip',
            'warning_offset_days': 0,
            'warning_color_class': 'warning',
        })

        dashboard_data = self.Warning.with_company(self.test_company).get_payroll_dashboard_data()
        closing_dates_data = dashboard_data['closing_dates_data']
        closing_entries = [entry for entry in closing_dates_data if not entry['schedule']]
        closing_entry = closing_entries[0]
        self.assertEqual(closing_entry['label'], ' Payrun')

        warning_entry = self.Warning.with_company(self.test_company).get_payroll_dashboard_warning_cards([warning.id])[0]
        self.assertEqual(warning_entry['structure_type_suffix'], '', "Schedule should not display a structure type suffix")

    def test_compute_issues_no_crash_with_empty_warning_records(self):
        """A warning whose python condition matches no records should not
        crash _compute_issues with
        AttributeError: 'base' object has no attribute 'version_ids'."""
        warning = self.env['hr.payroll.warning'].create({
            'name': 'Employee Model Warning',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_type': 'python',
            'evaluation_code': "pass",
        })
        version = self.will_byers.version_id
        version._compute_issues()
        self.assertFalse(warning.id in (version.issues or {}))

    def test_compute_issues_no_crash_with_empty_warning_records_on_version_model(self):
        """Same as above but for a warning whose model_name is 'hr.version',
        covering the other branch in _compute_issues."""
        warning = self.env['hr.payroll.warning'].create({
            'name': 'Test Warning on Version',
            'model_id': self.env.ref('hr.model_hr_version').id,
            'warning_type': 'python',
            'evaluation_code': "pass",
        })
        version = self.will_byers.version_id
        version._compute_issues()
        self.assertFalse(warning.id in (version.issues or {}))

    def test_employee_python_warning_custom_warning_details(self):
        """Test that Python warnings targeting hr.employee with custom warning_details are properly extracted into version.issues"""
        self.Warning.create({
            'name': 'Employee Details Warning',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'warning_type': 'python',
            'display_on_model': True,
            'active': True,
            'evaluation_code': """
warning_records = self.env['hr.employee']
warning_details = defaultdict(list)

for emp in self.env['hr.employee'].browse(active_ids):
    warning_records |= emp
    warning_details[emp].append({
        'message': 'Custom employee alert',
        'level': 'warning',
    })
""",
        })
        version = self.will_byers.version_id
        version._compute_issues()

        self.assertTrue(version.issues, "Version issues should not be empty")

        first_issue = version.issues.get('0')
        self.assertIsNotNone(first_issue, "Issue index 0 should exist in version.issues")
        self.assertEqual(first_issue.get('message'), 'Custom employee alert')
        self.assertEqual(first_issue.get('level'), 'warning')

    def test_payroll_dashboard_button_action_context_merged(self):
        action = self.env['ir.actions.act_window'].create({
            'name': 'Employees',
            'res_model': 'hr.employee',
            'context': "{'search_default_my_filter': 1, 'shared_key': 'action'}",
        })
        warning = self.Warning.with_company(self.test_company).create({
            'name': 'Context Warning',
            'warning_type': 'python',
            'model_id': self.env.ref('hr.model_hr_employee').id,
            'evaluation_code': (
                f"warning_records = model.browse({self.will_byers.id})\n"
                "additional_context = {'from_warning': True, 'shared_key': 'warning'}"
            ),
            'closing_on': 'next_payslip',
            'button_action': action.id,
        })

        warning_entry = self.Warning.with_company(self.test_company).get_payroll_dashboard_warning_cards([warning.id])[0]
        self.assertEqual(
            warning_entry['button_action']['context'],
            {'search_default_my_filter': 1, 'from_warning': True, 'shared_key': 'warning'},
            "The warning additional context should be merged into the button action context, taking precedence on conflicts",
        )

    # -------------------------------------------------------------------------
    # Untrusted bank accounts warning
    # -------------------------------------------------------------------------

    def _create_bank_account(self, employee, number='BE68539007547034', trusted=False):
        account = self.env['res.partner.bank'].create({
            'account_number': number,
            'partner_id': employee.work_contact_id.id,
            'company_id': employee.company_id.id,
            'allow_out_payment': trusted,
        })
        # just to make sure the fixture is what the test expects
        self.assertEqual(account.allow_out_payment, trusted, "The trust flag should be kept at creation")
        employee.bank_account_ids = [Command.link(account.id)]
        return account

    def _create_unpaid_bank_account(self, employee, paid_account, number='BE71096123456769'):
        """
        Create a second untrusted bank account that receives 0% of the salary, the whole salary being allocated to `paid_account`.
        """
        unpaid_account = self._create_bank_account(employee, number=number)
        employee.salary_distribution = {
            str(paid_account.id): {'amount': 100.0, 'amount_is_percentage': True, 'sequence': 1},
            str(unpaid_account.id): {'amount': 0.0, 'amount_is_percentage': True, 'sequence': 2},
        }
        return unpaid_account

    def _get_untrusted_bank_account_ids(self, companies=None):
        """
        Return the untrusted bank account ids, as seen by a user who only
        selected `companies` (the test company by default) in the company switcher.
        """
        companies = companies or self.test_company
        self.env.flush_all()
        return set(self.env['hr.employee'].with_context(allowed_company_ids=companies.ids)._get_untrusted_bank_account_ids())

    def test_untrusted_account_with_salary_is_counted(self):
        """
        An untrusted account that receives the salary must be reported.
        """
        account = self._create_bank_account(self.will_byers)

        # a single account automatically receives 100% of the salary
        self.assertEqual(account.employee_salary_amount, 100)
        self.assertFalse(account.allow_out_payment)
        self.assertIn(account.id, self._get_untrusted_bank_account_ids())

    def test_trusted_account_is_not_counted(self):
        """
        A trusted account must never be reported.
        """
        account = self._create_bank_account(self.will_byers, trusted=True)

        self.assertEqual(account.employee_salary_amount, 100)
        self.assertNotIn(account.id, self._get_untrusted_bank_account_ids())

    def test_untrusted_account_without_salary_allocation_is_not_counted(self):
        """
        An untrusted account that is not used to pay a salary (employee_salary_amount == 0) must not be reported.
        """
        paid_account = self._create_bank_account(self.will_byers)
        unpaid_account = self._create_unpaid_bank_account(self.will_byers, paid_account)

        self.assertEqual(paid_account.employee_salary_amount, 100)
        self.assertEqual(unpaid_account.employee_salary_amount, 0)

        untrusted_ids = self._get_untrusted_bank_account_ids()
        self.assertIn(paid_account.id, untrusted_ids)
        self.assertNotIn(unpaid_account.id, untrusted_ids)

    def test_archived_account_is_not_counted(self):
        """
        An archived bank account must not be reported.
        """
        account = self._create_bank_account(self.will_byers)
        self.assertIn(account.id, self._get_untrusted_bank_account_ids())

        account.action_archive()

        self.assertNotIn(account.id, self._get_untrusted_bank_account_ids())

    def test_account_of_archived_employee_is_not_counted(self):
        """
        The bank accounts of an archived employee must not be reported.
        """
        account = self._create_bank_account(self.will_byers)
        self.assertIn(account.id, self._get_untrusted_bank_account_ids())

        self.will_byers.write({'active': False})

        self.assertNotIn(account.id, self._get_untrusted_bank_account_ids())

    def test_account_of_unselected_company_is_not_counted(self):
        """
        The bank accounts of a company the user did not select (or has no access to) must not be reported.
        """
        other_company = self.env['res.company'].create({'name': 'Other Company'})
        self.env.user.company_ids |= other_company
        other_employee = self.env['hr.employee'].create({
            'name': 'Mike Wheeler',
            'company_id': other_company.id,
        })
        account = self._create_bank_account(other_employee)

        # if test company is selected the account is not visible
        self.assertNotIn(account.id, self._get_untrusted_bank_account_ids(self.test_company))
        # if other company is selected the account is reported
        self.assertIn(account.id, self._get_untrusted_bank_account_ids(other_company))

    @freeze_time('2025-11-14')
    def test_untrusted_bank_accounts_warning(self):
        """
        Only the untrusted account that receives the salary must be listed in the warning,
        the one with a 0% allocation must be ignored.
        """
        counted_account = self._create_bank_account(self.will_byers)

        eleven = self.env['hr.employee'].create({
            'name': 'Eleven',
            'company_id': self.test_company.id,
        })
        paid_account = self._create_bank_account(eleven, number='BE62510007547061', trusted=True)
        ignored_account = self._create_unpaid_bank_account(eleven, paid_account)

        self.env.flush_all()
        warning = self.env.ref('hr_payroll.hr_payroll_warning_untrusted_bank_accounts')
        results = self.Warning.with_context(allowed_company_ids=self.test_company.ids)._get_applicable_payroll_warnings(self.test_company)

        records = self.env['res.partner.bank']
        for result in results:
            if result['warning'] == warning:
                records |= result['records']

        self.assertIn(counted_account, records, "The account used to pay a salary should be reported")
        self.assertNotIn(ignored_account, records, "An account without salary allocation should be ignored")
        self.assertNotIn(paid_account, records, "A trusted account should be ignored")

    @freeze_time('2025-11-14')
    def test_email_alert_targets_flagged_employees(self):
        """The 'employee' and 'employee_manager' email alerts are sent to the employees (or
        managers) of the records flagged by the warning only, also for python warnings on another
        model than hr.employee."""
        manager = self.env['hr.employee'].create({
            'name': 'Joyce Byers',
            'company_id': self.test_company.id,
            'work_email': 'joyce@example.com',
        })
        self.will_byers.write({'work_email': 'will@example.com', 'parent_id': manager.id})
        self.env['hr.employee'].create({
            'name': 'Mike Wheeler',
            'company_id': self.test_company.id,
            'work_email': 'mike@example.com',
            'parent_id': manager.id,
        })
        warning_vals = {
            'warning_type': 'python',
            'model_id': self.env.ref('hr.model_hr_version').id,
            'country_id': False,
            'evaluation_code': f"warning_records = model.browse({self.will_byers.version_id.id})",
            'closing_on': 'next_payslip',
            # closing date 2025-11-25, warning date 2025-11-10, overdue by 4 days today
            'warning_offset_days': -15,
            'email_alert_days': 4,
            'email_message': '<p>Please check</p>',
        }
        self.Warning.create([{
            **warning_vals,
            'name': 'Employee Email Warning',
            'email_visibility_type_id': 'employee',
        }, {
            **warning_vals,
            'name': 'Manager Email Warning',
            'email_visibility_type_id': 'employee_manager',
        }])
        MailMail = self.env.registry['mail.mail']
        with patch.object(MailMail, 'send', lambda self, *args, **kwargs: None):
            self.Warning._cron_payroll_warning_email_alert()
        mails = self.env['mail.mail'].search([('subject', 'like', 'Email Warning')])
        self.assertEqual(
            set(mails.filtered(lambda m: m.subject == 'Warning Alert: Employee Email Warning').mapped('email_to')),
            {'will@example.com'},
        )
        self.assertEqual(
            set(mails.filtered(lambda m: m.subject == 'Warning Alert: Manager Email Warning').mapped('email_to')),
            {'joyce@example.com'},
        )


@tagged('-at_install', 'post_install')
class TestPayrollWarningTranslations(TransactionCase):

    def test_warning_texts_are_translated(self):
        """ The texts given to _get_payroll_translation in the code of the payroll warnings must be listed in
        _get_payroll_translation, to be exported in the translation files. """
        warning_model = self.env['hr.payroll.warning']
        texts = set()
        for code in warning_model.with_context(active_test=False).search([('evaluation_code', '!=', False)]).mapped('evaluation_code'):
            for node in ast.walk(ast.parse(code)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                func_name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
                if func_name == '_get_payroll_translation' and node.args \
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    texts.add(node.args[0].value)
        for text in texts:
            with self.subTest(text=text), self.assertNoLogs('odoo.addons.hr_payroll.models.hr_payroll_warning', level='WARNING'):
                warning_model._get_payroll_translation(text, **dict.fromkeys(re.findall(r'%\((\w+)\)', text), 1))
