import unittest

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import BogCommon


@tagged('post_install', '-at_install')
class TestBankIsolation(BogCommon):
    """Every bank button acts on its own bank's payments only, also over RPC."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'tbc.connection' not in cls.env:
            raise unittest.SkipTest("tbc_bank is not installed")
        tbc_account = cls.env['res.partner.bank'].create({
            'account_number': 'GE29TB7777777777777755',
            'partner_id': cls.company.partner_id.id,
            'bank_bic': 'TBCBGE22',
        })
        cls.tbc_journal = cls.env['account.journal'].create({
            'name': 'TBC Isolation', 'type': 'bank', 'code': 'TBCIS', 'bank_account_id': tbc_account.id,
        })
        method = cls.env.ref('tbc_bank.account_payment_method_tbc')
        cls.tbc_line = cls.tbc_journal.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id == method)[:1]
        cls.tbc_recipient = cls.env['res.partner.bank'].create({
            'account_number': 'GE29TB9999999999999955',
            'partner_id': cls.partner.id,
            'bank_bic': 'TBCBGE22',
        })

    def _tbc_payment(self, state):
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier',
            'partner_id': self.partner.id, 'partner_bank_id': self.tbc_recipient.id,
            'journal_id': self.tbc_journal.id, 'payment_method_line_id': self.tbc_line.id,
            'amount': 10.0, 'memo': 'TBC isolation', 'tbc_transfer_type': 'internal',
        })
        payment.action_post()
        payment._gec_bank_internal_write({'gec_bank_state': state, 'gec_bank_request_id': '1%08d' % payment.id})
        return payment

    def _bog_payment(self, state):
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': state, 'gec_bank_request_id': 'bog-%s' % payment.id})
        return payment

    def test_each_payment_runs_its_own_bank_flow(self):
        tbc, bog = self._tbc_payment('pending'), self._bog_payment('pending')
        self.assertEqual((tbc.gec_bank_code, bog.gec_bank_code), ('tbc_transfer', 'bog_transfer'))

    def test_tbc_buttons_refuse_a_bog_payment(self):
        bog = self._bog_payment('unknown')
        for action in (bog.action_tbc_recover, bog.action_tbc_send):
            with self.assertRaisesRegex(UserError, 'not an outbound TBC Bank transfer'):
                action()
        bog._gec_bank_internal_write({'gec_bank_state': 'awaiting_approval'})
        with self.assertRaisesRegex(UserError, 'No TBC Bank transfer awaiting approval'):
            bog.action_tbc_approve()
        with self.assertRaisesRegex(UserError, 'No pending TBC Bank transfer'):
            bog.action_tbc_submit_approval()
        bog.action_tbc_confirm_manual()
        bog.action_tbc_refresh_status()
        self.assertEqual(bog.gec_bank_state, 'awaiting_approval')

    def test_bog_buttons_refuse_a_tbc_payment(self):
        """Only the bank check stops Reset to Pending."""
        tbc = self._tbc_payment('failed')
        for state, action in (('failed', tbc.action_bog_reset_to_pending),
                              ('failed', tbc.action_bog_create_anyway),
                              ('sent', tbc.action_bog_cancel_document),
                              ('pending', tbc.action_bog_upload_attachments),
                              ('unknown', tbc.action_bog_recover),
                              ('pending', tbc.action_bog_send)):
            tbc._gec_bank_internal_write({'gec_bank_state': state})
            with self.assertRaisesRegex(UserError, 'not an outbound Bank of Georgia transfer'):
                action()
            self.assertEqual(tbc.gec_bank_state, state)

    def test_mixed_selection_only_moves_the_buttons_bank(self):
        tbc, bog = self._tbc_payment('sent'), self._bog_payment('sent')
        (tbc | bog).action_bog_confirm_manual()
        self.assertEqual((tbc.gec_bank_state, bog.gec_bank_state), ('sent', 'confirmed'))
        (tbc | bog).action_tbc_confirm_manual()
        self.assertEqual(tbc.gec_bank_state, 'confirmed')

    def test_payment_moving_to_another_bank_starts_clean(self):
        """BOG would otherwise reuse TBC's request id as its UniqueId."""
        payment = self._tbc_payment('failed')
        payment._gec_bank_internal_write({'gec_bank_reference': 'T-77', 'gec_bank_approved_by': self.env.user.id})
        payment.action_draft()
        payment.write({'journal_id': self.journal.id, 'payment_method_line_id': self.method_line.id,
                       'partner_bank_id': self.partner_bank.id})
        self.assertEqual(payment.gec_bank_code, 'bog_transfer')
        self.assertEqual(payment.gec_bank_state, 'pending')
        self.assertFalse(payment.gec_bank_request_id or payment.gec_bank_reference or payment.gec_bank_approved_by)
        self.assertIn('T-77', payment.message_ids[0].body)

    def test_a_payment_at_the_bank_cannot_change_bank(self):
        payment = self._tbc_payment('sent')
        with self.assertRaisesRegex(UserError, 'cannot move to another bank'):
            payment.write({'payment_method_line_id': self.tbc_journal.outbound_payment_method_line_ids.filtered(
                lambda line: line.code != 'tbc_transfer')[:1].id})

    def test_a_journal_with_a_payment_at_the_bank_cannot_change_bank_by_account_number(self):
        """Saving a Georgian account number fills its bank's BIC, so a BOG number alone would take the transfer off TBC."""
        self._tbc_payment('sent')
        with self.assertRaisesRegex(UserError, "journal's bank cannot change"):
            self.tbc_journal.bank_account_id.account_number = 'GE29BG7777777777777755'
        self.assertTrue(self.tbc_journal.is_tbc)

    def test_basis_payments_stay_out_of_the_shared_flow(self):
        if 'basisbank.connection' not in self.env:
            self.skipTest("basis_bank is not installed")
        basis_method = self.env.ref('basis_bank.account_payment_method_basisbank')
        line = self.env['account.payment.method.line'].new({'payment_method_id': basis_method.id})
        self.assertFalse(line._gec_bank_transfer_flow())

    def test_payment_list_shows_one_bank_state_column(self):
        arch = self.env['account.payment'].get_views([(False, 'list')])['views']['list']['arch']
        self.assertEqual(arch.count('name="gec_bank_state"'), 1)
