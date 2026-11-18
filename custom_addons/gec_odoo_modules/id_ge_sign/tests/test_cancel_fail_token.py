import datetime

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import COMMON_NAME, PERSONAL_NUMBER, GeoeidCommon


@tagged('post_install', '-at_install')
class TestCancelFailToken(GeoeidCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Item = cls.env['sign.request.item']
        cls.params = cls.env['ir.config_parameter'].sudo()

    def assertReleased(self, item):
        document = item.sign_request_id.request_document_ids
        self.assertEqual((item.geoeid_state, item.geoeid_error), ('idle', False))
        self.assertFalse(item.geoeid_token)
        self.assertFalse(item.geoeid_token_expiry)
        self.assertEqual(document.state, 'in_progress')
        self.assertFalse(document.frozen_file)

    def test_cancel_from_launched_releases_the_document(self):
        item = self.launched_item(self.signer)
        item._geoeid_cancel()
        self.assertReleased(item)

    def test_cancel_from_failed_releases_the_document(self):
        item = self.launched_item(self.signer)
        item._geoeid_fail("Rejected")
        item._geoeid_cancel()
        self.assertReleased(item)

    def test_cancel_from_signed_changes_nothing(self):
        item = self.launched_item(self.signer)
        item.sudo()._geoeid_submit_document(self.card_sign(item)[1])
        item._geoeid_cancel()
        self.assertEqual((item.geoeid_state, item.state), ('signed', 'completed'))
        self.assertEqual(item.geoeid_cert_personal_number, PERSONAL_NUMBER)

    def test_cancel_from_idle_changes_nothing(self):
        item = self.card_item(self.signer)
        item.geoeid_error = "Kept"
        item._geoeid_cancel()
        self.assertEqual((item.geoeid_state, item.geoeid_error), ('idle', "Kept"))

    def test_signer_change_cancels_the_card_session_and_kills_the_old_link(self):
        self.card_role_1.change_authorized = True
        item = self.launched_item(self.signer)
        old_token = item.geoeid_token
        item.write({'partner_id': self.make_partner('Nino', email='nino@example.com').id})
        self.assertReleased(item)
        self.assertFalse(self.Item._geoeid_find_by_token(old_token))

    def test_signer_change_cancels_a_failed_card_session(self):
        self.card_role_1.change_authorized = True
        item = self.launched_item(self.signer)
        item._geoeid_fail("Rejected")
        item.write({'partner_id': self.make_partner('Nino', email='nino@example.com').id})
        self.assertReleased(item)

    def test_writing_the_same_signer_keeps_the_card_session(self):
        self.card_role_1.change_authorized = True
        item = self.launched_item(self.signer)
        token = item.geoeid_token
        item.write({'partner_id': self.signer.id})
        self.assertEqual(item.geoeid_state, 'launched')
        self.assertEqual(item.geoeid_token, token)
        self.assertEqual(item.sign_request_id.request_document_ids.state, 'awaiting_signature')

    def test_refusal_note_is_an_internal_note_by_the_signer_with_the_stored_reason(self):
        item = self.launched_item(self.signer)
        messages = item.sign_request_id.message_ids
        item._geoeid_fail('x' * 600)
        new_messages = item.sign_request_id.message_ids - messages
        self.assertEqual(len(new_messages), 1)
        self.assertEqual(new_messages.author_id, self.signer)
        self.assertEqual(new_messages.subtype_id, self.env.ref('mail.mt_note'))
        self.assertIn('x' * 512, new_messages.body)
        self.assertNotIn('x' * 513, new_messages.body)
        self.assertEqual(item.geoeid_error, 'x' * 512)

    def test_fail_stores_the_error_and_clears_the_token(self):
        item = self.launched_item(self.signer)
        item._geoeid_fail("Rejected")
        self.assertEqual((item.geoeid_state, item.geoeid_error), ('failed', "Rejected"))
        self.assertFalse(item.geoeid_token)
        self.assertFalse(item.geoeid_token_expiry)

    def test_fail_truncates_the_error_to_512_characters(self):
        item = self.launched_item(self.signer)
        item._geoeid_fail('x' * 600)
        self.assertEqual(len(item.geoeid_error), 512)

    def test_find_by_token_returns_the_item(self):
        item = self.launched_item(self.signer)
        self.assertEqual(self.Item._geoeid_find_by_token(item.geoeid_token), item)

    def test_find_by_token_ignores_an_expired_token(self):
        item = self.launched_item(self.signer)
        item.geoeid_token_expiry = fields.Datetime.now() - datetime.timedelta(seconds=1)
        self.assertFalse(self.Item._geoeid_find_by_token(item.geoeid_token))

    def test_find_by_token_ignores_unknown_and_empty_tokens(self):
        self.launched_item(self.signer)
        for token in ('unknown-token', '', None, False):
            with self.subTest(token=token):
                self.assertFalse(self.Item._geoeid_find_by_token(token))

    def test_settings_defaults(self):
        self.params.search([('key', '=like', 'id_ge_sign.%')]).unlink()
        self.assertEqual(self.Item._geoeid_settings(), {
            'language': 'ka', 'trust_anchor': ''})

    def test_settings_custom_values(self):
        self.params.set_str('id_ge_sign.language', 'en')
        self.params.set_str('id_ge_sign.trust_anchor', self.card_pem)
        self.assertEqual(self.Item._geoeid_settings(), {
            'language': 'en', 'trust_anchor': self.card_pem})

    def audit_body(self, common_name):
        item = self.card_item(self.signer)
        return item._geoeid_audit_body({
            'subject': 'CN=' + COMMON_NAME, 'common_name': common_name, 'personal_number': PERSONAL_NUMBER, 'serial': 'a1b2',
            'not_after': datetime.date(2030, 1, 1), 'trusted': True})

    def test_audit_body_names_the_card_holder_when_it_is_the_signer(self):
        body = self.audit_body(self.signer.name.upper())
        for text in (self.signer.name.upper() + ' signed with a Georgian ID Card (certificate chain verified, revocation not checked).',
                     'CN=' + COMMON_NAME, PERSONAL_NUMBER):
            self.assertIn(text, body)
        self.assertNotIn('on the link sent to', body)

    def test_audit_body_names_the_card_holder_and_the_invited_contact_when_they_differ(self):
        body = self.audit_body(COMMON_NAME)
        for text in (COMMON_NAME + ' signed with a Georgian ID Card on the link sent to ' + self.signer.name
                     + ' (certificate chain verified, revocation not checked).', 'CN=' + COMMON_NAME, PERSONAL_NUMBER):
            self.assertIn(text, body)
        self.assertNotIn('Qualified Electronic Signature', body)

    def test_audit_formats_html_and_escapes_partner_and_certificate_values(self):
        item = self.card_item(self.signer)
        self.signer.name = '<b>Signer</b>'
        body = item._geoeid_audit_body({
            'subject': '<a href="https://example.com">Fake</a>', 'personal_number': '<i>123</i>',
            'serial': '<strong>abc</strong>', 'not_after': datetime.date(2030, 1, 1), 'common_name': None, 'trusted': True})
        item.sign_request_id.message_post(body=body)
        stored = item.sign_request_id.message_ids.sorted('id')[-1].body
        self.assertIn('<br', stored)
        self.assertNotIn('&lt;br', stored)
        self.assertIn('&lt;b&gt;Signer&lt;/b&gt;', stored)
        self.assertIn('&lt;a href=', stored)
        self.assertNotIn('<a href=', stored)

    def test_trust_anchor_validation_covers_create_value_write_and_key_rename(self):
        key = 'id_ge_sign.trust_anchor'
        self.params.search([('key', '=', key)]).unlink()
        with self.assertRaises(ValidationError):
            self.params.create({'key': key, 'value': 'invalid pem'})
        parameter = self.params.create({'key': key, 'value': self.card_pem})
        with self.assertRaises(ValidationError):
            parameter.write({'value': 'invalid pem'})
        parameter.write({'value': False})
        parameter.unlink()
        other = self.params.create({'key': 'id_ge_sign.test_parameter', 'value': 'invalid pem'})
        with self.assertRaises(ValidationError):
            other.write({'key': key})
