# Part of Odoo. See LICENSE file for full copyright and licensing details.

from lxml import html

from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPlanningFieldServicePortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = new_test_user(cls.env, login='field_service_customer', groups='base.group_portal')
        cls.intervention = cls.env['planning.slot'].create({
            'name': 'Customer intervention',
            'partner_id': cls.portal_user.partner_id.id,
            'start_datetime': '2026-02-23 08:00:00',
            'end_datetime': '2026-02-23 12:00:00',
            'state': '4_completed',
        })
        cls.intervention.message_subscribe(partner_ids=cls.portal_user.partner_id.ids)

    def _get_portal_chatter_params(self):
        response = self.url_open(self.intervention.get_portal_url())
        response.raise_for_status()
        chatter = html.fromstring(response.content).get_element_by_id('discussion')
        return {
            'thread_model': chatter.get('data-res_model'),
            'thread_id': int(chatter.get('data-res_id')),
            'token': chatter.get('data-token'),
        }

    def test_portal_chatter_fetch_messages(self):
        message = self.intervention.message_post(
            body='The intervention is complete.',
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            attachments=[('report.txt', b'Intervention report')],
        )
        note = self.intervention.message_post(
            body='Internal note.', message_type='comment', subtype_xmlid='mail.mt_note',
        )
        self.assertFalse(self.intervention.with_user(self.portal_user).has_access('read'))

        for login in (self.portal_user.login, None):
            with self.subTest(login=login):
                self.authenticate(login, login)
                params = self._get_portal_chatter_params()
                params['access_params'] = {'token': params.pop('token')}
                data = self.make_jsonrpc_request('/mail/store', {
                    'fetch_params': [['/mail/chatter_fetch', params]],
                })
                message_ids = [message['id'] for message in data.get('mail.message', [])]
                self.assertIn(message.id, message_ids)
                self.assertNotIn(note.id, message_ids)
                fetched_message = next(item for item in data['mail.message'] if item['id'] == message.id)
                attachment_ids = [attachment['id'] for attachment in fetched_message['attachment_ids']]
                self.assertIn(message.attachment_ids.id, attachment_ids)

    def test_portal_chatter_post_message(self):
        for login in (self.portal_user.login, None):
            with self.subTest(login=login):
                self.authenticate(login, login)
                params = self._get_portal_chatter_params()
                result = self.make_jsonrpc_request('/mail/message/post', {
                    **params,
                    'post_data': {'body': 'Thank you for the intervention.'},
                })
                message = self.env['mail.message'].browse(result['message_id'])
                self.assertEqual(message.model, self.intervention._name)
                self.assertEqual(message.res_id, self.intervention.id)
                self.assertEqual(message.author_id, self.portal_user.partner_id)
                self.assertEqual(message.subtype_id, self.env.ref('mail.mt_comment'))
                self.assertIn('Thank you for the intervention.', message.body)
