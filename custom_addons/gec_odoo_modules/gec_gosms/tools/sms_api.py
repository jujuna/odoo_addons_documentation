from odoo.addons.sms.tools.sms_api import SmsApiBase
from odoo.exceptions import UserError
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

GOSMS_ERRORS = {
    100: _lt("The GoSMS API key is wrong or missing. Fix it in Settings."),
    101: _lt("The GoSMS sender name is not registered or not active. Check it on app.gosms.ge."),
    102: _lt("The GoSMS SMS balance is used up. Top it up on app.gosms.ge."),
    103: _lt("GoSMS refused the message: the text is too long or a value is missing."),
    104: _lt("GoSMS cannot find this message. Check that it was sent with this GoSMS account."),
    105: _lt("GoSMS does not accept this phone number. Correct it and try again."),
    106: _lt("GoSMS could not send the code. Try again."),
    107: _lt("This sender name already exists on GoSMS. Check it on app.gosms.ge."),
    108: _lt("GoSMS cannot set this up: check the sender name, and for SMS codes the OTP settings, on app.gosms.ge."),
    109: _lt("Too many codes were requested. Wait a few minutes, then send a new code."),
    110: _lt("Too many failed attempts: GoSMS has paused codes for a while. Try again later."),
    111: _lt("The code has expired. Send a new code."),
    112: _lt("This code was already used. Send a new code."),
    113: _lt("The opt-out number is not valid or not set up on GoSMS. Check it on app.gosms.ge."),
}
GOSMS_FAILED = 'gosms_failed'
GOSMS_CODE_TO_STATE = {102: 'insufficient_credit', 105: 'wrong_number_format'}


def _failed(uuids, state, reason=False):
    return [{'uuid': uuid, 'state': state, 'failure_reason': reason} for uuid in uuids]


class SmsApiGosms(SmsApiBase):
    PROVIDER_TO_SMS_FAILURE_TYPE = SmsApiBase.PROVIDER_TO_SMS_FAILURE_TYPE | {'insufficient_credit': 'sms_credit'}

    def _send_sms_batch(self, messages, delivery_reports_url=False):
        """One result per uuid. Rows and log are written here too: direct callers (the SMS Marketing test) skip core's result handling."""
        company = self.company.sudo()  # sudo: sender and opt-out number are settings read for every user who sends
        uuids = [info['uuid'] for message in messages for info in message['numbers']]
        if not company.gosms_sender:
            return self._save_results(_failed(uuids, GOSMS_FAILED, self.env._("Add the GoSMS sender name in Settings first.")))
        urgent_uuids = set(self.env['sms.sms'].sudo().search_fetch([('uuid', 'in', uuids), ('gosms_urgent', '=', True)], ['uuid']).mapped('uuid'))
        results = []
        calls = []
        for message in messages:
            recipients = []
            for info in message['numbers']:
                number = info['number'] and company._phone_format(number=info['number'])  # no number: _phone_format would take the company's own
                if number:
                    recipients.append((number.lstrip('+'), info['uuid']))
                else:
                    results += _failed([info['uuid']], 'wrong_number_format')
            for urgent in (False, True):
                group = [(number, uuid) for number, uuid in recipients if (uuid in urgent_uuids) == urgent]
                if group:
                    calls.append((message, group, urgent))
        for message, recipients, urgent in calls:
            numbers = [number for number, _uuid in recipients]
            uuids = [uuid for _number, uuid in recipients]
            marketing = message.get('sms_type') == 'marketing'
            payload = {'from': company.gosms_sender, 'text': message['content']}
            if urgent:
                payload['urgent'] = True
            if len(numbers) == 1 and not marketing:
                endpoint, payload['to'] = 'sendsms', numbers[0]
            else:
                endpoint, payload['to'] = 'sendbulk', numbers
                if marketing and company.gosms_nosms_number:
                    payload['noSmsNumber'] = company.gosms_nosms_number
            try:
                data = company._gosms_request(endpoint, payload)
            except UserError as error:
                results += _failed(uuids, 'server_error', error.args[0])
                continue
            if not data.get('success'):
                code = data.get('errorCode')
                reason = self.env._(GOSMS_ERRORS[code]) if code in GOSMS_ERRORS else data.get('message')
                results += _failed(uuids, GOSMS_CODE_TO_STATE.get(code, GOSMS_FAILED), reason)
                continue
            sent = {'state': 'sent', 'gosms_segments': data.get('segment'), 'gosms_encoding': data.get('encode')}
            answers = [{**data, 'to': numbers[0]}] if endpoint == 'sendsms' else data.get('messages') or []
            uuids_by_number = {}
            for number, uuid in recipients:
                uuids_by_number.setdefault(number, []).append(uuid)
            for answer in answers:
                pending = uuids_by_number.get(answer.get('to'))
                if pending and not answer.get('success'):
                    results += _failed([pending.pop(0)], GOSMS_FAILED, answer.get('error'))
                elif pending and answer.get('messageId'):
                    results.append({'uuid': pending.pop(0), 'gosms_message_id': str(answer['messageId']), **sent})
            missing = [uuid for waiting in uuids_by_number.values() for uuid in waiting]
            results += _failed(missing, 'server_error', self.env._("GoSMS did not confirm this message. Check it before sending again."))
        return self._save_results(results)

    def _save_results(self, results):
        failure_types = self.PROVIDER_TO_SMS_FAILURE_TYPE
        values_by_uuid = {}
        for result in results:
            state = result['state']
            values_by_uuid[result['uuid']] = ('pending', False) if state == 'sent' else ('error', failure_types.get(state, 'unknown'))
        results_by_uuid = {result['uuid']: result for result in results}
        # sudo: sms.sms and the message log are system-only, regular users send SMS
        sms_rows = self.env['sms.sms'].sudo().search([('uuid', 'in', list(results_by_uuid))])
        outgoing = sms_rows.filtered(lambda sms: sms.state == 'outgoing')
        for (state, failure_type), group in outgoing.grouped(lambda sms: values_by_uuid[sms.uuid]).items():
            group.write({'state': state, 'failure_type': failure_type})
        sms_rows.env['gosms.message'].create([{
            'company_id': self.company.id,
            'direction': 'outgoing',
            'number': sms.number,
            'partner_id': sms.partner_id.id,
            'body': sms.body,
            'sms_uuid': sms.uuid,
            'gosms_id': results_by_uuid[sms.uuid].get('gosms_message_id'),
            'segments': results_by_uuid[sms.uuid].get('gosms_segments'),
            'encoding': results_by_uuid[sms.uuid].get('gosms_encoding'),
            'state': 'sent' if results_by_uuid[sms.uuid]['state'] == 'sent' else 'error',
            'failure_reason': results_by_uuid[sms.uuid].get('failure_reason'),
        } for sms in sms_rows])
        return results
