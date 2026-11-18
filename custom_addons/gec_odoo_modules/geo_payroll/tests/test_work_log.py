from datetime import date, timedelta

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollWorkLog(GeoPayrollCase):
    def test_create_always_forces_draft_and_clears_forged_snapshots(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._make_work_log(
            employee,
            state='approved',
            version_id=employee.version_id.id,
            rate_snapshot=999.0,
            amount_snapshot=999.0,
            component_code_snapshot='daily_basic',
            currency_id_snapshot=self.company.currency_id.id,
            approved_by_id=self.env.user.id,
            approved_at='2026-01-01 00:00:00',
        )
        self.assertRecordValues(log, [{
            'state': 'draft',
            'version_id': False,
            'rate_snapshot': 0.0,
            'amount_snapshot': 0.0,
            'component_code_snapshot': False,
            'currency_id_snapshot': False,
            'approved_by_id': False,
            'approved_at': False,
        }])

    def test_create_syncs_user_from_employee(self):
        user = self._make_user('Worker')
        employee = self._make_employee('fixed', user=user)
        log = self._make_work_log(employee, user_id=self.env.user.id)
        self.assertEqual(log.user_id, user)

    def test_create_resolves_employee_from_user(self):
        user = self._make_user('Worker')
        employee = self._make_employee('fixed', user=user)
        log = self.env['hr.employee.work.log'].create({
            'name': 'User-resolved log',
            'user_id': user.id,
            'date': self.period_start,
            'type': 'overtime',
            'hours': 1.0,
        })
        self.assertEqual(log.employee_id, employee)
        self.assertEqual(log.user_id, user)

    def test_overtime_quantity_boundaries(self):
        employee = self._make_employee('fixed')
        for invalid in (-1.0, 0.0, 0.004, 24.01):
            with self.subTest(hours=invalid), self.assertRaises(ValidationError):
                self._make_work_log(employee, hours=invalid)
        valid = self._make_work_log(employee, hours=24.0)
        self.assertEqual(valid.hours, 24.0)

    def test_overtime_clears_day_units(self):
        employee = self._make_employee('fixed')
        self.assertEqual(self._make_work_log(employee, units=0.5).units, 0.0)

    def test_daily_quantity_boundaries(self):
        employee = self._make_employee('daily')
        for invalid in (-1.0, 0.0, 0.004, 1.01):
            with self.subTest(units=invalid), self.assertRaises(ValidationError):
                self._make_work_log(employee, log_type='daily', units=invalid)
        half_day = self._make_work_log(
            employee,
            log_type='daily',
            units=0.5,
            work_date=self.period_start + timedelta(days=1),
        )
        full_day = self._make_work_log(
            employee,
            log_type='daily',
            units=1.0,
            work_date=self.period_start + timedelta(days=2),
        )
        self.assertEqual((half_day.units, full_day.units), (0.5, 1.0))

    def test_daily_clears_hours(self):
        employee = self._make_employee('daily')
        self.assertEqual(self._make_work_log(employee, log_type='daily', hours=1.0, units=1.0).hours, 0.0)

    def test_onchange_type_normalizes_units_and_hours(self):
        employee = self._make_employee('daily')
        form = Form(self.env['hr.employee.work.log'])
        form.employee_id = employee
        form.name = 'Onchange log'
        form.hours = 3.0
        form.type = 'daily'
        self.assertEqual(form.hours, 0.0)
        self.assertEqual(form.units, 1.0)
        form.type = 'overtime'
        self.assertEqual(form.units, 0.0)

    def test_daily_unique_index_blocks_two_active_logs(self):
        employee = self._make_employee('daily')
        self._make_work_log(employee, log_type='daily')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._make_work_log(employee, log_type='daily')

    def test_rejected_or_cancelled_daily_log_allows_replacement(self):
        employee = self._make_employee('daily')
        rejected = self._make_work_log(employee, log_type='daily')
        rejected.action_submit()
        rejected.rejection_reason = 'Not worked'
        rejected.action_reject()
        rejected.flush_recordset(['state'])
        replacement = self._make_work_log(employee, log_type='daily')
        replacement.action_cancel()
        replacement.flush_recordset(['state'])
        second_replacement = self._make_work_log(employee, log_type='daily')
        self.assertTrue(second_replacement)

    def test_reset_daily_log_checks_for_active_replacement(self):
        employee = self._make_employee('daily')
        original = self._make_work_log(employee, log_type='daily')
        original.action_cancel()
        original.flush_recordset(['state'])
        self._make_work_log(employee, log_type='daily')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            original.action_reset_to_draft()
            original.flush_recordset(['state'])

    def test_overtime_aggregate_cap_accepts_24_and_rejects_more(self):
        employee = self._make_employee('fixed')
        self._make_work_log(employee, hours=12.0)
        self._make_work_log(employee, hours=12.0)
        with self.assertRaises(ValidationError):
            self._make_work_log(employee, hours=0.01)

    def test_overtime_aggregate_cap_ignores_rejected_and_cancelled(self):
        employee = self._make_employee('fixed')
        rejected = self._make_work_log(employee, hours=20.0)
        rejected.action_submit()
        rejected.rejection_reason = 'Rejected'
        rejected.action_reject()
        cancelled = self._make_work_log(employee, hours=20.0)
        cancelled.action_cancel()
        active = self._make_work_log(employee, hours=24.0)
        self.assertTrue(active)

    def test_overtime_aggregate_cap_applies_on_write(self):
        employee = self._make_employee('fixed')
        self._make_work_log(employee, hours=12.0)
        other = self._make_work_log(employee, hours=10.0)
        with self.assertRaises(ValidationError):
            other.hours = 13.0

    def test_submit_and_reject_lifecycle(self):
        employee = self._make_employee('fixed')
        log = self._make_work_log(employee)
        log.action_submit()
        self.assertEqual(log.state, 'submitted')
        with self.assertRaises(UserError):
            log.action_submit()
        with self.assertRaises(UserError):
            log.action_reject()
        log.rejection_reason = 'Incorrect entry'
        log.action_reject()
        self.assertEqual(log.state, 'rejected')
        log.action_submit()
        self.assertEqual(log.state, 'submitted')
        self.assertFalse(log.rejection_reason)

    def test_approve_overtime_freezes_percentage_amount_and_identity(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        log = self._approve_log(employee, hours=3.0, percentage='150')
        self.assertRecordValues(log, [{
            'state': 'approved',
            'version_id': employee.version_id.id,
            'rate_snapshot': 10.0,
            'amount_snapshot': 45.0,
            'component_code_snapshot': 'worklog_ot',
            'currency_id_snapshot': self.company.currency_id.id,
            'approved_by_id': self.env.user.id,
        }])
        self.assertTrue(log.approved_at)

    def test_approve_daily_routes_pure_daily_to_basic(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        log = self._approve_log(employee, log_type='daily', units=0.5)
        self.assertEqual(log.component_code_snapshot, 'daily_basic')
        self.assertEqual(log.rate_snapshot, 80.0)
        self.assertEqual(log.amount_snapshot, 40.0)

    def test_approve_daily_routes_fixed_daily_to_addition(self):
        employee = self._make_employee('fixed_daily', daily_wage=80.0)
        log = self._approve_log(employee, log_type='daily', units=1.0)
        self.assertEqual(log.component_code_snapshot, 'worklog_daily')
        self.assertEqual(log.amount_snapshot, 80.0)

    def test_approval_uses_version_effective_on_work_date(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        old_version = employee.version_id
        new_version = employee.create_version({
            'date_version': self.period_start + timedelta(days=10),
            'hourly_wage': 20.0,
        })
        old_log = self._approve_log(employee, work_date=self.period_start + timedelta(days=9))
        new_log = self._approve_log(employee, work_date=self.period_start + timedelta(days=10))
        self.assertEqual(old_log.version_id, old_version)
        self.assertEqual(old_log.rate_snapshot, 10.0)
        self.assertEqual(new_log.version_id, new_version)
        self.assertEqual(new_log.rate_snapshot, 20.0)

    def test_approved_snapshot_survives_later_version_changes(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        log = self._approve_log(employee, hours=2.0, percentage='150')
        employee.version_id.write({'hourly_wage': 50.0, 'worklog_ot_enabled': False})
        self.assertEqual(log.rate_snapshot, 10.0)
        self.assertEqual(log.amount_snapshot, 30.0)
        self.assertEqual(log.component_code_snapshot, 'worklog_ot')

    def test_approval_rejects_date_outside_contract(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._make_work_log(employee, work_date=date(2024, 12, 31))
        with self.assertRaises(UserError):
            log.action_approve()

    def test_approval_rejects_disabled_pay_route(self):
        fixed = self._make_employee('fixed', worklog_ot_enabled=False)
        overtime = self._make_work_log(fixed)
        with self.assertRaises(UserError):
            overtime.action_approve()

        daily = self._make_work_log(fixed, log_type='daily', work_date=self.period_start + timedelta(days=1))
        with self.assertRaises(UserError):
            daily.action_approve()

    def test_approval_rejects_nonpositive_rate(self):
        overtime_employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=0.0)
        with self.assertRaises(UserError):
            self._make_work_log(overtime_employee).action_approve()

        daily_employee = self._make_employee('daily', daily_wage=0.0)
        with self.assertRaises(UserError):
            self._make_work_log(daily_employee, log_type='daily').action_approve()

    def test_hourly_attendance_source_rejects_custom_overtime(self):
        if 'attendance_based' not in self.env['hr.version']._fields:
            self.skipTest("hr_attendance is not installed")
        employee = self._make_employee('hourly', worklog_ot_enabled=True)
        self._seed_attendance_based(employee.version_id)
        with self.assertRaises(UserError):
            self._make_work_log(employee).action_approve()

    def test_direct_workflow_and_snapshot_writes_are_forbidden(self):
        employee = self._make_employee('fixed')
        log = self._make_work_log(employee)
        for values in (
            {'state': 'approved'},
            {'version_id': employee.version_id.id},
            {'rate_snapshot': 10.0},
            {'user_id': self.env.user.id},
        ):
            with self.subTest(values=values), self.assertRaises(UserError):
                log.write(values)

    def test_approved_log_is_frozen_except_rejection_reason(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._approve_log(employee)
        with self.assertRaises(UserError):
            log.write({'hours': 5.0})
        log.write({'rejection_reason': 'Administrative note'})
        self.assertEqual(log.rejection_reason, 'Administrative note')

    def test_payroll_can_reset_approved_log_and_clear_snapshots(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._approve_log(employee)
        log.action_reset_to_draft()
        self.assertRecordValues(log, [{
            'state': 'draft',
            'version_id': False,
            'rate_snapshot': 0.0,
            'amount_snapshot': 0.0,
            'component_code_snapshot': False,
            'currency_id_snapshot': False,
            'approved_by_id': False,
            'approved_at': False,
        }])

    def test_cancel_is_payroll_only_and_idempotent_for_payroll(self):
        employee = self._make_employee('fixed')
        log = self._make_work_log(employee)
        log.action_cancel()
        log.action_cancel()
        self.assertEqual(log.state, 'cancelled')

    def test_unlink_allows_terminal_unprocessed_states_only(self):
        employee = self._make_employee('fixed')
        draft = self._make_work_log(employee)
        draft.unlink()

        submitted = self._make_work_log(employee)
        submitted.action_submit()
        with self.assertRaises(UserError):
            submitted.unlink()

        submitted.rejection_reason = 'Rejected'
        submitted.action_reject()
        submitted.unlink()
