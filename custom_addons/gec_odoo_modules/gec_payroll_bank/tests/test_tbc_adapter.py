import unittest
from types import SimpleNamespace

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.hr_payroll_account.tests.test_hr_payroll_account import TestHrPayrollAccountCommon


def _tbc_connection(env, **values):
    """The company's TBC connection, reused when the database already has one (one per company)."""
    connection = env['tbc.connection'].search([('company_id', '=', env.company.id)], limit=1)
    if not connection:
        connection = env['tbc.connection'].create({
            'company_id': env.company.id,
            'client_id': 'payroll-client',
            'client_secret': 'payroll-secret',
            'environment': 'test',
            'processing_mode': 'direct',
        })
    connection.write(dict({'state': 'active', 'processing_mode': 'direct'}, **values))
    return connection


def _tbc_channel(env, code, iban):
    """A TBC journal with its 'TBC Bank Transfer' line, ready to be a payroll channel."""
    company_account = env['res.partner.bank'].create({
        'account_number': iban,
        'partner_id': env.company.partner_id.id,
        'bank_bic': 'TBCBGE22',
    })
    journal = env['account.journal'].create({
        'name': 'TBC %s' % code, 'code': code, 'type': 'bank',
        'company_id': env.company.id, 'bank_account_id': company_account.id,
    })
    channel = journal._tbc_method_line()
    channel.payment_account_id = env['account.account'].create({
        'name': 'TBC Outstanding %s' % code, 'code': 'O%s' % code,
        'account_type': 'asset_current', 'reconcile': True,
    })
    return channel


