# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, timedelta

from freezegun import freeze_time

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import SQL

from odoo.addons.hr_timesheet.tests.test_timesheet import TestCommonTimesheet
from odoo.addons.hr.tests.test_utils import get_admin_employee


@tagged('-at_install', 'post_install')
class TestRecordTime(TestCommonTimesheet, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env['project.project'].create({
            'name': 'Test Project'
        })

        cls.admin_employee = get_admin_employee(cls.env)

    def test_timesheet_overtime(self):
        flexible_calendar = self.env['resource.calendar'].create({
            'name': 'Flexible Calendar',
            'calendar_type': 'undefined',
            'attendance_ids': [],
            'hours_per_week': 40,
            'hours_per_day': 8
        })
        self.empl_employee.write({
            'resource_calendar_id': flexible_calendar.id,
        })
        # Get this week's Monday (or next Monday if today is Sunday)
        relevant_monday = date.today() + timedelta(
            days=-date.today().weekday() + (7 if date.today().weekday() == 6 else 0)
        )
        timesheets = self.env['account.analytic.line'].create([
            {
                'name': f"Test Timesheet {i+1}",
                'project_id': self.project_customer.id,
                'task_id': self.task1.id,
                'date': relevant_monday - timedelta(days=i),
                'unit_amount': 3.0 + i,
                'employee_id': self.empl_employee.id,
            }
            for i in range(8)
        ])

        self.start_tour('/odoo', 'timesheet_overtime_hour_encoding', login=self.user_employee.login, timeout=100)

        timesheets[6].write({'unit_amount': 0.0})

        self.env['res.config.settings'].create({'timesheet_encode_method': 'days'}).execute()
        self.start_tour('/odoo', 'timesheet_overtime_day_encoding', login=self.user_employee.login, timeout=100)

    def test_timesheet_tour(self):
        self.start_tour("/odoo", "timesheet_tour", login=self.user_manager.login)

    def test_timesheet_availabilty_days(self):
        # Create company
        company = self.env['res.company'].create({'name': 'New Test Company'})

        # Create user
        test_user = self.env['res.users'].create({
            'name': 'Test User',
            'login': 'test_user',
            'email': 'test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
            'company_ids': [(6, 0, [company.id])],
            'company_id': company.id,
        })

        # Create employee linked to user
        flexible_calendar = self.env['resource.calendar'].create({
            'name': 'Flexible Calendar',
            'calendar_type': 'undefined',
            'attendance_ids': [],
            'hours_per_week': 8,
            'hours_per_day': 8,
            'company_id': company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'Test Employee',
            'user_id': test_user.id,
            'company_id': company.id,
            'resource_calendar_id': flexible_calendar.id,
        })

        # Ensure company calendar is NOT flexible (to avoid global override)
        company.resource_calendar_id = self.env['resource.calendar'].create({
            'name': 'Company Calendar (Rigid)',
        })

        # Call grid_unavailability() with the employee
        unavailable_days = self.env['account.analytic.line'].with_user(test_user).with_company(company).grid_unavailability(
            date.today(),
            date.today() + timedelta(days=7)
        )

        # No unavailable days for flexible schedule in my Timesheet
        self.assertFalse(len(unavailable_days[False]))

        # Call again, this time with groupby='employee_id'
        unavailable_days = self.env['account.analytic.line'].with_company(company).grid_unavailability(
            date.today(),
            date.today() + timedelta(days=7),
            groupby='employee_id',
            res_ids=[employee.id]
        )

        # Company availability
        self.assertTrue(len(unavailable_days[False]))
        self.assertFalse(unavailable_days[employee.id])

    def test_timer_onchange_project_prefills_recent_task(self):
        """Selecting a project in the timer prefills the most recent eligible task the user logged time on."""
        Timesheet = self.env['account.analytic.line'].with_user(self.user_employee)
        timesheet = self.env['account.analytic.line'].create({
            'name': '/',
            'date': date.today() - timedelta(days=60),
            'project_id': self.project_customer.id,
            'task_id': self.task1.id,
            'employee_id': self.empl_employee.id,
            'unit_amount': 1.0,
        })

        line = Timesheet.with_context(timesheet_timer_search=True).new({'project_id': self.project_customer.id})
        line._onchange_project_id()
        self.assertFalse(line.task_id, "The timer should not prefill a task that is no longer relevant")

        timesheet.date = date.today()
        line = Timesheet.with_context(timesheet_timer_search=True).new({'project_id': self.project_customer.id})
        line._onchange_project_id()
        self.assertEqual(line.task_id, self.task1,
                         "The timer should prefill the task the user recently logged time on")

        line = Timesheet.new({'project_id': self.project_customer.id})
        line._onchange_project_id()
        self.assertFalse(line.task_id, "Selecting a project only prefills a task in the timer")

        timesheet.task_id = False
        line = Timesheet.with_context(timesheet_timer_search=True).new({'project_id': self.project_customer.id})
        line._onchange_project_id()
        self.assertFalse(line.task_id, "The timer should prefill no task when the last timesheet has none")

    @freeze_time('2026-07-13 00:30:00')  # 00:30 UTC == 20:30 the previous day in America/Guadeloupe (UTC-4)
    def test_systray_timer_survives_utc_midnight(self):
        """A running timer stays visible in the systray after the server's UTC clock
        passes midnight while it is still the previous day in the user's timezone."""
        self.user_employee.tz = 'America/Guadeloupe'
        self.user_employee.password = self.user_employee.login
        self.authenticate(self.user_employee.login, self.user_employee.login)
        running = self.env['account.analytic.line'].create({
            'name': '/',
            'project_id': self.project_customer.id,
            'employee_id': self.empl_employee.id,
            'date': date(2026, 7, 12),
            'unit_amount': 0.0,
        })
        result = self.make_jsonrpc_request('/timesheet_grid/timesheet_systray_user_data', params={})
        self.assertIn(running.id, [ts['id'] for ts in result['timesheets']['records']])

    @freeze_time('2026-07-13 12:00:00')
    def test_systray_multi_company(self):
        """The systray and its timer only use the timesheets of the companies selected in the
        company switcher, not those of every company the user is allowed in."""
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'Company B'})
        self.user_employee.company_ids = [Command.link(company_b.id)]
        employee_b = self.env['hr.employee'].create({
            'name': 'User Empl Employee B',
            'user_id': self.user_employee.id,
            'company_id': company_b.id,
        })
        project_b = self.env['project.project'].create({
            'name': 'Project B',
            'allow_timesheets': True,
            'company_id': company_b.id,
        })
        self.timesheet.unlink()
        timesheet_a, timesheet_b = self.env['account.analytic.line'].create([{
            'name': '/',
            'project_id': self.project_customer.id,
            'employee_id': self.empl_employee.id,
            'date': date(2026, 7, 13),
        }, {
            'name': '/',
            'project_id': project_b.id,
            'employee_id': employee_b.id,
            'date': date(2026, 7, 13),
        }])
        self.assertEqual(timesheet_b.company_id, company_b, "The timesheet should take the company of its project")
        # create_date comes from the database clock, which freeze_time does not affect
        self.env.cr.execute(SQL(
            "UPDATE account_analytic_line SET create_date = '2026-07-13 11:30:00' WHERE id = %s", timesheet_a.id,
        ))
        self.env.cr.execute(SQL(
            "UPDATE account_analytic_line SET create_date = '2026-07-13 11:50:00' WHERE id = %s", timesheet_b.id,
        ))
        (timesheet_a | timesheet_b).invalidate_recordset(['create_date'])

        self.user_employee.password = self.user_employee.login
        self.authenticate(self.user_employee.login, self.user_employee.login)
        for company, employee, timesheet, elapsed_seconds in (
            (company_a, self.empl_employee, timesheet_a, 1800),
            (company_b, employee_b, timesheet_b, 600),
        ):
            with self.subTest(company=company.name):
                params = {'context': {'allowed_company_ids': company.ids}}
                result = self.make_jsonrpc_request('/timesheet_grid/timesheet_systray_user_data', params=params)
                self.assertEqual(result['employee']['id'], employee.id,
                                 "The systray should use the user's employee of the selected company")
                self.assertEqual([ts['id'] for ts in result['timesheets']['records']], timesheet.ids,
                                 "The systray should only list the timesheets of the selected company")
                result = self.make_jsonrpc_request('/timesheet_grid/get_timer_start_time', params=params)
                self.assertEqual(result['elapsed_seconds'], elapsed_seconds,
                                 "The timer should resume from the last timesheet of the selected company")

        result = self.make_jsonrpc_request('/timesheet_grid/timesheet_systray_user_data', params={
            'context': {'allowed_company_ids': (company_a | company_b).ids},
        })
        self.assertCountEqual([ts['id'] for ts in result['timesheets']['records']], (timesheet_a | timesheet_b).ids,
                              "The systray should list the timesheets of every selected company")
