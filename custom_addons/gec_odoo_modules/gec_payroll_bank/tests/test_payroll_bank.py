from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.hr_payroll_account.tests.test_hr_payroll_account import TestHrPayrollAccountCommon


@tagged('post_install', '-at_install')
class TestPayrollBank(TestHrPayrollAccountCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.net_account = cls.env['account.account'].create({
            'name': 'Salary Payable',
            'code': 'GECNET',
            'reconcile': True,
            'account_type': 'liability_current',
        })
        cls.authority_account = cls.env['account.account'].create({
            'name': 'Pension Payable',
            'code': 'GECPEN',
            'reconcile': True,
            'account_type': 'liability_payable',
        })
        cls.blocked_account = cls.env['account.account'].create({
            'name': 'Income Tax Payable',
            'code': 'GECTAX',
            'reconcile': False,
            'account_type': 'liability_current',
        })
        cls.expense_account = cls.env['account.account'].create({
            'name': 'Salary Expense GEC',
            'code': 'GECEXP',
            'account_type': 'expense',
        })

        cls.env['hr.salary.rule'].create({
            'name': 'Net Salary',
            'amount_select': 'code',
            'amount_python_compute': 'result = categories["BASIC"] + categories["ALW"] + categories["DED"]',
            'code': 'NET',
            'category_ids': [Command.set(cls.env.ref('hr_payroll.NET').ids)],
            'sequence': 200,
            'employee_move_line': True,
            'account_debit': cls.expense_account.id,
            'account_credit': cls.net_account.id,
            'struct_ids': [Command.set(cls.hr_structure_softwaredeveloper.ids)],
        })
        cls.hr_structure_softwaredeveloper.journal_id.default_account_id = cls.net_account

        cls.bank_a = cls._gec_make_bank_journal('GBKA', 'GEC Bank A')
        cls.bank_b = cls._gec_make_bank_journal('GBKB', 'GEC Bank B')
        cls.channel_a = cls.bank_a.outbound_payment_method_line_ids[:1]
        cls.channel_b = cls.bank_b.outbound_payment_method_line_ids[:1]

        # John already owns exactly one trusted bank account in the parent fixture;
        # adding another would silently switch every payslip to the multi-bank split.
        cls.payslip_a = cls.hr_payslip_john
        cls.payslip_b = cls.env['hr.payslip'].create({
            'employee_id': cls.hr_employee_mark.id,
            'struct_id': cls.hr_structure_softwaredeveloper.id,
            'version_id': cls.hr_contract_mark.id,
            'journal_id': cls.account_journal.id,
            'name': 'Test Payslip Mark',
            'date_from': cls.hr_payslip_john.date_from,
            'date_to': cls.hr_payslip_john.date_to,
        })

    @classmethod
    def _gec_make_bank_journal(cls, code, name):
        outstanding = cls.env['account.account'].create({
            'name': 'Outstanding %s' % code,
            'code': 'OUT%s' % code,
            'account_type': 'asset_current',
            'reconcile': True,
        })
        journal = cls.env['account.journal'].create({
            'name': name,
            'code': code,
            'type': 'bank',
            'company_id': cls.env.company.id,
            'bank_account_number': 'GE00%s0000000000001' % code,
        })
        journal.bank_account_id.write({
            'bank_name': name, 'bank_bic': '%sGE22' % code,
        })
        journal.outbound_payment_method_line_ids.payment_account_id = outstanding
        return journal

    def _gec_validate(self, payslip, post=True):
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')
        self.assertTrue(payslip.move_id)
        if post and payslip.move_id.state == 'draft':
            payslip.move_id.action_post()
        return payslip

    def _gec_routing(self, payslips, channel):
        return {slip.id: channel for slip in payslips}

    def _gec_add_pension_rule(self, agency):
        # A negative rule books through account_debit; the engine flips it to a credit.
        return self.env['hr.salary.rule'].create({
            'name': 'Pension',
            'amount_select': 'fix',
            'amount_fix': -10.0,
            'code': 'PENSION',
            'category_ids': [Command.set(self.env.ref('hr_payroll.DED').ids)],
            'sequence': 190,
            'partner_id': agency.id,
            'account_debit': self.authority_account.id,
            'struct_ids': [Command.set(self.hr_structure_softwaredeveloper.ids)],
        })

    def _gec_agency(self, account_number):
        agency = self.env['res.partner'].create({'name': 'Pension Agency'})
        self.env['res.partner.bank'].create({
            'account_number': account_number,
            'partner_id': agency.id,
            'allow_out_payment': True,
        })
        return agency

    def _gec_validate_with_net(self, agency, shortfall):
        """Validate payslip A with a pension that cancels the whole pay and then `shortfall` more: net = -shortfall."""
        rule = self._gec_add_pension_rule(agency)
        rule.write({
            'amount_select': 'code',
            'amount_python_compute': 'result = -(categories["BASIC"] + categories["ALW"] + categories["DED"]) - %s' % shortfall,
        })
        return self._gec_validate(self.payslip_a)

    def _gec_authority_routing(self, payslip):
        return {(line.partner_id.id, line.account_id.id): self.channel_a for line in payslip._gec_payroll_authority_lines()}

    def _gec_payroll_batches(self):
        return self.env['account.batch.payment'].search(
            [('gec_payroll_is_batch', '=', True)], order='id')

    def test_manual_channel_is_classified_manual(self):
        self.assertEqual(self.channel_a._gec_bank_channel_kind(), 'manual')

    def test_file_channel_is_classified_from_core_registry(self):
        """A method core lists as file-generating is a 'file' channel, no bank module needed."""
        code = self.channel_a.code
        with patch.object(
            type(self.env['account.batch.payment']), '_get_methods_generating_files',
            lambda batch_self: [code],
        ):
            self.assertEqual(self.channel_a._gec_bank_channel_kind(), 'file')

    def test_config_error_without_outstanding_account(self):
        self.channel_a.payment_account_id = False
        self.assertTrue(any(
            'Outstanding' in error for error in self.channel_a._gec_bank_config_errors()))

    def test_config_error_on_non_reconcilable_outstanding_account(self):
        self.channel_a.payment_account_id.reconcile = False
        self.assertTrue(any(
            'reconciliation' in error for error in self.channel_a._gec_bank_config_errors()))

    def test_config_error_on_cash_outstanding_account(self):
        self.channel_a.payment_account_id.account_type = 'asset_cash'
        self.assertTrue(self.channel_a._gec_bank_config_errors())

    def test_base_config_checks_cannot_be_removed_by_a_bank(self):
        self.channel_a.payment_account_id = False
        with patch.object(
            type(self.channel_a), '_gec_bank_extra_config_errors', lambda line_self: [],
        ):
            self.assertTrue(self.channel_a._gec_bank_config_errors())

    def test_api_channel_needs_the_sender_iban(self):
        """Every API bank identifies the paying account by its IBAN; a manual channel does not."""
        journal = self.env['account.journal'].create({
            'name': 'GEC Bank Without IBAN', 'code': 'GBKN', 'type': 'bank',
            'company_id': self.env.company.id,
        })
        channel = journal.outbound_payment_method_line_ids[:1]
        channel.payment_account_id = self.env['account.account'].create({
            'name': 'Outstanding GBKN', 'code': 'OUTGBKN',
            'account_type': 'asset_current', 'reconcile': True,
        })
        self.assertFalse(channel._gec_bank_config_errors())
        with patch.object(type(channel), '_gec_bank_channel_kind', lambda line_self: 'api'):
            self.assertTrue(any(
                'has no IBAN' in error for error in channel._gec_bank_config_errors()))
            self.assertFalse(self.channel_a._gec_bank_config_errors())

    def test_actual_receiver_account_is_checked_for_every_bank(self):
        """The account Odoo chose must exist and be trusted; a Treasury Code needs none."""
        Payslip = self.env['hr.payslip']
        recipient = self.env['res.partner'].create({'name': 'Payroll Recipient'})
        untrusted = self.env['res.partner.bank'].create({
            'account_number': 'GE00RECIPIENT000000001',
            'partner_id': recipient.id,
            'allow_out_payment': False,
        })
        payment = self.env['account.payment'].new({'partner_id': recipient.id})
        with self.assertRaisesRegex(UserError, 'no receiver bank account'):
            Payslip._gec_payroll_check_payment_account(payment)
        payment.partner_bank_id = untrusted
        with self.assertRaisesRegex(UserError, 'not trusted'):
            Payslip._gec_payroll_check_payment_account(payment)
        trusted = self.env['res.partner.bank'].create({
            'account_number': 'GE00RECIPIENT000000002',
            'partner_id': recipient.id,
            'allow_out_payment': True,
        })
        Payslip._gec_payroll_check_payment_account(self.env['account.payment'].new({
            'partner_id': recipient.id, 'partner_bank_id': trusted.id}))

        treasury = self.env['res.partner'].create({
            'name': 'State Treasury', 'gec_treasury_code': '101001000'})
        Payslip._gec_payroll_check_payment_account(
            self.env['account.payment'].new({'partner_id': treasury.id}))

    def test_employee_lines_need_both_account_and_partner(self):
        self._gec_validate(self.payslip_a)
        lines = self.payslip_a._gec_payroll_employee_lines()
        self.assertTrue(lines)
        self.assertEqual(lines.account_id, self.net_account)
        self.assertEqual(lines.partner_id, self.hr_employee_john.work_contact_id)

    def test_non_reconcilable_partnered_account_is_reported_not_paid(self):
        self._gec_validate(self.payslip_a, post=False)
        move = self.payslip_a.move_id
        move.write({'line_ids': [
            Command.create({
                'name': 'Income tax',
                'account_id': self.blocked_account.id,
                'partner_id': self.env.company.partner_id.id,
                'debit': 0.0,
                'credit': 10.0,
            }),
            Command.create({
                'name': 'Income tax expense',
                'account_id': self.expense_account.id,
                'debit': 10.0,
                'credit': 0.0,
            }),
        ]})
        move.action_post()
        self.assertIn(self.blocked_account, self.payslip_a._gec_payroll_blocked_accounts())
        self.assertNotIn(
            self.blocked_account, self.payslip_a._gec_payroll_authority_lines().account_id)

    def test_untrusted_bank_account_blocks_the_run(self):
        self._gec_validate(self.payslip_a)
        self.hr_employee_john.bank_account_ids.allow_out_payment = False
        with self.assertRaisesRegex(UserError, 'not trusted'):
            self.payslip_a._gec_payroll_pay(
                self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        self.assertFalse(self._gec_payroll_batches())

    def test_missing_work_contact_blocks_the_run_with_a_useful_message(self):
        self._gec_validate(self.payslip_a)
        self.hr_employee_john.work_contact_id = False
        with self.assertRaisesRegex(UserError, 'work contact'):
            self.payslip_a._gec_payroll_pay(
                self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())

    def test_changed_work_contact_cannot_turn_net_salary_into_authority(self):
        self._gec_validate(self.payslip_a)
        net_lines = self.payslip_a._gec_payroll_net_lines()
        old_contact = self.hr_employee_john.work_contact_id
        self.hr_employee_john.work_contact_id = self.env['res.partner'].create({
            'name': 'Replacement Work Contact',
        })

        self.assertEqual(net_lines.partner_id, old_contact)
        self.assertFalse(net_lines & self.payslip_a._gec_payroll_authority_lines())
        with self.assertRaisesRegex(UserError, 'current work contact'):
            self.payslip_a._gec_payroll_pay(
                self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())

    def test_partnerless_reconcilable_liability_blocks_the_run(self):
        self._gec_validate(self.payslip_a, post=False)
        self.payslip_a.move_id.write({'line_ids': [
            Command.create({
                'name': 'Unaddressed liability',
                'account_id': self.authority_account.id,
                'debit': 0.0,
                'credit': 10.0,
            }),
            Command.create({
                'name': 'Unaddressed liability expense',
                'account_id': self.expense_account.id,
                'debit': 10.0,
                'credit': 0.0,
            }),
        ]})
        self.payslip_a.move_id.action_post()

        with self.assertRaisesRegex(UserError, 'no partner'):
            self.payslip_a._gec_payroll_pay(
                self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())

    def test_draft_entries_are_posted_before_the_whole_selection_is_paid(self):
        self._gec_validate(self.payslip_a)
        self._gec_validate(self.payslip_b, post=False)
        payslips = self.payslip_a | self.payslip_b

        payslips._gec_payroll_pay(
            self._gec_routing(payslips, self.channel_a), {}, fields.Date.today())

        self.assertEqual(set(payslips.move_id.mapped('state')), {'posted'})
        self.assertEqual(set(payslips.mapped('state')), {'paid'})
        self.assertTrue(self._gec_payroll_batches())

    def test_company_currency_boundary_is_checked_before_payment(self):
        self._gec_validate(self.payslip_a)
        foreign_currency = self.env['res.currency'].with_context(active_test=False).search([
            ('id', '!=', self.env.company.currency_id.id),
        ], limit=1)
        self.assertTrue(foreign_currency)
        foreign_currency.active = True
        self.bank_a.currency_id = foreign_currency

        with self.assertRaisesRegex(UserError, "company's currency"):
            self.payslip_a._gec_payroll_pay(
                self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        self.assertFalse(self._gec_payroll_batches())

    def test_changed_residual_snapshot_is_refused_under_the_line_lock(self):
        self._gec_validate(self.payslip_a)
        lines = self.payslip_a._gec_payroll_employee_lines()
        context = self.payslip_a._gec_payroll_register_context(
            self.channel_a, 'salary', lines)
        context['gec_payroll_residual_snapshot'][lines.id] += 1.0
        register = self.env['account.payment.register'].with_context(**context).create({
            'journal_id': self.channel_a.journal_id.id,
            'payment_method_line_id': self.channel_a.id,
            'payment_date': fields.Date.today(),
            'group_payment': False,
        })

        with self.assertRaisesRegex(UserError, 'amounts changed'):
            register._create_payments()

    def test_trigger_field_from_a_bank_hook_is_refused(self):
        self._gec_validate(self.payslip_a)
        trigger_field = self.env['account.payment']._get_trigger_fields_to_synchronize()[0]
        with patch.object(
            type(self.channel_a), '_gec_bank_payment_vals',
            lambda line_self, kind, payment: {trigger_field: False},
        ):
            with self.assertRaises(UserError):
                self.payslip_a._gec_payroll_pay(
                    self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())

    def test_bank_hook_cannot_overwrite_engine_batch_values(self):
        self._gec_validate(self.payslip_a)
        with patch.object(
            type(self.channel_a), '_gec_bank_batch_vals',
            lambda line_self, kind: {'gec_payroll_is_batch': False},
        ):
            with self.assertRaises(UserError):
                self.payslip_a._gec_payroll_pay(
                    self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())

    def test_single_payslip_produces_one_payment_and_one_batch(self):
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())

        batches = self._gec_payroll_batches()
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches.gec_payroll_kind, 'salary')
        self.assertEqual(batches.gec_payroll_channel_id, self.channel_a)
        self.assertEqual(batches.journal_id, self.bank_a)
        self.assertEqual(len(batches.payment_ids), 1)
        self.assertEqual(batches.payment_ids.payment_method_line_id, self.channel_a)
        self.assertFalse(self.payslip_a._gec_payroll_employee_lines())

    def test_batch_uses_the_selected_payment_date(self):
        self._gec_validate(self.payslip_a)
        payment_date = fields.Date.add(fields.Date.today(), days=7)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, payment_date)

        batch = self._gec_payroll_batches()
        self.assertEqual(batch.date, payment_date)
        self.assertEqual(batch.payment_ids.date, payment_date)

    def test_two_employees_two_banks_produce_two_batches(self):
        self._gec_validate(self.payslip_a)
        self._gec_validate(self.payslip_b)
        payslips = self.payslip_a | self.payslip_b

        routing = {self.payslip_a.id: self.channel_a, self.payslip_b.id: self.channel_b}
        payslips._gec_payroll_pay(routing, {}, fields.Date.today())

        batches = self._gec_payroll_batches()
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches.mapped('journal_id'), self.bank_a | self.bank_b)
        for batch in batches:
            self.assertEqual(len(batch.payment_ids), 1)
            self.assertEqual(batch.payment_ids.journal_id, batch.journal_id)
        self.assertFalse(payslips._gec_payroll_employee_lines())

    def test_authority_lines_get_their_own_batch(self):
        agency = self.env['res.partner'].create({'name': 'Pension Agency'})
        self.env['res.partner.bank'].create({
            'account_number': 'GECAGENCY01',
            'partner_id': agency.id,
            'allow_out_payment': True,
        })
        self._gec_add_pension_rule(agency)
        self._gec_validate(self.payslip_a)

        authority_lines = self.payslip_a._gec_payroll_authority_lines()
        self.assertTrue(authority_lines)
        self.assertEqual(authority_lines.partner_id, agency)
        authority_routing = {
            (line.partner_id.id, line.account_id.id): self.channel_b
            for line in authority_lines
        }
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a),
            authority_routing, fields.Date.today())

        batches = self._gec_payroll_batches()
        self.assertEqual(len(batches), 2)
        self.assertEqual(
            batches.filtered(lambda b: b.gec_payroll_kind == 'authority').journal_id, self.bank_b)
        self.assertEqual(
            batches.filtered(lambda b: b.gec_payroll_kind == 'salary').journal_id, self.bank_a)

    def test_one_authority_payment_covers_several_payslips(self):
        agency = self.env['res.partner'].create({'name': 'Pension Agency'})
        self.env['res.partner.bank'].create({
            'account_number': 'GECAGENCY02',
            'partner_id': agency.id,
            'allow_out_payment': True,
        })
        self._gec_add_pension_rule(agency)
        self._gec_validate(self.payslip_a)
        self._gec_validate(self.payslip_b)
        payslips = self.payslip_a | self.payslip_b

        authority_routing = {
            (line.partner_id.id, line.account_id.id): self.channel_b
            for line in payslips._gec_payroll_authority_lines()
        }
        payslips._gec_payroll_pay(
            self._gec_routing(payslips, self.channel_a), authority_routing, fields.Date.today())

        authority = self._gec_payroll_batches().filtered(
            lambda b: b.gec_payroll_kind == 'authority')
        self.assertEqual(len(authority), 1)
        self.assertEqual(len(authority.payment_ids), 1)
        self.assertEqual(authority.payment_ids.partner_id, agency)

        salary = self._gec_payroll_batches().filtered(
            lambda b: b.gec_payroll_kind == 'salary').payment_ids
        salary_a = salary.filtered(
            lambda payment: payment.partner_id == self.payslip_a.employee_id.work_contact_id)
        salary_b = salary.filtered(
            lambda payment: payment.partner_id == self.payslip_b.employee_id.work_contact_id)
        self.assertEqual(len(salary_a), 1)
        self.assertEqual(len(salary_b), 1)
        self.assertEqual(
            self.payslip_a.move_id.reconciled_payment_ids,
            authority.payment_ids | salary_a,
        )
        self.assertEqual(
            self.payslip_b.move_id.reconciled_payment_ids,
            authority.payment_ids | salary_b,
        )

    def test_authority_is_paid_into_its_account_at_the_paying_bank(self):
        """An agency holding one account per bank is paid at the bank we pay from."""
        agency = self.env['res.partner'].create({'name': 'Pension Agency'})
        account_at_a, account_at_b = self.env['res.partner.bank'].create([
            {
                'account_number': 'GECAGENCYA',
                'partner_id': agency.id,
                'bank_bic': self.bank_a.bank_bic,
                'allow_out_payment': True,
                'sequence': 1,
            },
            {
                'account_number': 'GECAGENCYB',
                'partner_id': agency.id,
                'bank_bic': self.bank_b.bank_bic,
                'allow_out_payment': True,
                'sequence': 2,
            },
        ])
        self._gec_add_pension_rule(agency)
        self._gec_validate(self.payslip_a)

        authority_routing = {
            (line.partner_id.id, line.account_id.id): self.channel_b
            for line in self.payslip_a._gec_payroll_authority_lines()
        }
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a),
            authority_routing, fields.Date.today())

        authority = self._gec_payroll_batches().filtered(
            lambda b: b.gec_payroll_kind == 'authority')
        # Without matching, core would take the lowest sequence, i.e. account_at_a.
        self.assertEqual(authority.payment_ids.partner_bank_id, account_at_b)
        self.assertNotEqual(authority.payment_ids.partner_bank_id, account_at_a)

    def test_wizard_resolves_payslips_from_the_pay_run_button(self):
        self._gec_validate(self.payslip_a)
        self.payslip_a.payslip_run_id = self.payslip_run
        action = self.payslip_run.with_context(
            active_model='hr.payslip.run', active_ids=self.payslip_run.ids,
        ).action_gec_pay_salaries()
        wizard = self.env['hr.payroll.pay.wizard'].with_context(
            **action['context'],
            active_model='hr.payslip.run', active_ids=self.payslip_run.ids,
        ).create({})
        self.assertEqual(wizard.payslip_ids, self.payslip_a)

    def test_pay_salaries_wizard_pays_and_closes_the_payslip(self):
        """The real button path, wizard included: the open net goes out and the payslip is paid."""
        self._gec_validate(self.payslip_a)
        net = sum(-line.amount_residual for line in self.payslip_a._gec_payroll_employee_lines())
        action = self.payslip_a.action_gec_pay_salaries()
        wizard = self.env['hr.payroll.pay.wizard'].with_context(**action['context']).create({})
        wizard.channel_id = self.channel_a
        wizard.line_ids.channel_id = self.channel_a
        wizard.authority_line_ids.channel_id = self.channel_a
        wizard.manual_ack = True
        wizard.action_pay()
        self.assertEqual(self.payslip_a.state, 'paid')
        contact = self.payslip_a.employee_id.work_contact_id
        paid = self._gec_payroll_batches().payment_ids.filtered(lambda p: p.partner_id == contact)
        self.assertAlmostEqual(sum(paid.mapped('amount')), net)
        self.assertFalse(self.payslip_a._gec_payroll_employee_lines())

    def test_pay_salaries_on_a_correction_pays_the_difference(self):
        """geo_payroll settles the correction family, so Pay Salaries sends only the difference."""
        if not self.env['ir.module.module'].search_count(
                [('name', '=', 'geo_payroll'), ('state', '=', 'installed')]):
            self.skipTest("geo_payroll settles correction families")
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        self.assertEqual(self.payslip_a.state, 'paid')
        self.payslip_a.version_id.wage += 100.0
        self.payslip_a._action_refund_payslips()
        correction = self.payslip_a._action_correct_payslips()
        correction.action_payslip_done()
        delta = correction.net_wage - self.payslip_a.net_wage
        self.assertGreater(delta, 0.0)
        before = self._gec_payroll_batches()
        correction._gec_payroll_pay(
            self._gec_routing(correction, self.channel_a), {}, fields.Date.today())
        contact = correction.employee_id.work_contact_id
        paid = (self._gec_payroll_batches() - before).payment_ids.filtered(
            lambda p: p.partner_id == contact)
        self.assertAlmostEqual(sum(paid.mapped('amount')), delta)
        self.assertEqual(correction.state, 'paid')

    def test_a_corrected_unpaid_payslip_does_not_block_its_run(self):
        """Its refund cancelled it, so the run pays the other payslips and leaves it out."""
        if not self.env['ir.module.module'].search_count(
                [('name', '=', 'geo_payroll'), ('state', '=', 'installed')]):
            self.skipTest("geo_payroll settles correction families")
        self._gec_validate(self.payslip_a)
        self._gec_validate(self.payslip_b)
        (self.payslip_a | self.payslip_b).payslip_run_id = self.payslip_run
        self.payslip_a._action_refund_payslips()
        self.assertTrue(self.payslip_run.gec_payroll_can_pay)
        action = self.payslip_run.action_gec_pay_salaries()
        wizard = self.env['hr.payroll.pay.wizard'].with_context(**action['context']).create({})
        self.assertEqual(wizard.payslip_ids, self.payslip_b)

    def test_mixed_run_and_off_cycle_slips_do_not_claim_one_run(self):
        self._gec_validate(self.payslip_a)
        self._gec_validate(self.payslip_b)
        self.payslip_a.payslip_run_id = self.payslip_run
        payslips = self.payslip_a | self.payslip_b
        payslips._gec_payroll_pay(
            self._gec_routing(payslips, self.channel_a), {}, fields.Date.today())

        self.assertFalse(self._gec_payroll_batches().payslip_run_id)

    def test_generated_payroll_batch_cannot_be_deleted_or_changed(self):
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        batch = self._gec_payroll_batches()
        with self.assertRaises(UserError):
            batch.unlink()
        with self.assertRaises(UserError):
            batch.write({'payment_ids': [Command.clear()]})
        with self.assertRaises(UserError):
            batch.payment_ids.write({'batch_payment_id': False})

    def test_stale_cron_flags_a_batch_nobody_sent(self):
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        batch = self._gec_payroll_batches()
        self.env.cr.execute(
            "UPDATE account_batch_payment SET create_date = create_date - interval '72 hours' "
            "WHERE id = %s", [batch.id])
        batch.invalidate_recordset(['create_date'])

        self.env['account.batch.payment']._cron_gec_payroll_stale_batches()
        self.assertTrue(batch.gec_payroll_stale_notified)
        self.assertTrue(self.env['mail.activity'].search([
            ('res_model', '=', 'account.batch.payment'),
            ('res_id', '=', batch.id),
        ]))

    def test_failed_handoff_is_flagged_immediately(self):
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        batch = self._gec_payroll_batches()
        with patch.object(
            type(self.channel_a), '_gec_bank_handoff_state',
            lambda line_self, target: 'failed',
        ):
            self.env['account.batch.payment']._cron_gec_payroll_stale_batches()
        self.assertTrue(batch.gec_payroll_stale_notified)

    def test_watchdog_alerts_when_a_terminal_batch_later_fails(self):
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        batch = self._gec_payroll_batches()
        states = iter(('transmitted', 'failed'))
        with patch.object(
            type(self.channel_a), '_gec_bank_handoff_state',
            lambda line_self, target: next(states),
        ):
            self.env['account.batch.payment']._cron_gec_payroll_stale_batches()
            self.assertEqual(batch.gec_payroll_last_notified_state, 'transmitted')
            self.env['account.batch.payment']._cron_gec_payroll_stale_batches()

        self.assertEqual(batch.gec_payroll_last_notified_state, 'failed')
        self.assertTrue(self.env['mail.activity'].search([
            ('res_model', '=', 'account.batch.payment'),
            ('res_id', '=', batch.id),
        ]))

    def test_acknowledged_manual_batch_is_not_flagged(self):
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {},
            fields.Date.today(), manual_ack=True)
        batch = self._gec_payroll_batches()
        self.assertTrue(batch.gec_payroll_manual_ack)
        self.env.cr.execute(
            "UPDATE account_batch_payment SET create_date = create_date - interval '72 hours' "
            "WHERE id = %s", [batch.id])
        batch.invalidate_recordset(['create_date'])

        self.env['account.batch.payment']._cron_gec_payroll_stale_batches()
        self.assertFalse(batch.gec_payroll_stale_notified)

    def test_payment_states_merge_into_one_batch_state(self):
        merge = self.channel_a._gec_bank_merge_handoff_states
        self.assertEqual(merge({'failed'}), 'failed')
        self.assertEqual(merge({'failed', 'transmitted'}), 'partial')
        self.assertEqual(merge({'uncertain', 'confirmed'}), 'uncertain')
        self.assertEqual(merge({'prepared', 'transmitted'}), 'prepared')
        self.assertEqual(merge({'pending', 'transmitted'}), 'pending')
        self.assertEqual(merge({'transmitted', 'confirmed'}), 'transmitted')
        self.assertEqual(merge({'confirmed'}), 'confirmed')
        self.assertEqual(merge(set()), 'prepared')

    def test_payroll_payment_booking_fields_are_locked(self):
        """A payment of a generated batch refuses amount or recipient edits: core would not update the entry."""
        self._gec_validate(self.payslip_a)
        self.payslip_a._gec_payroll_pay(
            self._gec_routing(self.payslip_a, self.channel_a), {}, fields.Date.today())
        payment = self._gec_payroll_batches().payment_ids[:1]
        with self.assertRaisesRegex(UserError, 'generated payroll batch'):
            payment.write({'amount': payment.amount + 1})
        with self.assertRaisesRegex(UserError, 'generated payroll batch'):
            payment.write({'partner_bank_id': False})
        payment.write({'memo': 'still editable'})

    def test_negative_net_slip_pays_authority_legs_and_stays_validated(self):
        agency = self._gec_agency('GECAGENCYNEG')
        slip = self._gec_validate_with_net(agency, 100.0)
        self.assertAlmostEqual(slip.net_wage, -100.0)
        authority_lines = slip._gec_payroll_authority_lines()
        self.assertEqual(authority_lines.partner_id, agency)
        self.assertTrue(slip._gec_payroll_has_open_legs())
        self.assertFalse(slip._gec_payroll_salary_due())

        action = slip.action_gec_pay_salaries()
        wizard = self.env['hr.payroll.pay.wizard'].with_context(**action['context']).create({})
        self.assertFalse(wizard.line_ids)
        self.assertEqual(wizard.authority_line_ids.partner_id, agency)
        self.assertEqual(len(wizard.authority_line_ids), 1)

        slip._gec_payroll_pay({}, self._gec_authority_routing(slip), fields.Date.today(), manual_ack=True)

        batches = self._gec_payroll_batches()
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches.gec_payroll_kind, 'authority')
        self.assertEqual(slip.state, 'validated')
        self.assertFalse(slip.paid_date)
        self.assertFalse(slip._gec_payroll_authority_lines())
        self.assertEqual(sum(authority_lines.mapped('amount_residual')), 0.0)
        self.assertFalse(slip._gec_payroll_has_open_legs())

    def test_zero_net_slip_is_paid_once_authority_legs_close(self):
        agency = self._gec_agency('GECAGENCYZERO')
        slip = self._gec_validate_with_net(agency, 0.0)
        self.assertAlmostEqual(slip.net_wage, 0.0)
        self.assertTrue(slip._gec_payroll_has_open_legs())
        self.assertFalse(slip._gec_payroll_salary_due())

        slip._gec_payroll_pay({}, self._gec_authority_routing(slip), fields.Date.today(), manual_ack=True)

        self.assertEqual(slip.state, 'paid')
        self.assertEqual(self._gec_payroll_batches().gec_payroll_kind, 'authority')
        self.assertFalse(slip._gec_payroll_has_open_legs())

    def test_pay_salaries_skips_settled_salary_leg_but_pays_open_authority_legs(self):
        """The employee was paid outside this flow: the open pension leg is still offered and paid."""
        agency = self._gec_agency('GECAGENCYOPEN')
        self._gec_add_pension_rule(agency)
        slip = self._gec_validate(self.payslip_a)
        lines = slip._gec_payroll_employee_lines()
        self.env['account.payment.register'].with_context(
            **slip._gec_payroll_register_context(self.channel_a, 'salary', lines)
        ).create({
            'journal_id': self.channel_a.journal_id.id,
            'payment_method_line_id': self.channel_a.id,
            'payment_date': fields.Date.today(),
            'group_payment': False,
        })._create_payments()
        self.assertEqual(slip.state, 'validated')
        self.assertTrue(slip._gec_payroll_is_settled())
        self.assertFalse(slip._gec_payroll_salary_due())
        self.assertTrue(slip._gec_payroll_has_open_legs())

        action = slip.action_gec_pay_salaries()
        wizard = self.env['hr.payroll.pay.wizard'].with_context(**action['context']).create({})
        self.assertFalse(wizard.line_ids)
        self.assertEqual(wizard.authority_line_ids.partner_id, agency)

        slip._gec_payroll_pay({}, self._gec_authority_routing(slip), fields.Date.today(), manual_ack=True)

        self.assertEqual(slip.state, 'paid')
        self.assertFalse(slip._gec_payroll_has_open_legs())
