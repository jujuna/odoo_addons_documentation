from datetime import date

from odoo.exceptions import UserError

from .common import GeoPayrollCase


class TestTaxExemption(GeoPayrollCase):

    def _make_exemption(self, limit, employees):
        return self.env['hr.payroll.tax.exemption'].create({
            'name': self._next_name('Exemption'),
            'yearly_limit': limit,
            'employee_ids': [(6, 0, employees.ids)],
        })

    def _line_total(self, payslip, code):
        return sum(payslip.line_ids.filtered(lambda l: l.code == code).mapped('total'))

    def test_same_date_slips_cannot_both_use_the_allowance(self):
        """Salary and Benefits slips share the allowance; validated together, the second is refused until recomputed."""
        employee = self._make_employee('fixed')
        salary = self._make_payslip(employee, worked_hours=160.0)
        salary.compute_sheet()
        gross = self._line_total(salary, 'GROSS')
        self._make_exemption(gross + 500.0, employee)
        benefit = self.env['hr.payroll.benefit'].create({
            'name': self._next_name('GEO Separate Bonus'),
            'company_id': self.company.id,
            'recurrence': 'once',
            'pay_mode': 'separate',
            'date_from': self.period_start,
            'company_amount': 1000.0,
        })
        self.env['hr.payroll.benefit.line'].create({
            'benefit_id': benefit.id, 'employee_id': employee.id, 'company_amount': 1000.0,
        })
        wizard = self.env['hr.payroll.benefit.payrun'].create({
            'name': 'Bonus', 'company_id': self.company.id,
            'date_start': self.period_start, 'date_end': self.period_end,
        })
        bonus_slip = self.env['hr.payslip'].search(wizard.action_generate()['domain'])
        salary.compute_sheet()
        self.assertEqual(self._line_total(salary, 'PIT'), 0.0)
        self.assertEqual(self._line_total(bonus_slip, 'PIT'), 0.0)
        with self.assertRaisesRegex(UserError, 'exemption used by'):
            (salary | bonus_slip).action_payslip_done()
        salary.action_payslip_done()
        bonus_slip.compute_sheet()
        self.assertAlmostEqual(self._line_total(bonus_slip, 'PIT'), -500.0 * 0.20, places=2)
        bonus_slip.action_payslip_done()
        self.assertEqual(bonus_slip.state, 'validated')

    def test_under_limit_no_pit(self):
        employee = self._make_employee('fixed')
        employee.pension_fund_member = True
        self._make_exemption(1000000.0, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        gross = self._line_total(payslip, 'GROSS')
        self.assertGreater(gross, 0)
        self.assertEqual(self._line_total(payslip, 'PIT'), 0.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -gross * 0.02, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), gross * 0.98, places=2)

    def test_crossing_month_taxes_excess_only(self):
        employee = self._make_employee('fixed')
        january = self._make_payslip(employee, worked_hours=160.0)
        january.compute_sheet()
        jan_gross = self._line_total(january, 'GROSS')
        self._make_exemption(jan_gross + 300.0, employee)
        january.compute_sheet()
        self.assertEqual(self._line_total(january, 'PIT'), 0.0)
        january.action_payslip_done()
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        feb_gross = self._line_total(february, 'GROSS')
        self.assertAlmostEqual(self._line_total(february, 'PIT'), -(feb_gross - 300.0) * 0.20, places=2)

    def test_exact_limit_untaxed_then_full_tax_and_max_category_wins(self):
        employee = self._make_employee('fixed')
        january = self._make_payslip(employee, worked_hours=160.0)
        january.compute_sheet()
        jan_gross = self._line_total(january, 'GROSS')
        self._make_exemption(100.0, employee)
        self._make_exemption(jan_gross, employee)
        january.compute_sheet()
        self.assertEqual(self._line_total(january, 'PIT'), 0.0)
        january.action_payslip_done()
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        feb_gross = self._line_total(february, 'GROSS')
        self.assertAlmostEqual(self._line_total(february, 'PIT'), -feb_gross * 0.20, places=2)

    def test_bonus_counts_toward_limit(self):
        employee = self._make_employee('fixed')
        january = self._make_payslip(employee, worked_hours=160.0)
        january.compute_sheet()
        base_gross = self._line_total(january, 'GROSS')
        benefit = self.env['hr.payroll.benefit'].create({
            'name': self._next_name('Bonus'),
            'company_id': self.company.id,
            'recurrence': 'once',
            'pay_mode': 'with_salary',
            'date_from': self.period_start,
            'company_amount': 500.0,
        })
        self.env['hr.payroll.benefit.line'].create({
            'benefit_id': benefit.id,
            'employee_id': employee.id,
            'company_amount': 500.0,
        })
        self._make_exemption(base_gross + 200.0, employee)
        january.compute_sheet()
        gross = self._line_total(january, 'GROSS')
        self.assertEqual(gross, base_gross + 500.0)
        self.assertAlmostEqual(self._line_total(january, 'PIT'), -(gross - (base_gross + 200.0)) * 0.20, places=2)

    def test_no_category_unchanged(self):
        employee = self._make_employee('fixed')
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        gross = self._line_total(payslip, 'GROSS')
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -gross * 0.20, places=2)

    def _make_advance(self, employee, total, count):
        benefit = self.env['hr.payroll.benefit'].create({
            'name': self._next_name('Advance'),
            'company_id': self.company.id,
            'recurrence': 'once',
            'pay_mode': 'with_salary',
            'date_from': self.period_start,
            'advance': True,
            'payslip_count': count,
            'employee_amount': total,
        })
        self.env['hr.payroll.benefit.line'].create({
            'benefit_id': benefit.id,
            'employee_id': employee.id,
            'employee_amount': total,
        })
        return benefit

    def test_advance_inside_limit_prepays_nothing(self):
        employee = self._make_employee('fixed')
        january = self._make_payslip(employee, worked_hours=160.0)
        january.compute_sheet()
        jan_gross = self._line_total(january, 'GROSS')
        january.action_payslip_done()
        # allowance left for February: 1,000 (advance) + 500 (salary part)
        self._make_exemption(jan_gross + 1500.0, employee)
        self._make_advance(employee, 1000.0, 2)
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        feb_gross = self._line_total(february, 'GROSS')
        self.assertEqual(self._line_total(february, 'ADV_PIT_PRE'), 0.0)
        self.assertEqual(self._line_total(february, 'ADVANCE_PAY'), 1000.0)
        self.assertAlmostEqual(self._line_total(february, 'PIT'), -(feb_gross - 500.0) * 0.20, places=2)
        february.action_payslip_done()
        march = self._make_payslip(employee, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31), worked_hours=160.0)
        march.compute_sheet()
        self.assertEqual(self._line_total(march, 'ADVANCE'), -500.0)
        self.assertEqual(self._line_total(march, 'REPAY_PIT'), 0.0)
        self.assertEqual(self._line_total(march, 'REPAY_NET'), 500.0)

    def test_crossing_slip_folds_advance_into_single_pit_line(self):
        employee = self._make_employee('fixed')
        january = self._make_payslip(employee, worked_hours=160.0)
        january.compute_sheet()
        jan_gross = self._line_total(january, 'GROSS')
        january.action_payslip_done()
        self._make_exemption(jan_gross + 400.0, employee)
        self._make_advance(employee, 1000.0, 2)
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        feb_gross = self._line_total(february, 'GROSS')
        # allowance still open: nothing is prepaid; the monthly Income Tax line takes (salary + advance - 400) x 20%
        self.assertEqual(self._line_total(february, 'ADV_PIT_PRE'), 0.0)
        self.assertEqual(self._line_total(february, 'ADVANCE_PAY'), 1000.0)
        self.assertAlmostEqual(self._line_total(february, 'PIT'), -(feb_gross + 1000.0 - 400.0) * 0.20, places=2)
        february.action_payslip_done()
        march = self._make_payslip(employee, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31), worked_hours=160.0)
        march.compute_sheet()
        # nothing was prepaid, so the installments close only the net advance
        self.assertEqual(self._line_total(march, 'REPAY_PIT'), 0.0)
        self.assertEqual(self._line_total(march, 'REPAY_NET'), 500.0)

    def test_correction_keeps_the_allowance_of_its_refunded_origin(self):
        employee = self._make_employee('fixed')
        june = self._make_payslip(employee, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30), worked_hours=160.0)
        refund, correction = self._make_correction_pair(june)
        correction.compute_sheet()
        limit = self._line_total(correction, 'GROSS') + 100.0
        self._make_exemption(limit, employee)
        correction.compute_sheet()
        self.assertAlmostEqual(correction._gec_exemption_remaining(), limit, places=2)
        self.assertEqual(self._line_total(correction, 'PIT'), 0.0)
        (refund | correction).filtered(lambda slip: slip.state == 'draft').action_payslip_done()
        july = self._make_payslip(employee, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), worked_hours=160.0)
        july.compute_sheet()
        self.assertAlmostEqual(july._gec_exemption_remaining(), 100.0, places=2)
