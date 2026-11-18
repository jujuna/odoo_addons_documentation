from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.gec_bank.models.account_payment import GEC_BANK_BYPASS_KEY


@tagged('post_install', '-at_install')
class TestGecBank(TransactionCase):
    """The shared plumbing every bank relies on, on a plain bank journal with no bank module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Test mode makes registry.cursor() share this transaction instead of a second connection.
        cls.enterClassContext(cls.registry_test_mode())
        cls.service = cls.env['gec.bank.service']
        cls.journal = cls.env['account.journal'].create({
            'name': 'Plain Bank', 'type': 'bank', 'code': 'GECPB',
            'bank_account_number': 'GE29XX0000000000000001',
        })
        cls.outstanding = cls.env['account.account'].create({
            'name': 'Plain Outstanding', 'code': 'GECOUT', 'account_type': 'asset_current',
            'reconcile': True,
        })
        cls.line = cls.journal.outbound_payment_method_line_ids[:1]
        cls.line.payment_account_id = cls.outstanding
        cls.partner = cls.env['res.partner'].create({'name': 'Plain Vendor'})

    def _payment(self, post=True, amount=100.0):
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier',
            'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'payment_method_line_id': self.line.id, 'amount': amount, 'memo': 'plain',
        })
        if post:
            payment.action_post()
        return payment

    def _at_bank(self):
        return patch.object(type(self.env['account.payment']), '_gec_bank_at_bank',
                            lambda payment: True)

    def test_a_double_click_cannot_claim_twice(self):
        payment = self._payment()
        claim = {'state': 'canceled', 'memo': 'request-1'}
        self.assertTrue(self.service._reserve_send(payment, claim, 'state', ('canceled',)))
        self.assertFalse(self.service._reserve_send(
            payment, {'state': 'canceled', 'memo': 'request-2'}, 'state', ('canceled',)))
        payment.invalidate_recordset(['memo'])
        self.assertEqual(payment.memo, 'request-1', "the first claim's request id stands")

    def test_durable_write_refuses_what_is_not_a_plain_column(self):
        payment = self._payment()
        with self.assertRaises(ValueError):
            self.service._durable_write(payment, {'display_name': 'x'})
        self.assertTrue(self.service._durable_write(payment, {'memo': 'durable'}))
        payment.invalidate_recordset(['memo'])
        self.assertEqual(payment.memo, 'durable')

    def test_a_payment_at_the_bank_cannot_be_undone(self):
        payment = self._payment()
        with self._at_bank():
            for undo in (payment.action_draft, payment.action_cancel, payment.move_id.button_draft,
                         payment.move_id.button_cancel):
                with self.assertRaisesRegex(UserError, 'at the bank'):
                    undo()
            with self.assertRaisesRegex(UserError, 'at the bank'):
                payment.unlink()
            payment.with_context(**{GEC_BANK_BYPASS_KEY: True}).action_draft()
        self.assertEqual(payment.state, 'draft', "core's statement unmatching still goes through")

    def test_only_a_paid_payment_can_be_sent(self):
        draft = self._payment(post=False)
        with self.assertRaisesRegex(UserError, 'Confirm these payments'):
            draft._gec_bank_check_sendable()
        rejected = self._payment()
        rejected.action_reject()
        with self.assertRaisesRegex(UserError, 'cannot be sent'):
            rejected._gec_bank_check_sendable()
        self._payment()._gec_bank_check_sendable()

    def test_bank_answers_map_onto_core_fields(self):
        payment = self._payment()
        self.assertEqual(payment._gec_bank_mirror_vals('held'), {'is_sent': True})
        self.assertEqual(payment._gec_bank_mirror_vals('rejected'), {'state': 'rejected'})

    def _statement_line(self, amount):
        return self.env['account.bank.statement.line'].create({
            'journal_id': self.journal.id, 'date': fields.Date.today(),
            'payment_ref': 'plain', 'amount': amount,
        })

    def test_statement_debit_for_the_amount_reconciles_the_payment(self):
        payment = self._payment()
        self.assertFalse(self._statement_line(100.0)._gec_bank_matches_payment(payment),
                         "a credit is never the payment's debit")
        self.assertFalse(self._statement_line(-99.0)._gec_bank_matches_payment(payment))
        line = self._statement_line(-100.0)
        self.assertTrue(line._gec_bank_matches_payment(payment))
        line._gec_bank_reconcile_payment(payment)
        self.assertTrue(payment.is_matched)

    def test_api_channel_gets_core_outstanding_account(self):
        Line = type(self.env['account.payment.method.line'])
        with patch.object(Line, '_gec_bank_channel_kind', lambda line: 'api'):
            line = self.env['account.payment.method.line'].create({
                'name': 'API channel', 'journal_id': self.journal.id,
                'payment_method_id': self.line.payment_method_id.id,
            })
        self.assertEqual(line.payment_account_id, self.journal._gec_bank_default_outstanding_account())

    def test_channel_setup_errors(self):
        self.assertEqual(self.line._gec_bank_config_errors(), [])
        self.line.payment_account_id = False
        self.assertTrue(any('no Outstanding Payments account' in error
                            for error in self.line._gec_bank_config_errors()))
        self.line.payment_account_id = self.journal.default_account_id
        self.assertTrue(any("journal's own account" in error or 'bank/cash account' in error
                            for error in self.line._gec_bank_config_errors()))

    def test_handoff_states_merge(self):
        merge = self.env['account.payment.method.line']._gec_bank_merge_handoff_states
        self.assertEqual(merge({'failed'}), 'failed')
        self.assertEqual(merge({'failed', 'confirmed'}), 'partial')
        self.assertEqual(merge({'uncertain', 'transmitted'}), 'uncertain')
        self.assertEqual(merge({'prepared', 'transmitted'}), 'prepared')
        self.assertEqual(merge({'confirmed'}), 'confirmed')
        self.assertEqual(merge(set()), 'prepared')

    def _paid_bill(self, amount=100.0):
        expense = self.env['account.account'].create({
            'name': 'Plain Expense', 'code': 'GECEXP', 'account_type': 'expense',
        })
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.partner.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'name': 'plain', 'quantity': 1, 'price_unit': amount, 'account_id': expense.id,
                'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({'journal_id': self.journal.id, 'payment_method_line_id': self.line.id})._create_payments()
        return bill, payment

    def test_reversing_the_entry_of_a_payment_at_the_bank_is_refused(self):
        bill, payment = self._paid_bill()
        reversal = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=payment.move_id.ids,
        ).create({'journal_id': payment.move_id.journal_id.id, 'date': fields.Date.today()})
        with self._at_bank(), self.assertRaisesRegex(UserError, 'at the bank'):
            reversal.refund_moves()
        self.assertNotEqual(bill.payment_state, 'not_paid', "the bill stays paid")

    def test_unreconciling_a_bill_paid_by_a_payment_at_the_bank_is_refused(self):
        bill, payment = self._paid_bill()
        partial = bill.line_ids.matched_debit_ids
        self.assertTrue(partial)
        with self._at_bank():
            with self.assertRaisesRegex(UserError, 'at the bank'):
                bill.js_remove_outstanding_partial(partial.id)
            self.assertNotEqual(bill.payment_state, 'not_paid')
            bill.with_context(**{GEC_BANK_BYPASS_KEY: True}).js_remove_outstanding_partial(partial.id)
        self.assertEqual(bill.payment_state, 'not_paid', "the core bypass key still goes through")

    def test_unreconciling_a_payment_not_at_the_bank_still_works(self):
        bill, payment = self._paid_bill()
        bill.js_remove_outstanding_partial(bill.line_ids.matched_debit_ids.id)
        self.assertEqual(bill.payment_state, 'not_paid')

    def test_a_batch_holding_a_payment_at_the_bank_cannot_be_deleted_or_emptied(self):
        payment = self._payment()
        batch = self.env['account.batch.payment'].create({
            'journal_id': self.journal.id, 'batch_type': 'outbound',
            'payment_ids': [Command.set(payment.ids)],
        })
        with self._at_bank():
            with self.assertRaisesRegex(UserError, 'at the bank'):
                batch.unlink()
            with self.assertRaisesRegex(UserError, 'at the bank'):
                batch.payment_ids = [Command.unlink(payment.id)]
        self.assertEqual(payment.batch_payment_id, batch)
        batch.payment_ids = [Command.unlink(payment.id)]
        self.assertFalse(payment.batch_payment_id, "a payment not at the bank leaves its batch")

    def test_a_payment_matched_with_the_statement_unlocks_the_bill(self):
        """Once the bank statement booked the money, the bill unreconciles like any other."""
        bill, payment = self._paid_bill()
        self._statement_line(-100.0)._gec_bank_reconcile_payment(payment)
        self.assertTrue(payment.is_matched)
        with self._at_bank():
            bill.js_remove_outstanding_partial(bill.line_ids.matched_debit_ids.id)
        self.assertEqual(bill.payment_state, 'not_paid')

    def test_a_context_or_personal_default_cannot_preset_bank_fields(self):
        self.env['ir.default'].set('account.payment', 'gec_bank_approved_by', self.env.uid, user_id=True)
        self.assertFalse(self._payment(post=False).gec_bank_approved_by)
        self.env = self.env(context={
            **self.env.context,
            'default_gec_bank_approved_by': self.env.uid,
            'default_gec_bank_state': 'approved',
            'default_gec_bank_request_id': 'FORGED',
        })
        forged = self._payment(post=False)
        self.assertFalse(forged.gec_bank_approved_by)
        self.assertFalse(forged.gec_bank_request_id)
        self.assertFalse(forged.gec_bank_state)

    def test_a_forged_default_gives_way_to_the_fields_own_default(self):
        Batch = self.env['account.batch.payment'].with_context(default_state='sent')
        with patch.object(type(Batch), '_gec_bank_protected_fields', lambda batch: {'state'}):
            self.assertEqual(Batch.default_get(['state']), {'state': 'draft'})

    def test_an_account_number_of_another_bank_cannot_take_held_payments_off_their_bank(self):
        """Saving a Georgian account number fills its bank's BIC (gec_localization), so the number alone can change the bank."""
        account = self.journal.bank_account_id
        account.account_number = 'GE29TB0000000000000001'
        payment = self._payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'sent'})
        with patch.object(type(payment), '_gec_bank_at_bank', lambda held: held.journal_id.bank_account_id.bank_bic == 'TBCBGE22'):
            account.account_number = 'GE29TB0000000000000002'
            with self.assertRaisesRegex(UserError, "journal's bank cannot change"):
                account.account_number = 'GE29BG0000000000000001'
        self.assertEqual(account.bank_bic, 'TBCBGE22')
