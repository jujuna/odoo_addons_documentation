import base64
from datetime import datetime, timedelta
from unittest.mock import call, patch

import requests

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import DOCUMENT_LOGGER, PDF, RECIPIENT_LOGGER, SignifyCommon

STATUS = 'get-documents-status'
NOT_YET = 'EVIDENCE_REPORT_NOT_YET_GENERATED'


@tagged('post_install', '-at_install')
class TestSignifySync(SignifyCommon):

    def _linked_attachments(self):
        return self.env['ir.attachment'].search([('res_model', '=', 'res.partner'), ('res_id', '=', self.linked.id)])

    def test_the_cron_is_set_up(self):
        cron = self.env.ref('signify.ir_cron_signify_sync')
        self.assertEqual(cron.model_id.model, 'signify.document')
        self.assertEqual(cron.code.strip(), 'model._cron_signify_sync()')

    def test_a_signed_document_is_finished_with_its_recipients(self):
        document = self._shared()
        recipient = document.recipient_ids
        entry = self._status(document, 'FINISHED', {recipient: {
            'status': 'FINISHED', 'actionTime': '2022-11-17T10:20:58.420+00:00'}})
        with self._signify(self._sync_handlers(entry)):
            self._run_cron()
        self.assertEqual(document.state, 'finished')
        self.assertEqual(recipient.status, 'finished')
        self.assertEqual(recipient.action_time, datetime(2022, 11, 17, 10, 20, 58, 420000))

    def test_the_action_time_is_converted_to_naive_utc(self):
        document = self._shared()
        recipient = document.recipient_ids
        entry = self._status(document, 'SHARED', {recipient: {
            'status': 'FINISHED', 'actionTime': '2022-11-17T14:20:58+04:00'}})
        with self._signify(self._sync_handlers(entry)):
            document.action_refresh()
        self.assertEqual(recipient.action_time, datetime(2022, 11, 17, 10, 20, 58))

    def test_every_recipient_status_is_mapped(self):
        statuses = ['PENDING', 'PENDING_ON_USER', 'NO_ACTION_REQUIRED', 'NO_ACTION_REQUIRED_INTERRUPTED',
                    'REJECTED', 'FINISHED']
        document = self._shared(recipients=[self._line() for _status in statuses])
        recipients = document.recipient_ids.sorted('id')
        entry = self._status(document, 'SHARED', dict(zip(recipients, statuses)))
        with self._signify(self._sync_handlers(entry)):
            document.action_refresh()
        self.assertEqual(recipients.mapped('status'), [status.lower() for status in statuses])

    def test_an_unknown_document_status_changes_nothing(self):
        document = self._shared()
        with (
            self._signify(self._sync_handlers(self._status(document, 'SOMETHING_NEW'))),
            self.assertLogs(DOCUMENT_LOGGER, 'WARNING'),
        ):
            document.action_refresh()
        self.assertEqual(document.state, 'shared')

    def test_a_draft_status_leaves_a_sent_document_sent(self):
        document = self._shared()
        with (
            self._signify(self._sync_handlers(self._status(document, 'DRAFT'))),
            self.assertLogs(DOCUMENT_LOGGER, 'WARNING'),
        ):
            document.action_refresh()
        self.assertEqual(document.state, 'shared')

    def test_an_unknown_recipient_status_skips_only_that_recipient(self):
        document = self._shared(recipients=[self._line(), self._line()])
        unknown, known = document.recipient_ids.sorted('id')
        entry = self._status(document, 'SHARED', {unknown: 'SOMETHING_NEW', known: 'FINISHED'})
        with self._signify(self._sync_handlers(entry)), self.assertLogs(RECIPIENT_LOGGER, 'WARNING'):
            document.action_refresh()
        self.assertFalse(unknown.status)
        self.assertEqual(known.status, 'finished')

    def test_the_signed_files_are_kept_on_the_document_and_copied_to_the_linked_record(self):
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))):
            document.action_refresh()
        signed = document.signed_attachment_ids
        self.assertEqual(sorted(signed.mapped('name')), ['attachment.pdf', 'contract-signed.pdf'])
        self.assertEqual({bytes(attachment.raw) for attachment in signed}, {PDF})
        self.assertEqual(set(signed.mapped('res_model')), {'signify.document'})
        self.assertEqual(set(signed.mapped('res_id')), {document.id})
        copies = self._linked_attachments()
        self.assertEqual(copies.mapped('name'), ['contract-signed.pdf'])
        self.assertEqual(bytes(copies.raw), PDF)

    def test_the_note_on_the_linked_record_has_no_attachments(self):
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))):
            document.action_refresh()
        notes = self._notes(self.linked, "Signed with Signify")
        self.assertEqual(len(notes), 1)
        self.assertIn('contract-signed.pdf', str(notes.body))
        self.assertFalse(notes.attachment_ids)

    def test_the_evidence_report_stays_on_the_document(self):
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))):
            document.action_refresh()
        evidence = document.evidence_attachment_id
        self.assertEqual(evidence.name, 'evidence.pdf')
        self.assertEqual(bytes(evidence.raw), PDF)
        self.assertEqual((evidence.res_model, evidence.res_id), ('signify.document', document.id))
        self.assertNotIn('evidence.pdf', self._linked_attachments().mapped('name'))
        self.assertFalse(self._notes(self.linked, "Evidence"))

    def test_an_evidence_report_not_ready_is_not_an_error_and_is_asked_again(self):
        document = self._shared()
        handlers = self._sync_handlers(self._status(document, 'FINISHED'), overrides={
            'download-evidence-report': [self._failure("Not yet", code=NOT_YET), self._evidence_response()]})
        with self._signify(handlers) as post:
            self._run_cron()
            self.assertEqual(document.state, 'finished')
            self.assertFalse(document.evidence_attachment_id)
            self._run_cron()
        self.assertEqual(self._operations(post).count(STATUS), 2)
        self.assertEqual(document.evidence_attachment_id.name, 'evidence.pdf')

    def test_the_signed_files_are_downloaded_once_while_the_evidence_is_pending(self):
        document = self._shared()
        handlers = self._sync_handlers(self._status(document, 'FINISHED'), overrides={
            'download-evidence-report': [self._failure("Not yet", code=NOT_YET)] * 2})
        with self._signify(handlers) as post:
            self._run_cron()
            self._run_cron()
        self.assertEqual(self._operations(post).count('download-document'), 1)
        self.assertEqual(len(document.signed_attachment_ids), 2)

    def test_deleted_signed_files_are_not_downloaded_again(self):
        """Documents deletes our attachment with its file; a second download would copy the file to the linked record again."""
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))) as post:
            document.action_refresh()
            document.sudo().signed_attachment_ids.unlink()
            document.action_refresh()
        self.assertEqual(self._operations(post).count('download-document'), 1)
        self.assertFalse(document.signed_attachment_ids)
        self.assertEqual(len(self._linked_attachments()), 1)
        self.assertEqual(len(self._notes(self.linked, "Signed with Signify")), 1)

    def test_a_failed_download_is_tried_again_on_the_next_run(self):
        """The status write is rolled back with the failed download, so the next run sees the change to Signed again."""
        document = self._shared()
        handlers = self._sync_handlers(self._status(document, 'FINISHED'), overrides={
            'download-document': [self._failure("Cannot download"), self._signed_files_response()]})
        with self._signify(handlers), self.assertLogs(DOCUMENT_LOGGER, 'ERROR'):
            self._run_cron()
            self.assertEqual(document.state, 'shared')
            self._run_cron()
        self.assertEqual(document.state, 'finished')
        self.assertEqual(len(document.signed_attachment_ids), 2)

    def test_a_finished_document_with_its_evidence_is_no_longer_polled(self):
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))) as post:
            self._run_cron()
            calls_after_first_run = len(post.call_args_list)
            self._run_cron()
        self.assertEqual(len(post.call_args_list), calls_after_first_run)

    def test_a_failed_evidence_download_keeps_the_signed_files(self):
        document = self._shared()
        handlers = self._sync_handlers(self._status(document, 'FINISHED'), overrides={
            'download-evidence-report': requests.Timeout()})
        with self._signify(handlers), self.assertLogs(DOCUMENT_LOGGER, 'ERROR'):
            self._run_cron()
        self.assertEqual(document.state, 'finished')
        self.assertEqual(len(document.signed_attachment_ids), 2)
        self.assertFalse(document.evidence_attachment_id)

    def test_refresh_shows_the_error_of_the_evidence_download(self):
        document = self._shared()
        handlers = self._sync_handlers(self._status(document, 'FINISHED'), overrides={
            'download-evidence-report': self._failure("Evidence broke")})
        with self._signify(handlers), self.assertRaises(UserError) as cm:
            document.action_refresh()
        self.assertIn("Evidence broke", str(cm.exception))

    def test_a_download_without_a_document_file_posts_no_note_on_the_linked_record(self):
        document = self._shared()
        item = {'fileName': 'attachment.pdf', 'base64': base64.b64encode(PDF).decode(), 'fileType': 'ATTACHMENT'}
        handlers = self._sync_handlers(self._status(document, 'FINISHED'), overrides={
            'download-document': self._ok(documents=[item])})
        with self._signify(handlers):
            document.action_refresh()
        self.assertEqual(len(document.signed_attachment_ids), 1)
        self.assertFalse(self._linked_attachments())
        self.assertFalse(self._notes(self.linked, "Signed with Signify"))

    def test_a_rejection_is_noted_on_the_document_and_the_linked_record(self):
        document = self._shared()
        recipient = document.recipient_ids
        entry = self._status(document, 'REJECTED', {recipient: {'status': 'REJECTED', 'message': "Wrong amount"}})
        with self._signify({STATUS: self._status_body(entry)}):
            document.action_refresh()
        self.assertEqual(document.state, 'rejected')
        for record in (document, self.linked):
            with self.subTest(record=record._name):
                notes = self._notes(record, "Wrong amount")
                self.assertEqual(len(notes), 1)
                self.assertIn("Test Person", str(notes.body))

    def test_a_rejection_without_a_message_is_still_noted(self):
        document = self._shared()
        entry = self._status(document, 'REJECTED', {document.recipient_ids: 'REJECTED'})
        with self._signify({STATUS: self._status_body(entry)}):
            document.action_refresh()
        for record in (document, self.linked):
            with self.subTest(record=record._name):
                self.assertEqual(len(self._notes(record, "Rejected in Signify by Test Person")), 1)

    def test_a_rejection_is_noted_only_once(self):
        document = self._shared()
        entry = self._status(document, 'REJECTED', {document.recipient_ids: 'REJECTED'})
        with self._signify({STATUS: self._status_body(entry)}):
            document.action_refresh()
            document.action_refresh()
        self.assertEqual(len(self._notes(self.linked, "Rejected in Signify")), 1)

    def test_canceled_and_deleted_statuses_are_mapped(self):
        for status, state in (('CANCELED', 'canceled'), ('DELETED', 'deleted')):
            with self.subTest(status=status):
                document = self._shared()
                with self._signify({STATUS: self._status_body(self._status(document, status))}):
                    document.action_refresh()
                self.assertEqual(document.state, state)

    def test_a_failed_batch_is_retried_one_document_per_call(self):
        first, second = self._shared(), self._shared()
        by_ref = {document.signify_ref: document for document in (first, second)}

        def status(payload):
            if len(payload['documentIds']) > 1:
                return self._failure("Batch failed")
            return self._status_body(self._status(by_ref[str(payload['documentIds'][0])], 'CANCELED'))

        with self._signify({STATUS: status}) as post:
            (first | second).action_refresh()
        ids = [body['documentIds'] for body in self._sent(post, STATUS)]
        self.assertEqual(sorted(ids[0]), sorted(int(ref) for ref in by_ref))
        self.assertEqual([single[0] for single in ids[1:]], ids[0])
        self.assertTrue(all(len(single) == 1 for single in ids[1:]))
        self.assertEqual((first | second).mapped('state'), ['canceled', 'canceled'])

    def test_in_the_cron_a_missing_document_is_deleted_and_another_error_changes_nothing(self):
        missing, broken = self._shared(), self._shared()

        def status(payload):
            ids = payload['documentIds']
            if len(ids) > 1:
                return self._failure("Batch failed")
            if str(ids[0]) == missing.signify_ref:
                return self._failure("Gone", code='DOCUMENT_NOT_FOUND')
            return self._failure("Boom")

        with self._signify({STATUS: status}), self.assertLogs(DOCUMENT_LOGGER, 'WARNING'):
            self._run_cron()
        self.assertEqual(missing.state, 'deleted')
        self.assertEqual(broken.state, 'shared')

    def test_refresh_marks_a_missing_document_deleted(self):
        """Refresh treats DOCUMENT_NOT_FOUND like the cron does."""
        document = self._shared()
        with self._signify({STATUS: self._failure("Gone", code='DOCUMENT_NOT_FOUND')}):
            document.action_refresh()
        self.assertEqual(document.state, 'deleted')

    def test_refresh_shows_the_error_of_a_single_document(self):
        """Unlike the cron, Refresh raises the error to the user."""
        document = self._shared()
        with self._signify({STATUS: self._failure("Boom")}), self.assertRaises(UserError) as cm:
            document.action_refresh()
        self.assertIn("Boom", str(cm.exception))
        self.assertEqual(document.state, 'shared')

    def test_the_status_poll_is_batched(self):
        documents = self._shared() | self._shared() | self._shared()
        by_ref = {document.signify_ref: document for document in documents}

        def status(payload):
            return self._status_body(*[self._status(by_ref[str(ref)], 'SHARED') for ref in payload['documentIds']])

        with (
            self._signify({STATUS: status}) as post,
            patch('odoo.addons.signify.models.signify_document.STATUS_BATCH_SIZE', 2),
        ):
            documents.action_refresh()
        batches = [body['documentIds'] for body in self._sent(post, STATUS)]
        self.assertEqual([len(batch) for batch in batches], [2, 1])
        self.assertEqual(sorted(sum(batches, [])), sorted(int(ref) for ref in by_ref))

    def test_each_account_is_polled_with_its_own_token_and_documents(self):
        self.connection_b.access_token = 'tok-b'
        document_a, document_b = self._shared(), self._shared(user=self.user_b)
        documents = {document_a.signify_ref: document_a, document_b.signify_ref: document_b}

        def status(payload):
            return self._status_body(*[self._status(documents[str(ref)], 'SHARED') for ref in payload['documentIds']])

        with self._signify({STATUS: status}) as post:
            self._run_cron()
        ids_by_token = {kwargs['headers']['Authorization']: kwargs['json']['documentIds'] for kwargs in self._calls(post, STATUS)}
        self.assertEqual(ids_by_token, {'Bearer tok-1': [int(document_a.signify_ref)], 'Bearer tok-b': [int(document_b.signify_ref)]})

    def test_the_cron_uses_the_account_that_sent_the_document_not_the_current_account_of_the_user(self):
        document = self._shared()
        self.connection.action_archive()
        other = self._connect(self.user, signify_sub='sub-other', access_token='tok-other')
        with self._signify(self._sync_handlers(self._status(document, 'SHARED'))) as post:
            self._run_cron()
        self.assertEqual(self._calls(post, STATUS)[0]['headers']['Authorization'], 'Bearer tok-1')
        self.assertNotEqual(document.connection_id, other)

    def test_refresh_uses_the_account_of_the_document_not_the_one_of_the_viewer(self):
        self.connection_manager.access_token = 'tok-manager'
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'SHARED'))) as post:
            document.with_user(self.manager).action_refresh()
        self.assertEqual({kwargs['headers']['Authorization'] for kwargs in self._calls(post, STATUS)}, {'Bearer tok-1'})

    def test_a_document_without_an_account_is_skipped_and_the_others_continue(self):
        document_a, orphan = self._shared(), self._shared()
        orphan.sudo().connection_id = False
        handlers = {STATUS: self._status_body(self._status(document_a, 'CANCELED'))}
        with self._signify(handlers) as post, self.assertLogs(DOCUMENT_LOGGER, 'WARNING') as logs:
            self._run_cron()
        self.assertEqual((document_a.state, orphan.state), ('canceled', 'shared'))
        self.assertEqual(self._operations(post), [STATUS])
        self.assertEqual(len(logs.records), 1)

    def test_refresh_of_a_document_without_an_account_asks_to_connect(self):
        document = self._shared()
        document.sudo().connection_id = False
        with self._signify() as post, self.assertRaises(UserError) as cm:
            document.action_refresh()
        self.assertIn("Connect your Signify account", str(cm.exception))
        post.assert_not_called()

    def test_an_account_whose_refresh_fails_does_not_block_the_other(self):
        document_a, document_b = self._shared(), self._shared(user=self.user_b)
        self.connection.expiry = fields.Datetime.now() - timedelta(minutes=5)
        handlers = {'oauth/token': self._oauth_error('invalid_grant'), STATUS: self._status_body(self._status(document_b, 'CANCELED'))}
        with self._signify(handlers), self.assertLogs(DOCUMENT_LOGGER, 'WARNING'):
            self._run_cron()
        self.assertEqual(document_a.state, 'shared')
        self.assertEqual(document_b.state, 'canceled')

    def test_a_failed_refresh_is_tried_once_for_all_the_documents_of_an_account(self):
        documents = self._shared() | self._shared() | self._shared()
        self.connection.expiry = fields.Datetime.now() - timedelta(minutes=5)
        with self._signify({'oauth/token': self._oauth_error('invalid_grant')}) as post, self.assertLogs(DOCUMENT_LOGGER, 'WARNING') as logs:
            self._run_cron()
        self.assertEqual(self._operations(post), ['oauth/token'])
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(documents.mapped('state'), ['shared'] * 3)

    def test_a_null_recipient_list_does_not_stop_the_status_update(self):
        """Signify may answer recipientsStatus null."""
        document = self._shared()
        entry = {**self._status(document, 'CANCELED'), 'recipientsStatus': None}
        with self._signify({STATUS: self._status_body(entry)}):
            document.action_refresh()
        self.assertEqual(document.state, 'canceled')

    def test_refresh_leaves_a_draft_alone(self):
        """A draft has no Signify id."""
        document = self._document()
        with self._signify() as post:
            document.action_refresh()
        post.assert_not_called()
        self.assertEqual(document.state, 'draft')

    def test_the_files_of_a_sync_belong_to_the_company_of_the_document(self):
        """The cron runs as a user of the main company."""
        document = self._shared(user=self.user_b)
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))):
            self._run_cron()
        document = document.sudo()
        attachments = document.signed_attachment_ids | document.evidence_attachment_id
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments.company_id, self.company_b)

    def test_a_failing_download_does_not_stop_the_next_document(self):
        """A failed download rolls its document back."""
        broken, healthy = self._shared(), self._shared()
        entries = [self._status(document, 'FINISHED') for document in (broken, healthy)]

        def download(payload):
            if str(payload['documentId']) == broken.signify_ref:
                return self._failure("Cannot download")
            return self._signed_files_response()

        handlers = self._sync_handlers(*entries, overrides={'download-document': download})
        with self._signify(handlers), self.assertLogs(DOCUMENT_LOGGER, 'ERROR'):
            self._run_cron()
        self.assertEqual(healthy.state, 'finished')
        self.assertEqual(len(healthy.signed_attachment_ids), 2)
        self.assertEqual(broken.state, 'shared')
        self.assertFalse(broken.signed_attachment_ids)

    def test_the_cron_commits_once_per_document(self):
        documents = self._shared() | self._shared()
        entries = [self._status(document, 'SHARED') for document in documents]
        with self._signify(self._sync_handlers(*entries)):
            commit = self._run_cron()
        self.assertEqual(commit.call_args_list, [call(1), call(1)])

    def test_the_cron_stops_when_there_is_no_time_left(self):
        documents = self._shared() | self._shared()
        entries = [self._status(document, 'CANCELED') for document in documents]
        with (
            self._signify(self._sync_handlers(*entries)),
            patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=0) as commit,
        ):
            self.env['signify.document']._cron_signify_sync()
        self.assertEqual(commit.call_count, 1)
        self.assertEqual(sorted(documents.mapped('state')), ['canceled', 'shared'])

    def test_the_cron_asks_no_other_account_when_there_is_no_time_left(self):
        documents = self._shared() | self._shared(user=self.manager)
        entries = [self._status(document, 'CANCELED') for document in documents]
        with (
            self._signify(self._sync_handlers(*entries)) as post,
            patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=0) as commit,
        ):
            self.env['signify.document']._cron_signify_sync()
        self.assertEqual(self._operations(post), [STATUS])
        self.assertEqual(commit.call_count, 1)
        self.assertEqual(sorted(documents.mapped('state')), ['canceled', 'shared'])

    def test_refresh_never_commits(self):
        """Refresh runs in the user's transaction."""
        document = self._shared()
        with (
            self._signify(self._sync_handlers(self._status(document, 'SHARED'))),
            patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=float('inf')) as commit,
        ):
            document.action_refresh()
        commit.assert_not_called()

    def test_drafts_and_documents_without_a_signify_id_are_not_polled(self):
        self._document()
        unsent = self._shared()
        unsent.sudo().signify_ref = False
        with self._signify() as post:
            self._run_cron()
        post.assert_not_called()

    def test_documents_in_a_final_state_are_not_polled(self):
        for state in ('rejected', 'canceled', 'deleted'):
            document = self._shared()
            document.sudo().state = state
        with self._signify() as post:
            self._run_cron()
        post.assert_not_called()

    def test_the_owner_can_refresh_a_sent_document(self):
        document = self._shared()
        recipient = document.recipient_ids
        self.assertFalse(document.with_user(self.user).has_access('write'))
        entry = self._status(document, 'SHARED', {recipient: 'PENDING_ON_USER'})
        with self._signify(self._sync_handlers(entry)):
            document.with_user(self.user).action_refresh()
        self.assertEqual(recipient.status, 'pending_on_user')

    def test_another_user_cannot_refresh_my_document(self):
        """A user who cannot read the document cannot refresh it."""
        document = self._shared()
        with self._signify() as post, self.assertRaises(AccessError):
            document.with_user(self.user_2).action_refresh()
        post.assert_not_called()
