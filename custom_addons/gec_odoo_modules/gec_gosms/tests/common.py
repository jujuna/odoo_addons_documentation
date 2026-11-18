from unittest.mock import MagicMock, patch

from odoo.addons.gec_gosms.models.res_company import GOSMS_URL
from odoo.tests import TransactionCase

PHONE_A = '+995555123456'
PHONE_B = '+995599000000'


class GosmsCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_a.write({
            'country_id': cls.env.ref('base.ge').id,
            'gosms_api_key': 'key-a',
            'gosms_sender': 'SENDER-A',
            'gosms_sms_enabled': True,
        })
        cls.company_b = cls.env['res.company'].create({
            'name': 'GoSMS Company B',
            'country_id': cls.env.ref('base.ge').id,
            'gosms_api_key': 'key-b',
            'gosms_sender': 'SENDER-B',
            'gosms_sms_enabled': True,
        })

    def setUp(self):
        super().setUp()
        self.sent = []
        self.headers = {}
        self.answers = {'sendsms': {'success': True, 'messageId': 501}, 'sendbulk': self._bulk_answer}
        self.post = self.startPatcher(patch('odoo.addons.gec_gosms.models.res_company.requests.post', side_effect=self._post))

    def _bulk_answer(self, payload):
        return {'success': True, 'messages': [{'messageId': 600 + i, 'to': to, 'success': True} for i, to in enumerate(payload['to'])]}

    def _post(self, url, json=None, **kwargs):
        endpoint = url.removeprefix(f'{GOSMS_URL}/')
        self.sent.append((endpoint, json))
        answer = self.answers[endpoint]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return MagicMock(**{'json.return_value': answer(json) if callable(answer) else answer, 'headers': self.headers})

    def _payloads(self, endpoint):
        return [payload for sent_endpoint, payload in self.sent if sent_endpoint == endpoint]

    def _send_sms(self, numbers, body="Hello", **values):
        sms = self.env['sms.sms'].create([{'number': number, 'body': body, **values} for number in numbers])
        sms.send()
        return sms

    def _log(self, sms):
        return self.env['gosms.message'].search([('sms_uuid', 'in', sms.mapped('uuid'))])
