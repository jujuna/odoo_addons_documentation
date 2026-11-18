import json
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import LockError, UserError
from odoo.tests.common import tagged

from .common import BogCommon


@tagged('post_install', '-at_install')
class TestBogBatch(BogCommon):
    """Bulk sends: a package's answer only reaches its own members."""

    def setUp(self):
        super().setUp()
        self.connection.store_token('tok-123', 3600)

    def _batch(self, payments):
        return self.env['account.batch.payment'].create({
            'journal_id': self.journal.id,
            'batch_type': 'outbound',
            'payment_method_id': self.method_line.payment_method_id.id,
            'payment_ids': [Command.set(payments.ids)],
        })

    def _bank_answers(self, body, status=200):
        return patch('requests.request', return_value=self._response(status, body))

    def _back_to_paid(self, payment):
        """The user's recovery of a failed transfer: reset to draft and confirm again; the bank state stays Failed."""
        payment.action_draft()
        payment.action_post()
        self.assertEqual((payment.state, payment.gec_bank_state), ('paid', 'failed'))

    def _rejected_notes(self, payment):
        return [text for text in payment.message_ids.mapped('body') if 'marked Rejected' in text]

    def test_bulk_send_marks_each_payment_with_its_package(self):
        first, second = self._new_payment(), self._new_payment()
        batch = self._batch(first | second)
        with self._bank_answers('777'):
            batch.action_bog_send_batch()
        self.assertEqual(batch.bog_bulk_key, '777')
        self.assertEqual((first | second).mapped('bog_bulk_key'), ['777', '777'])
        self.assertEqual(set((first | second).mapped('gec_bank_state')), {'created'})

    def test_batch_is_not_sent_again_while_its_earlier_send_is_open(self):
        """A second package would take the batch's key while the first is open."""
        first, second = self._new_payment(), self._new_payment()
        batch = self._batch(first | second)
        with self._bank_answers('777'):
            batch.action_bog_send_batch()
        first._gec_bank_write_result({'gec_bank_state': 'failed'})
        with self.assertRaisesRegex(UserError, 'not settled'):
            batch.action_bog_send_batch()
        with self.assertRaisesRegex(UserError, 'not settled'):
            batch.action_bog_send_batch_individually()

    def test_package_rejection_leaves_a_transfer_sent_on_its_own_alone(self):
        """A member resent on its own is outside the rejected package and must not be marked failed."""
        first, second = self._new_payment(), self._new_payment()
        batch = self._batch(first | second)
        with self._bank_answers('777'):
            batch.action_bog_send_batch()
        with self._bank_answers(json.dumps({'Status': 'R'})):
            batch._bog_refresh_bulk_status()
        self.assertEqual(set((first | second).mapped('gec_bank_state')), {'failed'})

        first.action_draft()
        first.action_post()
        first.action_bog_reset_to_pending()
        with self._bank_answers(json.dumps([{'UniqueKey': 5551, 'ResultCode': 0}])):
            first._bog_send_one()
        self.assertEqual(first.gec_bank_state, 'created')
        self.assertFalse(first.bog_bulk_key)

        with self._bank_answers(json.dumps({'Status': 'R'})):
            batch._bog_refresh_bulk_status()
        self.assertEqual(first.gec_bank_state, 'created')
        self.assertEqual(second.gec_bank_state, 'failed')

    def test_a_failed_claim_releases_the_claims_before_it(self):
        """Nothing was sent, so earlier claims go back to their state."""
        payments = self._new_payment() | self._new_payment()
        batch = self._batch(payments)
        last = batch._bog_sendable_payments()[-1]
        real_reserve = type(last)._bog_reserve_send

        def reserve(payment):
            if payment == last:
                raise UserError("claimed elsewhere")
            return real_reserve(payment)

        with patch.object(type(last), '_bog_reserve_send', reserve), \
                patch('requests.request') as request, self.assertRaisesRegex(UserError, 'claimed elsewhere'):
            batch.action_bog_send_batch()
        request.assert_not_called()
        released = payments - last
        released.invalidate_recordset(['gec_bank_state'])
        self.assertEqual(released.gec_bank_state, 'pending')

    def test_bulk_answer_without_a_key_leaves_no_member_sending(self):
        """No key, no package status: each member must be recoverable alone."""
        payments = self._new_payment() | self._new_payment()
        batch = self._batch(payments)
        with self._bank_answers('null'):
            batch.action_bog_send_batch()
        self.assertEqual(batch.bog_state, 'unknown')
        self.assertEqual(set(payments.mapped('gec_bank_state')), {'unknown'})

    def test_send_one_by_one_all_failed_gives_a_failed_batch(self):
        batch = self._batch(self._new_payment() | self._new_payment())
        with self._bank_answers('{"message": "bad iban"}', 400):
            batch.action_bog_send_batch_individually()
        self.assertEqual(batch.bog_state, 'failed')

    def test_send_one_by_one_all_created_gives_a_created_batch_without_an_old_key(self):
        batch = self._batch(self._new_payment() | self._new_payment())
        batch._gec_bank_internal_write({'bog_bulk_key': '555', 'bog_state': 'unknown'})
        keys = iter(range(7001, 7010))

        def answer(method, url, **kwargs):
            """A create answers with the next key; a status lookup answers empty."""
            body = json.dumps([{'UniqueKey': next(keys), 'ResultCode': 0}]) if method == 'POST' else '{}'
            return self._response(200, body)

        with patch('requests.request', side_effect=answer):
            batch.action_bog_send_batch_individually()
        self.assertEqual(batch.bog_state, 'created')
        self.assertFalse(batch.bog_bulk_key)

    def test_refresh_of_a_batch_without_a_key_takes_its_state_from_its_transfers(self):
        payments = self._new_payment() | self._new_payment()
        batch = self._batch(payments)
        batch._gec_bank_internal_write({'bog_state': 'unknown'})
        for payment in payments:
            payment._gec_bank_write_result({'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'status'})
        with patch('requests.request') as request:
            batch.action_bog_refresh_bulk_status()
        request.assert_not_called()
        self.assertEqual(batch.bog_state, 'confirmed')

    def test_poll_takes_a_batch_without_a_key_only_while_a_transfer_is_open(self):
        self.connection.state = 'active'
        open_batch = self._batch(self._new_payment())
        settled_batch = self._batch(self._new_payment())
        open_batch.payment_ids._gec_bank_write_result({'gec_bank_state': 'created'})
        settled_batch.payment_ids._gec_bank_write_result({'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'status'})
        polled = self.env['account.batch.payment']

        def record(batch):
            nonlocal polled
            polled |= batch

        with patch.object(type(open_batch), '_bog_refresh_bulk_status', record):
            self.env['account.batch.payment']._cron_bog_bulk_status_poll()
        self.assertIn(open_batch, polled)
        self.assertNotIn(settled_batch, polled)

    def test_reset_of_a_failed_package_member_clears_its_package_key_and_keeps_its_request_id(self):
        first, second = self._new_payment(), self._new_payment()
        batch = self._batch(first | second)
        with self._bank_answers('777'):
            batch.action_bog_send_batch()
        request_id = first.gec_bank_request_id
        with self._bank_answers(json.dumps({'Status': 'R'})):
            batch._bog_refresh_bulk_status()
        self.assertEqual(first.bog_bulk_key, '777')
        first.action_bog_reset_to_pending()
        self.assertFalse(first.bog_bulk_key)
        self.assertEqual(first.gec_bank_request_id, request_id)

    def test_unrecognised_package_status_is_noted_once(self):
        batch = self._batch(self._new_payment() | self._new_payment())
        with self._bank_answers('777'):
            batch.action_bog_send_batch()
        for _poll in range(2):
            with self._bank_answers(json.dumps({'Status': 'XX'})):
                batch._bog_refresh_bulk_status()
        notes = [text for text in batch.message_ids.mapped('body') if 'unrecognised' in text]
        self.assertEqual(len(notes), 1)

    def test_send_one_by_one_names_a_refused_payment(self):
        good, refused = self._new_payment(), self._new_payment()
        batch = self._batch(good | refused)
        refused.mark_as_sent()
        with self._bank_answers(json.dumps([{'UniqueKey': 6161, 'ResultCode': 0}])):
            action = batch.action_bog_send_batch_individually()
        self.assertIn(refused.display_name, action['params']['message'])
        self.assertEqual(batch.bog_state, 'partial')

    def test_refresh_of_a_batch_without_a_key_does_not_reject_a_failed_transfer_that_is_paid_again(self):
        first = self._new_payment()
        batch = self._batch(first | self._new_payment())
        first._gec_bank_write_result({'gec_bank_state': 'failed', 'gec_bank_reference': '55'})
        self._back_to_paid(first)
        notes = len(self._rejected_notes(first))
        with self._bank_answers(json.dumps({'Status': 'R'})):
            batch.action_bog_refresh_bulk_status()
        self.assertEqual((first.state, first.gec_bank_state), ('paid', 'failed'))
        self.assertEqual(len(self._rejected_notes(first)), notes)

    def test_package_line_rejected_does_not_reject_a_failed_transfer_that_is_paid_again(self):
        first, second = self._new_payment(), self._new_payment()
        batch = self._batch(first | second)
        with self._bank_answers('777'):
            batch.action_bog_send_batch()
        with self._bank_answers(json.dumps({'Status': 'R'})):
            batch._bog_refresh_bulk_status()
        self._back_to_paid(first)
        notes = len(self._rejected_notes(first))
        body = json.dumps({'Status': 'S', 'DocumentStatuses': [{'UniqueId': first.gec_bank_request_id, 'Status': 'R'}]})
        with self._bank_answers(body):
            batch._bog_refresh_bulk_status()
        self.assertEqual((first.state, first.gec_bank_state), ('paid', 'failed'))
        self.assertEqual(len(self._rejected_notes(first)), notes)

    def test_refresh_of_a_batch_without_a_key_asks_the_bank_only_about_open_transfers(self):
        confirmed, failed, sent = self._new_payment(), self._new_payment(), self._new_payment()
        batch = self._batch(confirmed | failed | sent)
        confirmed._gec_bank_write_result({'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'status', 'gec_bank_reference': '51'})
        failed._gec_bank_write_result({'gec_bank_state': 'failed', 'gec_bank_reference': '52'})
        sent._gec_bank_write_result({'gec_bank_state': 'sent', 'gec_bank_reference': '53'})
        with self._bank_answers(json.dumps({'Status': 'S'})) as request:
            batch.action_bog_refresh_bulk_status()
        self.assertEqual(request.call_count, 1)
        self.assertIn('53', request.call_args.args[1])

    def test_send_is_refused_while_another_process_holds_the_batch(self):
        batch = self._batch(self._new_payment())
        with patch.object(type(batch), 'lock_for_update', side_effect=LockError("locked")), \
                self.assertRaisesRegex(UserError, 'already being processed'):
            batch._bog_sendable_payments()

    def test_poll_takes_a_batch_without_a_key_left_unknown_and_moves_it_out_of_unknown(self):
        self.connection.state = 'active'
        batch = self._batch(self._new_payment() | self._new_payment())
        batch._gec_bank_internal_write({'bog_state': 'unknown'})
        self.env['account.batch.payment']._cron_bog_bulk_status_poll()
        self.assertEqual(batch.bog_state, 'draft')

    def test_batch_state_from_its_transfers_without_a_package(self):
        first, second = self._new_payment(), self._new_payment()
        batch = self._batch(first | second)
        self.assertEqual(batch._bog_state_from_members(), 'draft')
        first._gec_bank_write_result({'gec_bank_state': 'unknown'})
        self.assertEqual(batch._bog_state_from_members(), 'unknown')
        first._gec_bank_write_result({'gec_bank_state': 'sent'})
        second._gec_bank_write_result({'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'status'})
        self.assertEqual(batch._bog_state_from_members(), 'sent')
