import logging
import time

from datetime import timedelta

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


REQUEST_TIMEOUT = 15
TICKET_LIFETIME_SECONDS = 540

ENDPOINT_AUTH = 'auth'
ENDPOINT_LOGOUT = 'auth/logout'
ENDPOINT_CHANGE_PASSWORD = 'main/changepassword'
ENDPOINT_UPLOAD_GEL = 'main/uploadpackagegel'
ENDPOINT_UPLOAD_SALARY = 'main/uploadpackagesalary'
ENDPOINT_UPLOAD_TREASURY = 'main/uploadpackagetreasury'
ENDPOINT_UPLOAD_SINGLE = 'main/uploadsingletransfersbatch'
ENDPOINT_GET_REPORT = 'main/getreport'

PACKAGE_ENDPOINT_BY_KIND = {'gel': ENDPOINT_UPLOAD_GEL, 'salary': ENDPOINT_UPLOAD_SALARY, 'treasury': ENDPOINT_UPLOAD_TREASURY}

API_LANGUAGE = 'GEO'
TECHNICAL_ERROR_CODE = 999

ERROR_MESSAGES = {
    0: lambda: _("Successful"),
    1: lambda: _("Wrong username or password"),
    2: lambda: _("OTP code is wrong"),
    3: lambda: _("Session ticket is invalid"),
    4: lambda: _("Client is blocked by the bank"),
    5: lambda: _("Client is blocked due to incorrect attempts"),
    6: lambda: _("Service suspended"),
    7: lambda: _("Insufficient funds"),
    8: lambda: _("Wrong amount"),
    9: lambda: _("Wrong receiver bank BIC"),
    10: lambda: _("Wrong treasury code"),
    11: lambda: _("Error in one of the batch transactions"),
    12: lambda: _("No such account exists"),
    13: lambda: _("Wrong receiver account"),
    TECHNICAL_ERROR_CODE: lambda: _("Bank technical issue"),
}

BLOCKING_ERROR_CODES = {4, 5}
WRONG_LOGIN_CODE = 1
SERVICE_SUSPENDED_CODE = 6
INVALID_TICKET_CODE = 3
# Upload replies: wrong OTP / expired session are retryable; 999 = fate unknown until the report is read.
RETRYABLE_SEND_CODES = {2, 3}
UNKNOWN_SEND_CODES = {TECHNICAL_ERROR_CODE}

# Transfer groups of the single-transfers upload (op 7), in request order.
TRANSFER_GROUPS = ('InternalTransfers', 'NationalCurrencyTransfers', 'ForeignCurrencyTransfers', 'TreasuryTransfers')

SENSITIVE_KEYS = frozenset({'Password', 'OldPassword', 'NewPassword', 'Otp', 'TicketId'})

REPORT_WINDOW_DAYS = 2


def report_window(sent):
    """Date range to search the bank report for a transfer sent at ``sent`` (a datetime).
    The bank can book a couple of days around the send date; the range always reaches tomorrow."""
    sent_date = (sent or fields.Datetime.now()).date()
    window = timedelta(days=REPORT_WINDOW_DAYS)
    return sent_date - window, max(sent_date + window, fields.Date.today() + timedelta(days=1))


