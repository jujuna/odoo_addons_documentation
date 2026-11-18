import hashlib
import hmac
import json
from urllib.parse import urlparse

from odoo.addons.gec_gosms.tests.common import PHONE_A, GosmsCommon
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

SECRET = 'webhook-secret'
CUSTOMER_PHONE = '+995555987654'


@tagged('post_install', '-at_install')
class TestGosmsWebhook(GosmsCommon, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a.gosms_webhook_secret = SECRET

    def _signature(self, body, secret=SECRET):
        return f"t=1700000000,v1={hmac.digest(secret.encode(), b'1700000000.' + body, hashlib.sha256).hex()}"

    def _webhook(self, payload, company=None, secret=SECRET, token=None, headers=None, url=None):
        body = json.dumps(payload).encode()
        if headers is None:
            headers = {**({'X-Webhook-Signature': self._signature(body, secret)} if secret else {}), **({'X-Webhook-Token': token} if token else {})}
        url = url or f'/gosms/webhook/{(company or self.company_a).id}'
        response = self.url_open(url, data=body, headers={'Content-Type': 'application/json', **headers})
        self.env.invalidate_all()
        return response

    def _delivery(self, status, message_id=501):
        return {'eventId': 'e1', 'event': 'delivery_status', 'messageId': message_id, 'status': status, 'to': '995555123456'}

    def _inbound(self, event_id='in-1', text="Yes, please"):
        return {'eventId': event_id, 'event': 'inbound', 'from': '995555987654', 'to': '995322123456', 'text': text}

    def _sent_to_partner(self):
        partner = self.env['res.partner'].create({'name': 'Nino', 'phone': PHONE_A})
        partner._message_sms("Hi", partner_ids=partner.ids)
        return partner.message_ids[:1].notification_ids

    @mute_logger('odoo.addons.gec_gosms.controllers.main')
    def test_wrong_signature_is_refused(self):
        notification = self._sent_to_partner()
        self.assertEqual(self._webhook(self._delivery('DELIVERED'), secret='other').status_code, 404)
        self.assertEqual(notification.notification_status, 'pending')
        self.assertEqual(self.env['gosms.message'].search([]).state, 'sent')

    @mute_logger('odoo.addons.gec_gosms.controllers.main')
    def test_missing_signature_is_refused(self):
        self.assertEqual(self._webhook(self._inbound(), headers={}).status_code, 404)
        self.assertFalse(self.env['gosms.message'].search([('direction', '=', 'inbound')]))

    @mute_logger('odoo.addons.gec_gosms.controllers.main')
    def test_company_without_secret_is_refused(self):
        self.assertEqual(self._webhook(self._inbound(), company=self.company_b).status_code, 404)

    @mute_logger('odoo.addons.gec_gosms.controllers.main')
    def test_unknown_company_is_refused(self):
        body = json.dumps(self._inbound()).encode()
        response = self.url_open('/gosms/webhook/999999', data=body, headers={'X-Webhook-Signature': self._signature(body)})
        self.assertEqual(response.status_code, 404)

    @mute_logger('odoo.addons.gec_gosms.controllers.main')
    def test_unreadable_body_is_refused(self):
        for body in (b'{not json', b'{}', b'[]'):
            response = self.url_open(f'/gosms/webhook/{self.company_a.id}', data=body, headers={'X-Webhook-Signature': self._signature(body)})
            self.assertEqual(response.status_code, 400, body)
        self.assertFalse(self.env['gosms.message'].search([('direction', '=', 'inbound')]))

    def test_delivered_updates_log_and_chatter(self):
        notification = self._sent_to_partner()
        response = self._webhook(self._delivery('DELIVERED'))
        self.assertEqual((response.status_code, response.text), (200, 'OK'))
        self.assertEqual(self.env['gosms.message'].search([]).state, 'delivered')
        self.assertEqual(notification.notification_status, 'sent')

    def test_expired_marks_notification_failed(self):
        notification = self._sent_to_partner()
        self._webhook(self._delivery('EXPIRED'))
        self.assertEqual(self.env['gosms.message'].search([]).state, 'expired')
        self.assertEqual((notification.notification_status, notification.failure_type), ('exception', 'sms_expired'))

    def test_unknown_message_id_is_acknowledged(self):
        response = self._webhook(self._delivery('DELIVERED', message_id=424242))
        self.assertEqual((response.status_code, response.text), (200, 'OK'))

    def test_inbound_is_posted_on_the_matching_contact(self):
        partner = self.env['res.partner'].create({'name': 'Customer', 'phone': CUSTOMER_PHONE})
        self._webhook(self._inbound())
        self.assertRecordValues(self.env['gosms.message'].search([]), [{
            'company_id': self.company_a.id,
            'direction': 'inbound',
            'number': CUSTOMER_PHONE,
            'partner_id': partner.id,
            'body': "Yes, please",
            'state': 'received',
            'event_id': 'in-1',
        }])
        message = partner.message_ids[:1]
        self.assertEqual((message.message_type, message.author_id, message.body), ('comment', partner, "<p>Yes, please</p>"))

    def test_same_event_twice_gives_one_row(self):
        self.env['res.partner'].create({'name': 'Customer', 'phone': CUSTOMER_PHONE})
        self._webhook(self._inbound())
        self._webhook(self._inbound())
        self.assertEqual(self.env['gosms.message'].search_count([('event_id', '=', 'in-1')]), 1)

    def test_two_contacts_with_the_same_phone_are_not_posted(self):
        partners = self.env['res.partner'].create([{'name': 'One', 'phone': CUSTOMER_PHONE}, {'name': 'Two', 'phone': CUSTOMER_PHONE}])
        messages = partners.message_ids
        self._webhook(self._inbound())
        self.assertFalse(self.env['gosms.message'].search([]).partner_id)
        self.assertEqual(partners.message_ids, messages)

    def test_inbound_text_is_escaped_in_the_chatter(self):
        partner = self.env['res.partner'].create({'name': 'Customer', 'phone': CUSTOMER_PHONE})
        self._webhook(self._inbound(text="<b>Hi</b>"))
        self.assertEqual(partner.message_ids[:1].body, "<p>&lt;b&gt;Hi&lt;/b&gt;</p>")

    def test_settings_address_is_the_live_route(self):
        path = urlparse(self.env['res.config.settings'].create({}).gosms_webhook_url).path
        self.assertEqual(self._webhook(self._inbound(), url=path).status_code, 200)

    def test_token_alone_is_enough(self):
        self.company_a.write({'gosms_webhook_secret': False, 'gosms_webhook_token': 'tok'})
        self.assertEqual(self._webhook(self._inbound(), secret=False, token='tok').status_code, 200)

    @mute_logger('odoo.addons.gec_gosms.controllers.main')
    def test_wrong_token_is_refused(self):
        self.company_a.write({'gosms_webhook_secret': False, 'gosms_webhook_token': 'tok'})
        self.assertEqual(self._webhook(self._inbound(), secret=False, token='other').status_code, 404)

    @mute_logger('odoo.addons.gec_gosms.controllers.main')
    def test_secret_and_token_must_both_match(self):
        self.company_a.gosms_webhook_token = 'tok'
        self.assertEqual(self._webhook(self._inbound()).status_code, 404)
        self.assertEqual(self._webhook(self._inbound(), token='tok').status_code, 200)

    def _sent_by_company_b(self, key):
        self.company_b.write({'gosms_api_key': key})
        self.answers['sendsms'] = {'success': True, 'messageId': 777}
        return self._send_sms([PHONE_A], record_company_id=self.company_b.id)

    def test_status_of_another_gosms_account_is_ignored(self):
        sms = self._sent_by_company_b('key-b')
        self._webhook(self._delivery('DELIVERED', message_id=777))
        self.assertEqual(self.env['gosms.message'].search([('sms_uuid', '=', sms.uuid)]).state, 'sent')

    def test_status_of_a_company_with_the_same_gosms_account_is_applied(self):
        sms = self._sent_by_company_b('key-a')
        self._webhook(self._delivery('DELIVERED', message_id=777))
        self.assertEqual(self.env['gosms.message'].search([('sms_uuid', '=', sms.uuid)]).state, 'delivered')

    def test_inbound_on_a_shared_contact_is_posted_for_the_url_company(self):
        self.company_b.gosms_webhook_secret = SECRET
        partner = self.env['res.partner'].create({'name': 'Customer', 'phone': CUSTOMER_PHONE})
        self._webhook(self._inbound(), company=self.company_b)
        self.assertEqual(partner.message_ids[:1].record_company_id, self.company_b)
