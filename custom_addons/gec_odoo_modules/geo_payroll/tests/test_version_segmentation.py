from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollVersionSegmentation(GeoPayrollCase):
    """Mid-period version changes for work items: each is priced by the version of its work date."""

    def _make_slip_across_versions(self, employee, new_version_values, worked_hours=None):
        version_b = employee.create_version({'date_version': date(2026, 1, 16), **new_version_values})
        slip = self._make_payslip(employee, worked_hours=worked_hours)
        return slip, version_b

    def test_overtime_logs_priced_by_their_work_date_version(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        version_a = employee._get_version(self.period_start)
        slip, version_b = self._make_slip_across_versions(employee, {'hourly_wage': 20.0}, worked_hours=160.0)
        early = self._approve_log(employee, work_date=date(2026, 1, 10), hours=2.0, percentage='100')
        late = self._approve_log(employee, work_date=date(2026, 1, 20), hours=2.0, percentage='100')
        self.assertEqual(early.rate_snapshot, 10.0)
        self.assertEqual(late.rate_snapshot, 20.0)

        slip.compute_sheet()

        self.assertEqual(self._line_total(slip, 'WORKLOG_OT'), 60.0)
        self.assertEqual(early.settlement_ids.filtered('active_claim').payslip_id, slip)
        self.assertEqual(late.settlement_ids.filtered('active_claim').payslip_id, slip)
        self.assertEqual(early.settlement_ids.filtered('active_claim').source_version_id, version_a)
        self.assertEqual(late.settlement_ids.filtered('active_claim').source_version_id, version_b)

    def test_daily_logs_priced_by_their_work_date_version(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        slip, _version_b = self._make_slip_across_versions(employee, {'daily_wage': 100.0})
        early = self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 10))
        late = self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 20))
        self.assertEqual(early.amount_snapshot, 80.0)
        self.assertEqual(late.amount_snapshot, 100.0)

        slip.compute_sheet()

        self.assertEqual(self._line_total(slip, 'DAILY_BASIC'), 180.0)

    def test_fixed_daily_worklogs_priced_by_their_work_date_version(self):
        employee = self._make_employee('fixed_daily', wage=1600.0, daily_wage=80.0)
        slip, _version_b = self._make_slip_across_versions(employee, {'daily_wage': 100.0}, worked_hours=160.0)
        self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 10))
        self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 20))

        slip.compute_sheet()

        self.assertEqual(self._line_total(slip, 'WORKLOG_DAILY'), 180.0)

    def test_timesheets_priced_by_their_work_date_version(self):
        employee = self._make_employee('fixed_hourly', wage=1600.0, hourly_wage=10.0)
        slip, _version_b = self._make_slip_across_versions(employee, {'hourly_wage': 20.0}, worked_hours=160.0)
        self._make_timesheet(employee, work_date=date(2026, 1, 10), hours=2.0)
        self._make_timesheet(employee, work_date=date(2026, 1, 20), hours=2.0)

        slip.compute_sheet()

        self.assertEqual(self._line_total(slip, 'TIMESHEET_EXTRA'), 60.0)

    def test_adjacent_clipped_monthly_payslips_are_blocked(self):
        # Two shortened monthly slips would each pay a full monthly wage for a partial period.
        employee = self._make_employee('fixed', wage=1600.0)
        employee.create_version({'date_version': date(2026, 1, 16), 'wage': 2000.0})

        first = self._make_payslip(
            employee,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 15),
            version=employee._get_version(date(2026, 1, 1)),
            worked_hours=80.0,
            worked_days=10.0,
        )
        first.compute_sheet()

        with self.assertRaisesRegex(UserError, 'shorter than its period'):
            first.action_payslip_done()
