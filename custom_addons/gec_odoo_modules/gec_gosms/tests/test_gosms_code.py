import requests

from odoo.addons.gec_gosms.tests.common import GosmsCommon
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

PHONE = '995555123456'


@tagged('post_install', '-at_install')
class TestGosmsCode(GosmsCommon):

    def setUp(self):
        super().setUp()
        self.answers.update({'otp/send': {'success': True, 'hash': 'h1'}, 'otp/verify': {'success': True, 'verify': True}})

    def test_send_code_returns_the_answer_and_logs_a_code_row(self):
        answer = self.company_a._gosms_send_code(PHONE)
        self.assertEqual(answer['hash'], 'h1')
        self.assertEqual(self._payloads('otp/send'), [{'api_key': 'key-a', 'phone': PHONE}])
        self.assertRecordValues(self.env['gosms.message'].search([]), [{
            'company_id': self.company_a.id,
            'kind': 'code',
            'direction': 'outgoing',
            'number': '+' + PHONE,
            'state': 'sent',
        }])

    def test_check_code_returns_the_answer(self):
        self.assertTrue(self.company_a._gosms_check_code(PHONE, 'h1', '4831')['verify'])
        self.assertEqual(self._payloads('otp/verify'), [{'api_key': 'key-a', 'phone': PHONE, 'hash': 'h1', 'code': '4831'}])

    def test_rate_limit_headers_are_added_to_the_answer(self):
        self.headers.update({'X-RateLimit-Remaining': '7', 'Retry-After': '900'})
        answer = self.company_a._gosms_request('otp/send', {'phone': PHONE})
        self.assertEqual((answer['rate_limit_remaining'], answer['retry_after']), (7, 900))

    def test_wait_is_told_in_minutes(self):
        self.headers['Retry-After'] = '900'
        for code, text in [(110, "Try again in 15 minutes."), (109, "Wait 15 minutes")]:
            with self.subTest(code=code):
                self.answers['otp/send'] = {'success': False, 'errorCode': code}
                with self.assertRaisesRegex(UserError, text):
                    self.company_a._gosms_send_code(PHONE)

    def test_wait_is_rounded_up(self):
        self.headers['Retry-After'] = '61'
        self.answers['otp/send'] = {'success': False, 'errorCode': 110}
        with self.assertRaisesRegex(UserError, "2 minutes"):
            self.company_a._gosms_send_code(PHONE)

    def test_failed_code_is_not_logged(self):
        self.post.side_effect = requests.ConnectionError()
        with mute_logger('odoo.addons.gec_gosms.models.res_company'), self.assertRaises(UserError):
            self.company_a._gosms_send_code(PHONE)
        self.assertFalse(self.env['gosms.message'].search([]))
