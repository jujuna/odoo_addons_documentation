from unittest.mock import patch

import requests

from odoo import Command
from odoo.exceptions import AccessError, RedirectWarning, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import DOCUMENT_LOGGER, RECIPIENT_LOGGER, SignifyCommon

SEND = ['create-document', 'set-document-details', 'share-document']


@tagged('post_install', '-at_install')
class TestSignifySend(SignifyCommon):

    def _delete_payload(self):
        return {'documentId': 777, 'omitTrash': True}

    def test_send_runs_the_three_calls_in_order_and_shares_the_document(self):
        document = self._document(recipients=[
            self._line(sequence=10), self._line(sequence=20, partner_id=self.company_partner.id)])
        with self._signify(self._send_handlers()) as post:
            document.action_send()
        self.assertEqual(self._operations(post), SEND)
        self.assertEqual(self._sent(post, 'share-document'), [{'documentId': 777}])
        self.assertEqual(document.state, 'shared')
        self.assertEqual(document.signify_ref, '777')

    def test_send_matches_the_recipients_by_their_code(self):
        """Signify answers in another order."""
        document = self._document(recipients=[
            self._line(sequence=10), self._line(sequence=20, partner_id=self.company_partner.id)])
        first, second = document.recipient_ids.sorted('sequence')
        with self._signify(self._send_handlers()):
            document.action_send()
        self.assertEqual((first.signify_ref, first.status), (str(first.id + 5000), 'pending_on_user'))
        self.assertEqual((second.signify_ref, second.status), (str(second.id + 5000), 'pending'))

    def test_send_posts_a_note_without_attachments_on_the_linked_record(self):
        document = self._document()
        with self._signify(self._send_handlers()):
            document.action_send()
        notes = self._notes(self.linked, "Sent for signature with Signify: contract")
        self.assertEqual(len(notes), 1)
        self.assertFalse(notes.attachment_ids)

    def test_the_state_is_in_the_database_before_the_share_call(self):
        """share-document cannot be undone, so the Odoo writes come before it."""
        document = self._document()
        seen = []

        def share(payload):
            self.env.cr.execute("SELECT state FROM signify_document WHERE id = %s", [document.id])
            seen.append(self.env.cr.fetchone()[0])
            return self._ok()

        with self._signify(self._send_handlers({'share-document': share})) as post:
            document.action_send()
        self.assertEqual(seen, ['shared'])
        self.assertEqual(self._operations(post)[-1], 'share-document')

    def test_the_state_tracking_message_is_written_before_the_share_call(self):
        """The flush before share-document also runs the tracking hook."""
        document = self._document()
        # A record created in the same transaction is not tracked; Send comes in a later request.
        self.env.cr.flush()
        seen = []

        def share(payload):
            self.env.cr.execute("""
                SELECT 1 FROM mail_message
                WHERE model = 'signify.document' AND res_id = %s AND message_type = 'tracking'
            """, [document.id])
            seen.append(bool(self.env.cr.fetchall()))
            return self._ok()

        with self._signify(self._send_handlers({'share-document': share})):
            document.with_context(mail_notrack=False).action_send()
        self.assertEqual(seen, [True])

    def test_a_details_error_deletes_the_uploaded_draft(self):
        document = self._document()
        failure = self._failure("Bad recipient")
        handlers = self._send_handlers({'set-document-details': failure, 'delete-document': self._ok()})
        with self._signify(handlers) as post, self.assertRaises(UserError) as cm:
            document.action_send()
        self.assertIn("Bad recipient", str(cm.exception))
        self.assertEqual(self._sent(post, 'delete-document'), [self._delete_payload()])
        self.assertIs(self._sent(post, 'delete-document')[0]['omitTrash'], True)
        self.assertNotIn('share-document', self._operations(post))
        self.assertEqual(document.state, 'draft')
        self.assertFalse(document.signify_ref)

    def test_a_share_error_deletes_the_draft_and_leaves_the_document_a_draft(self):
        """The Odoo writes are rolled back."""
        document = self._document()
        handlers = self._send_handlers({'share-document': self._failure("Cannot share"), 'delete-document': self._ok()})
        with self._signify(handlers) as post, self.assertRaises(UserError) as cm:
            document.action_send()
        self.assertIn("Cannot share", str(cm.exception))
        self.assertEqual(self._operations(post)[-2:], ['share-document', 'delete-document'])
        self.assertEqual(self._sent(post, 'delete-document'), [self._delete_payload()])
        self.assertEqual(document.state, 'draft')
        self.assertFalse(document.signify_ref)

    def test_a_share_timeout_keeps_the_draft_at_signify_and_points_to_the_portal(self):
        """The share may have reached Signify, so the draft must not be deleted."""
        document = self._document()
        handlers = self._send_handlers({'share-document': requests.Timeout()})
        with self._signify(handlers) as post, self.assertRaises(UserError) as cm:
            document.action_send()
        self.assertIn("check the Signify portal", str(cm.exception))
        self.assertIn("did not answer in time", str(cm.exception))
        self.assertNotIn('delete-document', self._operations(post))
        self.assertEqual(document.state, 'draft')

    def test_a_transport_error_before_the_share_still_deletes_the_draft(self):
        document = self._document()
        handlers = self._send_handlers({'set-document-details': requests.Timeout(), 'delete-document': self._ok()})
        with self._signify(handlers) as post, self.assertRaises(UserError):
            document.action_send()
        self.assertEqual(self._sent(post, 'delete-document'), [self._delete_payload()])

    def test_a_failing_cleanup_does_not_hide_the_original_error(self):
        document = self._document()
        handlers = self._send_handlers({
            'set-document-details': self._failure("Original problem"),
            'delete-document': self._failure("Cannot delete"),
        })
        with self._signify(handlers), self.assertLogs(DOCUMENT_LOGGER, 'ERROR'), self.assertRaises(UserError) as cm:
            document.action_send()
        self.assertIn("Original problem", str(cm.exception))

    def test_a_create_error_deletes_nothing(self):
        """When the upload itself fails there is no draft at Signify to delete."""
        document = self._document()
        handlers = self._send_handlers({'create-document': self._failure("Cannot create")})
        with self._signify(handlers) as post, self.assertRaises(UserError):
            document.action_send()
        self.assertEqual(self._operations(post), ['create-document'])
        self.assertEqual(document.state, 'draft')

    def test_an_unconfirmed_recipient_is_an_error_and_the_draft_is_deleted(self):
        """Signify must confirm every recipient by its code."""
        document = self._document(recipients=[self._line(sequence=10), self._line(sequence=20)])
        first = document.recipient_ids.sorted('sequence')[0]
        partial = self._ok(recipients=[{'recipientCode': str(first.id), 'id': 1, 'status': 'PENDING_ON_USER'}])
        handlers = self._send_handlers({'set-document-details': partial, 'delete-document': self._ok()})
        with self._signify(handlers) as post, self.assertRaises(UserError) as cm:
            document.action_send()
        self.assertIn("did not confirm every recipient", str(cm.exception))
        self.assertEqual(self._sent(post, 'delete-document'), [self._delete_payload()])
        self.assertNotIn('share-document', self._operations(post))
        self.assertEqual(document.state, 'draft')

    def test_a_manager_cannot_send_a_document_that_is_not_a_draft(self):
        document = self._shared()
        with self._signify() as post, self.assertRaises(UserError) as cm:
            document.with_user(self.manager).action_send()
        self.assertNotIsInstance(cm.exception, AccessError)
        self.assertIn("Only a draft document can be sent", str(cm.exception))
        post.assert_not_called()

    def test_the_owner_cannot_send_a_document_that_is_not_a_draft(self):
        """The owner can no longer write a sent document, so a second send is refused by access rights."""
        document = self._shared()
        with self._signify() as post, self.assertRaises(AccessError):
            document.action_send()
        post.assert_not_called()

    def test_another_user_cannot_send_my_draft(self):
        document = self._document()
        with self._signify() as post, self.assertRaises(AccessError):
            document.with_user(self.user_2).action_send()
        post.assert_not_called()

    def test_a_manager_can_send_the_draft_of_a_user(self):
        document = self._document()
        with self._signify(self._send_handlers()) as post:
            document.with_user(self.manager).action_send()
        self.assertEqual(self._operations(post), SEND)
        self.assertEqual(document.state, 'shared')

    def test_a_document_that_is_being_sent_cannot_be_sent_again(self):
        """Refused when the row lock is not obtained."""
        document = self._document()
        empty = self.env['signify.document']
        with (
            self._signify() as post,
            patch.object(type(empty), 'try_lock_for_update', return_value=empty),
            self.assertRaises(UserError) as cm,
        ):
            document.action_send()
        self.assertIn("being sent already", str(cm.exception))
        post.assert_not_called()

    def test_send_without_a_connection_is_refused_before_any_call(self):
        document = self._document(user=self.user_2)
        with self._signify() as post, self.assertRaises(RedirectWarning) as cm:
            document.with_user(self.user_2).action_send()
        message, action_id, button = cm.exception.args[:3]
        self.assertIn("Connect your Signify account", message)
        self.assertEqual(action_id, self.env.ref('signify.action_signify_connection').id)
        self.assertEqual(button, "Open Signify Accounts")
        post.assert_not_called()
        self.assertEqual(document.state, 'draft')

    def test_send_stores_the_connection_of_the_user_who_sends(self):
        document = self._document()
        with self._signify(self._send_handlers()) as post:
            document.with_user(self.user).action_send()
        self.assertEqual(document.connection_id, self.connection)
        self.assertEqual({kwargs['headers']['Authorization'] for operation in SEND for kwargs in self._calls(post, operation)}, {'Bearer tok-1'})

    def test_a_manager_sends_a_draft_of_a_user_with_the_account_of_the_manager(self):
        self.connection_manager.access_token = 'tok-manager'
        document = self._document()
        with self._signify(self._send_handlers()) as post:
            document.with_user(self.manager).action_send()
        self.assertEqual(document.connection_id, self.connection_manager)
        self.assertEqual({kwargs['headers']['Authorization'] for operation in SEND for kwargs in self._calls(post, operation)},
            {'Bearer tok-manager'})

    def test_send_does_not_use_an_archived_connection(self):
        self.connection.action_archive()
        document = self._document()
        with self._signify() as post, self.assertRaises(RedirectWarning):
            document.with_user(self.user).action_send()
        post.assert_not_called()

    def test_send_uses_the_connection_of_the_company_of_the_document(self):
        user = new_test_user(self.env, login='signify_user_ab', groups='base.group_user,signify.group_signify_user',
            company_id=self.company.id, company_ids=[Command.set((self.company | self.company_b).ids)])
        connection = self._connect(user, self.company_b)
        document = self._document(user=user, company_id=self.company_b.id)
        with self._signify(self._send_handlers()):
            document.with_user(user).action_send()
        self.assertEqual(document.connection_id, connection)

    def test_send_without_a_linked_record_posts_nothing_elsewhere(self):
        before = self.linked.sudo().message_ids
        document = self._document(reference_doc=False)
        with self._signify(self._send_handlers()):
            document.action_send()
        self.assertEqual(document.state, 'shared')
        self.assertEqual(self.linked.sudo().message_ids, before)

    def test_send_works_when_the_linked_record_was_deleted(self):
        """The deleted record is skipped, not an error."""
        gone = self.env['res.partner'].create({'name': "Gone Soon"})
        document = self._document(reference_doc=f'res.partner,{gone.id}')
        gone.unlink()
        with self._signify(self._send_handlers()):
            document.action_send()
        self.assertEqual(document.state, 'shared')

    def test_an_unknown_recipient_status_does_not_stop_the_send(self):
        unknown = lambda payload: self._ok(recipients=[{  # noqa: E731
            'recipientCode': item['recipientCode'], 'id': 99, 'status': 'SOMETHING_NEW'}
            for item in payload['recipients']])
        document = self._document()
        with (
            self._signify(self._send_handlers({'set-document-details': unknown})),
            self.assertLogs(RECIPIENT_LOGGER, 'WARNING'),
        ):
            document.action_send()
        self.assertEqual(document.state, 'shared')
        self.assertEqual(document.recipient_ids.signify_ref, '99')
        self.assertFalse(document.recipient_ids.status)

    def _refused(self, document, text, name):
        with self._signify() as post, self.assertRaises(UserError) as cm:
            document.action_send()
        self.assertIn(text, str(cm.exception))
        self.assertIn(name, str(cm.exception))
        post.assert_not_called()
        self.assertEqual(document.state, 'draft')

    def test_a_signer_on_link_with_basic_is_refused_before_any_call(self):
        document = self._document(recipients=[self._line(contact_type='link', auth_type='basic')])
        self._refused(document, "Choose SMS Code or another Signing Method", "Test Person")

    def test_an_approver_on_link_with_basic_is_refused_before_any_call(self):
        document = self._document(recipients=[self._line(role='approver', contact_type='link', auth_type='basic', placement_keyword=False)])
        self._refused(document, "Choose SMS Code or another Signing Method", "Test Person")

    def test_a_signer_on_link_with_signature_pad_is_sent(self):
        document = self._document(recipients=[self._line(contact_type='link', auth_type='sign_pad')])
        with self._signify(self._send_handlers()) as post:
            document.action_send()
        self.assertEqual(self._operations(post), SEND)

    def test_an_sms_code_signer_without_a_phone_is_refused_before_any_call(self):
        partner = self.env['res.partner'].create({'name': "No Phone", 'email': 'nophone@example.com'})
        document = self._document(recipients=[self._line(partner_id=partner.id, auth_type='sms_otp')])
        self._refused(document, "Add a mobile number to the Phone of", "No Phone")

    def test_an_sms_invitation_without_a_phone_is_refused_before_any_call(self):
        partner = self.env['res.partner'].create({'name': "No Phone", 'email': 'nophone@example.com'})
        document = self._document(recipients=[self._line(partner_id=partner.id, contact_type='mobile')])
        self._refused(document, "Add a mobile number to the Phone of", "No Phone")

    def test_an_sms_code_signer_with_a_phone_is_sent(self):
        document = self._document(recipients=[self._line(auth_type='sms_otp')])
        with self._signify(self._send_handlers()) as post:
            document.action_send()
        self.assertEqual(self._operations(post), SEND)
