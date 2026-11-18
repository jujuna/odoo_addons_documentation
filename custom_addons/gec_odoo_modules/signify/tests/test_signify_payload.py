import base64

from odoo.tests import Form, tagged
from odoo.tools import BinaryBytes

from .common import PDF, SignifyCommon


def _leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


@tagged('post_install', '-at_install')
class TestSignifyPayload(SignifyCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner'].with_context(no_vat_validation=True)

    def _payload(self, partner=None, **vals):
        """The set-document-details entry of one recipient line."""
        line = self._line(**vals)
        if partner:
            line['partner_id'] = partner.id
        return self._document(recipients=[line]).recipient_ids._signify_payload(1)

    def test_serial_order_numbers_follow_the_sequence(self):
        document = self._document(recipients=[
            self._line(sequence=30), self._line(sequence=10), self._line(sequence=20)])
        by_sequence = {recipient.sequence: recipient for recipient in document.recipient_ids}
        payload = document._signify_details_payload(42)
        self.assertEqual(
            [(item['recipientCode'], item['orderNumber']) for item in payload['recipients']],
            [(str(by_sequence[10].id), 1), (str(by_sequence[20].id), 2), (str(by_sequence[30].id), 3)],
        )

    def test_serial_payload_header(self):
        document = self._document()
        payload = document._signify_details_payload(42)
        self.assertEqual(payload['workflowType'], 'SERIAL')
        self.assertIs(payload['shareAutomatically'], False)
        self.assertEqual(payload['documentId'], 42)
        self.assertIsInstance(payload['documentId'], int)
        self.assertEqual(payload['recipients'][0]['recipientCode'], str(document.recipient_ids.id))

    def test_parallel_workflow_has_no_order_numbers(self):
        document = self._document(workflow_type='parallel', recipients=[self._line(), self._line()])
        payload = document._signify_details_payload(42)
        self.assertEqual(payload['workflowType'], 'PARALLEL')
        self.assertEqual(len(payload['recipients']), 2)
        for item in payload['recipients']:
            self.assertNotIn('orderNumber', item)

    def test_the_message_is_sent_when_set(self):
        document = self._document(message="Please sign today")
        payload = document._signify_details_payload(42)
        self.assertEqual(payload['additionalDetails']['messageForRecipients'], "Please sign today")

    def test_no_message_no_message_key(self):
        payload = self._document()._signify_details_payload(42)
        self.assertNotIn('messageForRecipients', payload['additionalDetails'])

    def test_reminders_follow_the_company_of_the_document(self):
        self.company_b.write({'signify_reminder_frequency': 'every2days', 'signify_reminder_max_count': 5})
        details_b = self._document(user=self.user_b)._signify_details_payload(42)['additionalDetails']
        self.assertEqual(details_b, {'remindersFrequencyType': 'EVERY2DAYS', 'remindersMaxCount': 5})
        details_a = self._document()._signify_details_payload(42)['additionalDetails']
        self.assertEqual(details_a, {'remindersFrequencyType': 'EVERYDAY', 'remindersMaxCount': 3})

    def test_never_sends_no_reminder_count(self):
        self.company.signify_reminder_frequency = 'never'
        details = self._document()._signify_details_payload(42)['additionalDetails']
        self.assertEqual(details, {'remindersFrequencyType': 'NEVER'})

    def test_recipient_identity_keys(self):
        document = self._document()
        payload = document.recipient_ids._signify_payload(1)
        self.assertEqual(payload['recipientCode'], str(document.recipient_ids.id))
        self.assertEqual(payload['name'], "Test Person")
        self.assertEqual(payload['email'], 'person@example.com')
        self.assertEqual(payload['role'], 'SIGNER')

    def test_signer_with_basic_email(self):
        payload = self._payload()
        self.assertEqual(payload['possibleSignatureTypes'], ['BASIC'])
        self.assertEqual(payload['recipientContactType'], 'EMAIL')
        self.assertEqual(payload['fields'], [{
            'type': 'SIGNATURE', 'autoPlacementText': 'Director', 'width': 150, 'height': 60}])

    def test_signer_without_keyword_has_no_fields(self):
        self.assertNotIn('fields', self._payload(placement_keyword=False))

    def test_sms_otp_by_mobile_sends_the_number_in_e164(self):
        payload = self._payload(auth_type='sms_otp', contact_type='mobile')
        self.assertEqual(payload['mobileNumber'], '+995599123456')
        self.assertEqual(payload['recipientContactType'], 'MOBILE')
        self.assertEqual(payload['possibleSignatureTypes'], ['SMS_OTP'])

    def test_a_number_that_cannot_be_formatted_is_sent_as_typed(self):
        partner = self.Partner.create({'name': "Odd Phone", 'email': 'odd@example.com', 'phone': 'not-a-number'})
        payload = self._payload(partner=partner, contact_type='mobile')
        self.assertEqual(payload['mobileNumber'], 'not-a-number')

    def test_qualified_id_card_sends_the_personal_number(self):
        payload = self._payload(auth_type='qualified', qualified_type='geo_id_card')
        self.assertEqual(payload['personalId'], '01010112312')
        self.assertEqual(payload['qualifiedSignatureType'], 'GEO_ID_CARD')
        self.assertEqual(payload['possibleSignatureTypes'], ['QUALIFIED'])

    def test_a_contact_person_does_not_send_the_company_code_as_personal_number(self):
        """A contact inherits the 9-digit company code: only an 11-digit number is sent as personalId."""
        self.assertEqual(self.contact.vat, '204567890')
        payload = self._payload(partner=self.contact, auth_type='qualified', qualified_type='geo_id_card')
        self.assertNotIn('personalId', payload)

    def test_the_personal_number_defaults_from_an_11_digit_tax_id(self):
        self.assertEqual(self._document().recipient_ids.personal_id, '01010112312')

    def test_the_personal_number_stays_empty_for_a_9_digit_tax_id(self):
        recipient = self._document(recipients=[self._line(partner_id=self.contact.id)]).recipient_ids
        self.assertFalse(recipient.personal_id)

    def test_a_typed_personal_number_is_sent(self):
        payload = self._payload(
            partner=self.contact, auth_type='qualified', qualified_type='geo_id_card', personal_id='01001012345')
        self.assertEqual(payload['personalId'], '01001012345')

    def test_a_basic_signer_does_not_send_the_personal_number(self):
        self.assertNotIn('personalId', self._payload(personal_id='01001012345'))

    def test_a_vat_with_the_country_prefix_is_stripped(self):
        partner = self.Partner.create({'name': "Prefixed", 'email': 'prefixed@example.com', 'vat': 'GE01010112312'})
        self.assertEqual(partner.vat, 'GE01010112312')
        payload = self._payload(partner=partner, auth_type='qualified', qualified_type='geo_id_card')
        self.assertEqual(payload['personalId'], '01010112312')

    def test_company_stamp_sends_the_tax_code_of_the_commercial_partner(self):
        payload = self._payload(partner=self.contact, auth_type='qualified', qualified_type='geo_stamp')
        self.assertEqual(payload['taxCode'], '204567890')
        self.assertEqual(payload['qualifiedSignatureType'], 'GEO_STAMP')
        self.assertNotIn('personalId', payload)

    def test_company_stamp_without_a_company_vat_has_no_tax_code(self):
        partner = self.Partner.create({'name': "No Vat", 'email': 'novat@example.com'})
        payload = self._payload(partner=partner, auth_type='qualified', qualified_type='geo_stamp')
        self.assertNotIn('taxCode', payload)

    def test_remote_id_sends_the_personal_number(self):
        """Remote ID identifies the person: an 11-digit vat is sent as personalId."""
        payload = self._payload(auth_type='remote_id')
        self.assertEqual(payload['possibleSignatureTypes'], ['REMOTE_ID'])
        self.assertEqual(payload['personalId'], '01010112312')

    def test_remote_id_without_a_vat_has_no_personal_number(self):
        partner = self.Partner.create({'name': "No Vat", 'email': 'novat@example.com'})
        self.assertNotIn('personalId', self._payload(partner=partner, auth_type='remote_id'))

    def test_approver_with_remote_id_sends_the_personal_number(self):
        """An approver using Remote ID is identified the same way as a signer."""
        payload = self._payload(role='approver', auth_type='remote_id')
        self.assertEqual(payload['possibleApprovalTypes'], ['REMOTE_ID'])
        self.assertEqual(payload['personalId'], '01010112312')

    def test_approver_has_approval_types_and_no_signature_part(self):
        payload = self._payload(role='approver')
        self.assertEqual(payload['role'], 'APPROVER')
        self.assertEqual(payload['possibleApprovalTypes'], ['BASIC'])
        self.assertNotIn('possibleSignatureTypes', payload)
        self.assertNotIn('fields', payload)

    def test_receive_signed_copy_has_no_signing_keys(self):
        payload = self._payload(role='receive_signed_copy')
        self.assertEqual(payload['role'], 'RECEIVE_SIGNED_COPY')
        for key in ('fields', 'possibleSignatureTypes', 'possibleApprovalTypes'):
            self.assertNotIn(key, payload)

    def test_auto_signer_sends_the_auto_sign_type_and_a_signature_field(self):
        for auto_sign_type, expected in (('company_seal', 'COMPANY_SEAL'), ('geo_qualified', 'GEO_QUALIFIED')):
            with self.subTest(auto_sign_type=auto_sign_type):
                payload = self._payload(role='auto_signer', auto_sign_type=auto_sign_type)
                self.assertEqual(payload['autoSignType'], expected)
                self.assertEqual(payload['fields'][0]['type'], 'SIGNATURE')
                self.assertEqual(payload['fields'][0]['autoPlacementText'], 'Director')
                self.assertNotIn('possibleSignatureTypes', payload)

    def test_link_contact_type(self):
        self.assertEqual(self._payload(contact_type='link')['recipientContactType'], 'LINK')

    def test_a_new_link_line_in_the_form_gets_the_sms_code_method(self):
        form = Form(self.env['signify.document'].with_user(self.user))
        form.name = "Form contract"
        form.file = BinaryBytes(PDF)
        with form.recipient_ids.new() as line:
            line.partner_id = self.person
            self.assertEqual(line.auth_type, 'basic')
            line.contact_type = 'link'
            self.assertEqual(line.auth_type, 'sms_otp')
        self.assertEqual(form.save().recipient_ids.auth_type, 'sms_otp')

    def test_switching_a_line_to_link_keeps_a_method_other_than_basic(self):
        for auth_type, extra in (('qualified', {'qualified_type': 'geo_id_card'}), ('sign_pad', {})):
            with self.subTest(auth_type=auth_type):
                line = self._document(recipients=[self._line(auth_type=auth_type, **extra)]).recipient_ids
                line.contact_type = 'link'
                self.assertEqual(line.auth_type, auth_type)

    def test_switching_a_basic_line_to_link_gets_the_sms_code_method(self):
        line = self._document().recipient_ids
        line.contact_type = 'link'
        self.assertEqual(line.auth_type, 'sms_otp')

    def test_a_line_created_on_link_with_basic_keeps_basic(self):
        line = self._document(recipients=[self._line(contact_type='link', auth_type='basic')]).recipient_ids
        self.assertEqual((line.contact_type, line.auth_type), ('link', 'basic'))

    def test_changing_other_fields_does_not_recompute_the_method_of_a_line(self):
        line = self._document(recipients=[self._line(contact_type='link', auth_type='basic')]).recipient_ids
        line.write({'role': 'approver', 'placement_keyword': 'Manager', 'sequence': 20})
        self.assertEqual(line.auth_type, 'basic')

    def test_no_value_is_none_or_empty(self):
        """A partner without email and phone."""
        partner = self.Partner.create({'name': "Bare Partner"})
        document = self._document(recipients=[self._line(partner_id=partner.id, placement_keyword=False)])
        payload = document._signify_details_payload(42)
        self.assertNotIn(None, list(_leaves(payload)))
        self.assertNotIn('', list(_leaves(payload)))
        self.assertNotIn('email', payload['recipients'][0])
        self.assertNotIn('mobileNumber', payload['recipients'][0])

    def test_create_document_sends_name_extension_and_content(self):
        document = self._document()
        with self._signify(self._send_handlers()) as post:
            document.action_send()
        self.assertEqual(self._sent(post, 'create-document'), [{
            'documentName': 'contract',
            'extension': 'pdf',
            'fileBase64': base64.b64encode(PDF).decode(),
        }])

    def test_create_document_lowercases_the_extension(self):
        document = self._document(file_name='offer.DOCX')
        with self._signify(self._send_handlers()) as post:
            document.action_send()
        sent = self._sent(post, 'create-document')[0]
        self.assertEqual(sent['extension'], 'docx')
        self.assertEqual(sent['documentName'], 'offer')

    def test_hidden_values_of_other_roles_and_types_do_not_leak(self):
        cases = [
            {'role': 'receive_signed_copy', 'auth_type': 'qualified', 'qualified_type': 'geo_id_card'},
            {'role': 'approver', 'auth_type': 'qualified', 'qualified_type': 'geo_id_card'},
            {'role': 'signer', 'auth_type': 'basic', 'qualified_type': 'geo_id_card'},
        ]
        for vals in cases:
            with self.subTest(**vals):
                payload = self._payload(**vals)
                self.assertNotIn('personalId', payload)
                self.assertNotIn('qualifiedSignatureType', payload)
