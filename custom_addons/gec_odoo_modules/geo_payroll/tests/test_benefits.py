from datetime import date

from odoo.exceptions import UserError, ValidationError

from .common import GeoPayrollCase


class TestBenefits(GeoPayrollCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.benefits_structure = cls.env.ref('geo_payroll.structure_geo_benefits')
        cls.benefits_type = cls.env.ref('geo_payroll.structure_type_geo_benefits')

    def _make_benefit(self, **values):
        vals = {
            'name': self._next_name('GEO Benefit'),
            'company_id': self.company.id,
            'recurrence': 'once',
            'pay_mode': 'with_salary',
            'date_from': self.period_start,
        }
        vals.update(values)
        return self.env['hr.payroll.benefit'].create(vals)

    def _assign(self, benefit, employee, **values):
        vals = {
            'benefit_id': benefit.id,
            'employee_id': employee.id,
            'company_amount': benefit.company_amount,
            'employee_amount': benefit.employee_amount,
        }
        vals.update(values)
        return self.env['hr.payroll.benefit.line'].create(vals)

    def _line_total(self, payslip, code):
        return sum(payslip.line_ids.filtered(lambda l: l.code == code).mapped('total'))

    def test_bonus_enters_gross_and_tax(self):
        employee = self._make_employee('fixed')
        employee.pension_fund_member = True
        benefit = self._make_benefit(company_amount=500.0)
        self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BONUS'), 500.0)
        gross = self._line_total(payslip, 'GROSS')
        self.assertEqual(gross, self._line_total(payslip, 'BASIC') + 500.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -gross * 0.02, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -(gross - gross * 0.02) * 0.20, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), gross * 0.784, places=2)

    def test_benefit_in_kind_is_charged_pension_and_income_tax(self):
        employee = self._make_employee('fixed', wage=1000.0, pension_fund_member=True)
        vendor = self.env['res.partner'].create({'name': self._next_name('GEO Vendor')})
        benefit = self._make_benefit(company_amount=100.0, partner_id=vendor.id)
        self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS'), 1100.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -22.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_ER'), 22.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -215.6)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 762.4)

    def test_employee_deduction_is_post_tax(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(employee_amount=80.0, recurrence='monthly')
        self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        gross = self._line_total(payslip, 'GROSS')
        self.assertEqual(self._line_total(payslip, 'BENEFIT_DED'), -80.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -gross * 0.20, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), gross * 0.80 - 80.0, places=2)

    def test_split_financing_both_sides(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(company_amount=200.0, employee_amount=50.0, recurrence='monthly')
        self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BONUS'), 200.0)
        self.assertEqual(self._line_total(payslip, 'BENEFIT_DED'), -50.0)

    def test_once_consumed_on_validation_released_on_cancel(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(company_amount=1000.0)
        line = self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertEqual(line.payslip_id, payslip)
        self.assertEqual(line.state, 'done')
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        self.assertEqual(self._line_total(february, 'BONUS'), 0.0)
        payslip.action_payslip_cancel()
        self.assertFalse(line.payslip_id)
        february.compute_sheet()
        self.assertEqual(self._line_total(february, 'BONUS'), 1000.0)

    def test_once_injected_into_single_draft_only(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(company_amount=1000.0)
        self._assign(benefit, employee)
        first = self._make_payslip(employee, worked_hours=160.0)
        first.compute_sheet()
        second = self._make_payslip(employee, worked_hours=160.0)
        second.compute_sheet()
        totals = sorted([self._line_total(first, 'BONUS'), self._line_total(second, 'BONUS')])
        self.assertEqual(totals, [0.0, 1000.0])

    def test_monthly_window(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(
            employee_amount=80.0, recurrence='monthly',
            date_from=self.period_start, date_to=date(2026, 2, 28))
        self._assign(benefit, employee)
        january = self._make_payslip(employee, worked_hours=160.0)
        january.compute_sheet()
        self.assertEqual(self._line_total(january, 'BENEFIT_DED'), -80.0)
        march = self._make_payslip(employee, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31), worked_hours=160.0)
        march.compute_sheet()
        self.assertEqual(self._line_total(march, 'BENEFIT_DED'), 0.0)

    def test_separate_payment_run_coexists_with_salary_slip(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(company_amount=1000.0, pay_mode='separate')
        self._assign(benefit, employee)

        salary_slip = self._make_payslip(employee, worked_hours=160.0)
        salary_slip.compute_sheet()
        self.assertEqual(self._line_total(salary_slip, 'BONUS'), 0.0)

        wizard = self.env['hr.payroll.benefit.payrun'].create({
            'name': 'Benefits January',
            'company_id': self.company.id,
            'date_start': self.period_start,
            'date_end': self.period_end,
        })
        action = wizard.action_generate()
        run = self.env['hr.payslip'].search(action['domain']).payslip_run_id
        self.assertEqual(len(run.slip_ids), 1)
        bonus_slip = run.slip_ids
        self.assertEqual(bonus_slip.struct_id, self.benefits_structure)
        self.assertFalse(bonus_slip.is_regular)
        self.assertEqual(self._line_total(bonus_slip, 'BONUS'), 1000.0)
        self.assertAlmostEqual(self._line_total(bonus_slip, 'NET'), 800.0, places=2)

        salary_slip.action_payslip_done()
        bonus_slip.action_payslip_done()
        self.assertEqual(salary_slip.state, 'validated')
        self.assertEqual(bonus_slip.state, 'validated')

    def test_archived_line_removed_on_recompute(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(company_amount=500.0)
        line = self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BONUS'), 500.0)
        line.active = False
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BONUS'), 0.0)

    def test_reopened_slip_keeps_consumed_once_bonus(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(company_amount=1000.0)
        line = self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertEqual(line.payslip_id, payslip)
        payslip.write({'state': 'draft'})
        self.env.add_to_compute(payslip._fields['input_line_ids'], payslip)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BONUS'), 1000.0)
        self.assertEqual(line.payslip_id, payslip)

    def test_line_delete_blocked_after_validated_payment(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(employee_amount=80.0, recurrence='monthly')
        line = self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        with self.assertRaises(UserError):
            line.unlink()
        with self.assertRaises(UserError):
            benefit.unlink()
        line.active = False

    def test_benefits_type_keeps_no_default_structure(self):
        with self.assertRaises(ValidationError):
            self.benefits_type.default_struct_id = self.benefits_structure

    def test_advance_payout_with_salary_then_repayment(self):
        employee = self._make_employee('fixed')
        employee.pension_fund_member = True
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0)
        line = self._assign(benefit, employee)
        payout = self._make_payslip(employee, worked_hours=160.0)
        payout.compute_sheet()
        self.assertEqual(self._line_total(payout, 'ADVANCE_PAY'), 1568.0)
        self.assertEqual(self._line_total(payout, 'ADV_PEE_PRE'), 40.0)
        self.assertEqual(self._line_total(payout, 'ADV_PIT_PRE'), 392.0)
        self.assertEqual(self._line_total(payout, 'ADV_PER_PRE'), 40.0)
        self.assertEqual(self._line_total(payout, 'ADVANCE'), 0.0)
        gross = self._line_total(payout, 'GROSS')
        self.assertEqual(gross, self._line_total(payout, 'BASIC'))
        self.assertAlmostEqual(self._line_total(payout, 'NET'), gross * 0.784 + 1568.0, places=2)
        payout.action_payslip_done()
        self.assertEqual(line.payslip_id, payout)
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        self.assertEqual(self._line_total(february, 'ADVANCE'), -1000.0)
        self.assertEqual(self._line_total(february, 'REPAY_NET'), 784.0)
        self.assertEqual(self._line_total(february, 'REPAY_PEE'), 20.0)
        self.assertEqual(self._line_total(february, 'REPAY_PIT'), 196.0)
        self.assertEqual(self._line_total(february, 'REPAY_PER'), 20.0)
        self.assertEqual(self._line_total(february, 'ADVANCE_PAY'), 0.0)
        gross = self._line_total(february, 'GROSS')
        self.assertEqual(gross, self._line_total(february, 'BASIC') - 1000.0)
        self.assertAlmostEqual(self._line_total(february, 'PIT'), -(gross - gross * 0.02) * 0.20, places=2)
        self.assertAlmostEqual(self._line_total(february, 'NET'), gross * 0.784, places=2)

    def test_advance_payout_separate_then_repayment(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0, pay_mode='separate')
        line = self._assign(benefit, employee)
        salary = self._make_payslip(employee, worked_hours=160.0)
        salary.compute_sheet()
        self.assertEqual(self._line_total(salary, 'ADVANCE_PAY'), 0.0)
        self.assertEqual(self._line_total(salary, 'ADVANCE'), 0.0)
        wizard = self.env['hr.payroll.benefit.payrun'].create({
            'name': 'Advance', 'company_id': self.company.id,
            'date_start': self.period_start, 'date_end': self.period_end,
        })
        action = wizard.action_generate()
        payout = self.env['hr.payslip'].search(action['domain'])
        self.assertEqual(self._line_total(payout, 'ADVANCE_PAY'), 1600.0)
        self.assertEqual(self._line_total(payout, 'ADV_PIT_PRE'), 400.0)
        self.assertEqual(self._line_total(payout, 'ADV_PEE_PRE'), 0.0)
        self.assertAlmostEqual(self._line_total(payout, 'NET'), 1600.0, places=2)
        payout.action_payslip_done()
        self.assertEqual(line.payslip_id, payout)
        salary.compute_sheet()
        self.assertEqual(self._line_total(salary, 'ADVANCE'), 0.0)
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        self.assertEqual(self._line_total(february, 'ADVANCE'), -1000.0)
        self.assertEqual(self._line_total(february, 'REPAY_NET'), 800.0)
        self.assertEqual(self._line_total(february, 'REPAY_PIT'), 200.0)

    def test_advance_repayment_stops_after_count(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0)
        self._assign(benefit, employee)
        payout = self._make_payslip(employee, worked_hours=160.0)
        payout.compute_sheet()
        payout.action_payslip_done()
        totals = []
        for date_from, date_to in ((date(2026, 2, 1), date(2026, 2, 28)),
                                   (date(2026, 3, 1), date(2026, 3, 31)),
                                   (date(2026, 4, 1), date(2026, 4, 30))):
            slip = self._make_payslip(employee, date_from=date_from, date_to=date_to, worked_hours=160.0)
            slip.compute_sheet()
            slip.action_payslip_done()
            totals.append(self._line_total(slip, 'ADVANCE'))
        self.assertEqual(totals, [-1000.0, -1000.0, 0.0])

    def test_advance_rounding_last_installment(self):
        """1000 in 3 installments: every prepaid account closes exactly, the last one takes the rounding."""
        employee = self._make_employee('fixed')
        employee.pension_fund_member = True
        benefit = self._make_benefit(advance=True, payslip_count=3, employee_amount=1000.0)
        self._assign(benefit, employee)
        payout = self._make_payslip(employee, worked_hours=160.0)
        payout.compute_sheet()
        payout.action_payslip_done()
        slips = []
        for date_from, date_to in ((date(2026, 2, 1), date(2026, 2, 28)),
                                   (date(2026, 3, 1), date(2026, 3, 31)),
                                   (date(2026, 4, 1), date(2026, 4, 30))):
            slip = self._make_payslip(employee, date_from=date_from, date_to=date_to, worked_hours=160.0)
            slip.compute_sheet()
            slip.action_payslip_done()
            slips.append(slip)
        gross_totals = [-self._line_total(slip, 'ADVANCE') for slip in slips]
        self.assertEqual(gross_totals[0], 333.33)
        self.assertAlmostEqual(sum(gross_totals), 1000.0, places=2)
        self.assertEqual(self._line_total(slips[0], 'REPAY_PEE'), 6.67)
        for repay_code, payout_code in (('REPAY_PEE', 'ADV_PEE_PRE'), ('REPAY_PIT', 'ADV_PIT_PRE'),
                                        ('REPAY_PER', 'ADV_PER_PRE'), ('REPAY_NET', 'ADVANCE_PAY')):
            with self.subTest(code=repay_code):
                self.assertAlmostEqual(
                    sum(self._line_total(slip, repay_code) for slip in slips),
                    self._line_total(payout, payout_code), places=2)

    def test_advance_repayment_follows_payout_after_pension_flag_change(self):
        employee = self._make_employee('fixed')
        employee.pension_fund_member = True
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=1000.0)
        self._assign(benefit, employee)
        payout = self._make_payslip(employee, worked_hours=160.0)
        payout.compute_sheet()
        payout.action_payslip_done()
        employee.pension_fund_member = False
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        self.assertEqual(self._line_total(february, 'PENSION_EE'), 0.0)
        self.assertEqual(self._line_total(february, 'REPAY_PEE'), 10.0)
        self.assertEqual(self._line_total(february, 'REPAY_PER'), 10.0)
        self.assertEqual(self._line_total(february, 'REPAY_PIT'), 98.0)
        self.assertEqual(self._line_total(february, 'REPAY_NET'), 392.0)

    def test_advance_deleted_repayment_returns_installment(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0)
        line = self._assign(benefit, employee)
        payout = self._make_payslip(employee, worked_hours=160.0)
        payout.compute_sheet()
        payout.action_payslip_done()
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        march = self._make_payslip(employee, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31), worked_hours=160.0)
        march.compute_sheet()
        april = self._make_payslip(employee, date_from=date(2026, 4, 1), date_to=date(2026, 4, 30), worked_hours=160.0)
        april.compute_sheet()
        self.assertEqual(self._line_total(april, 'ADVANCE'), 0.0)
        march.unlink()
        april.compute_sheet()
        self.assertEqual(self._line_total(april, 'ADVANCE'), -1000.0)
        self.env.invalidate_all()
        self.assertEqual(line.payslip_ids, payout | february | april)

    def test_advance_payout_cancel_releases_stamp(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0)
        line = self._assign(benefit, employee)
        payout = self._make_payslip(employee, worked_hours=160.0)
        payout.compute_sheet()
        payout.action_payslip_done()
        self.assertEqual(line.payslip_id, payout)
        february = self._make_payslip(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            worked_hours=160.0)
        february.compute_sheet()
        self.assertEqual(self._line_total(february, 'ADVANCE'), -1000.0)
        payout.action_payslip_cancel()
        self.assertFalse(line.payslip_id)
        february.compute_sheet()
        self.assertEqual(self._line_total(february, 'ADVANCE'), 0.0)
        self.assertEqual(self._line_total(february, 'ADVANCE_PAY'), 1600.0)

    def test_advance_line_without_amount_takes_program_total(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0)
        self.env['hr.payroll.benefit.line'].create({'benefit_id': benefit.id, 'employee_id': employee.id})
        payout = self._make_payslip(employee, worked_hours=160.0)
        payout.compute_sheet()
        self.assertEqual(self._line_total(payout, 'ADVANCE_PAY'), 1600.0)

    def test_advance_injects_on_form_created_slip(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0)
        self._assign(benefit, employee)
        # The web form saves an empty input list, as the client computed it.
        payslip = self._make_payslip(employee, worked_hours=160.0, input_line_ids=[])
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'ADVANCE_PAY'), 1600.0)

    def test_advance_created_after_compute_reaches_the_lines(self):
        employee = self._make_employee('fixed')
        june = self._make_payslip(employee, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30), worked_hours=160.0)
        june.compute_sheet()
        self.assertEqual(self._line_total(june, 'ADVANCE_PAY'), 0.0)
        benefit = self._make_benefit(advance=True, payslip_count=3, employee_amount=300.0, date_from=date(2026, 6, 1))
        line = self._assign(benefit, employee)
        self.assertTrue(june.line_ids.filtered(lambda l: l.code == 'ADVANCE_PAY'))
        self.assertTrue(june.line_ids.filtered(lambda l: l.code == 'ADV_PIT_PRE'))
        june.action_payslip_done()
        self.assertEqual(line.payslip_id, june)

    def _advance_june_july(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=3, employee_amount=300.0, date_from=date(2026, 6, 1))
        self._assign(benefit, employee)
        june = self._make_payslip(employee, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30), worked_hours=160.0)
        june.compute_sheet()
        july = self._make_payslip(employee, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), worked_hours=160.0)
        return june, july

    def test_validate_refuses_uncomputed_slip_whose_inputs_came_from_a_stamp(self):
        june, july = self._advance_june_july()
        self.assertFalse(july.input_line_ids.filtered(lambda inp: inp.code == 'ADVANCE'))
        june.action_payslip_done()
        self.assertEqual(sum(july.input_line_ids.filtered(lambda inp: inp.code == 'ADVANCE').mapped('amount')), 100.0)
        self.assertFalse(july.line_ids)
        with self.assertRaisesRegex(UserError, 'changed after its last computation'):
            july.action_payslip_done()
        july.compute_sheet()
        july.action_payslip_done()
        self.assertEqual(self._line_total(july, 'ADVANCE'), -100.0)

    def test_pay_out_validation_refreshes_a_computed_installment_slip(self):
        june, july = self._advance_june_july()
        july.compute_sheet()
        self.assertEqual(self._line_total(july, 'ADVANCE'), 0.0)
        june.action_payslip_done()
        self.assertEqual(self._line_total(july, 'ADVANCE'), -100.0)
        july.action_payslip_done()
        self.assertEqual(july.state, 'validated')

    def test_pay_out_cancel_refused_while_an_installment_is_validated(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(advance=True, payslip_count=3, employee_amount=900.0, date_from=date(2026, 6, 1))
        line = self._assign(benefit, employee)
        june = self._make_payslip(employee, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30), worked_hours=160.0)
        june.compute_sheet()
        june.action_payslip_done()
        july = self._make_payslip(employee, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), worked_hours=160.0)
        july.compute_sheet()
        self.assertEqual(self._line_total(july, 'ADVANCE'), -300.0)
        july.action_payslip_done()
        with self.assertRaisesRegex(UserError, 'installments are already validated'):
            june.action_payslip_cancel()
        july.action_payslip_cancel()
        june.action_payslip_cancel()
        self.assertFalse(line.payslip_id)

    def test_locked_program_refuses_vendor_and_advance_changes(self):
        employee = self._make_employee('fixed')
        vendor = self.env['res.partner'].create({'name': self._next_name('GEO Vendor')})
        benefit = self._make_benefit(company_amount=500.0)
        self._assign(benefit, employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertTrue(benefit.locked)
        with self.assertRaisesRegex(UserError, 'cannot change'):
            benefit.write({'partner_id': vendor.id})
        benefit.write({'note': 'x'})
        advance_employee = self._make_employee('fixed')
        advance = self._make_benefit(advance=True, payslip_count=2, employee_amount=2000.0)
        advance_line = self._assign(advance, advance_employee)
        payout = self._make_payslip(advance_employee, worked_hours=160.0)
        payout.compute_sheet()
        payout.action_payslip_done()
        self.assertEqual(advance_line.payslip_id, payout)
        with self.assertRaisesRegex(UserError, 'already paid out'):
            advance_line.write({'employee_amount': 100.0})
        draft_employee = self._make_employee('fixed')
        draft_benefit = self._make_benefit(company_amount=500.0)
        self._assign(draft_benefit, draft_employee)
        self._make_payslip(draft_employee, worked_hours=160.0).compute_sheet()
        self.assertFalse(draft_benefit.locked)

    def test_correction_keeps_its_own_benefit_input_amount(self):
        employee = self._make_employee('fixed')
        benefit = self._make_benefit(company_amount=500.0)
        self._assign(benefit, employee)
        original = self._make_payslip(employee, worked_hours=160.0)
        original.compute_sheet()
        _refund, correction = self._make_correction_pair(original)
        self.assertEqual(self._line_total(correction, 'BONUS'), 500.0)
        correction.input_line_ids.filtered(lambda inp: inp.code == 'BONUS').amount = 50.0
        correction.compute_sheet()
        benefit.note = 'x'
        correction.compute_sheet()
        self.assertEqual(self._line_total(correction, 'BONUS'), 50.0)
        self.assertEqual(len(correction.input_line_ids.filtered(lambda inp: inp.code == 'BONUS')), 1)
