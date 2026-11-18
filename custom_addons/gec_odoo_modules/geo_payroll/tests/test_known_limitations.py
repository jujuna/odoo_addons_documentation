import unittest
from datetime import date

from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollKnownLimitations(GeoPayrollCase):
    def test_same_day_daily_log_and_timesheet_are_both_paid(self):
        """KNOWN LIMITATION: a daily log and a timesheet on the same day are both paid (80 + 80)."""
        employee = self._make_employee('daily_hourly', daily_wage=80.0, hourly_wage=10.0)
        self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 5))
        self._make_timesheet(employee, work_date=date(2026, 1, 5), hours=8.0)

        payslip = self._make_payslip(employee)
        payslip.compute_sheet()

        self.assertEqual(self._line_total(payslip, 'DAILY_BASIC'), 80.0)
        self.assertEqual(self._line_total(payslip, 'TIMESHEET_EXTRA'), 80.0)

    @unittest.skip(
        "KNOWN LIMITATION: overtime is recognized only from approved work logs. "
        "Attendance and planning overtime are not compared against work logs, so there "
        "is no cross-source reconciliation behavior to assert until it is implemented.")
    def test_attendance_planning_overtime_reconciliation(self):
        pass
