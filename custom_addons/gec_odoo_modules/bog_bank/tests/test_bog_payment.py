import json
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form
from odoo.tests.common import tagged

from odoo.addons.bog_bank.models.account_batch_payment import BOG_BATCH_PROTECTED_FIELDS
from odoo.addons.bog_bank.models.account_payment import BOG_PROTECTED_FIELDS

from .common import BogCommon


@tagged('post_install', '-at_install')
class TestBogPayment(BogCommon):
    """Document building, state changes and money-safety rules."""

    def setUp(self):
        super().setUp()
        self.connection.store_token('tok-123', 3600)

    def test_document_carries_required_fields(self):
        payment = self._new_payment()
        payment._bog_reserve_send()
        document = payment._bog_build_document()
        for key in ('Nomination', 'UniqueId', 'CheckUniqueId', 'Amount', 'Currency', 'DocumentNo',
                    'ValueDate', 'SourceAccountNumber', 'BeneficiaryAccountNumber'):
            self.assertIn(key, document, "%s is mandatory on a BOG document" % key)

    def test_document_no_fits_bog_limit(self):
        """BOG caps DocumentNo at 16 characters."""
        payment = self._new_payment()
        payment._bog_reserve_send()
        self.assertLessEqual(len(payment.bog_document_no), 16)

    def test_empty_values_are_dropped(self):
        payment = self._new_payment(memo=False)
        payment._bog_reserve_send()
        document = payment._bog_build_document()
        self.assertNotIn(False, document.values())
        self.assertNotIn('', document.values())

    def test_check_inn_only_sent_when_requested(self):
        """Result code 28 rejects CheckInn outside Bank of Georgia transfers."""
        payment = self._new_payment()
        payment._bog_reserve_send()
        self.assertNotIn('CheckInn', payment._bog_build_document())
        payment.bog_check_inn = True
        self.assertTrue(payment._bog_build_document()['CheckInn'])

    def test_payer_inn_is_not_sent(self):
        """PayerInn belongs only to a treasury payment for a third person (bog.md F6)."""
        self.company.vat = 'GE405123456'
        payment = self._new_payment()
        payment._bog_reserve_send()
        self.assertNotIn('PayerInn', payment._bog_build_document())

    def test_reserve_send_is_a_mutex(self):
        """A second claim must fail rather than mint a new UniqueId."""
        payment = self._new_payment()
        payment._bog_reserve_send()
        with self.assertRaises(UserError):
            payment._bog_reserve_send()

    def test_reserve_send_reuses_the_same_unique_id(self):
        payment = self._new_payment()
        unique_id, _document_no = payment._bog_reserve_send()
        payment._gec_bank_write_result({'gec_bank_state': 'failed'})
        again, _again_no = payment._bog_reserve_send()
        self.assertEqual(unique_id, again,
                         "a retry must reuse UniqueId or BOG cannot deduplicate it")

    def test_reservation_keeps_the_request_id_in_memory(self):
        """The document built after the reservation carries its UniqueId and DocumentNo."""
        payment = self._new_payment()
        unique_id, document_no = payment._bog_reserve_send()
        document = payment._bog_build_document()
        self.assertEqual((document['UniqueId'], document['DocumentNo']), (unique_id, document_no))

    def test_a_send_that_may_still_run_cannot_be_reset(self):
        payment = self._new_payment()
        payment._bog_reserve_send()
        with self.assertRaisesRegex(UserError, 'may still be on its way'):
            payment.action_bog_reset_to_pending()
        self.assertEqual(payment.gec_bank_state, 'sending')

    def test_a_payment_left_sending_by_a_crash_can_be_reset(self):
        """A crash after the reservation leaves 'sending' with no result."""
        payment = self._new_payment()
        unique_id, _document_no = payment._bog_reserve_send()
        self.assertEqual(payment.gec_bank_state, 'sending')
        self.env.cr.execute(
            "UPDATE account_payment SET write_date = write_date - interval '20 minutes' "
            "WHERE id = %s", [payment.id])
        payment.invalidate_recordset(['write_date'])
        payment.action_bog_reset_to_pending()
        self.assertEqual(payment.gec_bank_state, 'pending')
        again, _again_no = payment._bog_reserve_send()
        self.assertEqual(unique_id, again, "a resend must reuse the reserved UniqueId")

    def test_send_refuses_an_untrusted_account_before_calling_the_bank(self):
        """An untrusted recipient account is refused before anything reaches BOG."""
        payment = self._new_payment()
        self.partner_bank.allow_out_payment = False
        with patch('requests.request', return_value=self._response(200, '[]')) as request:
            with self.assertRaisesRegex(UserError, 'not trusted'):
                payment._bog_send_one()
        self.assertFalse(request.called)
        self.assertNotIn(payment.gec_bank_state, ('sending', 'created', 'sent'))

    def _send(self, payment, status=200, body='[]'):
        with patch('requests.request', return_value=self._response(status, body)):
            return payment._bog_send_one()

    def test_successful_create_lands_in_created_not_sent(self):
        """ResultCode 0 means 'ready for signature', not 'money moved'."""
        payment = self._new_payment()
        key = 900000 + payment.id
        body = json.dumps([{'UniqueId': 'x', 'UniqueKey': key, 'ResultCode': 0, 'Match': 100}])
        self._send(payment, 200, body)
        self.assertEqual(payment.gec_bank_state, 'created')
        self.assertEqual(payment.gec_bank_reference, str(key))

    def test_timeout_leaves_state_unknown(self):
        import requests
        payment = self._new_payment()
        with patch('requests.request', side_effect=requests.Timeout()):
            payment._bog_send_one()
        self.assertEqual(payment.gec_bank_state, 'unknown')

    def test_server_error_leaves_state_unknown(self):
        payment = self._new_payment()
        self._send(payment, 503, '')
        self.assertEqual(payment.gec_bank_state, 'unknown')

    def test_client_error_is_a_definite_failure(self):
        payment = self._new_payment()
        self._send(payment, 400, '{"message": "bad iban"}')
        self.assertEqual(payment.gec_bank_state, 'failed')

    def test_business_error_inside_200_is_a_failure(self):
        """A 200 carrying ResultCode 33 is a failed payment."""
        payment = self._new_payment()
        self._send(payment, 200, json.dumps([{'UniqueKey': 1, 'ResultCode': 33}]))
        self.assertEqual(payment.gec_bank_state, 'failed')
        self.assertEqual(payment.bog_result_code, 33)

    def test_warn_code_waits_for_confirmation(self):
        """333 = insufficient working balance: BOG asks, it does not refuse."""
        payment = self._new_payment()
        self._send(payment, 200, json.dumps([{'ResultCode': 333}]))
        self.assertEqual(payment.gec_bank_state, 'awaiting_confirmation')
        self.assertEqual(payment.bog_warn_code, 333)

    def test_duplicate_warning_never_offers_create_anyway(self):
        """Resending past 363 pays twice."""
        payment = self._new_payment()
        self._send(payment, 200, json.dumps([{'ResultCode': 363}]))
        self.assertEqual(payment.gec_bank_state, 'failed')
        with self.assertRaises(UserError):
            payment.action_bog_create_anyway()

    def test_approval_required_before_send(self):
        self.connection.approval_id = self.env['bog.approval'].create({
            'approver_id': self.env.user.id, 'company_id': self.company.id})
        self.connection.processing_mode = 'odoo_approve'
        payment = self._new_payment()
        with self.assertRaises(UserError):
            payment._bog_send_one()

    def test_maker_cannot_be_checker(self):
        self.connection.approval_id = self.env['bog.approval'].create({
            'approver_id': self.env.user.id, 'company_id': self.company.id})
        self.connection.write({'processing_mode': 'odoo_approve',
                               'allow_self_approval': False})
        payment = self._new_payment()
        payment.action_bog_submit_approval()
        with self.assertRaises(UserError):
            payment.action_bog_approve()

    def test_editing_amount_revokes_approval(self):
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'approved'})
        payment.write({'amount': 250.0})
        self.assertEqual(payment.gec_bank_state, 'pending')

    def _attach(self, payment, name, raw=b'%PDF-1.4'):
        payment.bog_attachment_ids = self.env['ir.attachment'].create({'name': name, 'raw': raw})

    def test_attachments_are_uploaded_at_every_send(self):
        payment = self._new_payment()
        self._attach(payment, 'invoice.pdf')
        with patch('requests.request', return_value=self._response(200, '"hash-1"')) as request:
            payment._bog_ensure_attachments_uploaded(self.connection)
            payment._bog_ensure_attachments_uploaded(self.connection)
        self.assertEqual(request.call_count, 2, "the bank must get the files the payment has now")
        self.assertEqual(payment.bog_attachment_hashes, 'hash-1')

    def test_a_swapped_attachment_is_uploaded_again(self):
        payment = self._new_payment()
        self._attach(payment, 'invoice.pdf')
        with patch('requests.request', return_value=self._response(200, '"hash-1"')):
            payment._bog_ensure_attachments_uploaded(self.connection)
        self._attach(payment, 'contract.pdf', b'%PDF-1.7')
        with patch('requests.request', return_value=self._response(200, '"hash-2"')) as request:
            payment._bog_ensure_attachments_uploaded(self.connection)
        request.assert_called_once()
        self.assertEqual(payment.bog_attachment_hashes, 'hash-2')

    def test_a_removed_attachment_is_no_longer_sent(self):
        payment = self._new_payment()
        self._attach(payment, 'invoice.pdf')
        with patch('requests.request', return_value=self._response(200, '"hash-1"')):
            payment._bog_ensure_attachments_uploaded(self.connection)
        payment.bog_attachment_ids = [Command.clear()]
        with patch('requests.request') as request:
            payment._bog_ensure_attachments_uploaded(self.connection)
        request.assert_not_called()
        self.assertFalse(payment.bog_attachment_hashes)
        payment._bog_reserve_send()
        self.assertNotIn('AttachmentIds', payment._bog_build_document())

    def test_attachment_hashes_reach_the_document(self):
        payment = self._new_payment()
        payment._gec_bank_internal_write({'bog_attachment_hashes': 'hash-1 hash-2'})
        payment._bog_reserve_send()
        self.assertEqual(payment._bog_build_document()['AttachmentIds'], ['hash-1', 'hash-2'])

    def test_unrecognised_status_does_not_change_state(self):
        """A value outside BOG's status table must never mark a document paid."""
        payment = self._new_payment()
        payment._gec_bank_write_result({'gec_bank_state': 'created', 'gec_bank_reference': '55'})
        body = json.dumps({'Status': 'sample string 2'})
        with patch('requests.request', return_value=self._response(200, body)):
            payment._bog_refresh_status()
        self.assertEqual(payment.gec_bank_state, 'created')
        self.assertEqual(payment.bog_bank_status, 'sample string 2')

    def test_unrecognised_status_is_noted_once(self):
        """The hourly poll reads the same unknown letter again and again; one note is enough."""
        payment = self._new_payment()
        payment._gec_bank_write_result({'gec_bank_state': 'created', 'gec_bank_reference': '55'})
        body = json.dumps({'Status': 'sample string 2'})
        for _poll in range(2):
            with patch('requests.request', return_value=self._response(200, body)):
                payment._bog_refresh_status()
        notes = [text for text in payment.message_ids.mapped('body') if 'unrecognised' in text]
        self.assertEqual(len(notes), 1)

    def test_failed_status_text_is_a_plain_string(self):
        payment = self._new_payment()
        payment._gec_bank_write_result({'gec_bank_state': 'created', 'gec_bank_reference': '55'})
        self.assertIsInstance(payment._bog_status_vals('R')['gec_bank_error'], str)
        self.assertEqual(payment._bog_status_vals('R', 17)['gec_bank_error'], "Insufficient funds.")
        with patch('requests.request', return_value=self._response(200, json.dumps({'Status': 'D'}))):
            payment._bog_refresh_status()
        self.assertEqual(payment.gec_bank_error, "Cancelled by Bank")

    def test_a_rejected_letter_moves_only_a_transfer_that_is_still_open(self):
        payment = self._new_payment()
        self.assertEqual(payment._bog_status_vals('R'), {})
        payment._gec_bank_write_result({'gec_bank_state': 'failed'})
        self.assertEqual(payment._bog_status_vals('R'), {})

    def test_result_code_text_is_known_or_names_the_code(self):
        payment = self._new_payment()
        self.assertEqual(payment._bog_result_text(33), "Sender ID not found, or the sender account is invalid.")
        self.assertEqual(payment._bog_result_text(9999), "Bank of Georgia result code 9999.")

    def test_executed_status_confirms(self):
        payment = self._new_payment()
        payment._gec_bank_write_result({'gec_bank_state': 'created', 'gec_bank_reference': '55'})
        with patch('requests.request',
                   return_value=self._response(200, json.dumps({'Status': 'P'}))):
            payment._bog_refresh_status()
        self.assertEqual(payment.gec_bank_state, 'confirmed')
        self.assertEqual(payment.gec_bank_confirmed_source, 'status')

    def test_rejected_status_fails(self):
        payment = self._new_payment()
        payment._gec_bank_write_result({'gec_bank_state': 'created', 'gec_bank_reference': '55'})
        with patch('requests.request',
                   return_value=self._response(200, json.dumps({'Status': 'R'}))):
            payment._bog_refresh_status()
        self.assertEqual(payment.gec_bank_state, 'failed')

    def test_recover_matches_on_document_number(self):
        payment = self._new_payment()
        payment._bog_reserve_send()
        payment._gec_bank_write_result({'gec_bank_state': 'unknown'})
        activities = json.dumps([{'docNo': payment.bog_document_no, 'id': 1, 'docKey': 4242}])
        with patch('requests.request', return_value=self._response(200, activities)):
            payment.action_bog_recover()
        self.assertEqual(payment.gec_bank_reference, '4242')

    def test_recover_without_a_document_key_changes_nothing(self):
        payment = self._new_payment()
        payment._bog_reserve_send()
        payment._gec_bank_write_result({'gec_bank_state': 'unknown'})
        activities = json.dumps([{'docNo': payment.bog_document_no, 'id': 1}])
        with patch('requests.request', return_value=self._response(200, activities)):
            action = payment.action_bog_recover()
        self.assertEqual(payment.gec_bank_state, 'unknown')
        self.assertFalse(payment.gec_bank_reference)
        self.assertEqual(action['params']['type'], 'warning')

    def test_recover_does_not_claim_safety_when_not_found(self):
        """Today-activities only covers today, so absence proves nothing."""
        payment = self._new_payment()
        payment._bog_reserve_send()
        payment._gec_bank_write_result({'gec_bank_state': 'unknown'})
        with patch('requests.request', return_value=self._response(200, '[]')):
            action = payment.action_bog_recover()
        self.assertEqual(payment.gec_bank_state, 'unknown')
        self.assertEqual(action['params']['type'], 'warning')

    def test_recover_refuses_a_settled_transfer(self):
        """Recover writes Created first, which would reopen a confirmed transfer."""
        payment = self._new_payment()
        payment._bog_reserve_send()
        for state in ('confirmed', 'sent', 'created', 'pending', 'failed'):
            payment._gec_bank_write_result({'gec_bank_state': state})
            with patch('requests.request') as request, \
                    self.assertRaisesRegex(UserError, 'can be recovered'):
                payment.action_bog_recover()
            request.assert_not_called()

    def test_unknown_outcome_cannot_be_resent(self):
        """An unknown outcome goes through Recover, never a resend."""
        payment = self._new_payment()
        payment._bog_reserve_send()
        payment._gec_bank_write_result({'gec_bank_state': 'unknown'})
        with self.assertRaisesRegex(UserError, 'Recover it from the bank'):
            payment._bog_send_one()

    def test_unique_id_exists_parks_the_payment_as_unknown(self):
        """Code 702: BOG already holds this UniqueId, so nothing may be resent."""
        payment = self._new_payment()
        self._send(payment, 200, json.dumps([{'ResultCode': 702}]))
        self.assertEqual(payment.gec_bank_state, 'unknown')

    def test_draft_payment_is_not_sent(self):
        payment = self._new_payment(post=False)
        with self.assertRaisesRegex(UserError, 'Confirm these payments'):
            payment._bog_send_one()

    def test_failure_clears_the_approval(self):
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'approved', 'gec_bank_approved_by': self.env.user.id})
        self._send(payment, 400, '{"message": "bad iban"}')
        self.assertEqual(payment.gec_bank_state, 'failed')
        self.assertFalse(payment.gec_bank_approved_by)
        self.assertEqual(payment.state, 'rejected')

    def test_protected_fields_are_readonly(self):
        """A non-readonly protected field would make every payment and batch form refuse to save."""
        for model, names in (('account.payment', BOG_PROTECTED_FIELDS),
                             ('account.batch.payment', BOG_BATCH_PROTECTED_FIELDS)):
            for name in names:
                self.assertTrue(self.env[model]._fields[name].readonly, (model, name))

    def test_state_and_approval_cannot_be_written_directly(self):
        payment = self._new_payment()
        for vals in ({'gec_bank_state': 'approved'}, {'gec_bank_approved_by': self.env.user.id},
                     {'gec_bank_request_id': 'forged'}, {'bog_attachment_hashes': 'h'}):
            with self.assertRaises(UserError):
                payment.write(vals)
        batch = self.env['account.batch.payment'].create({
            'journal_id': self.journal.id, 'batch_type': 'outbound',
            'payment_method_id': self.method_line.payment_method_id.id,
            'payment_ids': [Command.set(payment.ids)],
        })
        with self.assertRaises(UserError):
            batch.write({'bog_state': 'draft', 'bog_bulk_key': '1'})
        self.assertEqual(payment.gec_bank_state, 'pending')

    def test_payment_form_still_saves(self):
        form = Form(self.env['account.payment'].with_context(
            default_payment_type='outbound', default_partner_type='supplier'))
        form.journal_id = self.journal
        form.partner_id = self.partner
        form.amount = 15
        form.payment_method_line_id = self.method_line
        payment = form.save()
        self.assertEqual(payment.gec_bank_state, 'pending')

    def test_journal_created_in_one_save_gets_the_bog_line(self):
        account = self.env['res.partner.bank'].create({
            'account_number': 'GE29BG7777777777777733', 'partner_id': self.company.partner_id.id,
            'bank_bic': 'BAGAGE22'})
        journal = self.env['account.journal'].create({
            'name': 'BOG One Save', 'type': 'bank', 'code': 'BOG1S', 'bank_account_id': account.id})
        self.assertIn('bog_transfer', journal.outbound_payment_method_line_ids.mapped('code'))

