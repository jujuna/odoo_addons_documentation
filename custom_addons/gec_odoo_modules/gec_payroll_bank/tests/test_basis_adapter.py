import unittest
from types import SimpleNamespace

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBasisPayrollAdapter(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'basisbank.connection' not in cls.env:
            raise unittest.SkipTest("basis_bank is not installed")
        method = cls.env.ref('basis_bank.account_payment_method_basisbank')
        journal = cls.env['account.journal'].create({
            'name': 'Basis Payroll Test',
            'code': 'BPAY',
            'type': 'bank',
            'company_id': cls.env.company.id,
            'bank_account_number': 'GE00TESTSENDER0000001',
        })
        journal.bank_account_id.bank_bic = 'CBASGE22'
        outstanding = cls.env['account.account'].create({
            'name': 'Basis Payroll Outstanding',
            'code': 'BPAYOUT',
            'account_type': 'asset_current',
            'reconcile': True,
        })
        cls.channel = journal.outbound_payment_method_line_ids.filtered(
            lambda line: line.code == 'basisbank_transfer')[:1]
        if cls.channel:
            cls.channel.payment_account_id = outstanding
        else:
            cls.channel = cls.env['account.payment.method.line'].create({
                'name': method.name,
                'payment_method_id': method.id,
                'journal_id': journal.id,
                'payment_account_id': outstanding.id,
            })

    def test_mixed_member_result_is_partial(self):
        payments = (
            self.env['account.payment'].new({'basisbank_state': 'sent'})
            | self.env['account.payment'].new({'basisbank_state': 'failed'})
        )
        batch = SimpleNamespace(
            payment_ids=payments,
            basisbank_state='sent_pending_confirm',
        )

        self.assertEqual(self.channel._gec_bank_handoff_state(batch), 'partial')

    def test_actual_recipient_without_bic_is_refused(self):
        gel = self.env['res.currency'].with_context(active_test=False).search([
            ('name', '=', 'GEL'),
        ], limit=1)
        gel.active = True
        partner = self.env['res.partner'].create({'name': 'Payroll Recipient'})
        account = self.env['res.partner.bank'].create({
            'account_number': 'GE00TEST000000000001',
            'partner_id': partner.id,
            'allow_out_payment': True,
        })
        payment = self.env['account.payment'].new({
            'partner_id': partner.id,
            'partner_bank_id': account.id,
            'currency_id': gel.id,
            'memo': 'Salary payment',
        })

        with self.assertRaisesRegex(UserError, 'receiver bank BIC'):
            self.channel._gec_bank_payment_vals('salary', payment)
