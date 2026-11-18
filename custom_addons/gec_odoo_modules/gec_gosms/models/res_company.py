import logging
import math

import requests

from odoo import fields, models
from odoo.addons.gec_gosms.tools.sms_api import GOSMS_ERRORS, SmsApiGosms
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GOSMS_URL = 'https://api.gosms.ge/api'
GOSMS_TIMEOUT = 15
GOSMS_RATE_HEADERS = {'X-RateLimit-Remaining': 'rate_limit_remaining', 'Retry-After': 'retry_after'}


class ResCompany(models.Model):
    _inherit = 'res.company'

    gosms_api_key = fields.Char("GoSMS API Key", groups='base.group_system', copy=False)
    gosms_sms_enabled = fields.Boolean("Send Odoo SMS through GoSMS")
    gosms_sender = fields.Char("Sender Name")
    gosms_nosms_number = fields.Char("Opt-out Number")
    gosms_webhook_secret = fields.Char("Webhook Secret", groups='base.group_system', copy=False)
    gosms_webhook_token = fields.Char("Webhook Token", groups='base.group_system', copy=False)

    def _get_sms_api_class(self):
        self.ensure_one()
        if self.gosms_sms_enabled:
            return SmsApiGosms
        return super()._get_sms_api_class()

    def _gosms_request(self, endpoint, payload):
        self.ensure_one()
        api_key = self.sudo().gosms_api_key  # sudo: the key is admin-only, every user who confirms or sends needs it
        if not api_key:
            raise UserError(self.env._("Add the GoSMS API key in Settings first."))
        try:
            response = requests.post(f'{GOSMS_URL}/{endpoint}', json={'api_key': api_key, **payload}, timeout=GOSMS_TIMEOUT)
            data = response.json()
        except requests.RequestException as error:
            _logger.warning("GoSMS %s failed: %s", endpoint, error)
            if isinstance(error, requests.ReadTimeout):
                raise UserError(self.env._("GoSMS did not answer in time: the message may have been sent. Check it before sending again.")) from error
            raise UserError(self.env._("GoSMS could not be reached. Try again in a minute.")) from error
        data.update({key: int(response.headers[header]) for header, key in GOSMS_RATE_HEADERS.items() if response.headers.get(header, '').isdigit()})
        return data

    def _gosms_call(self, endpoint, payload):
        data = self._gosms_request(endpoint, payload)
        if not data.get('success'):
            code = data.get('errorCode')
            minutes = math.ceil(data.get('retry_after', 0) / 60)
            if minutes and code == 109:
                raise UserError(self.env._("Too many codes were requested. Wait %s minutes, then send a new code.", minutes))
            if minutes and code == 110:
                raise UserError(self.env._("Too many failed attempts: GoSMS has paused codes. Try again in %s minutes.", minutes))
            message = GOSMS_ERRORS.get(code)
            raise UserError(self.env._(message) if message else self.env._("GoSMS refused the request: %s", data.get('message')))
        return data

    def _gosms_send_code(self, phone):
        """Send a one-time code to ``phone`` (995XXXXXXXXX) and log it; the answer holds the ``hash`` that ``_gosms_check_code`` needs."""
        answer = self._gosms_call('otp/send', {'phone': phone})
        # sudo: users who confirm an action have no rights on the message log
        self.env['gosms.message'].sudo().create({
            'company_id': self.id,
            'direction': 'outgoing',
            'kind': 'code',
            'number': f'+{phone}',
            'state': 'sent',
        })
        return answer

    def _gosms_check_code(self, phone, code_hash, code):
        return self._gosms_call('otp/verify', {'phone': phone, 'hash': code_hash, 'code': code})
