from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.signify.tests.common import PDF, SignifyCommon
from odoo.addons.signify_documents import _signify_documents_post_init


@tagged('post_install', '-at_install')
class TestSignifyDocuments(SignifyCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.folder = cls.company.documents_signify_folder_id
        cls.action = cls.env.ref('signify_documents.ir_actions_server_signify_send')

    def _finish(self):
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))):
            document.action_refresh()
        return document

    def _documents_of(self, attachments):
        return self.env['documents.document'].search([('attachment_id', 'in', attachments.ids)])

    def _pins(self, folders):
        return self.env['ir.embedded.actions'].search([
            ('action_id', '=', self.action.id),
            ('parent_res_model', '=', 'documents.document'),
            ('parent_res_id', 'in', folders.ids),
        ])

    def test_every_company_has_its_signify_folder_with_the_action_pinned(self):
        """Companies that existed at install get the folder from the hook, company B from create."""
        companies = self.env['res.company'].with_context(active_test=False).search([])
        self.assertIn(self.company_b, companies)
        for company in companies:
            folder = company.documents_signify_folder_id
            with self.subTest(company=company.name):
                self.assertEqual((folder.type, folder.company_id, folder.access_internal), ('folder', company, 'view'))
                self.assertFalse(folder.owner_id)
                self.assertEqual(len(self._pins(folder)), 1)

    def test_a_second_run_of_the_hook_keeps_the_folders_and_the_pins(self):
        chosen = self.env['documents.document'].create({'name': "Contracts", 'type': 'folder', 'company_id': self.company_b.id})
        self.company_b.documents_signify_folder_id = chosen
        _signify_documents_post_init(self.env)
        self.assertEqual(self.company.documents_signify_folder_id, self.folder)
        self.assertEqual(self.company_b.documents_signify_folder_id, chosen)
        self.assertEqual(len(self._pins(self.folder)), 1)

    def test_a_company_created_by_an_administrator_outside_signify_gets_its_folder(self):
        admin = new_test_user(self.env, login='signify_settings_admin', groups='base.group_system')
        company = self.env['res.company'].with_user(admin).create({'name': "Signify Company C"})
        folder = company.sudo().documents_signify_folder_id
        self.assertEqual(folder.company_id, company)
        self.assertEqual(len(self._pins(folder)), 1)

    def test_signed_files_and_evidence_land_in_the_company_folder(self):
        document = self._finish()
        attachments = document.signed_attachment_ids | document.evidence_attachment_id
        documents = self._documents_of(attachments)
        self.assertEqual(len(attachments), 3)
        self.assertEqual(documents.attachment_id, attachments)
        self.assertEqual(documents.folder_id, self.folder)
        self.assertEqual(documents.partner_id, self.person)

    def test_the_sender_sees_the_filed_files_but_does_not_own_them_when_the_cron_syncs(self):
        """The cron runs as OdooBot; the sender reads the files but cannot trash them, and other users of the folder read none."""
        documents_user = self.env.ref('documents.group_documents_user')
        (self.user | self.user_2).group_ids += documents_user
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))):
            self._run_cron()
        documents = self._documents_of(document.sudo().signed_attachment_ids | document.sudo().evidence_attachment_id)
        self.assertEqual(len(documents), 3)
        self.assertFalse(documents.owner_id)
        self.assertEqual(documents.with_user(self.user)._filtered_access('read'), documents)
        self.assertFalse(documents.with_user(self.user)._filtered_access('write'))
        self.assertFalse(documents.with_user(self.user)._filtered_access('unlink'))
        self.assertFalse(documents.with_user(self.user_2)._filtered_access('read'))
        self.assertTrue(self.folder.with_user(self.user_2).has_access('read'))

    def test_without_a_folder_no_document_is_created(self):
        self.company.documents_signify_folder_id = False
        document = self._finish()
        attachments = document.signed_attachment_ids | document.evidence_attachment_id
        self.assertFalse(self._documents_of(attachments))

    def test_with_a_folder_in_the_trash_the_signed_files_are_saved_and_not_filed(self):
        self.company.documents_signify_folder_id = False
        self.folder.action_archive()
        self.company.documents_signify_folder_id = self.folder
        document = self._finish()
        attachments = document.signed_attachment_ids | document.evidence_attachment_id
        self.assertEqual((document.state, len(attachments)), ('finished', 3))
        self.assertFalse(self._documents_of(attachments).with_context(active_test=False))

    def test_the_signify_folder_cannot_be_trashed_or_deleted(self):
        with self.assertRaises(ValidationError):
            self.folder.action_archive()
        with self.assertRaises(ValidationError):
            self.folder.unlink()
        self.assertTrue(self.folder.active)

    def test_files_deleted_in_documents_are_not_downloaded_again(self):
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))) as post:
            document.action_refresh()
            self._documents_of(document.signed_attachment_ids).unlink()
            self.assertFalse(document.signed_attachment_ids)
            document.action_refresh()
        self.assertEqual(self._operations(post).count('download-document'), 1)
        self.assertEqual(len(self._notes(self.linked, "Signed with Signify")), 1)

    def test_the_copy_on_the_linked_record_is_not_a_document(self):
        self._finish()
        copies = self.env['ir.attachment'].search([('res_model', '=', 'res.partner'), ('res_id', '=', self.linked.id)])
        self.assertTrue(copies)
        self.assertFalse(self._documents_of(copies))

    def test_send_with_signify_opens_a_draft_of_the_file(self):
        pdf = self.env['documents.document'].create({'name': "contract.pdf", 'raw': PDF, 'folder_id': self.folder.id})
        action = pdf.action_signify_send()
        document = self.env['signify.document'].browse(action['res_id'])
        self.assertEqual((action['type'], action['res_model']), ('ir.actions.act_window', 'signify.document'))
        self.assertEqual(document.state, 'draft')
        self.assertEqual(document.reference_doc, pdf)
        self.assertEqual(document.file.content, PDF)

    def test_send_with_signify_refuses_other_files(self):
        image = self.env['documents.document'].create({'name': "logo.png", 'raw': b'x', 'folder_id': self.folder.id})
        with self.assertRaises(UserError):
            image.action_signify_send()
        with self.assertRaises(UserError):
            self.folder.action_signify_send()

    def test_send_with_signify_takes_one_file(self):
        pdfs = self.env['documents.document'].create([
            {'name': name, 'raw': PDF, 'folder_id': self.folder.id} for name in ("a.pdf", "b.pdf")])
        with self.assertRaises(UserError):
            pdfs.action_signify_send()
