from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollSettlement(GeoPayrollCase):
    def _claim_fixture(self, source='work_log'):
        scheme = 'fixed_hourly' if source == 'timesheet' else 'fixed'
        employee = self._make_employee(scheme, worklog_ot_enabled=source == 'work_log')
        payslip = self._make_payslip(employee)
        if source == 'work_log':
            work_log = self._approve_log(employee)
            settlement = self._make_settlement(
                payslip,
                'worklog_ot',
                work_log.amount_snapshot,
                work_log=work_log,
                quantity=work_log.hours,
                rate=work_log.rate_snapshot,
            )
            return employee, payslip, work_log, settlement
        timesheet = self._make_timesheet(employee, hours=3.0)
        settlement = self._make_settlement(
            payslip,
            'timesheet_extra',
            30.0,
            timesheet=timesheet,
            quantity=3.0,
            rate=10.0,
        )
        return employee, payslip, timesheet, settlement

    def test_active_settlement_requires_exactly_one_source(self):
        employee = self._make_employee('fixed_hourly', worklog_ot_enabled=True)
        payslip = self._make_payslip(employee)
        log = self._approve_log(employee)
        timesheet = self._make_timesheet(employee)
        with self.assertRaises(ValidationError):
            self.env['hr.payroll.component.settlement'].sudo().create({
                'payslip_id': payslip.id,
                'payslip_ref': payslip.name,
                'employee_id': employee.id,
                'company_id': self.company.id,
                'currency_id': self.company.currency_id.id,
                'component_code': 'worklog_ot',
                'date': self.period_start,
                'quantity': 2.0,
                'rate': 10.0,
                'amount': 20.0,
            })
        with self.assertRaises(ValidationError):
            self._make_settlement(payslip, 'worklog_ot', 20.0, work_log=log, timesheet=timesheet)

    def test_released_settlement_may_exist_without_source(self):
        employee = self._make_employee('fixed')
        payslip = self._make_payslip(employee)
        settlement = self.env['hr.payroll.component.settlement'].sudo().create({
            'payslip_id': payslip.id,
            'payslip_ref': payslip.name,
            'employee_id': employee.id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'component_code': 'worklog_ot',
            'date': self.period_start,
            'quantity': 2.0,
            'rate': 10.0,
            'amount': 20.0,
            'active_claim': False,
        })
        self.assertFalse(settlement.active_claim)
        self.assertFalse(settlement.work_log_id)
        self.assertFalse(settlement.timesheet_line_id)

    def test_settlement_is_immutable_and_cannot_be_deleted(self):
        _employee, _payslip, _source, settlement = self._claim_fixture()
        with self.assertRaises(UserError):
            settlement.write({'amount': 999.0})
        with self.assertRaises(UserError):
            settlement.unlink()

    def test_release_records_reason_and_timestamp(self):
        _employee, _payslip, _source, settlement = self._claim_fixture()
        settlement._release('Test release')
        self.assertFalse(settlement.active_claim)
        self.assertEqual(settlement.release_reason, 'Test release')
        self.assertTrue(settlement.released_at)

    def test_forged_release_context_cannot_mutate_ledger(self):
        _employee, _payslip, _source, settlement = self._claim_fixture()
        with self.assertRaises(UserError):
            settlement.with_context(settlement_release=True).write({'amount': 999.0})
        self.assertNotEqual(settlement.amount, 999.0)

    def test_unique_active_claim_per_work_log(self):
        _employee, payslip, log, _settlement = self._claim_fixture()
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._make_settlement(
                payslip,
                'worklog_ot',
                log.amount_snapshot,
                work_log=log,
                quantity=log.hours,
                rate=log.rate_snapshot,
            )

    def test_released_work_log_claim_allows_new_active_claim(self):
        _employee, payslip, log, old = self._claim_fixture()
        old._release('Recompute')
        old.flush_recordset(['active_claim'])
        new = self._make_settlement(
            payslip,
            'worklog_ot',
            log.amount_snapshot,
            work_log=log,
            quantity=log.hours,
            rate=log.rate_snapshot,
        )
        self.assertFalse(old.active_claim)
        self.assertTrue(new.active_claim)

    def test_unique_active_claim_per_timesheet(self):
        _employee, payslip, timesheet, _settlement = self._claim_fixture('timesheet')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._make_settlement(payslip, 'timesheet_extra', 30.0, timesheet=timesheet, quantity=3.0, rate=10.0)

    def test_released_timesheet_claim_allows_new_active_claim(self):
        _employee, payslip, timesheet, old = self._claim_fixture('timesheet')
        old._release('Recompute')
        old.flush_recordset(['active_claim'])
        new = self._make_settlement(payslip, 'timesheet_extra', 30.0, timesheet=timesheet, quantity=3.0, rate=10.0)
        self.assertFalse(old.active_claim)
        self.assertTrue(new.active_claim)

    def test_payslip_count_includes_active_claims_only(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        payslip = self._make_payslip(employee)
        first_log = self._approve_log(employee, work_date=self.period_start)
        second_log = self._approve_log(employee, work_date=self.period_start.replace(day=2))
        first = self._make_settlement(payslip, 'worklog_ot', first_log.amount_snapshot, work_log=first_log)
        self._make_settlement(payslip, 'worklog_ot', second_log.amount_snapshot, work_log=second_log)
        self.assertEqual(payslip.gec_settlement_count, 2)
        first._release('Released')
        self.assertEqual(payslip.gec_settlement_count, 1)

    def test_claimed_timesheet_locked_fields_cannot_change(self):
        _employee, _payslip, timesheet, _settlement = self._claim_fixture('timesheet')
        task = self.env['project.task'].create({'name': 'Claimed Timesheet Task', 'project_id': self.project.id})
        locked_changes = (
            {'unit_amount': 4.0},
            {'employee_id': timesheet.employee_id.id},
            {'date': self.period_end},
            {'project_id': self.other_project.id},
            {'task_id': task.id},
            {'company_id': self.company.id},
        )
        for values in locked_changes:
            with self.subTest(values=values), self.assertRaises(UserError):
                timesheet.write(values)
        # Timesheet validation is not a payroll matter: a claimed line may be reset to draft.
        timesheet.write({'validated': False})
        self.assertFalse(timesheet.validated)

    def test_claimed_timesheet_cannot_be_deleted(self):
        _employee, _payslip, timesheet, _settlement = self._claim_fixture('timesheet')
        with self.assertRaises(UserError):
            timesheet.unlink()

    def test_released_timesheet_can_change_and_be_deleted(self):
        _employee, _payslip, timesheet, settlement = self._claim_fixture('timesheet')
        settlement._release('Released')
        timesheet.write({'unit_amount': 4.0})
        self.assertEqual(timesheet.unit_amount, 4.0)
        timesheet.unlink()
        self.assertFalse(timesheet.exists())
        self.assertFalse(settlement.timesheet_line_id)

    def test_work_log_with_released_history_still_cannot_be_deleted(self):
        _employee, _payslip, log, settlement = self._claim_fixture()
        settlement._release('Released')
        log.action_reset_to_draft()
        with self.assertRaises(UserError):
            log.unlink()

    def test_deleting_payslip_releases_active_claim(self):
        _employee, payslip, _source, settlement = self._claim_fixture()
        payslip.unlink()
        self.assertFalse(settlement.active_claim)
        self.assertFalse(settlement.payslip_id)
        self.assertEqual(settlement.release_reason, 'Payslip deleted')

    def test_deleting_pay_run_releases_claim_before_cascade(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        pay_run = self.env['hr.payslip.run'].create({
            'name': 'GEO Pay Run',
            'date_start': self.period_start,
            'date_end': self.period_end,
        })
        payslip = self._make_payslip(employee, payslip_run_id=pay_run.id)
        log = self._approve_log(employee)
        settlement = self._make_settlement(payslip, 'worklog_ot', log.amount_snapshot, work_log=log)
        pay_run.unlink()
        self.assertFalse(payslip.exists())
        self.assertFalse(settlement.active_claim)
        self.assertFalse(settlement.payslip_id)
        self.assertEqual(settlement.release_reason, 'Pay run deleted')

    def test_settlement_acl_lets_payroll_users_claim_and_release_but_never_delete(self):
        _employee, _payslip, _source, settlement = self._claim_fixture()
        payroll_user = self._make_user('Settlement Reader', groups=(self.env.ref('hr_payroll.group_hr_payroll_user'),))
        normal_user = self._make_user('Settlement Outsider')
        settlement.with_user(payroll_user).read(['amount'])
        self.assertTrue(settlement.with_user(payroll_user).has_access('write'))
        self.assertFalse(settlement.with_user(payroll_user).has_access('unlink'))
        self.assertTrue(self.env['hr.payroll.component.settlement'].with_user(payroll_user).has_access('create'))
        with self.assertRaisesRegex(UserError, 'cannot be edited'):
            settlement.with_user(payroll_user).write({'amount': 1.0})
        with self.assertRaises(AccessError):
            settlement.with_user(normal_user).read(['amount'])
