from datetime import timedelta
import hashlib
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.id_ge_sign.tools.cms import CmsVerificationError

from .common import COMMON_NAME, PERSONAL_NUMBER, GeoeidCommon, certificate_pem
from .test_pdf_update import increment, numbers


@tagged('post_install', '-at_install')
class TestSubmit(GeoeidCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env['ir.config_parameter'].sudo()

    def submit(self, item, signed):
        return item.sudo()._geoeid_submit_document(signed)

    def signed_item(self, partner=None):
        item = self.launched_item(partner or self.signer)
        return item, self.card_sign(item)[1]

    def assertRefused(self, item, pdf, message=''):
        with self.assertRaisesRegex(CmsVerificationError, message):
            self.submit(item, pdf)
        self.assertNotEqual(item.geoeid_state, 'signed')
        self.assertFalse(item.geoeid_cert_personal_number)
        self.assertFalse(item.sign_request_id._get_completed_documents())

    def test_submit_completes_the_item_and_the_request(self):
        item, signed = self.signed_item()
        self.submit(item, signed)
        request = item.sign_request_id
        self.assertEqual(item.state, 'completed')
        self.assertEqual(request.state, 'signed')
        self.assertEqual(bytes(request._get_completed_documents().file), signed)

    def test_submit_stores_the_certificate_identity(self):
        item, signed = self.signed_item()
        token, expiry = item.geoeid_token, item.geoeid_token_expiry
        self.submit(item, signed)
        self.assertRecordValues(item, [{
            'geoeid_state': 'signed',
            'geoeid_cert_personal_number': PERSONAL_NUMBER,
            'geoeid_cert_common_name': COMMON_NAME,
            'geoeid_cert_subject': self.card_cert.subject.rfc4514_string(),
            'geoeid_cert_serial': format(self.card_cert.serial_number, 'x'),
            'geoeid_cert_not_after': self.card_cert.not_valid_after_utc.date(),
            'geoeid_cert_trusted': True,
            'geoeid_token': token,
            'geoeid_token_expiry': expiry,
            'geoeid_signed_digest': hashlib.sha256(signed).hexdigest(),
            'geoeid_error': False,
        }])
        self.assertTrue(item.geoeid_signed_on)

    def test_submit_posts_a_chatter_message(self):
        item, signed = self.signed_item()
        self.submit(item, signed)
        messages = item.sign_request_id.message_ids.filtered(lambda message: 'Georgian ID Card' in message.body)
        self.assertEqual(len(messages), 1)
        self.assertIn(PERSONAL_NUMBER, messages.body)

    def test_certificate_of_completion_lists_the_card_signature(self):
        item, signed = self.signed_item()
        self.submit(item, signed)
        report = b''.join(
            bytes(attachment.raw) for attachment in item.sign_request_id.completed_document_attachment_ids
            if 'ertificate' in attachment.name)
        self.assertIn(b'Georgian ID Card Signatures', report)
        self.assertIn(PERSONAL_NUMBER.encode(), report)

    def test_resubmit_after_success_changes_nothing(self):
        item, signed = self.signed_item()
        self.submit(item, signed)
        signed_on = item.geoeid_signed_on
        completed = bytes(item.sign_request_id._get_completed_documents().file)
        self.assertIsNone(self.submit(item, signed))
        self.assertEqual(item.geoeid_signed_on, signed_on)
        self.assertEqual(bytes(item.sign_request_id._get_completed_documents().file), completed)

    def test_resubmit_with_different_bytes_does_not_downgrade_a_signed_item(self):
        item, signed = self.signed_item()
        token, expiry = item.geoeid_token, item.geoeid_token_expiry
        self.submit(item, signed)
        try:
            item._geoeid_submit_document(signed + b'\n', expected_token=token)
        except CmsVerificationError as exc:
            item._geoeid_fail(str(exc), expected_token=token)
        else:
            self.fail('A different upload must not acknowledge the completed attempt')
        self.assertEqual((item.geoeid_state, item.state), ('signed', 'completed'))
        self.assertEqual((item.geoeid_token, item.geoeid_token_expiry), (token, expiry))
        self.assertEqual(bytes(item.sign_request_id._get_completed_documents().file), signed)

    def test_replaced_and_expired_tokens_are_rechecked_before_submission(self):
        item, signed = self.signed_item()
        old_token = item.geoeid_token
        self.launch(item)
        with self.assertRaises(CmsVerificationError):
            item._geoeid_submit_document(signed, expected_token=old_token)
        self.assertEqual(item.geoeid_state, 'launched')
        item.geoeid_token_expiry = fields.Datetime.now() - timedelta(seconds=1)
        with self.assertRaises(CmsVerificationError):
            item._geoeid_submit_document(signed, expected_token=item.geoeid_token)

    def test_signature_increment_over_the_configured_limit_is_refused(self):
        self.params.set_int('id_ge_sign.max_signature_increment', 1)
        item, signed = self.signed_item()
        self.assertRefused(item, signed)

    def test_completion_user_error_rolls_back_the_certificate_and_document(self):
        item, signed = self.signed_item()
        Item = self.env.registry['sign.request.item']
        with patch.object(Item, '_apply_external_signatures', side_effect=UserError('Fail')):
            try:
                self.submit(item, signed)
            except UserError:
                pass
            else:
                self.fail('The completion error must propagate')
        self.env.invalidate_all()
        self.assertEqual((item.geoeid_state, item.state), ('launched', 'sent'))
        self.assertFalse(item.geoeid_signed_digest or item.geoeid_cert_subject)
        self.assertEqual(item.sign_request_id.request_document_ids.state, 'awaiting_signature')

    def test_previous_signers_pdf_cannot_complete_an_optional_second_signer(self):
        second_partner = self.make_partner('Second', email='second@example.com')
        template = self.make_template([self.card_role_1, self.card_role_2])
        template.sign_item_ids.filtered(lambda field: field.responsible_id == self.card_role_2).required = False
        request = self.make_request([(self.signer, self.card_role_1), (second_partner, self.card_role_2)], template)
        first, second = request.request_item_ids.sorted('mail_sent_order')
        self.launch(first)
        first_signed = self.card_sign(first)[1]
        self.submit(first, first_signed)
        second.sudo()._sign_externally({})
        frozen = bytes(second._get_documents_awaiting_external_signature().frozen_file)
        self.assertEqual(frozen, first_signed)
        for suffix in (b'', b'\n '):
            with self.subTest(suffix=suffix), self.assertRaises(CmsVerificationError):
                self.submit(second, frozen + suffix)
        self.assertEqual((second.state, second.geoeid_state, request.state), ('sent', 'launched', 'sent'))
        self.assertFalse(second.geoeid_cert_personal_number)

    def test_refused_when_the_session_was_not_launched(self):
        item = self.card_item(self.signer)
        self.assertRefused(item, self.pdf_raw)
        self.assertEqual(item.state, 'sent')

    def test_refused_when_the_request_validity_passed(self):
        item, signed = self.signed_item()
        item.sign_request_id.validity = fields.Date.today() - timedelta(days=2)
        self.assertRefused(item, signed)

    def test_refused_when_the_request_is_canceled(self):
        item, signed = self.signed_item()
        item.sign_request_id.cancel()
        self.assertRefused(item, signed)

    def test_refused_after_the_document_was_released(self):
        item, signed = self.signed_item()
        item._geoeid_cancel()
        self.assertRefused(item, signed)

    def test_refused_for_an_empty_pdf(self):
        item = self.launched_item(self.signer)
        self.assertRefused(item, b'')

    def test_a_card_signed_document_changed_after_freezing_is_refused(self):
        item = self.launched_item(self.signer)
        frozen = bytes(item._get_documents_awaiting_external_signature().frozen_file)
        was = numbers(frozen)
        tampered = increment(frozen, {was.content_id: b'<< /Length 2 >>\nstream\nq\nendstream'}, was.root_id)
        self.assertRefused(item, self.card_sign(item, pdf=tampered)[1], 'beyond adding one signature')

    def test_refused_when_the_pdf_does_not_extend_the_frozen_bytes(self):
        item = self.launched_item(self.signer)
        __, other = self.card_sign(item, pdf=self.pdf_raw)
        self.assertRefused(item, other)

    def test_submit_without_a_trust_anchor_is_refused(self):
        item, signed = self.signed_item()
        self.params.search([('key', '=', 'id_ge_sign.trust_anchor')]).unlink()
        self.assertRefused(item, signed)

    def test_submit_with_the_card_as_anchor_is_accepted(self):
        item, signed = self.signed_item()
        self.submit(item, signed)
        self.assertEqual(item.state, 'completed')
        self.assertTrue(item.geoeid_cert_trusted)

    def test_failed_completion_rolls_everything_back(self):
        placeholder = self.placeholder('ghost@id-card.invalid')
        item, signed = self.signed_item(placeholder)
        request = item.sign_request_id
        messages = request.message_ids
        with patch.object(self.env.registry['sign.request.item'], '_apply_external_signatures', lambda *args: None):
            try:
                self.submit(item, signed)
            except CmsVerificationError as exc:
                item._geoeid_fail(str(exc))
            else:
                self.fail("The submission must be refused when the signature could not be added")
        self.env.invalidate_all()
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

    def test_signer_linked_to_a_user_completes_too(self):
        user = new_test_user(self.env, login='geoeid_user', groups='base.group_user')
        item, signed = self.signed_item(user.partner_id)
        self.submit(item, signed)
        self.assertEqual(item.state, 'completed')
        self.assertEqual(item.sign_request_id.state, 'signed')

    def test_two_card_signers_sign_one_after_the_other(self):
        second_company, second_cert = self.make_card('NINO TESTADZE', 'PNOGE-01001000009')
        self.params.set_str('id_ge_sign.trust_anchor', self.card_pem + certificate_pem(second_cert))
        second_partner = self.make_partner('Nino', email='nino@example.com')
        request = self.make_request([(self.signer, self.card_role_1), (second_partner, self.card_role_2)])
        first, second = request.request_item_ids.sorted('mail_sent_order')
        self.launch(first)
        __, first_signed = self.card_sign(first)
        self.submit(first, first_signed)
        self.assertEqual((first.state, second.state, request.state), ('completed', 'sent', 'sent'))
        self.launch(second)
        frozen, second_signed = self.card_sign(second, second_company)
        self.assertTrue(frozen.startswith(first_signed))
        self.submit(second, second_signed)
        self.assertEqual(request.state, 'signed')
        self.assertEqual(second.geoeid_cert_personal_number, '01001000009')
