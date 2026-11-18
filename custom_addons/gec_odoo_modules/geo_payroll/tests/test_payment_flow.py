from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPaymentFlow(GeoPayrollCase):
    """Pay button sweeps NET plus partnered authority legs; paid flips on NET."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        AccountAccount = cls.env['account.account']
        cls.accounts = {
            code: AccountAccount.create({
                'name': f'GEO Pay Test {code}',
                'code': f'P{code}',
                'account_type': account_type,
                'reconcile': account_type == 'liability_payable',
            })
            for code, account_type in [
                ('7410', 'expense'), ('7490', 'expense'),
                ('3130', 'liability_payable'), ('3181', 'liability_payable'),
                ('3182', 'liability_payable'), ('3320', 'liability_payable'),
            ]
        }
        cls.salary_journal = cls.env['account.journal'].create({
            'name': 'GEO Pay Test Salaries',
            'code': 'PSLR',
            'type': 'general',
            'company_id': cls.company.id,
        })
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'GEO Pay Test Bank',
            'code': 'PBNK',
            'type': 'bank',
            'company_id': cls.company.id,
        })
        outstanding = AccountAccount.create({
            'name': 'GEO Pay Test Outstanding',
            'code': 'P1210OUT',
            'account_type': 'asset_current',
            'reconcile': True,
        })
        cls.bank_journal.outbound_payment_method_line_ids.payment_account_id = outstanding
        structure = cls.structures['monthly']
        structure.with_company(cls.company).journal_id = cls.salary_journal
        for rule in structure.rule_ids.with_company(cls.company):
            if rule.code in ('GROSS', 'LOAN'):
                continue
            if rule.code == 'NET':
                rule.account_credit = cls.accounts['3130']
            elif rule.code == 'PENSION_ER':
                rule.account_debit = cls.accounts['7490']
                rule.account_credit = cls.accounts['3181']
            elif rule.code == 'PENSION_EE':
                rule.account_debit = cls.accounts['3182']
            elif rule.code == 'PIT':
                rule.account_debit = cls.accounts['3320']
            else:
                rule.account_debit = cls.accounts['7410']

    def _validated_member_slip(self, employee=None, date_from=None, date_to=None):
        employee = employee or self._make_employee('fixed', wage=1000.0, pension_fund_member=True)
        if not employee.work_contact_id:
            employee.work_contact_id = self.env['res.partner'].create({'name': employee.name})
        payslip = self._make_payslip(
            employee, date_from=date_from, date_to=date_to,
            worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        if payslip.move_id.state == 'draft':
            payslip.move_id.action_post()
        return payslip

    def _open_payables(self, slips):
        return slips.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type == 'liability_payable'
            and not l.reconciled)

    def _pay_action(self, slips):
        """Mirror the Pay button: its view context widens the valid account types."""
        return slips.with_context(hr_payroll_payment_register=True).action_register_payment()

    def test_pay_button_targets_partnered_payables(self):
        """Income tax sits on a Payable account (331320 in the real chart), so it is paid too."""
        payslip = self._validated_member_slip()
        payables = self._open_payables(payslip)
        self.assertEqual(len(payables), 4)
        agency = self.env.ref('geo_payroll.partner_pension_agency')
        treasury = self.env.ref('geo_payroll.partner_state_treasury')
        pension_lines = payables.filtered(lambda l: l.account_id not in (self.accounts['3130'], self.accounts['3320']))
        self.assertEqual(pension_lines.partner_id, agency)
        pit_line = payables.filtered(lambda l: l.account_id == self.accounts['3320'])
        self.assertEqual(pit_line.partner_id, treasury)
        action = self._pay_action(payslip)
        self.assertCountEqual(action['context']['active_ids'], payables.ids)
        self.assertTrue(action['context']['default_group_payment'])

    def test_partnerless_payable_line_blocks_payment(self):
        self.structures['monthly'].rule_ids.filtered(lambda r: r.code == 'PENSION_EE').partner_id = False
        payslip = self._validated_member_slip()
        with self.assertRaises(UserError):
            self._pay_action(payslip)

    def test_payments_reconcile_and_paid_flip(self):
        payslip = self._validated_member_slip()
        action = self._pay_action(payslip)
        wizard = self.env['account.payment.register'].with_context(
            **action['context']).create({'journal_id': self.bank_journal.id})
        payments = wizard._create_payments()
        self.assertEqual(len(payments), 4)
        agency = self.env.ref('geo_payroll.partner_pension_agency')
        treasury = self.env.ref('geo_payroll.partner_state_treasury')
        employee_payment = payments.filtered(lambda p: p.partner_id == payslip.employee_id.work_contact_id)
        self.assertAlmostEqual(employee_payment.amount, 784.0)
        agency_payments = payments.filtered(lambda p: p.partner_id == agency)
        self.assertAlmostEqual(sum(agency_payments.mapped('amount')), 40.0)
        pit_payment = payments.filtered(lambda p: p.partner_id == treasury)
        self.assertAlmostEqual(pit_payment.amount, 196.0)
        self.assertEqual(payslip.state, 'paid')
        self.assertFalse(self._open_payables(payslip))

    def test_paid_payslip_cannot_be_cancelled_or_reset(self):
        """Core's list actions reach paid slips; cancelling one would free its items to be paid again."""
        payslip = self._validated_member_slip()
        action = self._pay_action(payslip)
        self.env['account.payment.register'].with_context(**action['context']).create(
            {'journal_id': self.bank_journal.id})._create_payments()
        self.assertEqual(payslip.state, 'paid')
        with self.assertRaisesRegex(UserError, 'already paid'):
            payslip.action_payslip_cancel()
        with self.assertRaisesRegex(UserError, 'already paid'):
            payslip.action_payslip_draft()

    def test_register_payment_needs_an_outstanding_account(self):
        """Without one the payment posts no entry and the payslip would stay unsettled."""
        payslip = self._validated_member_slip()
        self.bank_journal.outbound_payment_method_line_ids.payment_account_id = False
        action = self._pay_action(payslip)
        wizard = self.env['account.payment.register'].with_context(**action['context']).create(
            {'journal_id': self.bank_journal.id})
        with self.assertRaisesRegex(UserError, 'Outstanding Payments account'):
            wizard._create_payments()

    def test_run_reset_rebooks_the_journal_entry(self):
        """Core keeps the entry on a pay-run reset; recomputed amounts must reach the books."""
        slip = self._validated_member_slip()
        run = self.env['hr.payslip.run'].create({
            'name': 'GEO reset run', 'date_start': slip.date_from, 'date_end': slip.date_to,
            'company_id': self.company.id, 'structure_id': slip.struct_id.id})
        slip.payslip_run_id = run
        old_move = slip.move_id
        run.action_draft()
        self.assertEqual(slip.state, 'draft')
        self.assertFalse(slip.move_id)
        self.assertFalse(old_move.exists())
        slip.compute_sheet()
        slip.action_payslip_done()
        self.assertTrue(slip.move_id)
        self.assertNotEqual(slip.move_id, old_move)

    def test_list_set_to_draft_releases_the_entry(self):
        slip = self._validated_member_slip()
        old_move = slip.move_id
        slip.action_payslip_draft()
        self.assertEqual(slip.state, 'draft')
        self.assertFalse(slip.move_id)
        self.assertFalse(old_move.exists())

    def test_register_payment_takes_one_payslip(self):
        """Grouped authority payments over two entries would crash core's payment hook."""
        first = self._validated_member_slip()
        next_start = self.period_start + relativedelta(months=1)
        second = self._validated_member_slip(
            employee=first.employee_id,
            date_from=next_start,
            date_to=next_start + relativedelta(months=1, days=-1),
        )
        with self.assertRaises(ValueError):
            self._pay_action(first | second)

    def test_vendor_split_refuses_split_on_names(self):
        """With 'Split on names' the vendor share cannot be moved and would go unpaid."""
        employee = self._make_employee('fixed', wage=1000.0, pension_fund_member=True)
        vendor = self.env['res.partner'].create({'name': 'GEO Fitness Vendor'})
        benefit = self.env['hr.payroll.benefit'].create({
            'name': 'GEO Gym', 'company_id': self.company.id, 'recurrence': 'monthly',
            'pay_mode': 'with_salary', 'date_from': self.period_start,
            'partner_id': vendor.id, 'employee_amount': 80.0,
        })
        self.env['hr.payroll.benefit.line'].create({
            'benefit_id': benefit.id, 'employee_id': employee.id, 'employee_amount': 80.0,
        })
        self.structures['monthly'].rule_ids.filtered(lambda r: r.code == 'BENEFIT_DED').split_move_lines = True
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        self.assertTrue(payslip.line_ids.filtered(lambda l: l.code == 'BENEFIT_DED'))
        with self.assertRaisesRegex(UserError, 'pays benefit vendors'):
            payslip.action_payslip_done()

    def test_batch_journal_entries_are_refused(self):
        self.company.batch_payroll_move_lines = True
        employee = self._make_employee('fixed', wage=1000.0)
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        with self.assertRaisesRegex(UserError, 'one journal entry per payslip'):
            payslip.action_payslip_done()

    def _register(self, slip):
        action = self._pay_action(slip)
        return self.env['account.payment.register'].with_context(**action['context']).create(
            {'journal_id': self.bank_journal.id})._create_payments()

    def _corrected(self, origin, wage):
        origin.version_id.wage = wage
        refund, correction = self._make_correction_pair(origin)
        (refund | correction).filtered(lambda slip: slip.state == 'draft').action_payslip_done()
        return refund, correction

    def test_correction_up_pays_only_the_difference(self):
        """Paid at 1000 (1020 out), corrected to 1100: only the 102 difference goes out."""
        origin = self._validated_member_slip()
        self._register(origin)
        refund, correction = self._corrected(origin, 1100.0)
        payments = self._register(correction)
        self.assertAlmostEqual(sum(payments.mapped('amount')), 102.0)
        employee_payment = payments.filtered(lambda p: p.partner_id == origin.employee_id.work_contact_id)
        self.assertAlmostEqual(employee_payment.amount, 78.4)
        self.assertEqual((origin | refund | correction).mapped('state'), ['paid'] * 3)
        self.assertFalse(self._open_payables(origin | refund | correction))

    def test_correction_of_an_unpaid_payslip_pays_once(self):
        """The refund cancels the unpaid origin: the correction is paid in full, the origin never."""
        origin = self._validated_member_slip()
        refund, correction = self._corrected(origin, 1100.0)
        self.assertEqual((origin | refund).mapped('state'), ['validated'] * 2,
                         "nothing was paid yet: paying the correction marks the family")
        with self.assertRaisesRegex(UserError, 'corrected'):
            self._pay_action(origin)
        payments = self._register(correction)
        self.assertAlmostEqual(sum(payments.mapped('amount')), 1122.0)
        self.assertEqual((origin | refund | correction).mapped('state'), ['paid'] * 3)

    def test_correction_down_of_an_unpaid_payslip_is_paid_in_full(self):
        """Nothing was paid out, so nothing is owed back: the lower salary is simply paid."""
        origin = self._validated_member_slip()
        refund, correction = self._corrected(origin, 900.0)
        self.assertFalse(correction.has_negative_net_to_report)
        payments = self._register(correction)
        employee_payment = payments.filtered(lambda p: p.partner_id == origin.employee_id.work_contact_id)
        self.assertAlmostEqual(employee_payment.amount, 705.6)
        self.assertEqual(correction.state, 'paid')

    def test_correction_down_settles_without_a_payment(self):
        """Corrected below what was paid: nothing goes out, the refund stays open for the overpaid net."""
        origin = self._validated_member_slip()
        self._register(origin)
        refund, correction = self._corrected(origin, 900.0)
        self.assertEqual(origin.state, 'paid')
        self.assertEqual(correction.state, 'paid')
        self.assertEqual(refund.state, 'validated')
        self.assertAlmostEqual(sum(refund.sudo()._gec_net_payable_lines().mapped('amount_residual')), origin.net_wage - correction.net_wage)
        self.assertTrue(correction.has_negative_net_to_report)
        self.assertAlmostEqual(correction.negative_net_to_report, 78.4)
        owed = refund.move_id.line_ids.filtered(lambda l: l.account_id == self.accounts['3130'])
        self.assertAlmostEqual(owed.amount_residual, 78.4)

    def test_unchanged_correction_settles_without_a_payment(self):
        origin = self._validated_member_slip()
        self._register(origin)
        refund, correction = self._corrected(origin, 1000.0)
        self.assertEqual(correction.state, 'paid')
        self.assertFalse(self._open_payables(origin | refund | correction))

    def test_refund_only_leaves_nothing_to_pay(self):
        origin = self._validated_member_slip()
        origin._action_refund_payslips()
        with self.assertRaisesRegex(UserError, 'corrected or refunded'):
            self._pay_action(origin)

    def test_payslip_matched_with_a_payment_is_not_released(self):
        """Mark Unpaid then Cancel or Set to Draft would drop the match and pay the salary again."""
        slip = self._validated_member_slip()
        self._register(slip)
        slip.action_payslip_unpaid()
        entry = slip.move_id
        with self.assertRaisesRegex(UserError, 'payment'):
            slip.action_payslip_cancel()
        with self.assertRaisesRegex(UserError, 'payment'):
            slip.action_payslip_draft()
        self.assertTrue(entry.exists())
        self.assertEqual(slip.state, 'validated')

    def test_payroll_assistant_cannot_release_a_posted_entry(self):
        """As core's Cancel: a posted salary entry is undone only by an accounting user."""
        slip = self._validated_member_slip()
        assistant = new_test_user(self.env, login='geo_payroll_assistant', groups='hr_payroll.group_hr_payroll_user')
        with self.assertRaisesRegex(UserError, 'accounting rights'):
            slip.with_user(assistant).action_payslip_draft()
        self.assertTrue(slip.move_id.exists())
        assistant.group_ids |= self.env.ref('account.group_account_invoice')
        slip.with_user(assistant).action_payslip_draft()
        self.assertFalse(slip.move_id)

    def test_cancelling_an_unpaid_correction_releases_its_entry(self):
        origin = self._validated_member_slip()
        self._register(origin)
        refund, correction = self._corrected(origin, 1100.0)
        correction.action_payslip_cancel()
        self.assertEqual(correction.state, 'cancel')
        self.assertFalse(correction.move_id)

    def test_origin_with_an_active_correction_is_not_released(self):
        """Resetting the origin would drop its netting with the refund and pay it again."""
        origin = self._validated_member_slip()
        refund, correction = self._corrected(origin, 1100.0)
        with self.assertRaisesRegex(UserError, 'refund or correction'):
            origin.action_payslip_draft()
        self.assertTrue(origin.move_id.exists())
        (refund | correction).action_payslip_cancel()
        origin.action_payslip_draft()
        self.assertEqual(origin.state, 'draft')