class BasisbankService(models.AbstractModel):
    _name = 'basisbank.service'
    _description = 'Basis Bank REST Client'
    _inherit = 'gec.bank.service'

    _gec_bank_log_model = 'basisbank.api.log'
    _gec_bank_sensitive_keys = SENSITIVE_KEYS

    def error_message(self, code, fallback=''):
        builder = ERROR_MESSAGES.get(code)
        if builder:
            return builder()
        return fallback or _("Bank error %s") % code

    def authenticate(self, connection):
        """Open a session and persist TicketId + expiry on the connection."""
        payload = {'LoginName': connection.sudo().login_name or '', 'Password': connection.sudo().password or ''}
        response = self._call(connection, ENDPOINT_AUTH, payload, with_ticket=False)
        data = response.get('Data') or {}
        ticket = data.get('TicketId')
        client_info = data.get('Client') or {}
        error_code = response.get('ErrorCode', TECHNICAL_ERROR_CODE)
        if error_code != 0 or not ticket:
            failure = {'last_error_code': error_code, 'last_error_message': response.get('ErrorMessage') or self.error_message(error_code)}
            if error_code == WRONG_LOGIN_CODE:
                failure['state'] = 'error'
            connection.sudo().write(failure)
            return False
        connection.store_ticket(ticket, lifetime_seconds=TICKET_LIFETIME_SECONDS)
        connection.sudo().write({
            'state': 'active',
            'last_error_code': 0,
            'last_error_message': False,
        })
        if client_info.get('ActiveClient') is False:
            connection.sudo().state = 'blocked'
        return True

    def logout(self, connection):
        """Invalidate the session on the bank side."""
        if not connection.sudo().ticket_id:
            return True
        try:
            self._call(connection, ENDPOINT_LOGOUT, {})
        finally:
            connection.clear_ticket()
        return True

    def change_password(self, connection, old_password, new_password, otp):
        """Change the connection's Basis Bank password (needs a live session and an OTP)."""
        return self._call(connection, ENDPOINT_CHANGE_PASSWORD, {'OldPassword': old_password, 'NewPassword': new_password, 'Otp': otp})

    def upload_package(self, connection, kind, sender_iban, package_name, otp, items):
        """Send a package (ops 4/5/6): ``kind`` is 'gel', 'salary' or 'treasury';
        ``items`` are dicts shaped for ``PackageItems``."""
        endpoint = PACKAGE_ENDPOINT_BY_KIND.get(kind)
        if not endpoint:
            raise UserError(_("Unknown package kind: %s") % kind)
        payload = {'SenderAcc': sender_iban, 'PackageName': package_name, 'Lang': API_LANGUAGE, 'PackageItems': items}
        if otp:
            payload['Otp'] = otp
        return self._call(connection, endpoint, payload)

    def upload_single_batch(self, connection, otp, groups):
        """Send mixed individual transfers (op 7)."""
        payload = {'Lang': API_LANGUAGE}
        if otp:
            payload['Otp'] = otp
        for key in TRANSFER_GROUPS:
            value = groups.get(key)
            if value:
                payload[key] = value
        return self._call(connection, ENDPOINT_UPLOAD_SINGLE, payload)

    def get_report(self, connection, account, ccy, start_date, end_date, page_no=1):
        """Fetch one statement page."""
        payload = {
            'Account': account,
            'Ccy': ccy,
            'StartDate': fields.Date.to_string(start_date),
            'EndDate': fields.Date.to_string(end_date),
            'PageNo': page_no,
            'Lang': API_LANGUAGE,
        }
        return self._call(connection, ENDPOINT_GET_REPORT, payload, allow_reauth_retry=True)

    def fetch_report_items(self, connection, account, ccy, start_date, end_date):
        """Fetch every page of the statement report; raise UserError on any bank error."""
        items = []
        page = 1
        page_count = 1
        while page <= page_count:
            response = self.get_report(connection, account, ccy, start_date, end_date, page_no=page)
            if response.get('ErrorCode', TECHNICAL_ERROR_CODE) != 0:
                raise UserError(self.error_message(response.get('ErrorCode', TECHNICAL_ERROR_CODE), fallback=response.get('ErrorMessage', '')))
            data = response.get('Data') or {}
            page_count = data.get('PageCount') or 1
            items.extend(data.get('Items') or [])
            page += 1
        return items

    def _ensure_ticket(self, connection):
        if not connection.ticket_is_valid():
            if not self.authenticate(connection):
                raise UserError(_("Basis Bank authentication failed: %s")
                                % (connection.sudo().last_error_message or _("check the connection credentials.")))

    def _build_url(self, connection, path):
        host = (connection.sudo().api_host or 'bis.bankonline.ge').strip().rstrip('/')
        version = (connection.sudo().api_version or 'v2').strip().strip('/')
        host = host.split('://', 1)[-1]
        return f"https://{host}/{version}/api/{path}"

    def _call(self, connection, path, payload, with_ticket=True, allow_reauth_retry=False):
        if with_ticket:
            self._ensure_ticket(connection)
            payload = dict(payload)
            payload['TicketId'] = connection.sudo().ticket_id

        url = self._build_url(connection, path)
        start = time.monotonic()
        http_status = 0
        response_text = ''
        try:
            http_response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT, verify=True, headers={'Content-Type': 'application/json'})
            http_status = http_response.status_code
            response_text = http_response.text or ''
            http_response.raise_for_status()
            data = http_response.json() if response_text else {}
        except requests.Timeout:
            self._record_log(connection, path, payload, '', http_status, TECHNICAL_ERROR_CODE, 'Request timed out', start)
            raise UserError(_("Basis Bank request timed out. Please try again."))
        except requests.ConnectionError:
            self._record_log(connection, path, payload, '', http_status, TECHNICAL_ERROR_CODE, 'Bank unreachable', start)
            raise UserError(_("Basis Bank is unreachable."))
        except (requests.HTTPError, ValueError) as exc:
            self._record_log(connection, path, payload, response_text, http_status, TECHNICAL_ERROR_CODE, str(exc) or 'HTTP error', start)
            raise UserError(_("Basis Bank HTTP error %s.") % http_status)
        except requests.RequestException as exc:
            self._record_log(connection, path, payload, response_text, http_status, TECHNICAL_ERROR_CODE, str(exc) or 'Request error', start)
            raise UserError(_("Basis Bank request failed."))

        error_code = data.get('ErrorCode', TECHNICAL_ERROR_CODE) if isinstance(data, dict) else TECHNICAL_ERROR_CODE
        error_message = (data.get('ErrorMessage') or data.get('ErrorMsg') or '') if isinstance(data, dict) else ''
        self._record_log(connection, path, payload, response_text, http_status, error_code, error_message, start)

        if error_code == INVALID_TICKET_CODE and with_ticket:
            connection.clear_ticket()
            if allow_reauth_retry and self.authenticate(connection):
                return self._call(connection, path, {k: v for k, v in payload.items() if k != 'TicketId'}, with_ticket=True, allow_reauth_retry=False)
        elif with_ticket:
            connection.refresh_ticket(lifetime_seconds=TICKET_LIFETIME_SECONDS)

        if error_code in BLOCKING_ERROR_CODES:
            connection.sudo().write({
                'state': 'blocked',
                'last_error_code': error_code,
                'last_error_message': error_message or self.error_message(error_code),
            })
        elif error_code == SERVICE_SUSPENDED_CODE:
            connection.sudo().write({'last_error_code': error_code, 'last_error_message': error_message or self.error_message(error_code)})

        return data if isinstance(data, dict) else {'ErrorCode': TECHNICAL_ERROR_CODE, 'Data': None}

    def _record_log(self, connection, endpoint, request_payload, response_text, http_status, error_code, error_message, start_monotonic):
        self._write_log(dict(self._log_vals(connection, endpoint, request_payload, response_text, http_status, error_message, start_monotonic),
            error_code=error_code))
