import hashlib
import hmac
import json
import logging
import re

from werkzeug.exceptions import BadRequest

from odoo.http import Controller, request, route

_logger = logging.getLogger(__name__)


class GosmsController(Controller):

    @route('/gosms/webhook/<int:company_id>', type='http', auth='public', methods=['POST'], csrf=False)
    def gosms_webhook(self, company_id):
        # sudo: the caller is the public user, GoSMS; the secret or token check below is the only one
        company = request.env['res.company'].sudo().browse(company_id).exists()
        if not company or not self._validate_request(company):
            _logger.warning("GoSMS webhook: could not validate the call for company id=%s", company_id)
            raise request.not_found()
        try:
            payload = json.loads(request.httprequest.get_data())
            event = payload['event']
        except (ValueError, TypeError, KeyError):
            _logger.warning("GoSMS webhook: unreadable body for company id=%s", company_id)
            raise BadRequest()
        messages = request.env['gosms.message'].sudo()  # sudo: the log is for administrators, the call is already authenticated
        if event == 'delivery_status':
            # GoSMS message ids are account-wide and one key may serve several companies: search the companies of this key, not other accounts
            companies = company.search([('gosms_api_key', '=', company.gosms_api_key)]) if company.gosms_api_key else company
            message = messages.search([('gosms_id', '=', str(payload['messageId'])), ('company_id', 'in', companies.ids)])
            if message:
                message._gosms_set_status(payload['status'])
            else:
                _logger.info("GoSMS webhook: no message with GoSMS id %s", payload['messageId'])
        elif event == 'inbound' and not messages.search_count([('company_id', '=', company.id), ('event_id', '=', payload['eventId'])]):
            phone = company._phone_format(number='+' + payload['from'])
            partners = request.env['res.partner'].sudo()  # sudo: the sender is matched to contacts the public user cannot read
            if phone:
                partners = partners.search([('phone_sanitized', '=', phone), ('company_id', 'in', [company.id, False])], limit=2)
            partner = partners if len(partners) == 1 else partners.browse()
            messages.create({
                'company_id': company.id,
                'direction': 'inbound',
                'number': phone or payload['from'],
                'partner_id': partner.id,
                'body': payload['text'],
                'state': 'received',
                'event_id': payload['eventId'],
            })
            if partner:
                partner.with_company(company).message_post(body=payload['text'], author_id=partner.id, message_type='comment',
                    subtype_xmlid='mail.mt_comment')
        return 'OK'

    def _validate_request(self, company):
        """A call is valid when the secret or the token is set and every one that is set matches."""
        secret, token = company.gosms_webhook_secret, company.gosms_webhook_token
        headers, body = request.httprequest.headers, request.httprequest.get_data()
        checks = []
        if token:
            checks.append(hmac.compare_digest(token.encode(), headers.get('X-Webhook-Token', '').encode()))
        if secret:
            match = re.fullmatch(r't=(\d+),v1=([0-9a-f]+)', headers.get('X-Webhook-Signature', ''))
            if match:
                signed = f'{match[1]}.'.encode() + body
                checks.append(hmac.compare_digest(hmac.digest(secret.encode(), signed, hashlib.sha256).hex(), match[2]))
            else:
                checks.append(False)
        return bool(checks) and all(checks)
