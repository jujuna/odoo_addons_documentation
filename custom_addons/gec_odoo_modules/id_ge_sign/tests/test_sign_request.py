from odoo.addons.mail.tests.common import MockEmail
from odoo.tests import tagged

from .common import GeoeidCommon


@tagged('post_install', '-at_install')
class TestSignRequestMail(GeoeidCommon, MockEmail):

    def completed_mails(self, request, partner, signers):
        with self.mock_mail_gateway():
            request._send_completed_documents_message(signers, False, partner, force_send=True)
        return self._new_mails

    def test_completed_documents_mail_is_not_sent_to_a_placeholder(self):
        request = self.make_request([(self.signer, self.card_role_1)])
        partner = self.placeholder('holder@id-card.invalid')
        self.assertFalse(self.completed_mails(request, partner, []))
        self.assertFalse(self._mails)

    def test_completed_documents_mail_is_sent_to_a_regular_partner(self):
        request = self.make_request([(self.signer, self.card_role_1)])
        mails = self.completed_mails(request, self.signer, [])
        self.assertEqual(len(mails), 1)
        self.assertIn(self.signer.email, mails.email_to)

    def test_completed_documents_mail_hides_the_placeholder_email(self):
        request = self.make_request([(self.signer, self.card_role_1)])
        placeholder = self.placeholder('holder@id-card.invalid')
        reader = self.make_partner('Reader', email='reader@example.com')
        signers = [
            {'name': self.signer.name, 'email': self.signer.email, 'id': self.signer.id},
            {'name': placeholder.name, 'email': placeholder.email, 'id': placeholder.id},
        ]
        body = self.completed_mails(request, reader, signers).body_html
        self.assertIn(self.signer.email, body)
        self.assertIn(placeholder.name, body)
        self.assertNotIn('id-card.invalid', body)

    def test_placeholder_address_is_not_listed_as_a_final_recipient(self):
        holder = self.placeholder('holder@id-card.invalid')
        request = self.make_request([(holder, self.card_role_1)])
        request.cc_partner_ids = self.signer
        self.assertEqual(request._get_final_recipients(), {self.signer.email})

    def test_reminder_and_refusal_do_not_mail_placeholder_addresses(self):
        holder = self.placeholder('holder@id-card.invalid')
        request = self.make_request([(holder, self.card_role_1)])
        item = request.request_item_ids
        with self.mock_mail_gateway():
            item._send_signature_access_message()
            request._send_refused_message(holder, 'Declined', holder, force_send=True, sign_request_item=item)
        self.assertFalse(self._new_mails)
        self.assertFalse(self._mails)

    def test_actual_signer_address_controls_placeholder_mail_filter(self):
        request = self.make_request([(self.signer, self.card_role_1)])
        item = request.request_item_ids
        item.signer_email = 'alternate@id-card.invalid'
        with self.mock_mail_gateway():
            item._send_signature_access_message()
            request._send_refused_message(self.signer, 'Declined', self.signer, sign_request_item=item)
            request._send_completed_documents_message([], False, self.signer, sign_request_item=item)
        self.assertFalse(self._new_mails)
        self.assertFalse(self._mails)
