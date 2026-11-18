import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import LockError, UserError
from odoo.tests import HttpCase, tagged

from .common import PLACEHOLDER_DOMAIN, GeoeidCommon

BOUNDARY = '===1780578020325==='


@tagged('post_install', '-at_install')
class TestGeoeidControllers(GeoeidCommon, HttpCase):

    def url_open(self, *args, **kwargs):
        response = super().url_open(*args, **kwargs)
        self.env.invalidate_all()
        return response

    def _json_url_open(self, url, data):
        body = {'id': 0, 'jsonrpc': '2.0', 'method': 'call', 'params': data}
        return self.url_open(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})

    def rpc(self, url, **params):
        return self._json_url_open(url, params).json()['result']

    def upload(self, item, pdf, boundary=BOUNDARY):
        """The desktop app's multipart body: an unquoted boundary that contains '='."""
        part = (b'Content-Disposition: form-data; name="signedFile"; filename="signed.pdf"\r\n'
                b'Content-Type: application/pdf\r\n\r\n')
        delimiter = b'--' + boundary.encode()
        body = delimiter + b'\r\n' + part + pdf + b'\r\n' + delimiter + b'--\r\n'
        headers = {'Content-Type': 'multipart/form-data; boundary=' + boundary}
        return self.url_open('/sign/geoeid/submit/' + item.geoeid_token, data=body, headers=headers)

    def shared_request(self, role):
        template = self.make_template([role])
        return self.env['sign.request'].with_context(no_sign_mail=True).create({
            'template_id': template.id,
            'reference': 'Shared contract',
            'request_item_ids': [Command.create({'role_id': role.id})],
            'state': 'shared',
            'send_channel': 'shared',
            'validity': False,
        })

    def public_attempt(self, shared, attempt_id=None, core=False):
        route = '/sign/send_public' if core else '/sign/geoeid/public'
        return self.rpc('%s/%d/%s' % (route, shared.id, shared.access_token),
                        attempt_id=attempt_id or str(uuid.uuid4()))

    def test_sign_route_launches_a_card_signer(self):
        item = self.card_item(self.signer)
        request = item.sign_request_id
        result = self.rpc('/sign/sign/%d/%s' % (request.id, item.access_token), signature=self.signature_for(item))
        self.assertTrue(result['success'])
        self.assertTrue(result['authorization_url'].startswith('geoeid-unitool://'))
        self.assertEqual(item.geoeid_state, 'launched')

    def test_sign_route_refuses_a_card_signer_out_of_turn(self):
        card_partner = self.make_partner('Card signer', email='card@example.com')
        request = self.make_request([(self.signer, self.plain_role), (card_partner, self.card_role_1)])
        item = request.request_item_ids.filtered(lambda i: i.role_id == self.card_role_1)
        body = {'signature': self.signature_for(item)}
        response = self._json_url_open('/sign/sign/%d/%s' % (request.id, item.access_token), body).json()
        self.assertEqual(response['error']['data']['message'], "The signers before you have not signed yet.")
        self.assertEqual(item.geoeid_state, 'idle')

    def test_public_route_makes_a_placeholder_signer_and_a_sent_request(self):
        shared = self.shared_request(self.card_role_1)
        requests = self.env['sign.request'].search([])
        result = self.public_attempt(shared)
        new_request = self.env['sign.request'].search([]) - requests
        self.assertEqual(new_request.id, result['requestID'])
        self.assertEqual(new_request.state, 'sent')
        self.assertEqual(result['requestToken'], new_request.access_token)
        item = new_request.request_item_ids
        self.assertEqual(result['accessToken'], item.access_token)
        self.assertEqual(item.role_id, self.card_role_1)
        self.assertFalse(item.partner_id.active)
        self.assertTrue(item.partner_id.email.endswith('@' + PLACEHOLDER_DOMAIN))

    def test_public_retry_reuses_only_its_own_attempt(self):
        shared = self.shared_request(self.card_role_1)
        attempt_id = str(uuid.uuid4())
        first = self.public_attempt(shared, attempt_id)
        self.assertEqual(self.public_attempt(shared, attempt_id), first)
        second = self.public_attempt(shared)
        self.assertNotEqual(second['requestID'], first['requestID'])
        cookies = self.opener.cookies.copy()
        self.opener.cookies.clear()
        try:
            other_session = self.public_attempt(shared, attempt_id)
        finally:
            self.opener.cookies = cookies
        self.assertNotEqual(other_session['requestID'], first['requestID'])
        self.assertNotEqual(other_session['accessToken'], first['accessToken'])

    def test_core_public_route_uses_the_same_attempt_for_a_card_role(self):
        shared = self.shared_request(self.card_role_1)
        attempt_id = str(uuid.uuid4())
        first = self.public_attempt(shared, attempt_id)
        self.assertEqual(self.public_attempt(shared, attempt_id, core=True), first)

    def test_core_public_route_preserves_regular_signing(self):
        shared = self.shared_request(self.plain_role)
        result = self.rpc('/sign/send_public/%d/%s' % (shared.id, shared.access_token),
                          name='Regular visitor', mail='regular@example.com')
        new_request = self.env['sign.request'].browse(result['requestID'])
        self.assertEqual(new_request.request_item_ids.partner_id.email, 'regular@example.com')
        multi = self.make_request([(self.signer, self.plain_role), (self.signer, self.plain_role_2)])
        self.assertFalse(self.rpc('/sign/send_public/%d/%s' % (multi.id, multi.access_token)))

    def test_public_route_rejects_missing_attempt_and_expired_or_canceled_requests(self):
        shared = self.shared_request(self.card_role_1)
        self.assertFalse(self.rpc('/sign/geoeid/public/%d/%s' % (shared.id, shared.access_token)))
        shared.validity = fields.Date.today() - timedelta(days=1)
        self.assertFalse(self.public_attempt(shared))
        shared.validity = False
        shared.cancel()
        self.assertFalse(self.public_attempt(shared))

    def test_public_attempt_never_reuses_a_canceled_or_archived_copy(self):
        shared = self.shared_request(self.card_role_1)
        attempt_id = str(uuid.uuid4())
        result = self.public_attempt(shared, attempt_id)
        copied = self.env['sign.request'].browse(result['requestID'])
        copied.cancel()
        self.assertFalse(self.public_attempt(shared, attempt_id))
        another_id = str(uuid.uuid4())
        result = self.public_attempt(shared, another_id)
        self.env['sign.request'].browse(result['requestID']).active = False
        self.assertFalse(self.public_attempt(shared, another_id))

    def test_public_route_refuses_a_role_without_geoeid(self):
        shared = self.shared_request(self.plain_role)
        self.assertFalse(self.rpc('/sign/geoeid/public/%d/%s' % (shared.id, shared.access_token)))

    def test_public_route_refuses_a_request_that_has_a_partner(self):
        request = self.make_request([(self.signer, self.card_role_1)])
        self.assertFalse(self.rpc('/sign/geoeid/public/%d/%s' % (request.id, request.access_token)))

    def test_status_of_an_unknown_token(self):
        item = self.card_item(self.signer)
        result = self.rpc('/sign/geoeid/status/%d/unknown' % item.sign_request_id.id)
        self.assertEqual(result, {'state': 'failed'})

    def test_status_of_a_launched_item(self):
        item = self.launched_item(self.signer)
        result = self.rpc('/sign/geoeid/status/%d/%s' % (item.sign_request_id.id, item.access_token))
        self.assertEqual(result, {'state': 'launched'})

    def test_status_of_a_failed_item_hides_the_reason(self):
        item = self.launched_item(self.signer)
        item._geoeid_fail("Rejected")
        result = self.rpc('/sign/geoeid/status/%d/%s' % (item.sign_request_id.id, item.access_token))
        self.assertEqual(result, {'state': 'failed'})

    def test_cancel_puts_a_launched_item_back_to_idle(self):
        item = self.launched_item(self.signer)
        result = self.rpc('/sign/geoeid/cancel/%d/%s' % (item.sign_request_id.id, item.access_token))
        self.assertEqual(result, {'success': True})
        self.assertEqual(item.geoeid_state, 'idle')
        self.assertFalse(item.geoeid_token)

    def test_cancel_with_an_unknown_token_or_a_regular_role_fails(self):
        item = self.launched_item(self.signer)
        self.assertEqual(self.rpc('/sign/geoeid/cancel/%d/unknown' % item.sign_request_id.id), {'success': False})
        regular = self.card_item(self.signer, self.plain_role)
        result = self.rpc('/sign/geoeid/cancel/%d/%s' % (regular.sign_request_id.id, regular.access_token))
        self.assertEqual(result, {'success': False})
        self.assertEqual(item.geoeid_state, 'launched')

    def test_init_returns_the_document_spec(self):
        item = self.launched_item(self.signer)
        response = self.url_open('/sign/geoeid/init/' + item.geoeid_token)
        self.assertEqual(response.status_code, 200)
        spec = response.json()
        self.assertEqual(spec['dataType'], 'document')
        self.assertTrue(spec['dataUrl'].endswith('/sign/geoeid/document/' + item.geoeid_token))
        self.assertTrue(spec['submitUrl'].endswith('/sign/geoeid/submit/' + item.geoeid_token))
        self.assertEqual((spec['signatureProfile'], spec['language']), ('B', 'ka'))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_init_with_an_unknown_token_is_not_found(self):
        self.assertEqual(self.url_open('/sign/geoeid/init/unknown').status_code, 404)

    def test_init_after_cancel_is_not_found(self):
        item = self.launched_item(self.signer)
        token = item.geoeid_token
        item._geoeid_cancel()
        self.assertEqual(self.url_open('/sign/geoeid/init/' + token).status_code, 404)

    def test_document_returns_exactly_the_frozen_bytes(self):
        item = self.launched_item(self.signer)
        frozen = bytes(item.sign_request_id.request_document_ids.frozen_file)
        response = self.url_open('/sign/geoeid/document/' + item.geoeid_token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/pdf')
        self.assertEqual(response.content, frozen)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_document_with_an_unknown_token_is_not_found(self):
        self.assertEqual(self.url_open('/sign/geoeid/document/unknown').status_code, 404)

    def test_submit_with_the_apps_unquoted_boundary_completes_the_item(self):
        item = self.launched_item(self.signer)
        response = self.upload(item, self.card_sign(item)[1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        self.assertEqual((item.state, item.geoeid_state), ('completed', 'signed'))

    def test_submit_retry_acknowledges_only_the_committed_document(self):
        item = self.launched_item(self.signer)
        signed = self.card_sign(item)[1]
        expiry = item.geoeid_token_expiry
        self.assertEqual(self.upload(item, signed).status_code, 200)
        self.assertEqual(self.upload(item, signed).json(), {'success': True})
        self.assertEqual(item.geoeid_token_expiry, expiry)
        self.assertEqual(self.upload(item, signed + b'\n').status_code, 400)
        self.assertEqual((item.state, item.geoeid_state), ('completed', 'signed'))
        self.assertFalse(item.geoeid_error)
        self.assertEqual(self.url_open('/sign/geoeid/init/' + item.geoeid_token).status_code, 404)
        self.assertEqual(self.url_open('/sign/geoeid/document/' + item.geoeid_token).status_code, 404)

    def test_completed_upload_acknowledgement_expires_without_changing_the_signature(self):
        item = self.launched_item(self.signer)
        signed = self.card_sign(item)[1]
        self.assertEqual(self.upload(item, signed).status_code, 200)
        item.geoeid_token_expiry = fields.Datetime.now() - timedelta(seconds=1)
        self.assertEqual(self.upload(item, signed).status_code, 404)
        self.assertEqual((item.geoeid_state, item.state), ('signed', 'completed'))

    def test_concurrent_upload_returns_a_retriable_conflict(self):
        item = self.launched_item(self.signer)
        Item = self.env.registry['sign.request.item']
        with patch.object(Item, '_geoeid_submit_document', side_effect=LockError('Busy')):
            response = self.upload(item, b'pending upload')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.headers['Retry-After'], '1')
        self.assertEqual(item.geoeid_state, 'launched')

    def test_refusal_while_the_rows_are_locked_answers_json_and_keeps_the_attempt(self):
        item = self.launched_item(self.signer)
        token = item.geoeid_token
        Item = self.env.registry['sign.request.item']
        with (patch.object(Item, '_geoeid_submit_document', side_effect=UserError('Rejected')),
              patch.object(Item, 'try_lock_for_update', return_value=item.browse())):
            response = self.upload(item, b'pending upload')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertEqual((item.geoeid_state, item.geoeid_token), ('launched', token))

    def test_oversized_body_is_rejected_before_reading_the_signature(self):
        item = self.launched_item(self.signer)
        self.env['ir.config_parameter'].sudo().set_int('id_ge_sign.max_signature_increment', 0)
        module = 'odoo.addons.id_ge_sign.controllers.geoeid'
        controller = 'odoo.addons.id_ge_sign.controllers.geoeid.GeoeidController'
        with (patch(module + '.MAX_EXTERNAL_SIGNATURE_UPLOAD_SIZE', 64),
              patch(module + '.protocol.GEOEID_MULTIPART_OVERHEAD', 0)):
            with patch(controller + '._read_signed_file', side_effect=AssertionError('Upload was parsed')):
                response = self.upload(item, b'x' * 128, boundary='normal-boundary')
        self.assertEqual(response.status_code, 413)
        self.assertEqual(item.geoeid_state, 'launched')

    def test_completion_user_error_is_reported_and_rolls_back_the_signature(self):
        item = self.launched_item(self.signer)
        signed = self.card_sign(item)[1]
        with patch.object(self.env.registry['sign.request.item'], '_apply_external_signatures',
                          side_effect=UserError('Completion unavailable')):
            response = self.upload(item, signed)
        self.assertEqual(response.status_code, 400)
        self.assertEqual((item.state, item.geoeid_state), ('sent', 'failed'))
        self.assertEqual(item.geoeid_error, 'Completion unavailable')
        self.assertFalse(item.geoeid_signed_digest or item.geoeid_cert_subject)

    def test_submit_with_a_standard_multipart_upload_completes_the_item(self):
        item = self.launched_item(self.signer)
        files = {'signedFile': ('signed.pdf', self.card_sign(item)[1], 'application/pdf')}
        response = self.url_open('/sign/geoeid/submit/' + item.geoeid_token, files=files)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(item.state, 'completed')

    def test_submit_of_a_pdf_signed_over_other_bytes_fails_the_item(self):
        item = self.launched_item(self.signer)
        response = self.upload(item, self.card_sign(item, pdf=self.pdf_raw)[1])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(item.geoeid_state, 'failed')
        self.assertTrue(item.geoeid_error)
        self.assertEqual(item.state, 'sent')

    def test_submit_whose_completion_fails_leaves_the_request_untouched(self):
        placeholder = self.placeholder('ghost@id-card.invalid')
        item = self.launched_item(placeholder)
        request = item.sign_request_id
        messages = request.message_ids
        signed = self.card_sign(item)[1]
        with patch.object(self.env.registry['sign.request.item'], '_apply_external_signatures', lambda *args: None):
            response = self.upload(item, signed)
        self.assertEqual(response.status_code, 400)
        self.assertEqual((item.state, item.geoeid_state), ('sent', 'failed'))
        self.assertTrue(item.geoeid_error)
        self.assertFalse(item.geoeid_cert_personal_number or item.geoeid_cert_subject or item.geoeid_signed_on)
        new_messages = request.message_ids - messages
        self.assertEqual(len(new_messages), 1)
        self.assertIn('was refused', new_messages.body)
        self.assertEqual(request.state, 'sent')
        self.assertEqual(request.request_document_ids.state, 'awaiting_signature')
        self.assertEqual(
            (placeholder.name, placeholder.vat, placeholder.active), ('Georgian ID Card signer', False, False))

    def test_submit_with_an_unknown_token_is_not_found(self):
        response = self.url_open('/sign/geoeid/submit/unknown', files={'signedFile': ('signed.pdf', b'pdf')})
        self.assertEqual(response.status_code, 404)

    def test_submit_without_a_file_is_a_bad_request(self):
        item = self.launched_item(self.signer)
        response = self.url_open('/sign/geoeid/submit/' + item.geoeid_token, data=b'no file here')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(item.geoeid_state, 'launched')
