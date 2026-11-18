# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.hr_holidays_gantt import _uninstall_hook


@tagged('post_install', '-at_install')
class TestTimeOffOverview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = new_test_user(cls.env, login='overview_officer', groups='hr_holidays.group_hr_holidays_user')
        cls.employee = new_test_user(cls.env, login='overview_employee', groups='hr_holidays.group_hr_holidays_employee')
        # the time off responsible group is given to the time off approvers of employees
        cls.responsible = new_test_user(cls.env, login='overview_responsible', groups='hr_holidays.group_hr_holidays_employee')
        cls.env['hr.employee'].create({'name': 'Managed Employee', 'leave_manager_id': cls.responsible.id})

    def test_overview_menu_routing(self):
        overview_server_action = self.env.ref('hr_holidays_gantt.action_hr_holidays_overview')
        self.assertEqual(self.env.ref('hr_holidays.menu_hr_holidays_dashboard').action, overview_server_action)

        # officers: editable gantt of all time off, with the scope of the read-only overview
        action = overview_server_action.with_user(self.officer).run()
        self.assertEqual(action['res_model'], 'hr.leave')
        self.assertEqual([view_type for _view_id, view_type in action['views']], ['gantt'])
        self.assertIn("('state', 'not in', ('refuse', 'cancel'))", action['domain'])
        self.assertIn("('employee_id.active', '=', True)", action['domain'])
        self.assertFalse([key for key in action['context'] if key.startswith('search_default_')])

        # approvers without the officer right and employees: unchanged read-only overview
        self.assertTrue(self.responsible.has_group('hr_holidays.group_hr_holidays_responsible'))
        for user in self.responsible + self.employee:
            action = overview_server_action.with_user(user).run()
            self.assertEqual(action['res_model'], 'hr.leave.report.calendar')
            self.assertEqual(action['id'], self.env.ref('hr_holidays.action_hr_holidays_dashboard').id)

    def test_overview_menu_uninstall(self):
        _uninstall_hook(self.env)
        self.assertEqual(
            self.env.ref('hr_holidays.menu_hr_holidays_dashboard').action,
            self.env.ref('hr_holidays.action_hr_holidays_dashboard'))

    def test_overview_menu_user_without_time_off_group(self):
        """ Internal users without any Time Off group (e.g. created before hr_holidays was
            installed) keep the read-only overview. """
        user = new_test_user(self.env, login='overview_internal', groups='base.group_user')
        user.group_ids -= self.env.ref('hr_holidays.group_hr_holidays_employee')
        self.assertFalse(user.has_group('hr_holidays.group_hr_holidays_employee'))
        action = self.env.ref('hr_holidays_gantt.action_hr_holidays_overview').with_user(user).run()
        self.assertEqual(action['res_model'], 'hr.leave.report.calendar')
