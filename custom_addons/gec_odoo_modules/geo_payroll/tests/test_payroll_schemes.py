from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollSchemes(GeoPayrollCase):
    def _set_worked_days(self, payslip, paid_hours, paid_days=20.0, unpaid_hours=0.0):
        payslip.worked_days_line_ids.unlink()
        values = [{
            'payslip_id': payslip.id,
            'version_id': payslip.version_id.id,
            'work_entry_type_id': self.attendance_type.id,
            'number_of_days': paid_days,
            'number_of_hours': paid_hours,
        }]
        if unpaid_hours:
            values.append({
                'payslip_id': payslip.id,
                'version_id': payslip.version_id.id,
                'work_entry_type_id': self.env.ref(
                    'hr_work_entry.generic_work_entry_type_unpaid_leave'
                ).id,
                'number_of_days': unpaid_hours / 8.0,
                'number_of_hours': unpaid_hours,
            })
        self.env['hr.payslip.worked_days'].create(values)

    def _compute(self, employee, paid_hours=None, paid_days=None, unpaid_hours=0.0):
        paid_hours = self.period_hours if paid_hours is None else paid_hours
        paid_days = self.period_days if paid_days is None else paid_days
        payslip = self._make_payslip(employee)
        self._set_worked_days(payslip, paid_hours, paid_days, unpaid_hours)
        payslip.compute_sheet()
        return payslip

    def _approve_daily_logs(self, employee, units):
        logs = self.env['hr.employee.work.log']
        for index, quantity in enumerate(units):
            logs |= self._approve_log(
                employee,
                log_type='daily',
                units=quantity,
                work_date=self.period_start + timedelta(days=index),
            )
        return logs

    def _assert_totals(self, payslip, basic, gross, net=None, **components):
        self.assertAlmostEqual(self._line_total(payslip, 'BASIC'), basic)
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS'), gross)
        # Non-member fixtures: NET = GROSS - 20% PIT on full gross.
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), gross * 0.8 if net is None else net)
        for code, expected in components.items():
            self.assertAlmostEqual(self._line_total(payslip, code), expected)

    def test_fixed_monthly_full_period(self):
        payslip = self._compute(self._make_employee('fixed', wage=1600.0))
        self._assert_totals(
            payslip, 1600.0, 1600.0,
            DAILY_BASIC=0.0, WORKLOG_DAILY=0.0,
            TIMESHEET_EXTRA=0.0, WORKLOG_OT=0.0,
        )
        self.assertFalse(payslip.gec_settlement_ids.filtered('active_claim'))

    def test_fixed_monthly_prorates_unpaid_hours(self):
        payslip = self._compute(
            self._make_employee('fixed', wage=1600.0),
            paid_hours=158.4,
            paid_days=19.8,
            unpaid_hours=17.6,
        )
        self._assert_totals(payslip, 1440.0, 1440.0)

    def test_hourly_uses_paid_work_entry_hours(self):
        payslip = self._compute(
            self._make_employee('hourly', hourly_wage=10.0),
            paid_hours=144.0,
            paid_days=18.0,
            unpaid_hours=16.0,
        )
        self._assert_totals(payslip, 1440.0, 1440.0)

    def test_daily_base_is_only_approved_daily_logs(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        self._approve_daily_logs(employee, [1.0] * 20)
        payslip = self._compute(employee)
        self._assert_totals(
            payslip, 0.0, 1600.0,
            DAILY_BASIC=1600.0, WORKLOG_DAILY=0.0,
            TIMESHEET_EXTRA=0.0, WORKLOG_OT=0.0,
        )
        self.assertEqual(payslip.gec_settlement_count, 20)
        self.assertEqual(sum(payslip.gec_settlement_ids.filtered('active_claim').mapped('amount')), 1600.0)

    def test_daily_half_days_and_no_schedule_fallback(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        self._approve_daily_logs(employee, [1.0, 0.5])
        payslip = self._compute(employee)
        self._assert_totals(payslip, 0.0, 120.0, DAILY_BASIC=120.0)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('amount')), 0.0)

    def test_daily_without_logs_is_zero_even_with_worked_hours(self):
        payslip = self._compute(self._make_employee('daily', daily_wage=80.0))
        self._assert_totals(payslip, 0.0, 0.0, DAILY_BASIC=0.0)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('amount')), 0.0)

    def test_fixed_plus_daily_adds_daily_logs_to_monthly_base(self):
        employee = self._make_employee('fixed_daily', wage=1600.0, daily_wage=80.0)
        self._approve_daily_logs(employee, [1.0, 0.5])
        payslip = self._compute(employee)
        self._assert_totals(payslip, 1600.0, 1720.0, DAILY_BASIC=0.0, WORKLOG_DAILY=120.0)

    def test_fixed_plus_hourly_adds_timesheets(self):
        employee = self._make_employee('fixed_hourly', wage=1600.0, hourly_wage=10.0)
        self._make_timesheet(employee, hours=12.0)
        payslip = self._compute(employee)
        self._assert_totals(payslip, 1600.0, 1720.0, TIMESHEET_EXTRA=120.0, DAILY_BASIC=0.0)

    def test_daily_plus_hourly_adds_both_independent_sources(self):
        employee = self._make_employee('daily_hourly', daily_wage=80.0, hourly_wage=10.0)
        self._approve_daily_logs(employee, [1.0, 0.5])
        self._make_timesheet(employee, hours=10.0)
        payslip = self._compute(employee)
        self._assert_totals(payslip, 0.0, 220.0, DAILY_BASIC=120.0, TIMESHEET_EXTRA=100.0, WORKLOG_DAILY=0.0)

    def test_overtime_is_additive_for_every_scheme(self):
        expected_base = {
            'fixed': 1600.0,
            'hourly': 1760.0,
            'daily': 0.0,
            'fixed_daily': 1600.0,
            'fixed_hourly': 1600.0,
            'daily_hourly': 0.0,
        }
        for scheme, base in expected_base.items():
            with self.subTest(scheme=scheme):
                employee = self._make_employee(scheme, worklog_ot_enabled=True, hourly_wage=10.0)
                self._approve_log(employee, hours=3.0, percentage='150')
                payslip = self._compute(employee)
                self._assert_totals(payslip, base, base + 45.0, WORKLOG_OT=45.0)

    def test_all_overtime_percentages_sum_exactly(self):
        employee = self._make_employee('fixed', wage=1600.0, hourly_wage=10.0, worklog_ot_enabled=True)
        for index, percentage in enumerate(('100', '125', '150', '200')):
            self._approve_log(
                employee,
                work_date=self.period_start + timedelta(days=index),
                hours=2.0,
                percentage=percentage,
            )
        payslip = self._compute(employee)
        self._assert_totals(payslip, 1600.0, 1715.0, WORKLOG_OT=115.0)

    def test_fixed_daily_timesheet_is_not_an_implicit_third_component(self):
        employee = self._make_employee('fixed_daily')
        line = self._make_timesheet(employee, hours=8.0)
        payslip = self._compute(employee)
        self.assertFalse(line.gec_settlement_ids)
        self._assert_totals(payslip, 1600.0, 1600.0, TIMESHEET_EXTRA=0.0)

    def test_fixed_hourly_daily_log_is_not_an_implicit_third_component(self):
        employee = self._make_employee('fixed_hourly')
        daily_log = self._make_work_log(employee, log_type='daily')
        with self.assertRaises(UserError):
            daily_log.action_approve()
