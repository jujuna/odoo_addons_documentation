from odoo import Command
from odoo.tests.common import tagged
from odoo.addons.account_online_synchronization.tests.common import AccountOnlineSynchronizationCommon


@tagged('post_install', '-at_install')
class TestAccountOnlinePaymentBatch(AccountOnlineSynchronizationCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account_online_link.is_payment_enabled = True
        cls.account_online_link.is_payment_activated = True

        cls.partner_bank = cls.env['res.partner.bank'].create({
            'account_number': 'BE68539007547034',
            'account_type': 'iban',
            'allow_out_payment': True,
            'partner_id': cls.partner.id,
        })

        cls.company_bank = cls.env['res.partner.bank'].create({
            'account_number': 'BE32707171912447',
            'account_type': 'iban',
            'partner_id': cls.env.company.partner_id.id,
        })
        cls.euro_bank_journal.bank_account_id = cls.company_bank

        sepa_ct = cls.env.ref('account_iso20022.account_payment_method_sepa_ct')
        cls.sepa_method_line = cls.euro_bank_journal.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id == sepa_ct,
        )[0]

    def test_prepare_payment_data_missing_transaction_uuid(self):
        payment = self.env['account.payment'].create({
            'partner_id': self.partner.id,
            'partner_bank_id': self.partner_bank.id,
            'amount': 100.0,
            'payment_type': 'outbound',
            'journal_id': self.euro_bank_journal.id,
            'payment_method_line_id': self.sepa_method_line.id,
        })
        payment.transaction_uuid = ''
        payment.action_post()

        batch = self.env['account.batch.payment'].create({
            'batch_type': 'outbound',
            'journal_id': self.euro_bank_journal.id,
            'payment_ids': [Command.set(payment.ids)],
        })

        data = batch._prepare_payment_data()
        self.assertTrue(data['payments'][0]['transaction_uuid'])
        self.assertEqual(data['payments'][0]['transaction_uuid'], payment.transaction_uuid)
