import json
import re
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from odoo.addons.gec_gosms import gosms_confirm
from odoo.addons.gec_gosms.models.res_company import GOSMS_URL
from odoo.addons.gec_gosms.tools.sms_api import GOSMS_ERRORS
from odoo.exceptions import AccessError, UserError
from odoo.http import request_var
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

PHONE = '995555123456'


@gosms_confirm('phone')
def action_gosms_test(self):
    self.ref = 'SIGNED'
    return True


@tagged('post_install', '-at_install')
class TestGosmsConfirm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.startClassPatcher(patch.object(cls.registry['res.partner'], 'action_gosms_test', action_gosms_test, create=True))
        cls.env.company.gosms_api_key = 'key-a'
        cls.company_b = cls.env['res.company'].create({'name': 'GoSMS Company B', 'gosms_api_key': 'key-b'})
        cls.partner = cls.env['res.partner'].create({'name': 'Nino', 'phone': '555 12 34 56', 'country_id': cls.env.ref('base.ge').id})
        cls.user = new_test_user(cls.env, login='gosms_user', groups='base.group_user,base.group_partner_manager')
        cls.other_user = new_test_user(cls.env, login='gosms_other_user', groups='base.group_user,base.group_partner_manager')

    def setUp(self):
        super().setUp()
        self.sent = []
        self.headers = {}
        self.answers = {
            'otp/send': {'success': True, 'hash': 'h1'},
            'otp/verify': {'success': True, 'verify': True},
            'sms-balance': {'success': True, 'balance': 94},
        }
        self.post = self.startPatcher(patch('odoo.addons.gec_gosms.models.res_company.requests.post', side_effect=self._post))

    def _post(self, url, json=None, **kwargs):
        endpoint = url.removeprefix(f'{GOSMS_URL}/')
        self.sent.append((endpoint, json))
        return MagicMock(**{'json.return_value': self.answers[endpoint], 'headers': self.headers})

    def _payloads(self, endpoint):
        return [payload for sent_endpoint, payload in self.sent if sent_endpoint == endpoint]

    @contextmanager
    def _web_request(self):
        token = request_var.set(SimpleNamespace(env=self.env))
        try:
            yield
        finally:
            request_var.reset(token)

    def _click(self, partner=None, user=None):
        with self._web_request():
            return (partner or self.partner).with_user(user or self.user).action_gosms_test()

    def _dialog(self, partner=None, user=None):
        action = self._click(partner, user)
        return self.env[action['res_model']].browse(action['res_id']).with_user(user or self.user)

    def _assertUserError(self, text, func, *args):
        with self.assertRaisesRegex(UserError, re.escape(text)):
            func(*args)

    def test_code_confirms_button(self):
        action = self._click()
        self.assertEqual((action['res_model'], action['target']), ('gosms.confirm.wizard', 'new'))
        self.assertFalse(self.partner.ref)
        self.assertEqual(self._payloads('otp/send'), [{'api_key': 'key-a', 'phone': PHONE}])
        wizard = self.env['gosms.confirm.wizard'].browse(action['res_id']).with_user(self.user)
        self.assertTrue(wizard.with_context(gosms_code='4831').action_confirm())
        self.assertEqual(self.partner.ref, 'SIGNED')
        self.assertEqual(self._payloads('otp/verify'), [{'api_key': 'key-a', 'phone': PHONE, 'hash': 'h1', 'code': '4831'}])
        self.assertIn("Confirmed with the SMS code sent to +995 555 12 34 56.", self.partner.message_ids[:1].body)
        self.assertFalse(wizard.sudo().otp_hash)

    def test_wrong_code(self):
        wizard = self._dialog()
        messages = self.partner.message_ids
        self.answers['otp/verify'] = {'success': True, 'verify': False}
        self._assertUserError("The code is wrong. Check the SMS and try again.", wizard.with_context(gosms_code='1111').action_confirm)
        self.assertFalse(self.partner.ref)
        self.assertEqual(self.partner.message_ids, messages)

    def test_empty_code(self):
        wizard = self._dialog()
        self._assertUserError("Type the code from the SMS first.", wizard.action_confirm)
        self.assertFalse(self._payloads('otp/verify'))

    def test_gosms_errors(self):
        wizard = self._dialog().with_context(gosms_code='4831')
        for answer, text in [
            ({'errorCode': 111, 'message': 'x'}, str(GOSMS_ERRORS[111])),
            ({'errorCode': 999, 'message': 'Unknown'}, "GoSMS refused the request: Unknown"),
            ({'statusCode': 500, 'message': 'Internal server error'}, "GoSMS refused the request: Internal server error"),
        ]:
            with self.subTest(answer=answer):
                self.answers['otp/verify'] = answer
                self._assertUserError(text, wizard.action_confirm)
                self.assertFalse(self.partner.ref)

    def test_gosms_unreachable(self):
        self.post.side_effect = requests.ConnectionError()
        with mute_logger('odoo.addons.gec_gosms.models.res_company'):
            self._assertUserError("GoSMS could not be reached. Try again in a minute.", self._click)
        self.assertFalse(self.partner.ref)

    def test_no_phone(self):
        partner = self.partner.copy({'phone': False})
        self._assertUserError("Add a phone number first: the confirmation code is sent to it by SMS.", self._click, partner)
        self.assertFalse(self.sent)

    def test_one_record_per_click(self):
        partners = self.partner | self.partner.copy()
        self._assertUserError("Select one record at a time: each SMS code confirms one record.", self._click, partners)
        self.assertFalse(self.sent)
        self.assertFalse(self.env['gosms.confirm.wizard'].sudo().search([]))

    def test_outside_web_request(self):
        self._assertUserError("can only be run from the Odoo screen.", self.partner.with_user(self.user).action_gosms_test)
        self.assertFalse(self.sent)

    def test_record_company_key(self):
        partner = self.partner.copy({'company_id': self.company_b.id})
        wizard = self._dialog(partner, self.env.user)
        wizard.with_context(gosms_code='4831').action_confirm()
        self.assertEqual([payload['api_key'] for _endpoint, payload in self.sent], ['key-b', 'key-b'])
        self.company_b.gosms_api_key = False
        self._assertUserError("Add the GoSMS API key in Settings first.", self._click, partner, self.env.user)

    def test_resend_uses_new_code(self):
        wizard = self._dialog()
        self.answers['otp/send'] = {'success': True, 'hash': 'h2'}
        action = wizard.action_resend()
        self.assertEqual((action['res_model'], action['res_id']), ('gosms.confirm.wizard', wizard.id))
        wizard.with_context(gosms_code='4831').action_confirm()
        self.assertEqual(self._payloads('otp/verify')[0]['hash'], 'h2')
        self.assertEqual(self.partner.ref, 'SIGNED')

    def test_dialog_cannot_be_forged(self):
        wizards = self.env['gosms.confirm.wizard'].with_user(self.user)
        for field in ('request', 'phone', 'otp_hash', 'company_id'):
            value = self.env.company.id if field == 'company_id' else 'x'
            with self.subTest(field=field, operation='create'), self.assertRaises(AccessError):
                wizards.create({field: value})
            with self.subTest(field=field, operation='write'), self.assertRaises(AccessError):
                wizards.sudo().create({}).sudo(False).write({field: value})

    def test_dialog_of_another_user(self):
        wizard = self._dialog()
        with self.assertRaises(AccessError):
            wizard.with_user(self.other_user).with_context(gosms_code='4831').action_confirm()
        self.assertFalse(self.partner.ref)
        self.assertFalse(self._payloads('otp/verify'))

    def test_dialog_cannot_run_other_method(self):
        request = json.dumps([{}, 'res.partner', [self.partner.id], 'unlink', [], {}])
        wizard = self.env['gosms.confirm.wizard'].with_user(self.user).sudo().create({
            'request': request,
            'company_id': self.env.company.id,
            'phone': PHONE,
            'otp_hash': 'h1',
        })
        with self.assertRaises(AssertionError):
            wizard.with_user(self.user).with_context(gosms_code='4831').action_confirm()
        self.assertTrue(self.partner.exists())

    def test_context_cannot_skip_dialog(self):
        with self._web_request():
            action = self.partner.with_user(self.user).with_context(gosms_confirmed=True).action_gosms_test()
        self.assertEqual(action['res_model'], 'gosms.confirm.wizard')
        self.assertFalse(self.partner.ref)

    def test_check_connection(self):
        action = self.env['res.config.settings'].create({}).action_gosms_check_connection()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn("SMS balance: 94", action['params']['message'])
        self.assertEqual(self._payloads('sms-balance'), [{'api_key': 'key-a'}])

    def test_dialog_shows_attempts_left(self):
        self.headers['X-RateLimit-Remaining'] = '7'
        self.assertEqual(self._dialog().attempts_left, 7)

    def test_wrong_code_tells_attempts_left(self):
        wizard = self._dialog()
        self.answers['otp/verify'] = {'success': True, 'verify': False}
        self.headers['X-RateLimit-Remaining'] = '2'
        self._assertUserError("The code is wrong. Attempts left: 2.", wizard.with_context(gosms_code='1111').action_confirm)

    def test_codes_are_logged_with_the_first_click_and_the_new_code(self):
        self._dialog().action_resend()
        codes = self.env['gosms.message'].search([('kind', '=', 'code')])
        self.assertEqual(codes.mapped('number'), ['+' + PHONE] * 2)