@tagged('post_install', '-at_install')
class TestTbcPayrollHooks(TransactionCase):
    """The TBC answers to gec_payroll_bank's hooks, one by one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'tbc.connection' not in cls.env:
            raise unittest.SkipTest("tbc_bank is not installed")
        cls.connection = _tbc_connection(cls.env)
        cls.channel = _tbc_channel(cls.env, 'TBCH', 'GE29TB7777777777777702')

    def _state_of(self, *tbc_states):
        payments = self.env['account.payment']
        for gec_bank_state in tbc_states:
            payments |= self.env['account.payment'].new({'gec_bank_state': gec_bank_state})
        return self.channel._gec_bank_handoff_state(SimpleNamespace(payment_ids=payments))

    def test_tbc_is_an_api_channel(self):
        self.assertEqual(self.channel._gec_bank_channel_kind(), 'api')
        self.assertFalse(self.channel._gec_bank_config_errors())

    def test_channel_needs_an_unblocked_connection(self):
        self.connection.state = 'blocked'
        self.assertIn("The TBC Bank connection is blocked. Contact the bank.",
                      self.channel._gec_bank_config_errors())
        self.connection.company_id = self.env['res.company'].create({'name': 'TBC Other Co'})
        self.channel.journal_id.invalidate_recordset(['tbc_connection_id'])
        self.assertTrue(any('No TBC Bank connection' in error
                            for error in self.channel._gec_bank_config_errors()))

    def test_treasury_recipient_gets_a_treasury_transfer(self):
        treasury = self.env['res.partner'].create({
            'name': 'State Treasury', 'gec_treasury_code': ' 101001000 '})
        payment = self.env['account.payment'].new({'partner_id': treasury.id})
        self.assertEqual(self.channel._gec_bank_payment_vals('authority', payment),
                         {'tbc_transfer_type': 'treasury', 'tbc_treasury_code': '101001000'})
        employee = self.env['res.partner'].create({'name': 'Payroll Employee'})
        payment = self.env['account.payment'].new({'partner_id': employee.id})
        self.assertEqual(self.channel._gec_bank_payment_vals('salary', payment), {})

    def test_watchdog_state_is_read_from_every_payment(self):
        self.assertEqual(self._state_of('failed', 'failed'), 'failed')
        self.assertEqual(self._state_of('sent', 'failed'), 'partial')
        self.assertEqual(self._state_of('confirmed', 'unknown'), 'uncertain')
        self.assertEqual(self._state_of('sent', 'sending'), 'uncertain')
        self.assertEqual(self._state_of('sent', 'pending'), 'prepared')
        self.assertEqual(self._state_of('awaiting_approval', 'approved'), 'prepared')
        self.assertEqual(self._state_of('sent', 'confirmed'), 'transmitted')
        self.assertEqual(self._state_of('confirmed', 'confirmed'), 'confirmed')
        self.assertEqual(self._state_of(), 'prepared')


@tagged('post_install', '-at_install')
class TestTbcPayrollFlow(TestHrPayrollAccountCommon):
    """Pay Salaries through a TBC channel, without sending.
    One entry: net salary; pension leg (account at TBC and another bank); tax leg (State Treasury, Treasury Code)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'tbc.connection' not in cls.env:
            raise unittest.SkipTest("tbc_bank is not installed")
        account = cls.env['account.account']
        cls.net_account = account.create({
            'name': 'TBC Salary Payable', 'code': 'TBCNET',
            'reconcile': True, 'account_type': 'liability_current',
        })
        cls.pension_account = account.create({
            'name': 'TBC Pension Payable', 'code': 'TBCPEN',
            'reconcile': True, 'account_type': 'liability_payable',
        })
        cls.tax_account = account.create({
            'name': 'TBC Income Tax Payable', 'code': 'TBCPIT',
            'reconcile': True, 'account_type': 'liability_payable',
        })
        expense_account = account.create({
            'name': 'TBC Salary Expense', 'code': 'TBCEXP', 'account_type': 'expense',
        })
        cls.agency = cls.env['res.partner'].create({'name': 'Pension Agency'})
        cls.agency_bog, cls.agency_tbc = cls.env['res.partner.bank'].create([{
            'account_number': 'GE03BG0000000131131564', 'partner_id': cls.agency.id,
            'bank_bic': 'BAGAGE22', 'allow_out_payment': True, 'sequence': 1,
        }, {
            'account_number': 'GE88TB7458336020100010', 'partner_id': cls.agency.id,
            'bank_bic': 'TBCBGE22', 'allow_out_payment': True, 'sequence': 2,
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
            'account_debit': cls.pension_account.id,
            'struct_ids': [Command.set(structure.ids)],
        }, {
            'name': 'Income Tax', 'code': 'PIT', 'sequence': 191,
            'amount_select': 'fix', 'amount_fix': -20.0,
            'category_ids': [Command.set(deduction.ids)],
            'partner_id': cls.treasury.id,
            'account_debit': cls.tax_account.id,
            'struct_ids': [Command.set(structure.ids)],
        }])
        structure.journal_id.default_account_id = cls.net_account

        cls.connection = _tbc_connection(cls.env)
        cls.channel = _tbc_channel(cls.env, 'TBCPY', 'GE29TB7777777777777777')
        cls.hr_employee_john.bank_account_ids.write({
            'account_number': 'GE29TB9999999999999999', 'bank_bic': 'TBCBGE22'})

    def _validate(self, payslip):
        payslip.compute_sheet()
        payslip.action_payslip_done()
        if payslip.move_id.state == 'draft':
            payslip.move_id.action_post()
        return payslip

    def _pay(self, payslips):
        authority_routing = {
            (line.partner_id.id, line.account_id.id): self.channel
            for line in payslips._gec_payroll_authority_lines()
        }
        return payslips._gec_payroll_pay(
            {slip.id: self.channel for slip in payslips}, authority_routing, fields.Date.today())

    def _payroll_batches(self):
        return self.env['account.batch.payment'].search([('gec_payroll_is_batch', '=', True)])

    def test_salary_pension_and_income_tax_go_through_tbc(self):
        payslip = self._validate(self.hr_payslip_john)
        self._pay(payslip)

        batches = self._payroll_batches()
        self.assertEqual(sorted(batches.mapped('gec_payroll_kind')), ['authority', 'salary'])
        self.assertEqual(batches.gec_payroll_channel_id, self.channel)
        payments = batches.payment_ids
        self.assertTrue(all(payments.mapped(lambda p: p.gec_bank_code == 'tbc_transfer')))
        salary = payments.filtered(lambda p: p.partner_id == payslip.employee_id.work_contact_id)
        pension = payments.filtered(lambda p: p.partner_id == self.agency)
        tax = payments.filtered(lambda p: p.partner_id == self.treasury)

        self.assertEqual(salary.tbc_transfer_type, 'internal')
        self.assertEqual(pension.amount, 10.0)
        self.assertEqual(pension.partner_bank_id, self.agency_tbc,
                         "the agency must be paid into its own TBC account, not the first one")
        self.assertEqual(pension.tbc_transfer_type, 'internal')
        self.assertEqual(tax.amount, 20.0)
        self.assertEqual((tax.tbc_transfer_type, tax.tbc_treasury_code), ('treasury', '101001000'))
        order = tax._tbc_build_order()
        self.assertEqual(order['transferType'], 'TreasuryTransfer')
        self.assertEqual(order['treasuryCode'], '101001000')
        self.assertNotIn('creditAccount', order)

        self.assertEqual(payslip.state, 'paid')
        self.assertFalse(payslip._gec_payroll_employee_lines() | payslip._gec_payroll_authority_lines(),
                         "nothing of the payslip may stay unpaid")

    def test_two_payslips_of_one_employee_are_paid_separately(self):
        """Two months paid in one run stay two payments (merging them crashed on 'Expected singleton')."""
        first = self.hr_payslip_john
        second = self.env['hr.payslip'].create({
            'name': 'John Previous Month',
            'employee_id': first.employee_id.id,
            'version_id': first.version_id.id,
            'struct_id': first.struct_id.id,
            'journal_id': first.journal_id.id,
            'date_from': first.date_from - relativedelta(months=1),
            'date_to': first.date_from - relativedelta(days=1),
        })
        payslips = self._validate(first) | self._validate(second)
        self._pay(payslips)

        salary = self._payroll_batches().filtered(
            lambda batch: batch.gec_payroll_kind == 'salary').payment_ids
        self.assertEqual(len(salary), 2)
        self.assertEqual(set(payslips.mapped('state')), {'paid'})

    def test_foreign_iban_is_refused_before_anything_is_created(self):
        self.hr_employee_john.bank_account_ids.write({
            'account_number': 'IT22M8576110068R4A56E760901', 'bank_bic': False})
        payslip = self._validate(self.hr_payslip_john)
        with self.assertRaisesRegex(UserError, 'Georgian IBAN'):
            self._pay(payslip)
        self.assertFalse(self._payroll_batches())
        self.assertEqual(payslip.state, 'validated')

    def test_treasury_code_must_have_nine_digits(self):
        self.treasury.gec_treasury_code = '10100100'
        payslip = self._validate(self.hr_payslip_john)
        with self.assertRaisesRegex(UserError, '9-digit Treasury Code'):
            self._pay(payslip)
        self.assertFalse(self._payroll_batches())

    def test_batch_buttons_submit_and_approve_every_transfer(self):
        approver = self.env['tbc.approval'].create({'approver_id': self.env.user.id})
        self.connection.write({'approval_id': approver.id, 'processing_mode': 'odoo_approve',
                               'allow_self_approval': True})
        self._pay(self._validate(self.hr_payslip_john))
        # The salary batch: the test company runs in USD, and TBC takes treasury transfers in GEL only.
        batch = self._payroll_batches().filtered(lambda b: b.gec_payroll_kind == 'salary')
        self.assertEqual(batch.tbc_processing_mode, 'odoo_approve')

        batch.action_tbc_submit_approval()
        self.assertEqual(set(batch.payment_ids.mapped('gec_bank_state')), {'awaiting_approval'})
        batch.action_tbc_approve()
        self.assertEqual(set(batch.payment_ids.mapped('gec_bank_state')), {'approved'})
        self.assertEqual(batch.payment_ids.gec_bank_approved_by, self.env.user)
