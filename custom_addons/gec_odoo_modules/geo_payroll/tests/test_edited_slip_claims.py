from datetime import timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollEditedSlipClaims(GeoPayrollCase):
    """Edited payslips can neither strand nor silently drop claimed work items."""

    def _claimed_daily_slip(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        self._approve_log(employee, log_type='daily', units=1.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        return employee, payslip

    def test_recompute_of_edited_slip_with_claims_is_blocked(self):
        _employee, payslip = self._claimed_daily_slip()
        payslip.edited = True

        with self.assertRaisesRegex(UserError, 'cannot be recomputed'):
            payslip.compute_sheet()

        self.assertEqual(len(payslip.gec_settlement_ids.filtered('active_claim')), 1)
        self.assertEqual(self._line_total(payslip, 'DAILY_BASIC'), 80.0)

    def test_recompute_of_edited_slip_without_claims_is_allowed(self):
        employee = self._make_employee('fixed', wage=1600.0)
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        payslip.edited = True

        payslip.compute_sheet()

        self.assertEqual(self._line_total(payslip, 'BASIC'), 1600.0)

    def test_release_stale_claims_keeps_valid_claims_of_edited_slip(self):
        _employee, payslip = self._claimed_daily_slip()
        payslip.edited = True

        payslip._gec_release_stale_claims()

        self.assertEqual(len(payslip.gec_settlement_ids.filtered('active_claim')), 1)

    def test_line_edit_with_intact_claims_validates(self):
        _employee, payslip = self._claimed_daily_slip()
        pit_line = payslip.line_ids.filtered(lambda line: line.code == 'PIT')
        payslip.write({'line_ids': [Command.update(pit_line.id, {'amount': pit_line.amount})]})
        self.assertTrue(payslip.edited)

        payslip.action_payslip_done()

        self.assertEqual(payslip.state, 'validated')
        self.assertEqual(self._line_total(payslip, 'DAILY_BASIC'), 80.0)
        self.assertEqual(len(payslip.gec_settlement_ids.filtered('active_claim')), 1)

    def test_new_log_after_edit_blocks_validation(self):
        employee, payslip = self._claimed_daily_slip()
        payslip.edited = True
        self._approve_log(employee, log_type='daily', units=0.5, work_date=self.period_start + timedelta(days=1))

        with self.assertRaisesRegex(UserError, 'missing from the payslip'):
            payslip.action_payslip_done()

    def test_new_timesheet_after_edit_blocks_validation(self):
        employee = self._make_employee('fixed_hourly', wage=1600.0, hourly_wage=10.0)
        self._make_timesheet(employee, hours=2.0)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.edited = True
        self._make_timesheet(employee, hours=3.0, work_date=self.period_start + timedelta(days=1))

        with self.assertRaisesRegex(UserError, 'missing from the payslip'):
            payslip.action_payslip_done()

    def test_cancel_reopen_validate_cannot_silently_drop_claims(self):
        _employee, payslip = self._claimed_daily_slip()
        payslip.edited = True
        payslip.action_payslip_cancel()
        released = payslip.gec_settlement_ids.filtered(lambda s: not s.active_claim)
        self.assertEqual(released.release_reason, 'Payslip cancelled')
        payslip.action_payslip_draft()

        with self.assertRaisesRegex(UserError, 'does not match its work logs'):
            payslip.action_payslip_done()

    def test_cancelled_edited_slip_frees_claims_for_new_slip(self):
        employee, payslip = self._claimed_daily_slip()
        payslip.edited = True
        with self.assertRaisesRegex(UserError, 'cannot be recomputed'):
            payslip.compute_sheet()

        payslip.action_payslip_cancel()
        replacement = self._make_payslip(employee)
        replacement.compute_sheet()

        self.assertEqual(self._line_total(replacement, 'DAILY_BASIC'), 80.0)
        replacement.action_payslip_done()
        self.assertEqual(replacement.state, 'validated')
