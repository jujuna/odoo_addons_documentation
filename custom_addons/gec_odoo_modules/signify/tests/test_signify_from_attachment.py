import base64

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import PDF, SignifyCommon


@tagged('post_install', '-at_install')
class TestSignifyFromAttachment(SignifyCommon):

    def _chatter_file(self, **vals):
        """A PDF attached by the superuser, the way a chatter file is."""
        return self.env['ir.attachment'].create({
            'name': 'contract.pdf', 'raw': PDF, 'res_model': 'res.partner', 'res_id': self.linked.id, **vals})

    def _documents(self):
        return self.env['signify.document'].sudo().search([])

    def _from_attachment(self, attachment, user=None):
        return self.env['signify.document'].with_user(user or self.user).action_new_from_attachment(attachment.id)

    def _created(self, action, user=None):
        return self.env['signify.document'].with_user(user or self.user).browse(action['res_id'])

    def test_a_signify_user_gets_a_draft_of_the_chatter_file(self):
        attachment = self._chatter_file()
        document = self._created(self._from_attachment(attachment))
        self.assertEqual(document.file.content, PDF)
        self.assertEqual(document.file_name, 'contract.pdf')
        self.assertEqual(document.name, 'contract')
        self.assertEqual(document.reference_doc, self.linked)
        self.assertEqual(document.state, 'draft')
        self.assertEqual(document.create_uid, self.user)
        self.assertEqual(document.company_id, self.user.company_id)

    def test_the_action_opens_the_new_document_in_a_form(self):
        action = self._from_attachment(self._chatter_file())
        self.assertEqual(action, {
            'type': 'ir.actions.act_window',
            'res_model': 'signify.document',
            'res_id': self._documents()[:1].id,
            'views': [(False, 'form')],
            'target': 'current',
        })

    def test_the_original_attachment_is_not_changed(self):
        """The document copies the file."""
        attachment = self._chatter_file()
        self._from_attachment(attachment)
        attachment.invalidate_recordset()
        self.assertEqual(
            (attachment.name, attachment.res_model, attachment.res_id), ('contract.pdf', 'res.partner', self.linked.id))
        self.assertEqual(attachment.raw.content, PDF)

    def test_the_document_file_is_its_own_attachment(self):
        attachment = self._chatter_file()
        document = self._created(self._from_attachment(attachment))
        own = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'signify.document'), ('res_field', '=', 'file'), ('res_id', '=', document.id)])
        self.assertEqual(len(own), 1)
        self.assertNotEqual(own, attachment)

    def test_an_attachment_the_user_cannot_read_is_refused(self):
        """The file is read as the user."""
        cron = self.env.ref('base.autovacuum_job')
        attachment = self._chatter_file(res_model=cron._name, res_id=cron.id)
        self.assertFalse(attachment.with_user(self.user).has_access('read'))
        before = self._documents()
        with self.assertRaises(AccessError):
            self._from_attachment(attachment)
        self.assertEqual(self._documents(), before)

    def test_a_missing_attachment_is_refused(self):
        before = self._documents()
        with self.assertRaises(UserError):
            self.env['signify.document'].with_user(self.user).action_new_from_attachment(999999999)
        self.assertEqual(self._documents(), before)

    def test_an_employee_without_the_signify_group_cannot_create_a_draft(self):
        attachment = self._chatter_file()
        self.assertTrue(attachment.with_user(self.employee).has_access('read'))
        before = self._documents()
        with self.assertRaises(AccessError):
            self._from_attachment(attachment, user=self.employee)
        self.assertEqual(self._documents(), before)

    def test_a_file_on_a_record_that_is_not_a_mail_thread_gets_no_link(self):
        country = self.env.ref('base.ge')
        attachment = self._chatter_file(res_model=country._name, res_id=country.id)
        self.assertTrue(attachment.with_user(self.user).has_access('read'))
        document = self._created(self._from_attachment(attachment))
        self.assertFalse(document.reference_doc)
        self.assertEqual(document.file.content, PDF)

    def test_a_file_on_a_signify_document_gets_no_link(self):
        own = self._document()
        attachment = self._chatter_file(res_model=own._name, res_id=own.id)
        self.assertTrue(attachment.with_user(self.user).has_access('read'))
        document = self._created(self._from_attachment(attachment))
        self.assertFalse(document.reference_doc)

    def test_a_file_on_a_message_gets_no_link(self):
        message = self.linked.message_post(body="Note")
        attachment = self._chatter_file(res_model=message._name, res_id=message.id)
        self.assertTrue(attachment.with_user(self.user).has_access('read'))
        document = self._created(self._from_attachment(attachment))
        self.assertFalse(document.reference_doc)

    def test_a_file_without_a_record_gets_no_link(self):
        attachment = self.env['ir.attachment'].with_user(self.user).create({'name': 'loose.pdf', 'raw': PDF})
        document = self._created(self._from_attachment(attachment))
        self.assertFalse(document.reference_doc)
        self.assertEqual(document.name, 'loose')

    def test_a_file_in_a_channel_gets_no_link(self):
        channel = self.env['discuss.channel']._create_group(self.user)
        attachment = self._chatter_file(res_model=channel._name, res_id=channel.id)
        self.assertTrue(attachment.with_user(self.user).has_access('read'))
        document = self._created(self._from_attachment(attachment))
        self.assertFalse(document.reference_doc)
        self.assertEqual(document.file.content, PDF)

    def test_a_file_on_a_record_of_another_company_gives_a_draft_of_that_company(self):
        user = new_test_user(
            self.env, login='signify_user_ab', groups='base.group_user,signify.group_signify_user',
            company_id=self.company.id, company_ids=[Command.set((self.company | self.company_b).ids)])
        record = self.env['res.partner'].create({'name': "Company B record", 'company_id': self.company_b.id})
        document = self._created(self._from_attachment(self._chatter_file(res_id=record.id), user=user), user=user)
        self.assertEqual(document.reference_doc, record)
        self.assertEqual(document.company_id, self.company_b)

    def test_a_file_on_a_record_without_a_company_gives_a_draft_of_the_active_company(self):
        self.assertFalse(self.linked.company_id)
        document = self._created(self._from_attachment(self._chatter_file()))
        self.assertEqual(document.company_id, self.company)

    def test_a_loose_file_of_another_user_is_refused(self):
        """A file attached to nothing is readable by its creator only."""
        attachment = self.env['ir.attachment'].with_user(self.user_2).create({'name': 'loose.pdf', 'raw': PDF})
        self.assertFalse(attachment.with_user(self.user).has_access('read'))
        before = self._documents()
        with self.assertRaises(AccessError):
            self._from_attachment(attachment)
        self.assertEqual(self._documents(), before)

    def test_a_public_file_on_a_record_the_user_cannot_read_is_refused(self):
        unreadable = self.env['res.partner'].create({'name': "Company B only", 'company_id': self.company_b.id})
        attachment = self._chatter_file(res_id=unreadable.id, public=True)
        self.assertFalse(unreadable.with_user(self.user).has_access('read'))
        self.assertTrue(attachment.with_user(self.user).has_access('read'))
        before = self._documents()
        with self.assertRaises(AccessError):
            self._from_attachment(attachment)
        self.assertEqual(self._documents(), before)

    def test_a_context_default_cannot_fill_the_sync_fields(self):
        Document = self.env['signify.document'].with_user(self.user).with_context(
            default_signify_ref='999', default_state='shared')
        document = self._created(Document.action_new_from_attachment(self._chatter_file().id))
        self.assertEqual(document.state, 'draft')
        self.assertFalse(document.signify_ref)

    def test_the_draft_of_a_chatter_file_can_be_sent(self):
        document = self._created(self._from_attachment(self._chatter_file()))
        document.write({'recipient_ids': [Command.create(self._line())]})
        with self._signify(self._send_handlers()) as post:
            document.action_send()
        self.assertEqual(document.state, 'shared')
        self.assertEqual(self._sent(post, 'create-document')[0], {
            'documentName': 'contract',
            'extension': 'pdf',
            'fileBase64': base64.b64encode(PDF).decode(),
        })
