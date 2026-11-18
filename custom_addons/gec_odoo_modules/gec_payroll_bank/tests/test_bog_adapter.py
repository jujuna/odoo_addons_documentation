import unittest
from types import SimpleNamespace

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.hr_payroll_account.tests.test_hr_payroll_account import TestHrPayrollAccountCommon


def _bog_connection(env, **values):
    """The company's BOG connection, reused when the database already has one (one per company)."""
    connection = env['bog.connection'].search([('company_id', '=', env.company.id)], limit=1)
    if not connection:
        connection = env['bog.connection'].create({
            'company_id': env.company.id,
            'client_id': 'payroll-client',
            'client_secret': 'payroll-secret',
            'processing_mode': 'direct',
        })
    connection.write(dict({'state': 'active', 'processing_mode': 'direct'}, **values))
    return connection


def _outstanding(env, code):
    return env['account.account'].create({
        'name': 'Outstanding %s' % code, 'code': 'O%s' % code,
        'account_type': 'asset_current', 'reconcile': True,
    })


def _bog_channel(env, code, iban):
    """A BOG journal with its Bank of Georgia transfer line, ready to be a payroll channel."""
    company_account = env['res.partner.bank'].create({
        'account_number': iban,
        'partner_id': env.company.partner_id.id,
        'bank_bic': 'BAGAGE22',
    })
    journal = env['account.journal'].create({
        'name': 'BOG %s' % code, 'code': code, 'type': 'bank',
        'company_id': env.company.id, 'bank_account_id': company_account.id,
    })
    method = env.ref('bog_bank.account_payment_method_bog')
    channel = journal.outbound_payment_method_line_ids.filtered(
        lambda line: line.payment_method_id == method)[:1]
    if not channel:
        channel = env['account.payment.method.line'].create({
            'name': method.name, 'payment_method_id': method.id, 'journal_id': journal.id,
        })
    channel.payment_account_id = _outstanding(env, code)
    return channel


