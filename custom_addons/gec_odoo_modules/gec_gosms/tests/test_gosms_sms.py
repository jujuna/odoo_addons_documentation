from unittest.mock import patch

import requests

from odoo.addons.gec_gosms.tools.sms_api import GOSMS_ERRORS
from odoo.addons.sms.tools.sms_api import SmsApi
from odoo.addons.gec_gosms.tests.common import PHONE_A, PHONE_B, GosmsCommon
from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestGosmsSms(GosmsCommon):

    def test_one_alert_number_is_sent_with_sendsms(self):
        sms = self._send_sms([PHONE_A])
        self.assertEqual(self._payloads('sendsms'), [{'api_key': 'key-a', 'from': 'SENDER-A', 'to': '995555123456', 'text': "Hello"}])
        self.assertEqual((sms.state, sms.to_delete), ('pending', True))

    def test_sent_sms_is_logged(self):
        partner = self.env['res.partner'].create({'name': 'Nino'})
        sms = self._send_sms([PHONE_A], partner_id=partner.id)
        self.assertRecordValues(self._log(sms), [{
            'company_id': self.company_a.id,
            'direction': 'outgoing',
            'number': PHONE_A,
            'partner_id': partner.id,
            'body': "Hello",
            'state': 'sent',
            'gosms_id': '501',
            'failure_reason': False,
        }])

    def test_several_numbers_are_sent_with_one_sendbulk(self):
        sms = self._send_sms([PHONE_A, PHONE_B])
        self.assertEqual(self._payloads('sendbulk'), [{
            'api_key': 'key-a',
            'from': 'SENDER-A',
            'to': ['995555123456', '995599000000'],
            'text': "Hello",
        }])
        self.assertFalse(self._payloads('sendsms'))
        self.assertEqual(sms.mapped('state'), ['pending', 'pending'])
        self.assertEqual(self._log(sms).mapped('gosms_id'), ['600', '601'])

    def test_marketing_sms_goes_bulk_with_opt_out_number(self):
        self.company_a.gosms_nosms_number = '900100'
        sms = self._send_sms([PHONE_A], sms_type='marketing')
        self.assertEqual(self._payloads('sendbulk'), [{
            'api_key': 'key-a',
            'from': 'SENDER-A',
            'to': ['995555123456'],
            'text': "Hello",
            'noSmsNumber': '900100',
        }])
        self.assertEqual(sms.state, 'pending')

    def test_no_credit_marks_sms_as_credit_failure(self):
        self.answers['sendsms'] = {'success': False, 'errorCode': 102, 'message': 'No balance'}
        with patch.object(type(self.env['iap.account']), '_send_no_credit_notification') as notify:
            sms = self._send_sms([PHONE_A])
        notify.assert_not_called()
        self.assertEqual((sms.state, sms.failure_type), ('error', 'sms_credit'))
        self.assertEqual(self._log(sms).failure_reason, str(GOSMS_ERRORS[102]))

    def test_unregistered_sender_is_unknown_failure_with_reason(self):
        self.answers['sendsms'] = {'success': False, 'errorCode': 101, 'message': 'Invalid from'}
        sms = self._send_sms([PHONE_A])
        self.assertEqual((sms.state, sms.failure_type), ('error', 'unknown'))
        log = self._log(sms)
        self.assertEqual((log.state, log.failure_reason), ('error', str(GOSMS_ERRORS[101])))

    def test_error_without_code_uses_gosms_message(self):
        self.answers['sendsms'] = {'statusCode': 500, 'message': 'Internal server error'}
        sms = self._send_sms([PHONE_A])
        self.assertEqual((sms.failure_type, self._log(sms).failure_reason), ('unknown', 'Internal server error'))

    def test_no_sender_sends_nothing(self):
        self.company_a.gosms_sender = False
        sms = self._send_sms([PHONE_A])
        self.assertFalse(self.sent)
        self.assertEqual(sms.state, 'error')
        self.assertEqual(self._log(sms).failure_reason, "Add the GoSMS sender name in Settings first.")

    def test_unformattable_number_sends_nothing(self):
        sms = self._send_sms(['123'])
        self.assertFalse(self.sent)
        self.assertEqual((sms.state, sms.failure_type), ('error', 'sms_number_format'))

    def test_empty_number_does_not_reach_company_phone(self):
        self.company_a.phone = PHONE_A
        sms = self._send_sms([False])
        self.assertFalse(self.sent)
        self.assertEqual(sms.state, 'error')

    def test_network_error_keeps_the_other_text_sent(self):
        self.answers['sendsms'] = [{'success': True, 'messageId': 701}, requests.ConnectionError()]
        first = self.env['sms.sms'].create({'number': PHONE_A, 'body': "First"})
        second = self.env['sms.sms'].create({'number': PHONE_A, 'body': "Second"})
        with mute_logger('odoo.addons.gec_gosms.models.res_company'):
            (first | second).send()
        self.assertEqual((first.state, second.state, second.failure_type), ('pending', 'error', 'sms_server'))
        self.assertEqual(self._log(second).failure_reason, "GoSMS could not be reached. Try again in a minute.")

    def test_number_missing_from_bulk_answer_is_server_error(self):
        self.answers['sendbulk'] = {'success': True, 'messages': [{'messageId': 800, 'to': '995555123456', 'success': True}]}
        sms = self._send_sms([PHONE_A, PHONE_B])
        self.assertEqual((sms[0].state, sms[1].state, sms[1].failure_type), ('pending', 'error', 'sms_server'))
        self.assertEqual(self._log(sms[1]).state, 'error')

    def test_bulk_number_refused_by_gosms(self):
        self.answers['sendbulk'] = {'success': True, 'messages': [
            {'messageId': 800, 'to': '995555123456', 'success': True},
            {'messageId': 0, 'to': '995599000000', 'success': False, 'error': 'Invalid phone number format'},
        ]}
        sms = self._send_sms([PHONE_A, PHONE_B])
        self.assertEqual((sms[0].state, sms[1].state, sms[1].failure_type), ('pending', 'error', 'unknown'))
        self.assertEqual(self._log(sms[1]).failure_reason, 'Invalid phone number format')

    def test_sms_of_another_company_uses_its_own_key(self):
        sms = self._send_sms([PHONE_A], record_company_id=self.company_b.id)
        self.assertEqual(self._payloads('sendsms'), [{'api_key': 'key-b', 'from': 'SENDER-B', 'to': '995555123456', 'text': "Hello"}])
        self.assertEqual(self._log(sms).company_id, self.company_b)

    def test_contact_of_another_company_is_logged(self):
        partner = self.env['res.partner'].create({'name': 'Gela', 'company_id': self.company_b.id})
        sms = self._send_sms([PHONE_A], partner_id=partner.id)
        self.assertEqual(self._log(sms).partner_id, partner)

    def test_batch_size(self):
        sms = self.env['sms.sms']
        self.assertEqual(sms._get_send_batch_size(), 10)
        self.env['ir.config_parameter'].set_int('gec_gosms.session.batch.size', 3)
        self.assertEqual(sms._get_send_batch_size(), 3)
        (self.company_a | self.company_b).gosms_sms_enabled = False
        self.assertEqual(sms._get_send_batch_size(), 500)

    def test_other_company_keeps_core_provider(self):
        self.company_a.gosms_sms_enabled = False
        sms = self.env['sms.sms'].create({'number': PHONE_A, 'body': "Hello"})
        providers = [type(api).__name__ for api, _sms in sms._split_by_api()]
        self.assertEqual(providers, ['SmsApi'])

    def test_check_status_updates_message_and_notification(self):
        partner = self.env['res.partner'].create({'name': 'Nino', 'phone': PHONE_A})
        partner._message_sms("Hi", partner_ids=partner.ids)
        log = self.env['gosms.message'].search([('partner_id', '=', partner.id)])
        self.answers['checksms'] = {'success': True, 'status': 'DELIVERED'}
        action = log.action_check_status()
        self.assertEqual(action['params']['message'], "GoSMS status: DELIVERED.")
        self.assertEqual(self._payloads('checksms'), [{'api_key': 'key-a', 'messageId': 501}])
        self.assertEqual(log.state, 'delivered')
        self.assertEqual(partner.message_ids[:1].notification_ids.notification_status, 'sent')

    def test_administrator_can_check_status(self):
        sms = self._send_sms([PHONE_A])
        self.answers['checksms'] = {'success': True, 'status': 'EXPIRED'}
        admin = new_test_user(self.env, login='gosms_admin', groups='base.group_system')
        self._log(sms).with_user(admin).action_check_status()
        self.assertEqual(self._log(sms).state, 'expired')

    def test_register_sender_name(self):
        self.answers['sender'] = {'success': True}
        action = self.env['res.config.settings'].create({}).action_gosms_register_sender()
        self.assertEqual(self._payloads('sender'), [{'api_key': 'key-a', 'name': 'SENDER-A'}])
        self.assertEqual(action['params']['type'], 'success')

    def test_sender_already_registered(self):
        self.answers['sender'] = {'success': False, 'errorCode': 107, 'message': 'exists'}
        with self.assertRaisesRegex(UserError, "already exists"):
            self.env['res.config.settings'].create({}).action_gosms_register_sender()

    def test_send_screen_sends_typed_numbers_in_one_bulk(self):
        action = self._send_screen(f'{PHONE_A}, {PHONE_B}')
        self.assertEqual(self._payloads('sendbulk')[0]['to'], ['995555123456', '995599000000'])
        self.assertEqual(action['params']['message'], "2 of 2 SMS sent.")

    def _send_screen(self, numbers, **values):
        return self.env['gosms.send.wizard'].create({'numbers': numbers, 'body': "Hi all", **values}).action_send()

    def test_send_screen_refuses_when_gosms_is_off(self):
        self.company_a.gosms_sms_enabled = False
        with self.assertRaisesRegex(UserError, 'Turn on "Send Odoo SMS through GoSMS" in Settings first.'):
            self._send_screen(PHONE_A)
        self.assertFalse(self.sent)

    def test_send_screen_refuses_a_wrong_number(self):
        with self.assertRaisesRegex(UserError, "not correctly encoded"):
            self._send_screen('12')
        self.assertFalse(self.sent)

    def test_send_screen_warning_carries_the_first_reason(self):
        self.answers['sendbulk'] = {'success': True, 'messages': [
            {'messageId': 800, 'to': '995555123456', 'success': True},
            {'messageId': 0, 'to': '995599000000', 'success': False, 'error': 'Invalid phone number format'},
        ]}
        params = self._send_screen(f'{PHONE_A}, {PHONE_B}')['params']
        self.assertEqual((params['type'], params['message']), ('warning', "1 of 2 SMS sent. Invalid phone number format"))

    def test_send_screen_urgent_is_sent_as_urgent(self):
        self._send_screen(f'{PHONE_A}, {PHONE_B}', urgent=True)
        self.assertEqual(self._payloads('sendbulk')[0]['urgent'], True)

    def test_urgent_and_normal_recipients_of_one_text_use_separate_calls(self):
        normal, urgent = self.env['sms.sms'].create([
            {'number': PHONE_A, 'body': "Hi"},
            {'number': PHONE_B, 'body': "Hi", 'gosms_urgent': True},
        ])
        (normal | urgent).send()
        calls = [(payload['to'], payload.get('urgent')) for payload in self._payloads('sendsms')]
        self.assertEqual(calls, [('995555123456', None), ('995599000000', True)])
        self.assertEqual((normal.state, urgent.state), ('pending', 'pending'))

    def test_provider_call_marks_accepted_sms_pending(self):
        sms = self.env['sms.sms'].create([{'number': PHONE_A, 'body': "Hi"}, {'number': '123', 'body': "Hi"}])
        api = self.company_a._get_sms_api_class()(self.env)
        api._send_sms_batch([{'content': "Hi", 'numbers': [{'number': one.number, 'uuid': one.uuid} for one in sms]}])
        self.assertEqual(sms.mapped('state'), ['pending', 'error'])
        self.assertEqual(self._log(sms).mapped('state'), ['sent', 'error'])

    @mute_logger('odoo.addons.gec_gosms.models.res_company')
    def test_direct_call_with_timeout_is_not_sent_again_by_the_cron(self):
        sms = self.env['sms.sms'].create({'number': PHONE_A, 'body': "Hi"})
        self.post.side_effect = requests.ReadTimeout()
        self.company_a._get_sms_api_class()(self.env)._send_sms_batch([{'content': "Hi", 'numbers': [{'number': sms.number, 'uuid': sms.uuid}]}])
        self.assertEqual((sms.state, sms.failure_type), ('error', 'sms_server'))
        self.post.reset_mock()
        with patch.object(type(self.env['ir.cron']), '_commit_progress'):
            self.env['sms.sms']._process_queue()
        self.post.assert_not_called()

    def test_answer_without_message_id_is_server_error_and_keeps_the_earlier_text(self):
        self.answers['sendsms'] = [{'success': True, 'messageId': 701}, {'success': True}]
        first = self.env['sms.sms'].create({'number': PHONE_A, 'body': "First"})
        second = self.env['sms.sms'].create({'number': PHONE_A, 'body': "Second"})
        (first | second).send()
        self.assertEqual((first.state, second.state, second.failure_type), ('pending', 'error', 'sms_server'))
        self.assertEqual(self._log(second).failure_reason, "GoSMS did not confirm this message. Check it before sending again.")

    def test_bulk_answer_without_messages_is_server_error(self):
        self.answers['sendbulk'] = {'success': True}
        sms = self._send_sms([PHONE_A, PHONE_B])
        self.assertEqual(sms.mapped('state'), ['error', 'error'])

    def test_read_timeout_says_the_message_may_have_been_sent(self):
        self.post.side_effect = requests.ReadTimeout()
        with mute_logger('odoo.addons.gec_gosms.models.res_company'), self.assertRaisesRegex(UserError, "may have been sent"):
            self.company_a._gosms_call('sms-balance', {})

    def test_date_in_retry_after_header_is_ignored(self):
        self.headers['Retry-After'] = 'Wed, 21 Oct 2026 07:28:00 GMT'
        sms = self._send_sms([PHONE_A])
        self.assertEqual(sms.state, 'pending')

    def test_cron_sends_queued_sms(self):
        sms = self.env['sms.sms'].create({'number': PHONE_A, 'body': "Hello"})
        with patch.object(type(self.env['ir.cron']), '_commit_progress'):
            self.env['sms.sms']._process_queue()
        self.assertEqual(sms.state, 'pending')
        self.assertEqual(self._log(sms).state, 'sent')

    def test_cron_batch_size_when_only_another_company_has_gosms(self):
        self.company_a.gosms_sms_enabled = False
        self.assertEqual(self.env['sms.sms']._get_send_batch_size(), 10)

    def test_mass_composer_routes_each_contact_to_its_company(self):
        partner = self.env['res.partner'].create({'name': 'Gela', 'phone': PHONE_A, 'company_id': self.company_b.id})
        composer = self.env['sms.composer'].create({
            'composition_mode': 'mass',
            'res_model': 'res.partner',
            'res_ids': repr(partner.ids),
            'body': "Hello",
            'mass_force_send': True,
        })
        composer._action_send_sms()
        self.assertEqual(self._payloads('sendsms')[0]['api_key'], 'key-b')
        self.assertEqual(self._log(self.env['sms.sms'].search([('partner_id', '=', partner.id)])).company_id, self.company_b)

    def _mixed_batch(self, iap_state):
        company_c = self.env['res.company'].create({'name': "IAP Company", 'country_id': self.env.ref('base.ge').id})
        gosms_sms = self.env['sms.sms'].create({'number': PHONE_A, 'body': "Hello", 'record_company_id': self.company_a.id})
        iap_sms = self.env['sms.sms'].create({'number': PHONE_A, 'body': "Hello", 'record_company_id': company_c.id})
        self.answers['sendsms'] = {'success': False, 'errorCode': 102, 'message': 'No balance'}
        iap_results = [{'uuid': iap_sms.uuid, 'state': iap_state}]
        with patch.object(SmsApi, '_send_sms_batch', return_value=iap_results), patch.object(
            type(self.env['iap.account']), '_send_no_credit_notification'
        ) as notify:
            (gosms_sms | iap_sms).send()
        return gosms_sms, iap_sms, notify

    def test_gosms_no_credit_does_not_open_the_odoo_credit_notice(self):
        gosms_sms, iap_sms, notify = self._mixed_batch('success')
        notify.assert_not_called()
        self.assertEqual((gosms_sms.failure_type, iap_sms.state), ('sms_credit', 'pending'))
        self.assertFalse(self._log(iap_sms))

    def test_odoo_no_credit_still_opens_the_odoo_credit_notice(self):
        _gosms_sms, _iap_sms, notify = self._mixed_batch('insufficient_credit')
        notify.assert_called_once()

    def test_repeated_number_in_one_bulk_gets_one_message_each(self):
        sms = self._send_sms([PHONE_A, PHONE_A])
        self.assertEqual(self._payloads('sendbulk')[0]['to'], ['995555123456', '995555123456'])
        self.assertEqual(self._log(sms).mapped('gosms_id'), ['600', '601'])

    def test_send_details_are_logged(self):
        self.answers['sendsms'] = {'success': True, 'messageId': 501, 'segment': 2, 'encode': 'unicode'}
        log = self._log(self._send_sms([PHONE_A]))
        self.assertEqual((log.segments, log.encoding), (2, 'unicode'))

    def test_bulk_send_details_are_logged(self):
        self.answers['sendbulk'] = {'success': True, 'segment': 1, 'encode': 'default', 'messages': [
            {'messageId': 800, 'to': '995555123456', 'success': True},
            {'messageId': 801, 'to': '995599000000', 'success': True},
        ]}
        self.assertEqual(self._log(self._send_sms([PHONE_A, PHONE_B])).mapped('encoding'), ['default', 'default'])
