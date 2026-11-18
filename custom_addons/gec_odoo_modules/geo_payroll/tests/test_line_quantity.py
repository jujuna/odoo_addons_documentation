from datetime import timedelta

from odoo import Command
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollLineQuantity(GeoPayrollCase):
    """Salary lines show claimed quantities while totals stay settlement-exact."""

    def _line(self, payslip, code):
        line = payslip.line_ids.filtered(lambda line: line.code == code)
        line.ensure_one()
        return line

    def test_daily_line_shows_day_quantity(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        self._approve_log(employee, log_type='daily', units=1.0)
        self._approve_log(employee, log_type='daily', units=0.5, work_date=self.period_start + timedelta(days=1))
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()

        line = self._line(payslip, 'DAILY_BASIC')
        self.assertAlmostEqual(line.quantity, 1.5, places=2)
        self.assertAlmostEqual(line.amount, 80.0, places=2)
        self.assertAlmostEqual(line.total, 120.0, places=2)

        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_timesheet_extra_line_shows_hour_quantity(self):
        employee = self._make_employee('fixed_hourly', wage=1600.0, hourly_wage=10.0)
        self._make_timesheet(employee, hours=2.0)
        self._make_timesheet(employee, hours=3.5, work_date=self.period_start + timedelta(days=1))
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()

        line = self._line(payslip, 'TIMESHEET_EXTRA')
        self.assertAlmostEqual(line.quantity, 5.5, places=2)
        self.assertAlmostEqual(line.amount, 10.0, places=2)
        self.assertAlmostEqual(line.total, 55.0, places=2)
        payslip._gec_check_lines_match_settlements()

    def test_timesheet_basic_line_shows_hour_quantity(self):
        employee = self._make_employee(
            'hourly', hourly_source='timesheet', hourly_wage=10.0,
            timesheet_pay_start_date=self.contract_start)
        self._make_timesheet(employee, hours=4.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()

        line = self._line(payslip, 'TIMESHEET_BASIC')
        self.assertAlmostEqual(line.quantity, 4.0, places=2)
        self.assertAlmostEqual(line.amount, 10.0, places=2)
        self.assertAlmostEqual(line.total, 40.0, places=2)
        payslip._gec_check_lines_match_settlements()

    def test_overtime_line_shows_hours_and_effective_rate(self):
        employee = self._make_employee('fixed', wage=1600.0, hourly_wage=10.0, worklog_ot_enabled=True)
        self._approve_log(employee, log_type='overtime', hours=2.0, percentage='150')
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()

        line = self._line(payslip, 'WORKLOG_OT')
        self.assertAlmostEqual(line.quantity, 2.0, places=2)
        self.assertAlmostEqual(line.amount, 15.0, places=2)
        self.assertAlmostEqual(line.total, 30.0, places=2)
        payslip._gec_check_lines_match_settlements()

    def test_unit_mixed_rates_keep_total_settlement_exact(self):
        employee = self._make_employee('unit')
        rate_low = self._make_unit_rate(price=3.5)
        rate_high = self._make_unit_rate(price=10.0)
        self._approve_log(employee, log_type='unit', work_unit=rate_low, unit_qty=4.0)
        self._approve_log(
            employee, log_type='unit', work_unit=rate_high, unit_qty=12.5,
            work_date=self.period_start + timedelta(days=1))
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()

        line = self._line(payslip, 'UNIT_BASIC')
        self.assertAlmostEqual(line.quantity, 16.5, places=2)
        self.assertAlmostEqual(line.amount, 8.42, places=2)
        self.assertAlmostEqual(line.total, 139.0, places=2)
        payslip._gec_check_lines_match_settlements()

    def test_line_edit_round_trips_work_item_totals(self):
        employee = self._make_employee('unit')
        rate_low = self._make_unit_rate(price=3.5)
        rate_high = self._make_unit_rate(price=10.0)
        self._approve_log(employee, log_type='unit', work_unit=rate_low, unit_qty=4.0)
        self._approve_log(
            employee, log_type='unit', work_unit=rate_high, unit_qty=12.5,
            work_date=self.period_start + timedelta(days=1))
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()

        # Editing a line re-forces the others from stored amount x quantity; blended 8.42 would give 138.93.
        pit_line = self._line(payslip, 'PIT')
        payslip.write({'line_ids': [Command.update(pit_line.id, {'amount': pit_line.amount})]})

        line = self._line(payslip, 'UNIT_BASIC')
        self.assertAlmostEqual(line.quantity, 1.0, places=2)
        self.assertAlmostEqual(line.amount, 139.0, places=2)
        self.assertAlmostEqual(line.total, 139.0, places=2)
        payslip._gec_check_lines_match_settlements()

    def test_timesheet_rounding_mismatch_keeps_total_exact(self):
        employee = self._make_employee('fixed_hourly', wage=1600.0, hourly_wage=20.0)
        self._make_timesheet(employee, hours=1.3333)
        self._make_timesheet(employee, hours=1.3333, work_date=self.period_start + timedelta(days=1))
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()

        # Settlements round per line: 2 x round(26.666) = 53.34, not 2.6666 x 20 = 53.33.
        line = self._line(payslip, 'TIMESHEET_EXTRA')
        self.assertAlmostEqual(line.quantity, 2.67, places=2)
        self.assertAlmostEqual(line.total, 53.34, places=2)
        payslip._gec_check_lines_match_settlements()
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_zero_quantity_settlement_falls_back_to_single_unit(self):
        employee = self._make_employee('fixed', wage=1600.0, hourly_wage=10.0, worklog_ot_enabled=True)
        log = self._approve_log(employee, log_type='overtime', hours=2.0)
        payslip = self._make_payslip(employee)
        self._make_settlement(payslip, 'worklog_ot', 20.0, work_log=log, quantity=0.0, rate=10.0)

        amount, quantity = payslip.gec_component_line_vals('worklog_ot')
        self.assertAlmostEqual(amount, 20.0, places=2)
        self.assertAlmostEqual(quantity, 1.0, places=2)

    def test_refund_negates_totals_and_keeps_quantities(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        self._approve_log(employee, log_type='daily', units=1.0)
        self._approve_log(employee, log_type='daily', units=0.5, work_date=self.period_start + timedelta(days=1))
        original = self._make_payslip(employee)
        original.compute_sheet()
        original.action_payslip_done()

        refund, correction = self._make_correction_pair(original)
        (refund | correction).action_payslip_done()

        refund_line = self._line(refund, 'DAILY_BASIC')
        self.assertAlmostEqual(refund_line.quantity, 1.5, places=2)
        self.assertAlmostEqual(refund_line.amount, -80.0, places=2)
        self.assertAlmostEqual(refund_line.total, -120.0, places=2)

        correction_line = self._line(correction, 'DAILY_BASIC')
        self.assertAlmostEqual(correction_line.quantity, 1.5, places=2)
        self.assertAlmostEqual(correction_line.amount, 80.0, places=2)
        self.assertAlmostEqual(correction_line.total, 120.0, places=2)
