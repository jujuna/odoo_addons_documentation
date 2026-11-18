import base64
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# A transfer POST gets a long timeout: cutting it off does not cancel it at the bank, it only makes an 'unknown'.
REQUEST_TIMEOUT = 15
TRANSFER_TIMEOUT = 60
# Ceiling on statement paging, in case the API ignores PageIndex.
MAX_MOVEMENT_PAGES = 200
DEFAULT_HOSTS = {
    'test': 'test-api.tbcbank.ge',
    'production': 'api.tbcbank.ge',
}
TOKEN_PATH = 'oauth/token'
API_BASE_PATH = 'bab/v1'
SCOPES = 'bab_accounts bab_transfers'
# TBC uses local Tbilisi time (UTC+4, no DST); Odoo stores UTC.
TBC_TZ = ZoneInfo('Asia/Tbilisi')
SENSITIVE_KEYS = frozenset({'client_secret', 'access_token', 'refresh_token', 'id_token', 'Authorization'})
# BIS error titles meaning the Internet Banking user cannot act; the connection is marked 'blocked'.
BLOCKING_ERROR_TITLES = frozenset({'USER_IS_BLOCKED', 'USER_IS_NOT_ACTIVE', 'USER_IS_DELETED'})


class TbcService(models.AbstractModel):
    _name = 'tbc.service'
    _description = 'TBC Bank REST Client'
    _inherit = 'gec.bank.service'

    _gec_bank_log_model = 'tbc.api.log'
    _gec_bank_sensitive_keys = SENSITIVE_KEYS

    def _host(self, connection):
        connection = connection.sudo()
        return (connection.api_host or DEFAULT_HOSTS[connection.environment]).strip().split('://', 1)[-1].rstrip('/')

    def _token_url(self, connection):
        return f"https://{self._host(connection)}/{TOKEN_PATH}"

    def _api_url(self, connection, path):
        return f"https://{self._host(connection)}/{API_BASE_PATH}/{path.lstrip('/')}"

    def authenticate(self, connection):
        """Fetch an OAuth2 bearer token and cache it; True on success (state 'active'), else False (state 'error')."""
        connection = connection.sudo()
        client_id = connection.client_id or ''
        client_secret = connection.client_secret or ''
        if not client_id or not client_secret:
            connection._gec_bank_write_connection({
                'state': 'error',
                'last_error_code': 0,
                'last_error_message': _("Client ID and Client Secret are required."),
            })
            return False

        url = self._token_url(connection)
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {'Authorization': f"Basic {basic}", 'Content-Type': 'application/x-www-form-urlencoded'}
        body = {'grant_type': 'client_credentials', 'scope': SCOPES}
        start = time.monotonic()
        http_status = 0
        response_text = ''
        try:
            resp = requests.post(url, headers=headers, data=body, timeout=REQUEST_TIMEOUT)
            http_status = resp.status_code
            response_text = resp.text or ''
            resp.raise_for_status()
            data = resp.json() if response_text else {}
        except requests.Timeout:
            self._record_log(connection, TOKEN_PATH, body, '', http_status, 'Request timed out', start)
            connection._gec_bank_write_connection({'state': 'error', 'last_error_message': _("TBC token request timed out.")})
            return False
        except requests.ConnectionError:
            self._record_log(connection, TOKEN_PATH, body, '', http_status, 'Bank unreachable', start)
            connection._gec_bank_write_connection({'state': 'error', 'last_error_message': _("TBC Bank is unreachable.")})
            return False
        except (requests.HTTPError, ValueError, requests.RequestException) as exc:
            self._record_log(connection, TOKEN_PATH, body, response_text, http_status, str(exc), start)
            error_data = self._parse_json(response_text)
            if self._mark_blocked_if_needed(connection, error_data):
                return False
            message = self._error_text(error_data, response_text) or str(exc) or _("Authentication failed.")
            connection._gec_bank_write_connection({
                'state': 'error',
                'last_error_code': http_status,
                'last_error_message': message[:255],
            })
            return False

        self._record_log(connection, TOKEN_PATH, body, response_text, http_status, '', start)
        token = data.get('access_token')
        expires_in = data.get('expires_in') or 3600
        if not token:
            connection._gec_bank_write_connection({
                'state': 'error',
                'last_error_code': http_status,
                'last_error_message': _("No access token in TBC response."),
            })
            return False

        connection.store_token(token, int(expires_in), {
            'state': 'active',
            'last_error_code': 0,
            'last_error_message': False,
        })
        return True

    def _ensure_token(self, connection):
        """Authenticate if there is no valid bearer token."""
        if not connection.token_is_valid():
            if not self.authenticate(connection):
                raise UserError(_("TBC Bank authentication failed: %s", connection.sudo().last_error_message or _("check the credentials.")))

    def _call(self, connection, path, method='GET', params=None, payload=None, allow_reauth_retry=True, soft=False, timeout=None):
        """Authenticated call to a /bab/v1 endpoint; raises UserError on any error. soft=True never raises once logged in:
        returns {'http_status', 'data', 'error_text'}, http_status 0 without a response (money-moving calls
        tell ambiguous from definite failure)."""
        connection = connection.sudo()
        self._ensure_token(connection)
        url = self._api_url(connection, path)
        headers = {
            'Authorization': f"Bearer {connection.access_token}",
            'Accept': 'application/json',
        }
        log_payload = params if method.upper() == 'GET' else (payload or {})

        start = time.monotonic()
        http_status = 0
        response_text = ''
        try:
            resp = requests.request(method, url, headers=headers, params=params, json=payload, timeout=timeout or REQUEST_TIMEOUT)
            http_status = resp.status_code
            response_text = resp.text or ''
        except requests.Timeout:
            self._record_log(connection, path, log_payload, '', http_status, 'Request timed out', start)
            if soft:
                return {'http_status': 0, 'data': {}, 'error_text': _("TBC Bank did not answer in time.")}
            raise UserError(_("TBC Bank request timed out. Please try again."))
        except requests.ConnectionError:
            self._record_log(connection, path, log_payload, '', http_status, 'Bank unreachable', start)
            if soft:
                return {'http_status': 0, 'data': {}, 'error_text': _("TBC Bank is unreachable.")}
            raise UserError(_("TBC Bank is unreachable."))
        except requests.RequestException as exc:
            self._record_log(connection, path, log_payload, response_text, http_status, str(exc), start)
            if soft:
                return {'http_status': 0, 'data': {}, 'error_text': str(exc)}
            raise UserError(_("TBC Bank request failed."))

        self._record_log(connection, path, log_payload, response_text, http_status, '', start)

        if http_status == 401 and allow_reauth_retry:
            connection.clear_token()
            if self.authenticate(connection):
                return self._call(connection, path, method=method, params=params, payload=payload, allow_reauth_retry=False,
                    soft=soft, timeout=timeout)

        data = self._parse_json(response_text)
        if http_status >= 400:
            self._mark_blocked_if_needed(connection, data)

        if soft:
            return {
                'http_status': http_status,
                'data': data if isinstance(data, dict) else {},
                'error_text': self._error_text(data, response_text),
            }

        if http_status >= 400:
            raise UserError(_("TBC Bank error %s: %s", http_status, self._error_text(data, response_text)[:200]))
        return {} if data is None else data

    @staticmethod
    def _error_text(data, response_text):
        """TBC's title, detail and per-field messages (OAuth: error and its description), else the raw body."""
        if not isinstance(data, dict):
            return response_text
        parts = [data.get(key) for key in ('title', 'detail', 'error', 'error_description')]
        errors = data.get('errors')
        for messages in (errors.values() if isinstance(errors, dict) else ()):
            parts += messages if isinstance(messages, list) else [messages]
        return ' — '.join(str(part) for part in parts if part) or response_text

    def _mark_blocked_if_needed(self, connection, data):
        """Mark the connection 'blocked' when TBC says its Internet Banking user is blocked, inactive or deleted.

        Returns True if so; written durably, as the caller usually raises and rolls back a plain write."""
        title = data.get('title') if isinstance(data, dict) else None
        if title not in BLOCKING_ERROR_TITLES:
            return False
        message = _("TBC Bank rejected the integration user (%s). Fix the user in Business Internet Banking, "
                    "then ask a TBC Bank manager to use Test Connection.", title)
        vals = {
            'state': 'blocked',
            'last_error_code': data.get('status') or 400,
            'last_error_message': message[:255],
        }
        self._durable_write(connection.sudo(), vals)
        return True

    def get_account_movements(self, connection, account_number, currency_code, period_from, period_to, page_index=0, page_size=700):
        """GET /bab/v1/accounts/movements: one page, raw JSON."""
        params = {
            'AccountNumber': account_number,
            'AccountCurrencyCode': currency_code,
            'PeriodFrom': self._format_dt(self._to_tbc_local(period_from)),
            'PeriodTo': self._format_dt(self._to_tbc_local(period_to)),
            'PageIndex': page_index,
            'PageSize': page_size,
        }
        return self._call(connection, 'accounts/movements', method='GET', params=params)

    @staticmethod
    def _to_tbc_local(value):
        """Naive UTC datetime to naive Tbilisi time, which TBC reads; dates pass through."""
        if not isinstance(value, datetime):
            return value
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(TBC_TZ).replace(tzinfo=None)

    def get_account_statement(self, connection, account_number, currency_code, period_from, period_to):
        """GET /bab/v1/accounts/statements: the period balance summary, raw JSON.

        A bare date for PeriodTo means 00:00 and would drop the last day, so the period runs to its end."""
        params = {
            'AccountNumber': account_number,
            'AccountCurrencyCode': currency_code,
            'PeriodFrom': self._format_date(period_from, end_of_day=False),
            'PeriodTo': self._format_date(period_to, end_of_day=True),
        }
        return self._call(connection, 'accounts/statements', method='GET', params=params)

    @staticmethod
    def _format_date(value, end_of_day=False):
        """A date to a TBC date-time string, 00:00:00 or 23:59:59 with end_of_day."""
        return '%sT%s' % (value.strftime('%Y-%m-%d'), '23:59:59' if end_of_day else '00:00:00')

    def fetch_all_movements(self, connection, account_number, currency_code, period_from, period_to, page_size=700):
        """Page through every movement in the period; returns the transaction dicts. With a ``total``, paging
        runs until it is reached and an early empty page raises; without one, a short page is the last."""
        movements = []
        for page_index in range(MAX_MOVEMENT_PAGES):
            data = self.get_account_movements(connection, account_number, currency_code, period_from, period_to,
                page_index=page_index, page_size=page_size)
            batch = self._first_key(data, ('transactions', 'Transactions', 'movements', 'items'), []) or []
            if batch and page_index == 0 and not isinstance(batch, list):
                raise UserError(_("Unexpected movement payload from TBC Bank."))
            movements.extend(batch)
            total = self._first_key(data, ('total', 'Total', 'totalCount'))
            if total is not None:
                if len(movements) >= total:
                    return movements
                if not batch:
                    raise UserError(_("TBC sent %(count)s of the %(total)s movements of %(account)s and then "
                                      "stopped. Nothing was imported; import the period again later.",
                                      count=len(movements), total=total, account=account_number))
            elif not batch or len(batch) < page_size:
                return movements
        # Ceiling hit: raise rather than return a partial period.
        raise UserError(_("TBC returned more than %(pages)s pages of movements for %(account)s. "
                          "Import a shorter period.", pages=MAX_MOVEMENT_PAGES, account=account_number))

    @staticmethod
    def _format_dt(value):
        """ISO datetime string like 2026-04-01T00:00:00 from a date or datetime."""
        return value.strftime('%Y-%m-%dT%H:%M:%S')

    def import_single_transfer(self, connection, order):
        """POST /bab/v1/transfers/single in soft mode: tells an ambiguous failure (timeout/5xx) from a definite one."""
        payload = {'singleTransferOrders': [order]}
        return self._call(connection, 'transfers/single', method='POST', payload=payload, soft=True, timeout=TRANSFER_TIMEOUT)

    def get_single_transfer_by_external_id(self, connection, external_id):
        """GET /bab/v1/transfers/single/{transferExternalId}: the bank's transferId, to recover an 'unknown' transfer without resending."""
        return self._call(connection, 'transfers/single/%s' % external_id, method='GET', soft=True)

    def get_single_transfer_status(self, connection, transfer_id):
        """GET /bab/v1/transfers/single/{transferId}/status"""
        return self._call(connection, 'transfers/single/%s/status' % transfer_id, method='GET')

    def _record_log(self, connection, endpoint, request_payload, response_text, http_status, error_message, start_monotonic):
        self._write_log(self._log_vals(connection, endpoint, request_payload, response_text, http_status, error_message, start_monotonic))