@tagged('post_install', '-at_install')
class TestBogPayrollHooks(TransactionCase):
    """The Bank of Georgia answers to gec_payroll_bank's hooks, one by one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'bog.connection' not in cls.env:
            raise unittest.SkipTest("bog_bank is not installed")
        cls.connection = _bog_connection(cls.env)
        cls.channel = _bog_channel(cls.env, 'BOGH', 'GE29BG7777777777777702')

    def _state_of(self, *bog_states, batch_state='draft'):
        payments = self.env['account.payment']
        for bog_state in bog_states:
            payments |= self.env['account.payment'].new({'gec_bank_state': bog_state})
        batch = SimpleNamespace(payment_ids=payments, bog_state=batch_state)
        return self.channel._gec_bank_handoff_state(batch)

    def test_bog_is_an_api_channel(self):
        self.assertEqual(self.channel._gec_bank_channel_kind(), 'api')
        self.assertFalse(self.channel._gec_bank_config_errors())

    def test_channel_needs_an_unblocked_connection(self):
        self.connection.state = 'blocked'
        self.assertIn("The Bank of Georgia connection is blocked. Contact the bank.",
                      self.channel._gec_bank_config_errors())
        self.connection.company_id = self.env['res.company'].create({'name': 'BOG Other Co'})
        self.channel.journal_id.invalidate_recordset(['bog_connection_id'])
        self.assertTrue(any('No Bank of Georgia connection' in error
                            for error in self.channel._gec_bank_config_errors()))

    def test_only_a_salary_is_flagged_and_bulk_is_capped(self):
        gel = self.env.ref('base.GEL')
        payment = self.env['account.payment'].new({'amount': 10000.0, 'currency_id': gel.id})
        self.assertEqual(self.channel._gec_bank_payment_vals('salary', payment), {
            'bog_transfer_type': 'domestic', 'bog_is_salary': True, 'bog_dispatch_type': 'BULK'})
        payment = self.env['account.payment'].new({'amount': 10000.01, 'currency_id': gel.id})
        self.assertEqual(self.channel._gec_bank_payment_vals('authority', payment), {
            'bog_transfer_type': 'domestic', 'bog_is_salary': False, 'bog_dispatch_type': 'MT103'})

    def test_watchdog_state_is_read_from_payments_and_the_bulk_send(self):
        self.assertEqual(self._state_of('failed'), 'failed')
        self.assertEqual(self._state_of('created', 'failed'), 'partial')
        self.assertEqual(self._state_of('created', 'unknown'), 'uncertain')
        self.assertEqual(self._state_of('sending'), 'uncertain')
        self.assertEqual(self._state_of('awaiting_confirmation', 'created'), 'prepared')
        self.assertEqual(self._state_of('created', 'sent'), 'pending')
        self.assertEqual(self._state_of('sent', 'sent'), 'transmitted')
        self.assertEqual(self._state_of('confirmed', 'confirmed'), 'confirmed')
        # The bulk call may have reached the bank although no payment was updated.
        self.assertEqual(self._state_of('approved', batch_state='sending'), 'uncertain')
        self.assertEqual(self._state_of('approved', batch_state='unknown'), 'uncertain')


@tagged('post_install', '-at_install')
class TestBogPayrollFlow(TestHrPayrollAccountCommon):
    """Pay Salaries through a Bank of Georgia channel, without sending.
    One entry: net salary, a pension leg (account at BOG and TBC), a tax leg (State Treasury, paid via another bank)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'bog.connection' not in cls.env:
            raise unittest.SkipTest("bog_bank is not installed")
        account = cls.env['account.account']
        cls.net_account = account.create({
            'name': 'BOG Salary Payable', 'code': 'BOGNET',
            'reconcile': True, 'account_type': 'liability_current',
        })
        pension_account = account.create({
            'name': 'BOG Pension Payable', 'code': 'BOGPEN',
            'reconcile': True, 'account_type': 'liability_payable',
        })
        tax_account = account.create({
            'name': 'BOG Income Tax Payable', 'code': 'BOGPIT',
            'reconcile': True, 'account_type': 'liability_payable',
        })
        expense_account = account.create({
            'name': 'BOG Salary Expense', 'code': 'BOGEXP', 'account_type': 'expense',
        })
        cls.agency = cls.env['res.partner'].create({'name': 'Pension Agency'})
        cls.agency_bog, cls.agency_tbc = cls.env['res.partner.bank'].create([{
            'account_number': 'GE03BG0000000131131564', 'partner_id': cls.agency.id,
            'bank_bic': 'BAGAGE22', 'allow_out_payment': True, 'sequence': 2,
        }, {
            'account_number': 'GE88TB7458336020100010', 'partner_id': cls.agency.id,
            'bank_bic': 'TBCBGE22', 'allow_out_payment': True, 'sequence': 1,
        }])
        cls.treasury = cls.env['res.partner'].create({
            'name': 'State Treasury', 'gec_treasury_code': '101001000'})

        structure = cls.hr_structure_softwaredeveloper
        deduction = cls.env.ref('hr_payroll.DED')
        cls.env['hr.salary.rule'].create([{
            'name': 'Net Salary', 'code': 'NET', 'sequence': 200,
            'amount_select': 'code',
            'amount_python_compute':
                'result = categories["BASIC"] + categories["ALW"] + categories["DED"]',
            'category_ids': [Command.set(cls.env.ref('hr_payroll.NET').ids)],
            'employee_move_line': True,
            'account_debit': expense_account.id,
            'account_credit': cls.net_account.id,
            'struct_ids': [Command.set(structure.ids)],
        }, {
            'name': 'Pension', 'code': 'PENSION', 'sequence': 190,
            'amount_select': 'fix', 'amount_fix': -10.0,
            'category_ids': [Command.set(deduction.ids)],
            'partner_id': cls.agency.id,
            'account_debit': pension_account.id,
            'struct_ids': [Command.set(structure.ids)],
        }, {
            'name': 'Income Tax', 'code': 'PIT', 'sequence': 191,
            'amount_select': 'fix', 'amount_fix': -20.0,
            'category_ids': [Command.set(deduction.ids)],
            'partner_id': cls.treasury.id,
            'account_debit': tax_account.id,
            'struct_ids': [Command.set(structure.ids)],
        }])
        structure.journal_id.default_account_id = cls.net_account

        cls.connection = _bog_connection(cls.env)
        cls.channel = _bog_channel(cls.env, 'BOGPY', 'GE29BG7777777777777777')
        tax_journal = cls.env['account.journal'].create({
            'name': 'Tax Bank', 'code': 'TAXB', 'type': 'bank', 'company_id': cls.env.company.id,
        })
        cls.manual_channel = tax_journal.outbound_payment_method_line_ids[:1]
        cls.manual_channel.payment_account_id = _outstanding(cls.env, 'TAXB')
        cls.hr_employee_john.bank_account_ids.write({
            'account_number': 'GE29BG9999999999999999', 'bank_bic': 'BAGAGE22'})

    def _validate(self, payslip):
        payslip.compute_sheet()
        payslip.action_payslip_done()
        if payslip.move_id.state == 'draft':
            payslip.move_id.action_post()
        return payslip

    def _pay(self, payslip, tax_channel):
        routing = {}
        for line in payslip._gec_payroll_authority_lines():
            routing[(line.partner_id.id, line.account_id.id)] = (
                tax_channel if line.partner_id == self.treasury else self.channel)
        return payslip._gec_payroll_pay({payslip.id: self.channel}, routing, fields.Date.today())

    def _payroll_batches(self):
        return self.env['account.batch.payment'].search([('gec_payroll_is_batch', '=', True)])

    def test_salary_and_pension_go_through_bog(self):
        payslip = self._validate(self.hr_payslip_john)
        self._pay(payslip, self.manual_channel)

        payments = self._payroll_batches().payment_ids
        salary = payments.filtered(lambda p: p.partner_id == payslip.employee_id.work_contact_id)
        pension = payments.filtered(lambda p: p.partner_id == self.agency)
        tax = payments.filtered(lambda p: p.partner_id == self.treasury)

        self.assertEqual(salary.payment_method_line_id, self.channel)
        self.assertEqual(salary.gec_bank_code, 'bog_transfer')
        self.assertEqual((salary.bog_transfer_type, salary.bog_is_salary), ('domestic', True))
        self.assertEqual(salary.bog_dispatch_type, 'BULK' if salary.amount <= 10000 else 'MT103')
        self.assertEqual(pension.partner_bank_id, self.agency_bog,
                         "the agency must be paid into its own BOG account, not the first one")
        self.assertFalse(pension.bog_is_salary)
        self.assertEqual(tax.payment_method_line_id, self.manual_channel)
        self.assertEqual(payslip.state, 'paid')

    def test_income_tax_cannot_be_routed_to_bog(self):
        payslip = self._validate(self.hr_payslip_john)
        with self.assertRaisesRegex(UserError, 'no treasury transfers'):
            self._pay(payslip, self.channel)
        self.assertFalse(self._payroll_batches())
        self.assertEqual(payslip.state, 'validated')

    def test_foreign_iban_is_refused_before_anything_is_created(self):
        self.hr_employee_john.bank_account_ids.write({
            'account_number': 'IT22M8576110068R4A56E760901', 'bank_bic': False})
        payslip = self._validate(self.hr_payslip_john)
        with self.assertRaisesRegex(UserError, 'Georgian IBAN'):
            self._pay(payslip, self.manual_channel)
        self.assertFalse(self._payroll_batches())

    def test_recipient_account_needs_its_bank_code(self):
        self.agency_bog.bank_bic = False
        self.agency_tbc.unlink()
        payslip = self._validate(self.hr_payslip_john)
        with self.assertRaisesRegex(UserError, r'needs the bank \(BIC\)'):
            self._pay(payslip, self.manual_channel)
        self.assertFalse(self._payroll_batches())

    def test_batch_buttons_submit_and_approve_every_transfer(self):
        approver = self.env['bog.approval'].create({'approver_id': self.env.user.id})
        self.connection.write({'approval_id': approver.id, 'processing_mode': 'odoo_approve',
                               'allow_self_approval': True})
        self._pay(self._validate(self.hr_payslip_john), self.manual_channel)
        batch = self._payroll_batches().filtered(
            lambda b: b.gec_payroll_kind == 'salary' and b.gec_payroll_channel_id == self.channel)
        self.assertEqual(batch.bog_processing_mode, 'odoo_approve')

        batch.action_bog_submit_approval()
        self.assertEqual(set(batch.payment_ids.mapped('gec_bank_state')), {'awaiting_approval'})
        batch.action_bog_approve()
        self.assertEqual(set(batch.payment_ids.mapped('gec_bank_state')), {'approved'})
