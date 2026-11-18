from datetime import datetime

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import new_test_user
from odoo.tools import BinaryBytes

from .common import PDF, SignifyCommon


@tagged('post_install', '-at_install')
class TestSignifyAccess(SignifyCommon):

    def _sync_writes(self):
        """Values for each field only Signify may write, and what the field holds afterwards."""
        attachment = self._attachment()
        return {
            'state': ({'state': 'shared'}, 'shared'),
            'signify_ref': ({'signify_ref': '123'}, '123'),
            'signed_attachment_ids': ({'signed_attachment_ids': [Command.set(attachment.ids)]}, attachment),
            'evidence_attachment_id': ({'evidence_attachment_id': attachment.id}, attachment),
            'connection_id': ({'connection_id': self.connection.id}, self.connection),
        }

    def test_a_user_cannot_write_the_sync_fields_of_a_document(self):
        for field, (vals, _expected) in self._sync_writes().items():
            with self.subTest(field=field):
                document = self._document()
                with self.assertRaises(AccessError):
                    document.write(vals)

    def test_a_manager_cannot_write_the_state_either(self):
        """The guard is on the writer, not on the group."""
        document = self._document()
        with self.assertRaises(AccessError):
            document.with_user(self.manager).write({'state': 'shared'})

    def test_the_sync_fields_can_be_written_as_superuser(self):
        """The sync runs as superuser."""
        for field, (vals, expected) in self._sync_writes().items():
            with self.subTest(field=field):
                document = self._document()
                document.sudo().write(vals)
                self.assertEqual(document.sudo()[field], expected)

    def test_a_user_cannot_create_a_document_with_sync_fields(self):
        Document = self.env['signify.document'].with_user(self.user)
        for field, (vals, _expected) in self._sync_writes().items():
            with self.subTest(field=field):
                with self.assertRaises(AccessError):
                    Document.create(self._document_vals(**vals))

    def test_a_user_cannot_write_the_sync_fields_of_a_recipient(self):
        recipient = self._document().recipient_ids
        cases = {'signify_ref': '9', 'status': 'finished', 'action_time': datetime(2022, 11, 17, 10, 20, 58)}
        for field, value in cases.items():
            with self.subTest(field=field):
                with self.assertRaises(AccessError):
                    recipient.write({field: value})

    def test_the_sync_fields_of_a_recipient_can_be_written_as_superuser(self):
        recipient = self._document().recipient_ids
        recipient.sudo().write({'status': 'finished', 'signify_ref': '9'})
        self.assertEqual((recipient.status, recipient.signify_ref), ('finished', '9'))

    def test_a_user_cannot_create_a_recipient_with_a_status(self):
        document = self._document()
        with self.assertRaises(AccessError):
            self.env['signify.recipient'].with_user(self.user).create({
                'document_id': document.id, 'partner_id': self.person.id, 'status': 'finished'})

    def test_a_context_default_cannot_fill_the_sync_fields_of_a_document(self):
        Document = self.env['signify.document'].with_user(self.user).with_context(
            default_signify_ref='999', default_state='shared', default_status='finished', default_connection_id=self.connection.id)
        document = Document.create(self._document_vals())
        self.assertEqual(document.state, 'draft')
        self.assertFalse(document.signify_ref)
        self.assertFalse(document.connection_id)
        self.assertFalse(document.recipient_ids.signify_ref)
        self.assertFalse(document.recipient_ids.status)

    def test_a_personal_default_cannot_fill_the_sync_fields_of_a_document(self):
        Default = self.env['ir.default']
        Default.set('signify.document', 'signify_ref', '555', user_id=self.user.id)
        Default.set('signify.document', 'state', 'shared', user_id=self.user.id)
        Default.set('signify.document', 'connection_id', self.connection.id, user_id=self.user.id)
        Default.set('signify.recipient', 'signify_ref', '555', user_id=self.user.id)
        Default.set('signify.recipient', 'status', 'finished', user_id=self.user.id)
        document = self._document()
        self.assertEqual(document.state, 'draft')
        self.assertFalse(document.signify_ref)
        self.assertFalse(document.connection_id)
        self.assertFalse(document.recipient_ids.signify_ref)
        self.assertFalse(document.recipient_ids.status)

    def test_a_context_default_cannot_fill_the_sync_fields_of_a_recipient(self):
        document = self._document()
        recipient = self.env['signify.recipient'].with_user(self.user).with_context(
            default_signify_ref='9', default_status='finished', default_action_time='2022-11-17 10:20:58',
        ).create({'document_id': document.id, 'partner_id': self.person.id})
        self.assertFalse(recipient.signify_ref)
        self.assertFalse(recipient.status)
        self.assertFalse(recipient.action_time)

    def test_the_superuser_create_still_accepts_defaults_and_sync_values(self):
        """The sync runs as superuser."""
        Document = self.env['signify.document'].sudo()
        by_default = Document.with_context(default_signify_ref='999', default_state='shared').create(
            self._document_vals())
        self.assertEqual((by_default.state, by_default.signify_ref), ('shared', '999'))
        explicit = Document.create(self._document_vals(state='finished', signify_ref='5'))
        self.assertEqual((explicit.state, explicit.signify_ref), ('finished', '5'))
        Recipient = self.env['signify.recipient'].sudo()
        recipient = Recipient.with_context(default_status='finished', default_signify_ref='7').create({
            'document_id': explicit.id, 'partner_id': self.person.id})
        self.assertEqual((recipient.status, recipient.signify_ref), ('finished', '7'))
        recipient = Recipient.create({
            'document_id': explicit.id, 'partner_id': self.person.id, 'status': 'rejected', 'signify_ref': '8'})
        self.assertEqual((recipient.status, recipient.signify_ref), ('rejected', '8'))

    def test_a_duplicate_with_a_context_default_gets_no_signify_id(self):
        document = self._document()
        copy = document.with_context(default_signify_ref='999', default_state='shared').copy()
        self.assertEqual(copy.state, 'draft')
        self.assertFalse(copy.signify_ref)

    def test_a_user_creates_a_document_through_the_form(self):
        """The guard does not block the normal create of the form view."""
        form = Form(self.env['signify.document'].with_user(self.user))
        form.name = "Form contract"
        form.file = BinaryBytes(PDF)
        with form.recipient_ids.new() as line:
            line.partner_id = self.person
        document = form.save()
        self.assertEqual((document.name, document.state), ("Form contract", 'draft'))
        self.assertEqual(document.recipient_ids.partner_id, self.person)
        self.assertEqual(document.create_uid, self.user)

    def test_a_user_searches_only_own_documents(self):
        mine, theirs = self._document(), self._document(user=self.user_2)
        domain = [('id', 'in', [mine.id, theirs.id])]
        self.assertEqual(self.env['signify.document'].with_user(self.user).search(domain), mine)
        self.assertEqual(self.env['signify.document'].with_user(self.user_2).search(domain), theirs)

    def test_a_user_cannot_read_the_document_of_another_user(self):
        document = self._document()
        with self.assertRaises(AccessError):
            document.with_user(self.user_2).read(['name'])

    def test_a_user_edits_own_draft(self):
        document = self._document()
        document.write({'name': "Renamed"})
        self.assertEqual(document.name, "Renamed")

    def test_a_user_deletes_own_draft(self):
        document = self._document()
        document.unlink()
        self.assertFalse(document.exists())

    def test_a_manager_cannot_delete_a_sent_document(self):
        document = self._shared()
        with self.assertRaises(UserError) as cm:
            document.with_user(self.manager).unlink()
        self.assertNotIsInstance(cm.exception, AccessError)
        self.assertIn("Recall a sent document", str(cm.exception))
        self.assertTrue(document.exists())

    def test_a_manager_cannot_delete_a_signed_document(self):
        """Its signed files and evidence report would be deleted with it."""
        document = self._shared()
        document.sudo().state = 'finished'
        with self.assertRaises(UserError) as cm:
            document.with_user(self.manager).unlink()
        self.assertNotIsInstance(cm.exception, AccessError)
        self.assertIn("A signed document cannot be deleted", str(cm.exception))
        self.assertTrue(document.exists())

    def test_a_manager_deletes_a_recalled_document(self):
        document = self._shared()
        document.sudo().state = 'canceled'
        document.with_user(self.manager).unlink()
        self.assertFalse(document.exists())

    def test_a_user_cannot_write_own_sent_document(self):
        document = self._shared()
        with self.assertRaises(AccessError):
            document.write({'name': "Too late"})

    def test_a_user_cannot_delete_own_sent_document(self):
        document = self._shared()
        with self.assertRaises(AccessError):
            document.unlink()

    def test_a_user_cannot_edit_the_draft_of_another_user(self):
        document = self._document()
        with self.assertRaises(AccessError):
            document.with_user(self.user_2).write({'name': "Mine now"})

    def test_a_manager_reads_and_edits_every_document_of_the_company(self):
        draft, sent = self._document(), self._shared(user=self.user_2)
        found = self.env['signify.document'].with_user(self.manager).search([('id', 'in', [draft.id, sent.id])])
        self.assertEqual(set(found.ids), {draft.id, sent.id})
        sent.with_user(self.manager).write({'name': "Renamed by manager"})
        self.assertEqual(sent.name, "Renamed by manager")

    def test_an_employee_without_the_signify_group_cannot_read_documents(self):
        with self.assertRaises(AccessError):
            self.env['signify.document'].with_user(self.employee).search([])

    def test_an_employee_without_the_signify_group_cannot_create_documents(self):
        with self.assertRaises(AccessError):
            self.env['signify.document'].with_user(self.employee).create(self._document_vals())

    def test_a_user_adds_a_recipient_to_own_draft(self):
        document = self._document()
        self.env['signify.recipient'].with_user(self.user).create({
            'document_id': document.id, 'partner_id': self.contact.id})
        self.assertEqual(len(document.recipient_ids), 2)

    def test_a_user_cannot_move_a_recipient_to_another_document(self):
        """The access rule is checked on the old document only, so the move is refused in write."""
        document = self._document()
        recipient = document.recipient_ids
        for target in (self._document(user=self.user_2), self._document()):
            with self.subTest(owner=target.create_uid.login), self.assertRaises(AccessError):
                recipient.write({'document_id': target.id})
        recipient.write({'document_id': document.id})
        self.assertEqual(recipient.document_id, document)

    def test_a_recipient_can_be_moved_as_superuser(self):
        recipient, target = self._document().recipient_ids, self._document(user=self.user_2)
        recipient.sudo().write({'document_id': target.id})
        self.assertEqual(recipient.sudo().document_id, target)

    def test_a_user_edits_the_recipients_of_own_draft_through_the_form(self):
        """Create, update, reorder and delete lines as the form sends them."""
        document = self._document(recipients=[self._line(), self._line(partner_id=self.contact.id)])
        form = Form(document)
        with form.recipient_ids.new() as line:
            line.partner_id = self.company_partner
        with form.recipient_ids.edit(0) as line:
            line.placement_keyword = "Manager"
        form.recipient_ids.remove(1)
        form.save()
        first, added = document.recipient_ids.sorted('id')
        self.assertEqual((first.partner_id, first.placement_keyword), (self.person, "Manager"))
        self.assertEqual(added.partner_id, self.company_partner)
        document.write({'recipient_ids': [Command.update(first.id, {'sequence': 20}), Command.link(added.id)]})
        self.assertEqual(document.recipient_ids.sorted('sequence'), added | first)

    def test_a_user_cannot_add_a_recipient_to_own_sent_document(self):
        document = self._shared()
        with self.assertRaises(AccessError):
            self.env['signify.recipient'].with_user(self.user).create({
                'document_id': document.id, 'partner_id': self.contact.id})

    def test_a_user_cannot_add_a_recipient_to_the_draft_of_another_user(self):
        document = self._document()
        with self.assertRaises(AccessError):
            self.env['signify.recipient'].with_user(self.user_2).create({
                'document_id': document.id, 'partner_id': self.contact.id})

    def test_linking_a_record_the_user_cannot_read_is_refused(self):
        unreadable = self.env['res.partner'].create({'name': "Company B only", 'company_id': self.company_b.id})
        self.assertFalse(unreadable.with_user(self.user).has_access('read'))
        reference = f'res.partner,{unreadable.id}'
        with self.assertRaises(ValidationError):
            self.env['signify.document'].with_user(self.user).create(self._document_vals(reference_doc=reference))
        document = self._document()
        with self.assertRaises(ValidationError):
            document.write({'reference_doc': reference})

    def _unlinked_vals(self):
        """Leaves Linked To empty for a default to fill."""
        vals = self._document_vals()
        del vals['reference_doc']
        return vals

    def _unreadable_reference(self):
        unreadable = self.env['res.partner'].create({'name': "Company B only", 'company_id': self.company_b.id})
        self.assertFalse(unreadable.with_user(self.user).has_access('read'))
        return f'res.partner,{unreadable.id}'

    def test_a_context_default_cannot_link_a_record_the_user_cannot_read(self):
        """default_reference_doc is checked like an explicit value: on create and on a draft from a file."""
        reference = self._unreadable_reference()
        Document = self.env['signify.document'].with_user(self.user).with_context(default_reference_doc=reference)
        before = self.env['signify.document'].sudo().search([])
        with self.assertRaises(ValidationError):
            Document.create(self._unlinked_vals())
        loose = self.env['ir.attachment'].with_user(self.user).create({'name': 'loose.pdf', 'raw': PDF})
        with self.assertRaises(ValidationError):
            Document.action_new_from_attachment(loose.id)
        self.assertEqual(self.env['signify.document'].sudo().search([]), before)

    def test_a_personal_default_cannot_link_a_record_the_user_cannot_read(self):
        reference = self._unreadable_reference()
        self.env['ir.default'].set('signify.document', 'reference_doc', reference, user_id=self.user.id)
        with self.assertRaises(ValidationError):
            self.env['signify.document'].with_user(self.user).create(self._unlinked_vals())

    def test_a_default_link_is_kept_when_the_caller_is_superuser(self):
        """sudo() reads every record: the default link is stored, also for a user who calls sudo() himself."""
        reference = self._unreadable_reference()
        for Document in (self.env['signify.document'].sudo(), self.env['signify.document'].with_user(self.user).sudo()):
            document = Document.with_context(default_reference_doc=reference).create(self._unlinked_vals())
            self.assertEqual(f'{document.reference_doc._name},{document.reference_doc.id}', reference)

    def test_linking_a_record_that_does_not_exist_stores_no_link(self):
        """The core Reference field stores a missing id as empty, so nothing can be posted or copied there."""
        reference = 'res.partner,999999999'
        created = self.env['signify.document'].with_user(self.user).create(self._document_vals(reference_doc=reference))
        self.assertFalse(created.reference_doc)
        document = self._document()
        document.write({'reference_doc': reference})
        self.assertFalse(document.reference_doc)

    def test_a_user_of_another_company_sees_no_document(self):
        document = self._document()
        for user in (self.user_b, self.manager_b):
            with self.subTest(user=user.login):
                found = self.env['signify.document'].with_user(user).search([('id', '=', document.id)])
                self.assertFalse(found)
                with self.assertRaises(AccessError):
                    document.with_user(user).read(['name'])

    def test_a_recipient_of_another_company_is_refused(self):
        """The partner of a recipient must belong to the company of the document."""
        document = self._document()
        partner_b = self.env['res.partner'].create({'name': "Partner B", 'company_id': self.company_b.id})
        with self.assertRaisesRegex(UserError, "company inconsistencies"):
            self.env['signify.recipient'].create({'document_id': document.id, 'partner_id': partner_b.id})

    def test_the_client_secret_and_the_tokens_are_readable_by_settings_administrators_only(self):
        for user in (self.user, self.manager):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    self.env['ir.config_parameter'].with_user(user).get_str('signify.client_secret')
                for field in ('access_token', 'refresh_token', 'expiry'):
                    with self.assertRaises(AccessError):
                        self.connection.with_user(user).read([field])
        admin = new_test_user(self.env, login='signify_settings', groups='base.group_user,base.group_system')
        self.assertEqual(self.connection.with_user(admin).access_token, 'tok-1')

    def test_a_signify_user_reads_the_connections_of_the_company_but_cannot_change_them(self):
        connection = self.connection_manager.with_user(self.user)
        self.assertEqual(connection.read(['email', 'connected'])[0]['email'], self.connection_manager.email)
        self.assertTrue(connection.connected)
        with self.assertRaises(AccessError):
            connection.write({'email': 'other@example.com'})
        with self.assertRaises(AccessError):
            self.env['signify.connection'].with_user(self.user).create({'signify_sub': 'x'})
        with self.assertRaises(AccessError):
            connection.unlink()

    def test_a_user_of_another_company_sees_no_connection(self):
        found = self.env['signify.connection'].with_user(self.user_b).search([('id', 'in', (self.connection | self.connection_b).ids)])
        self.assertEqual(found, self.connection_b)
        with self.assertRaises(AccessError):
            self.connection.with_user(self.user_b).read(['email'])

    def test_an_employee_without_the_signify_group_sees_no_connection(self):
        with self.assertRaises(AccessError):
            self.env['signify.connection'].with_user(self.employee).search([])

    def test_connect_is_for_signify_users_only(self):
        action = self.env['signify.connection'].with_user(self.user).action_connect()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['url'], f'/signify/oauth/start?company_id={self.user.company_id.id}')
        with self.assertRaises(AccessError):
            self.env['signify.connection'].with_user(self.employee).action_connect()

    def test_connect_stops_in_odoo_when_signify_is_not_set_up(self):
        self.env['ir.config_parameter'].set_str('signify.client_id', '')
        with self.assertRaises(UserError) as cm:
            self.env['signify.connection'].with_user(self.user).action_connect()
        self.assertIn("Signify is not set up", str(cm.exception))

    def test_the_owner_recalls_a_sent_document(self):
        document = self._shared()
        with self._signify({'recall-document': self._ok()}) as post:
            document.action_recall()
        self.assertEqual(self._sent(post, 'recall-document'), [{'documentId': int(document.signify_ref)}])
        self.assertIsInstance(self._sent(post, 'recall-document')[0]['documentId'], int)
        self.assertEqual(document.state, 'canceled')

    def test_recall_uses_the_account_of_the_document_not_the_one_of_the_viewer(self):
        self.connection_manager.access_token = 'tok-manager'
        document = self._shared()
        with self._signify({'recall-document': self._ok()}) as post:
            document.with_user(self.manager).action_recall()
        self.assertEqual(self._calls(post, 'recall-document')[0]['headers']['Authorization'], 'Bearer tok-1')
        self.assertEqual(document.state, 'canceled')

    def test_a_document_without_an_account_cannot_be_recalled(self):
        document = self._shared()
        document.sudo().connection_id = False
        with self._signify() as post, self.assertRaises(UserError) as cm:
            document.action_recall()
        self.assertIn("Connect your Signify account", str(cm.exception))
        post.assert_not_called()

    def test_another_user_cannot_recall_my_document(self):
        document = self._shared()
        with self._signify() as post, self.assertRaises(AccessError):
            document.with_user(self.user_2).action_recall()
        post.assert_not_called()

    def test_a_draft_cannot_be_recalled(self):
        document = self._document()
        with self._signify() as post, self.assertRaises(UserError):
            document.action_recall()
        post.assert_not_called()

    def test_the_signing_page_link_is_opened_in_a_new_window(self):
        document = self._shared(recipients=[self._line(contact_type='link')])
        recipient = document.recipient_ids
        handlers = {'generate-document-link': self._ok(url='https://sign.example/abc')}
        with self._signify(handlers) as post:
            action = recipient.action_open_signing_page()
        self.assertEqual(action, {'type': 'ir.actions.act_url', 'url': 'https://sign.example/abc', 'target': 'new'})
        payload = self._sent(post, 'generate-document-link')[0]
        self.assertEqual(payload, {'documentId': int(document.signify_ref), 'recipientId': int(recipient.signify_ref)})
        self.assertIsInstance(payload['documentId'], int)
        self.assertIsInstance(payload['recipientId'], int)

    def test_the_signing_page_uses_the_account_of_the_document(self):
        self.connection_manager.access_token = 'tok-manager'
        recipient = self._shared(recipients=[self._line(contact_type='link')]).recipient_ids
        with self._signify({'generate-document-link': self._ok(url='https://sign.example/abc')}) as post:
            recipient.with_user(self.manager).action_open_signing_page()
        self.assertEqual(self._calls(post, 'generate-document-link')[0]['headers']['Authorization'], 'Bearer tok-1')

    def test_only_a_link_recipient_has_a_signing_page(self):
        recipient = self._shared().recipient_ids
        with self._signify() as post, self.assertRaises(UserError) as cm:
            recipient.action_open_signing_page()
        self.assertIn("Only link recipients", str(cm.exception))
        post.assert_not_called()

    def test_another_user_cannot_open_the_signing_page(self):
        recipient = self._shared(recipients=[self._line(contact_type='link')]).recipient_ids
        with self._signify() as post, self.assertRaises(AccessError):
            recipient.with_user(self.user_2).action_open_signing_page()
        post.assert_not_called()

    def test_a_duplicate_of_a_sent_document_is_a_clean_draft(self):
        document = self._shared()
        attachment = self._attachment()
        document.sudo().write({
            'signed_attachment_ids': [Command.set(attachment.ids)], 'evidence_attachment_id': attachment.id})
        copy = document.copy()
        self.assertEqual(copy.state, 'draft')
        self.assertFalse(copy.signify_ref)
        self.assertFalse(copy.connection_id)
        self.assertEqual((copy.recipient_ids.partner_id, copy.recipient_ids.placement_keyword), (self.person, 'Director'))
        self.assertFalse(copy.recipient_ids.signify_ref or copy.recipient_ids.status or copy.recipient_ids.action_time)
        copy.recipient_ids.placement_keyword = "Manager"
        self.assertEqual(copy.sudo().recipient_ids.placement_keyword, "Manager")
        self.assertFalse(copy.signed_attachment_ids)
        self.assertFalse(copy.evidence_attachment_id)

    def test_the_name_defaults_to_the_file_name_without_extension(self):
        self.assertEqual(self._document().name, 'contract')

    def test_an_explicit_name_is_kept(self):
        self.assertEqual(self._document(name="Service agreement").name, "Service agreement")

    def test_only_mail_thread_models_can_be_linked(self):
        models = [model for model, _label in self.env['signify.document']._selection_target_model()]
        self.assertIn('res.partner', models)
        self.assertNotIn('signify.document', models)
        self.assertNotIn('res.country', models)

    def test_no_abstract_model_can_be_linked(self):
        models = [model for model, _label in self.env['signify.document']._selection_target_model()]
        self.assertFalse(self.env['ir.model'].search([('model', 'in', models), ('abstract', '=', True)]))

    def test_a_channel_cannot_be_linked(self):
        """Linked to a channel, a document would post and attach files to every member."""
        models = [model for model, _label in self.env['signify.document']._selection_target_model()]
        self.assertNotIn('discuss.channel', models)
