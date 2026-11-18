# -*- coding:utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import new_test_user, tagged, TransactionCase


@tagged('at_install', '-post_install')  # LEGACY at_install
class TestResource(TransactionCase):

    def test_compute_work_time_rate_with_credit_time_in_calendar(self):
        """Test Case: check if the computation of the work rate time is correct event if the user add some credit time as attendances."""
        credit_time = self.env['hr.work.entry.type'].create({
            'name': 'Credit Time',
            'code': 'Leave',
            'count_as': 'absence'
        })

        resource_calendar = self.env['resource.calendar'].create({
            'name': 'Calendar Mid-Time',
            'hours_per_day': 8,
            'hours_per_week': 40,
            'full_time_required_hours': 40,
            'attendance_ids': [(5, 0, 0)]
        })

        # Define a mid time
        attendances = self.env['resource.calendar.attendance'].create([
            {'dayofweek': '0', 'hour_from': 8, 'hour_to': 12, 'calendar_id': resource_calendar.id},
            {'dayofweek': '0', 'hour_from': 13, 'hour_to': 17, 'calendar_id': resource_calendar.id},
            {'dayofweek': '1', 'hour_from': 8, 'hour_to': 12, 'calendar_id': resource_calendar.id},
            {'dayofweek': '1', 'hour_from': 13, 'hour_to': 17, 'calendar_id': resource_calendar.id},
            {'dayofweek': '2', 'hour_from': 8, 'hour_to': 12, 'calendar_id': resource_calendar.id},
            {'dayofweek': '2', 'hour_from': 13, 'hour_to': 17, 'work_entry_type_id': credit_time.id, 'calendar_id': resource_calendar.id},
            {'dayofweek': '3', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': credit_time.id, 'calendar_id': resource_calendar.id},
            {'dayofweek': '3', 'hour_from': 13, 'hour_to': 17, 'work_entry_type_id': credit_time.id, 'calendar_id': resource_calendar.id},
            {'dayofweek': '4', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': credit_time.id, 'calendar_id': resource_calendar.id},
            {'dayofweek': '4', 'hour_from': 13, 'hour_to': 17, 'work_entry_type_id': credit_time.id, 'calendar_id': resource_calendar.id}
        ])
        self.assertAlmostEqual(resource_calendar.work_time_rate, 0.5, 2)

        # Define a 4/5
        attendances_to_update = attendances.filtered(lambda attendance: (attendance.dayofweek == '2' and attendance.hour_from == 13) or attendance.dayofweek == '3')
        resource_calendar.write({
            'name': 'Calendar (4 / 5)',
            'attendance_ids': [(1, attendance.id, {'work_entry_type_id': self.env.ref('hr_work_entry.generic_work_entry_type_attendance').id}) for attendance in attendances_to_update]
        })
        self.assertAlmostEqual(resource_calendar.work_time_rate, 0.8, 2)

        # Define a 9/10
        attendances_to_update = attendances.filtered(lambda attendance: attendance.dayofweek == '4' and attendance.hour_from == 8)
        resource_calendar.write({
            'name': 'Calendar (9 / 10)',
            'attendance_ids': [(1, attendance.id, {'work_entry_type_id': self.env.ref('hr_work_entry.generic_work_entry_type_attendance').id}) for attendance in attendances_to_update]
        })
        self.assertAlmostEqual(resource_calendar.work_time_rate, 0.9, 2)

        # Define a Full-Time
        attendances_to_update = attendances.filtered(lambda attendance: attendance.dayofweek == '4' and attendance.hour_from == 13)
        resource_calendar.write({
            'name': 'Calendar Full-Time',
            'attendance_ids': [(1, attendance.id, {'work_entry_type_id': self.env.ref('hr_work_entry.generic_work_entry_type_attendance').id}) for attendance in attendances_to_update]
        })
        self.assertAlmostEqual(resource_calendar.work_time_rate, 1.0, 2)


@tagged('post_install', '-at_install')
class TestResourceCalendarAttendanceOptions(TransactionCase):

    def test_attendance_category_options(self):
        option = self.env['hr.salary.rule.category'].create({'name': 'Premium Pay', 'code': 'TEST_PREMIUM'})
        with_options = self.env['hr.work.entry.type'].create({
            'name': 'Work with options', 'code': 'TESTOPT', 'optional_category_ids': [(6, 0, option.ids)],
        })
        without_options = self.env['hr.work.entry.type'].create({'name': 'Work without options', 'code': 'TESTNOOPT'})
        calendar = self.env['resource.calendar'].create({
            'name': 'Calendar with options',
            'attendance_ids': [(5, 0, 0),
                (0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': with_options.id,
                        'category_options_ids': [(6, 0, option.ids)]}),
                (0, 0, {'dayofweek': '1', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': without_options.id}),
            ],
        })
        attendances = calendar.attendance_ids.sorted('dayofweek')
        self.assertEqual(attendances.mapped('has_category_options'), [True, False])
        self.assertEqual(attendances[0].category_options_ids, option)

        # A user without payroll rights can still open the attendances of a schedule
        hr_officer = new_test_user(self.env, login='hr_officer_options', groups='hr.group_hr_user,base.group_user')
        Attendance = self.env['resource.calendar.attendance'].with_user(hr_officer)
        for view_xmlid in ('resource.view_resource_calendar_attendance_form', 'hr_work_entry.view_resource_calendar_multi_create_form'):
            views = Attendance.get_views([(self.env.ref(view_xmlid).id, 'form')])
            self.assertNotIn('has_category_options', views['views']['form']['arch'])
            self.assertNotIn('category_options_ids', views['views']['form']['arch'])
            fields_spec = {field: {} for field in views['models']['resource.calendar.attendance']['fields']}
            fields_spec.pop('work_entry_type_id', None)
            Attendance.browse(attendances.ids).web_read(fields_spec)
