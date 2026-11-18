from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import GeoeidCommon


@tagged('post_install', '-at_install')
class TestLaunch(GeoeidCommon):

    def test_launch_returns_the_card_app_url(self):
        item = self.card_item(self.signer)
        result = self.launch(item)
        self.assertTrue(result['success'])
        url = result['authorization_url']
        self.assertTrue(url.startswith('geoeid-unitool://'))
        self.assertIn('/sign/geoeid/init/', url)
        self.assertTrue(url.endswith(item.geoeid_token))

    def test_launch_freezes_the_document_and_opens_a_card_session(self):
        item = self.card_item(self.signer)
        self.launch(item)
        document = item.sign_request_id.request_document_ids
        self.assertEqual(document.state, 'awaiting_signature')
        self.assertTrue(document.frozen_file)
        self.assertEqual(item.geoeid_state, 'launched')
        self.assertTrue(item.geoeid_token)
        remaining = (item.geoeid_token_expiry - fields.Datetime.now()).total_seconds()
        self.assertAlmostEqual(remaining, 600, delta=30)
        self.assertFalse(item.external_signature_session_token)

    def test_url_without_documents_is_empty_and_keeps_the_token(self):
        item = self.card_item(self.signer)
        self.assertEqual(item._get_external_signature_url(), {})
        self.assertFalse(item.geoeid_token)
        self.launch(item)
        token = item.geoeid_token
        self.assertEqual(item._get_external_signature_url(), {})
        self.assertEqual(item.geoeid_token, token)

    def test_relaunch_mints_a_new_token_on_the_same_frozen_bytes(self):
        item = self.card_item(self.signer)
        self.launch(item)
        token = item.geoeid_token
        frozen = bytes(item.sign_request_id.request_document_ids.frozen_file)
        self.launch(item)
        self.assertNotEqual(item.geoeid_token, token)
        self.assertEqual(bytes(item.sign_request_id.request_document_ids.frozen_file), frozen)

    def test_card_signer_out_of_turn_is_refused(self):
        card_partner = self.make_partner('Card signer', email='card@example.com')
        request = self.make_request([(self.signer, self.plain_role), (card_partner, self.card_role_1)])
        card_item = request.request_item_ids.filtered(lambda item: item.role_id == self.card_role_1)
        with self.assertRaisesRegex(UserError, "The signers before you have not signed yet."):
            self.launch(card_item)
        self.assertEqual(card_item.geoeid_state, 'idle')

    def test_document_added_to_template_is_refused_before_freezing(self):
        item = self.card_item(self.signer)
        self.env['sign.document'].create({
            'template_id': item.sign_request_id.template_id.id,
            'attachment_id': self.env['ir.attachment'].create({'name': 'added.pdf', 'raw': self.pdf_raw}).id,
        })
        with self.assertRaisesRegex(UserError, 'single document'):
            self.launch(item)
        self.assertFalse(item.geoeid_token)
        documents = item.sign_request_id.request_document_ids
        self.assertFalse(documents.filtered(lambda doc: doc.state == 'awaiting_signature'))

    def test_reminder_cron_keeps_the_frozen_document_and_calls_no_host(self):
        item = self.card_item(self.signer)
        self.launch(item)
        self.env['sign.request']._cron_reminder()
        document = item.sign_request_id.request_document_ids
        self.assertEqual(document.state, 'awaiting_signature')
        self.assertTrue(document.frozen_file)

    def test_launch_without_a_saved_certificate_is_refused_and_releases_the_document(self):
        item = self.card_item(self.signer)
        self.env['ir.config_parameter'].sudo().search([('key', '=', 'id_ge_sign.trust_anchor')]).unlink()
        result = self.launch(item)
        self.assertFalse(result['success'])
        self.assertIn('not set up yet', result['message'])
        document = item.sign_request_id.request_document_ids
        self.assertEqual(document.state, 'in_progress')
        self.assertFalse(document.frozen_file)
        self.assertEqual(item.geoeid_state, 'idle')
        self.assertFalse(item.geoeid_token)
        self.assertEqual(item.state, 'sent')
