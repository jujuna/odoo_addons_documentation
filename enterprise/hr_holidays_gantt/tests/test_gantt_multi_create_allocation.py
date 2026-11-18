# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import date, datetime

from odoo.exceptions import ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.hr_holidays.tests.common import TestHrHolidaysCommon


@tagged('post_install', '-at_install')
class TestGanttMultiCreateAllocation(TestHrHolidaysCommon):
    """ Tests the "Allocate and Add" flow of the Gantt multi-create popover: it grants - and only ever grants the
    missing part of - a matching, approved allocation, for any employee regardless of country. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.work_entry_type = cls.env['hr.work.entry.type'].create({
            'name': 'Paid Time Off',
            'code': 'Paid Time Off TEST',
            'requires_allocation': True,
            'employee_requests': False,
            'allocation_validation_type': 'hr',
            'leave_validation_type': 'both',
            'request_unit': 'day',
            'unit_of_measure': 'day',
        })

    def _create_multi_create_leave(self, employee, date_from, date_to, work_entry_type=None, grant=True, user=None):
        # sudo as the user: the access rights to the time off are not what is tested
        leave_model = self.env['hr.leave'].with_user(user).sudo() if user else self.env['hr.leave']
        return leave_model.with_context(
            multi_create=True, hr_holidays_gantt_grant_missing_allocation=grant,
        ).create([{
            'name': 'Multi-create leave',
            'employee_id': employee.id,
            'work_entry_type_id': (work_entry_type or self.work_entry_type).id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        }])

    def _allocations_for_emp(self):
        return self.env['hr.leave.allocation'].search([
            ('employee_id', '=', self.employee_emp.id),
            ('work_entry_type_id', '=', self.work_entry_type.id),
        ])

    def test_multi_create_no_allocation_needed_when_sufficient(self):
        existing = self.env['hr.leave.allocation'].create({
            'name': 'Existing allocation',
            'employee_id': self.employee_emp.id,
            'work_entry_type_id': self.work_entry_type.id,
            'number_of_days': 20,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
        })
        existing.action_approve()

        self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 12))

        self.assertEqual(self._allocations_for_emp(), existing, "No new allocation should have been granted")

    def test_multi_create_grants_only_shortfall(self):
        existing = self.env['hr.leave.allocation'].create({
            'name': 'Partial allocation',
            'employee_id': self.employee_emp.id,
            'work_entry_type_id': self.work_entry_type.id,
            'number_of_days': 2,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
        })
        existing.action_approve()

        leave = self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 12))

        new_allocations = self._allocations_for_emp() - existing
        self.assertEqual(len(new_allocations), 1, "Only one top-up allocation should have been granted")
        self.assertEqual(new_allocations.number_of_days, leave.number_of_days - 2)

    def test_multi_create_grants_shortfall_ignoring_allocation_not_yet_valid(self):
        """ An approved allocation that only starts after the leave is over shouldn't be
        counted as available for that leave - it can't cover a period before it exists. """
        existing = self.env['hr.leave.allocation'].create({
            'name': 'Allocation starting after the leave',
            'employee_id': self.employee_emp.id,
            'work_entry_type_id': self.work_entry_type.id,
            'number_of_days': 6,
            'date_from': date(2026, 8, 1),
        })
        existing.action_approve()

        leave = self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 12))

        new_allocations = self._allocations_for_emp() - existing
        self.assertEqual(len(new_allocations), 1, "A top-up allocation should still be granted even though a later allocation exists")
        self.assertEqual(new_allocations.number_of_days, leave.number_of_days)

    def test_multi_create_grants_shortfall_ignoring_already_expired_allocation(self):
        """ An approved allocation that already ended before the leave starts shouldn't be
        counted as available for that leave either - same gap, opposite direction. """
        existing = self.env['hr.leave.allocation'].create({
            'name': 'Already expired allocation',
            'employee_id': self.employee_emp.id,
            'work_entry_type_id': self.work_entry_type.id,
            'number_of_days': 6,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
        })
        existing.action_approve()

        leave = self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 12))

        new_allocations = self._allocations_for_emp() - existing
        self.assertEqual(len(new_allocations), 1, "A top-up allocation should still be granted even though an earlier, expired allocation exists")
        self.assertEqual(new_allocations.number_of_days, leave.number_of_days)

    def test_multi_create_allocation_date_from_matches_leave_timezone(self):
        """ _check_validity itself checks allocation coverage against leave.date_from.date()
        (UTC, converted through the employee's own tz) - not request_date_from. So the
        allocation we auto-grant must line up with THAT date, or the leave creation that
        follows will still be blocked even though we "covered" it. The employee's tz here
        (UTC+14) puts local morning hours on the previous calendar day in UTC. """
        self.employee_emp.tz = 'Pacific/Kiritimati'
        vals = {
            'name': 'Multi-create leave',
            'employee_id': self.employee_emp.id,
            'work_entry_type_id': self.work_entry_type.id,
            'request_date_from': date(2026, 6, 8),
            'request_date_to': date(2026, 6, 8),
        }
        expected_date_from = self.env['hr.leave'].new(vals).date_from.date()
        self.assertNotEqual(expected_date_from, date(2026, 6, 8), "This test needs a tz where the UTC date actually shifts")

        self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 8))

        new_allocations = self._allocations_for_emp()
        self.assertEqual(len(new_allocations), 1)
        self.assertEqual(new_allocations.date_from, expected_date_from)

    def test_multi_create_grants_shortfall_in_hours_for_hour_based_type(self):
        """ A time type measured in hours (unit_of_measure='hour') must be topped up using
        number_of_hours, not number_of_days - the two aren't numerically interchangeable
        (number_of_hours = number_of_days * hours_per_day), so using the wrong field would
        silently grant the wrong amount. """
        hour_work_entry_type = self.env['hr.work.entry.type'].create({
            'name': 'Hourly Time Off',
            'code': 'Hourly Time Off TEST',
            'requires_allocation': True,
            'employee_requests': False,
            'allocation_validation_type': 'hr',
            'leave_validation_type': 'both',
            'request_unit': 'hour',
            'unit_of_measure': 'hour',
        })

        leave = self._create_multi_create_leave(
            self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 8), work_entry_type=hour_work_entry_type,
        )

        new_allocations = self.env['hr.leave.allocation'].search([
            ('employee_id', '=', self.employee_emp.id),
            ('work_entry_type_id', '=', hour_work_entry_type.id),
        ])
        self.assertEqual(len(new_allocations), 1, "A top-up allocation should have been granted")
        self.assertEqual(new_allocations.number_of_hours, leave.number_of_hours, "The shortfall should be tracked in hours for an hour-based time type")

    def test_multi_create_without_allocate_and_add(self):
        """ Only "Allocate and Add" grants the missing allocation: the other creations of the Gantt (the "Add" of
        the popover, the quick time type buttons) still require an allocation. """
        with self.assertRaises(ValidationError):
            self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 12), grant=False)
        self.assertFalse(self._allocations_for_emp())

    def test_multi_create_allocation_granted_by_officer_only(self):
        """ Only a time off officer can grant the missing allocation """
        user = new_test_user(self.env, login='gantt_no_officer', groups='base.group_user,hr_holidays.group_hr_holidays_responsible')
        with self.assertRaises(ValidationError):
            self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 12), user=user)
        self.assertFalse(self._allocations_for_emp())

    def test_multi_create_allocation_approved(self):
        """ The allocation granted is approved, also for the time types validated by the officer and the manager """
        self.work_entry_type.allocation_validation_type = 'both'
        leave = self._create_multi_create_leave(self.employee_emp, datetime(2026, 6, 8), datetime(2026, 6, 12))
        allocation = self._allocations_for_emp()
        self.assertEqual(allocation.state, 'validate')
        self.assertFalse(allocation.date_to, "The allocation granted has no end date")
        self.assertEqual(allocation.number_of_days, leave.number_of_days)
