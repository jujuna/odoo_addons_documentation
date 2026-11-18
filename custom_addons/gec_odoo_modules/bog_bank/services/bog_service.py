import base64
import collections
import logging
import threading
import time

import requests
from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Tokens come from BOG's identity server, the API from another host.
TOKEN_URL = 'https://account.bog.ge/auth/realms/bog/protocol/openid-connect/token'
API_BASE = 'https://api.businessonline.ge/api'

# A document POST gets a long timeout: cutting it off cancels nothing at the bank.
REQUEST_TIMEOUT = 15
TRANSFER_TIMEOUT = 60

# BOG does not document expires_in for client credentials; assume the short 300s lifetime.
DEFAULT_TOKEN_LIFETIME = 300

# BOG's limit: 5 requests/second. _throttle is per worker; the 429 branch in _call is the backstop.
RATE_LIMIT_PER_SECOND = 5
RATE_WINDOW = 1.0
# One retry only: a repeating 429 is a quota problem, not a burst.
MAX_429_RETRIES = 1
MAX_RETRY_AFTER = 60

# Ceiling on statement paging, so an endpoint that keeps returning full pages cannot spin forever.
MAX_STATEMENT_PAGES = 200
# Records per statement page; a shorter page is the last one.
STATEMENT_PAGE_SIZE = 1000

SENSITIVE_KEYS = frozenset({'client_secret', 'access_token', 'refresh_token', 'id_token', 'Authorization'})

# The extensions BOG publishes for api/files/upload.
BOG_ALLOWED_UPLOAD_EXTENSIONS = frozenset({
    'docx', 'docm', 'dotx', 'dotm', 'docb', 'xls', 'xlsb', 'xlsm', 'xlsx',
    'jpg', 'jpeg', 'png', 'ppt', 'gif', 'txt', 'pdf', 'zip', 'rar', 'tar',
    'gzip', 'ico', 'dat', 'csv', 'xml', 'enc', 'svg',
})

_rate_lock = threading.Lock()
_rate_calls = collections.deque()


def bog_key(value):
    """A BOG key as an integer string, so 987654.0 and 987654 are one key."""
    if value in (None, '', False):
        return ''
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    if text.endswith('.0') and text[:-2].isdigit():
        return text[:-2]
    return text


class BogService(models.AbstractModel):
    _name = 'bog.service'
    _description = 'Bank of Georgia REST Client'
    _inherit = 'gec.bank.service'

    _gec_bank_log_model = 'bog.api.log'
    _gec_bank_sensitive_keys = SENSITIVE_KEYS

    @staticmethod
    def _api_url(path):
        return f"{API_BASE}/{path.lstrip('/')}"

    @staticmethod
    def split_account_currency(account_number):
        """Split a BOG account string into (iban, currency_or_None); endpoints reject an IBAN with currency appended."""
        value = (account_number or '').strip().upper().replace(' ', '')
        if len(value) > 3 and value[-3:].isalpha() and value[:2] == 'GE':
            return value[:-3], value[-3:]
        return value, None

    def authenticate(self, connection):
        """Fetch an OAuth2 token for the connection; True if state became 'active', else 'error'."""
        connection = connection.sudo()
        client_id = connection.client_id or ''
        client_secret = connection.client_secret or ''
        if not client_id or not client_secret:
            connection._gec_bank_write_connection({'state': 'error',
                                                   'last_error_code': 0,
                                                   'last_error_message': _("Client ID and Client Secret are required.")})
            return False

        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {'Authorization': f"Basic {basic}",
                   'Content-Type': 'application/x-www-form-urlencoded'}
        # Credentials go in both the body and the Basic header, as in BOG's own collection.
        body = {'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret}

        start = time.monotonic()
        http_status = 0
        response_text = ''
        try:
            resp = requests.post(TOKEN_URL, headers=headers, data=body, timeout=REQUEST_TIMEOUT)
            http_status = resp.status_code
            response_text = resp.text or ''
            correlation_id = resp.headers.get('x-correlationid') or ''
            resp.raise_for_status()
            data = self._parse_json(response_text) or {}
        except requests.Timeout:
            self._record_log(connection, 'oauth/token', body, '', http_status,
                             'Request timed out', start)
            connection._gec_bank_write_connection({'state': 'error',
                                                   'last_error_message': _("Bank of Georgia token request timed out.")})
            return False
        except requests.ConnectionError:
            self._record_log(connection, 'oauth/token', body, '', http_status,
                             'Bank unreachable', start)
            connection._gec_bank_write_connection({'state': 'error',
                                                   'last_error_message': _("Bank of Georgia is unreachable.")})
            return False
        except (requests.HTTPError, ValueError, requests.RequestException) as exc:
            self._record_log(connection, 'oauth/token', body, response_text, http_status,
                             str(exc), start)
            connection._gec_bank_write_connection({'state': 'error',
                                                   'last_error_code': http_status,
                                                   'last_error_message': (response_text or str(exc)
                                                                          or _("Authentication failed."))[:255]})
            return False

        self._record_log(connection, 'oauth/token', body, response_text, http_status, '',
                         start, correlation_id=correlation_id)
        token = data.get('access_token')
        expires_in = data.get('expires_in') or DEFAULT_TOKEN_LIFETIME
        if not token:
            connection._gec_bank_write_connection({'state': 'error',
                                                   'last_error_code': http_status,
                                                   'last_error_message': _("No access token in Bank of Georgia response.")})
            return False

        connection.store_token(token, int(expires_in),
                               {'state': 'active', 'last_error_code': 0, 'last_error_message': False})
        return True

    def _ensure_token(self, connection):
        """Authenticate if the token is not valid."""
        if not connection.token_is_valid():
            if not self.authenticate(connection):
                raise UserError(_("Bank of Georgia authentication failed: %s")
                                % (connection.sudo().last_error_message or _("check the credentials.")))

    @staticmethod
    def _throttle():
        """Block until one more request stays inside 5 requests/second (this worker only)."""
        while True:
            with _rate_lock:
                now = time.monotonic()
                while _rate_calls and now - _rate_calls[0] >= RATE_WINDOW:
                    _rate_calls.popleft()
                if len(_rate_calls) < RATE_LIMIT_PER_SECOND:
                    _rate_calls.append(now)
                    return
                wait = RATE_WINDOW - (now - _rate_calls[0])
            # Sleep outside the lock so other threads can drain the window.
            time.sleep(max(wait, 0.01))

    def _call(self, connection, path, method='GET', params=None, payload=None,
              allow_reauth_retry=True, soft=False, timeout=None, money=False,
              retries_429=MAX_429_RETRIES, files=None):
        """Authenticated call to an api.businessonline.ge endpoint; returns the parsed body. soft=True never
        raises: returns {'http_status', 'data', 'error_text', 'result_code', 'correlation_id'},
        http_status=0 without a response (ambiguous)."""
        connection = connection.sudo()
        self._ensure_token(connection)
        url = self._api_url(path)
        headers = {'Authorization': f"Bearer {connection.access_token}",
                   'Accept': 'application/json'}
        if files:
            # Never log file bytes: they may hold a contract or an invoice.
            log_payload = {'files': [value[0] for value in files.values()]}
        else:
            log_payload = params if method.upper() == 'GET' else (payload or {})

        self._throttle()
        start = time.monotonic()
        http_status = 0
        response_text = ''
        try:
            resp = requests.request(method, url, headers=headers, params=params,
                                    json=None if files else payload, files=files,
                                    timeout=timeout or REQUEST_TIMEOUT)
            http_status = resp.status_code
            response_text = resp.text or ''
        except requests.Timeout:
            self._record_log(connection, path, log_payload, '', http_status,
                             'Request timed out', start, money=money)
            if soft:
                return self._soft_failure('Request timed out')
            raise UserError(_("Bank of Georgia request timed out. Please try again."))
        except requests.ConnectionError:
            self._record_log(connection, path, log_payload, '', http_status,
                             'Bank unreachable', start, money=money)
            if soft:
                return self._soft_failure('Bank unreachable')
            raise UserError(_("Bank of Georgia is unreachable."))
        except requests.RequestException as exc:
            self._record_log(connection, path, log_payload, response_text, http_status,
                             str(exc), start, money=money)
            if soft:
                return self._soft_failure(str(exc))
            raise UserError(_("Bank of Georgia request failed."))

        correlation_id = resp.headers.get('x-correlationid') or ''
        retry_after = self._retry_after_seconds(resp)
        data = self._parse_json(response_text)
        result_code = self._extract_result_code(data)

        self._record_log(connection, path, log_payload, response_text, http_status, '',
                         start, correlation_id=correlation_id, result_code=result_code,
                         retry_after=retry_after, money=money)

        # A 429 is rejected before processing, so a retry is safe even for a document POST.
        if http_status == 429 and retries_429 > 0:
            time.sleep(min(retry_after or 1, MAX_RETRY_AFTER))
            return self._call(connection, path, method=method, params=params, payload=payload,
                              allow_reauth_retry=allow_reauth_retry, soft=soft, timeout=timeout,
                              money=money, retries_429=retries_429 - 1, files=files)

        if http_status == 401 and allow_reauth_retry:
            connection.clear_token()
            if self.authenticate(connection):
                return self._call(connection, path, method=method, params=params, payload=payload,
                                  allow_reauth_retry=False, soft=soft, timeout=timeout,
                                  money=money, retries_429=retries_429, files=files)

        if soft:
            return {'http_status': http_status,
                    'data': data,
                    'error_text': response_text,
                    'result_code': result_code,
                    'correlation_id': correlation_id}

        if http_status >= 400:
            raise UserError(_("Bank of Georgia error %(status)s: %(body)s",
                              status=http_status, body=(response_text or '')[:200]))
        return data

    @staticmethod
    def _soft_failure(error_text):
        """No response at all: the outcome is unknown, not failed."""
        return {'http_status': 0, 'data': None, 'error_text': error_text,
                'result_code': None, 'correlation_id': ''}

    @staticmethod
    def _extract_result_code(data):
        """BOG's business ResultCode, e.g. 363 (duplicate), which comes with HTTP 200."""
        if isinstance(data, list):
            first = data[0] if data else None
            return first.get('ResultCode') if isinstance(first, dict) else None
        if isinstance(data, dict):
            return data.get('ResultCode')
        return None

    @staticmethod
    def _retry_after_seconds(response):
        try:
            return int(response.headers.get('Retry-After') or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _format_date(value):
        """BOG statement paths take date-only strings: 2026-01-31."""
        if not value:
            return value
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d')
        return str(value)[:10]

    def get_statement(self, connection, account_number, currency_code, date_from, date_to):
        """GET api/v2/statement/{account}/{currency}/{startDate}/{endDate}: first page, totalCount and paging id."""
        iban, embedded = self.split_account_currency(account_number)
        currency = currency_code or embedded
        path = (f"v2/statement/{iban}/{currency}"
                f"/{self._format_date(date_from)}/{self._format_date(date_to)}")
        return self._call(connection, path)

    def get_statement_page(self, connection, account_number, currency_code, statement_id, page):
        """GET api/v2/statement/{account}/{currency}/{id}/{page} -> a bare array; pages must be read in order."""
        iban, embedded = self.split_account_currency(account_number)
        currency = currency_code or embedded
        return self._call(connection, f"v2/statement/{iban}/{currency}/{statement_id}/{page}")

    def fetch_all_records(self, connection, account_number, currency_code, date_from, date_to):
        """Return all record dicts of a period, paged. ``totalCount`` says when to stop, else a short page; a
        period cut off part-way raises; ``count`` is the page size, unused."""
        data = self.get_statement(connection, account_number, currency_code, date_from, date_to)
        if not isinstance(data, dict):
            raise UserError(_("Unexpected statement payload from Bank of Georgia."))

        records = list(self._first_key(data, ('records', 'Records'), []) or [])
        total = self._first_key(data, ('totalCount', 'TotalCount'))
        statement_id = self._first_key(data, ('id', 'Id'))
        if self._statement_complete(records, records, total):
            return records
        if not statement_id:
            raise UserError(_(
                "Bank of Georgia sent %(count)s entries of %(account)s but no statement id to "
                "read the rest. Nothing was imported; import a shorter period.",
                count=len(records), account=account_number))

        # The first response is page 1, so continue from 2.
        for page in range(2, MAX_STATEMENT_PAGES + 2):
            batch = self.get_statement_page(connection, account_number, currency_code,
                                            statement_id, page)
            if isinstance(batch, dict):
                batch = self._first_key(batch, ('records', 'Records'), []) or []
            if not batch:
                if total is None:
                    return records
                raise UserError(_(
                    "Bank of Georgia sent %(count)s of the %(total)s entries of %(account)s and "
                    "then stopped. Nothing was imported; import the period again later.",
                    count=len(records), total=total, account=account_number))
            records.extend(batch)
            if self._statement_complete(records, batch, total):
                return records
        # Ceiling hit: raise rather than return a partial period.
        raise UserError(_("Bank of Georgia returned more than %(pages)s pages for %(account)s. "
                          "Import a shorter period.",
                          pages=MAX_STATEMENT_PAGES, account=account_number))

    @staticmethod
    def _statement_complete(records, page, total):
        """True once ``totalCount`` records are read, else when the last page is short."""
        if total is not None:
            return len(records) >= total
        return len(page) < STATEMENT_PAGE_SIZE

    def get_statement_summary(self, connection, account_number, currency_code, date_from, date_to):
        """GET api/v2/statement/summary/{account}/{currency}/{startDate}/{endDate}"""
        iban, embedded = self.split_account_currency(account_number)
        currency = currency_code or embedded
        path = (f"v2/statement/summary/{iban}/{currency}"
                f"/{self._format_date(date_from)}/{self._format_date(date_to)}")
        return self._call(connection, path)

    def get_today_activities(self, connection, account_number, currency_code=None):
        """GET api/documents/todayactivities/{account}/{currency}. Quota 800/day per account and currency: only
        for recovering a timed-out POST. BOG's docs say api/v2/, its Postman collection the unversioned
        path; the collection works."""
        iban, embedded = self.split_account_currency(account_number)
        currency = currency_code or embedded
        return self._call(connection, f"documents/todayactivities/{iban}/{currency}")

    def create_domestic(self, connection, documents):
        """POST api/documents/domestic; the payload is a bare array. Soft mode, so a timeout is not a rejection."""
        return self._call(connection, 'documents/domestic', method='POST',
                          payload=list(documents), soft=True,
                          timeout=TRANSFER_TIMEOUT, money=True)

    def create_foreign(self, connection, documents):
        """POST api/documents/foreign - same shape, foreign currency."""
        return self._call(connection, 'documents/foreign', method='POST',
                          payload=list(documents), soft=True,
                          timeout=TRANSFER_TIMEOUT, money=True)

    def create_bulk_domestic(self, connection, documents, file_name):
        """POST api/documents/bulk/domestic?fileName={fileName}. The payload is a flat array; the response is a
        bare integer, the batch's UniqueKey; per-line results come only from get_bulk_status()."""
        return self._call(connection, 'documents/bulk/domestic', method='POST',
                          params={'fileName': file_name}, payload=list(documents),
                          soft=True, timeout=TRANSFER_TIMEOUT, money=True)

    def create_bulk_foreign(self, connection, documents, file_name):
        """POST api/documents/bulk/foreign?fileName={fileName} - same shape."""
        return self._call(connection, 'documents/bulk/foreign', method='POST',
                          params={'fileName': file_name}, payload=list(documents),
                          soft=True, timeout=TRANSFER_TIMEOUT, money=True)

    def get_bulk_status(self, connection, bulk_key):
        """GET api/documents/bulk/status/{key} -> Status + BulkLineStatus[]."""
        return self._call(connection, f"documents/bulk/status/{bulk_key}", soft=True)

    def delete_bulk(self, connection, bulk_key):
        """DELETE api/documents/bulk/{key} - cancel a batch that is not yet signed."""
        return self._call(connection, f"documents/bulk/{bulk_key}", method='DELETE',
                          soft=True, money=True)

    def get_document_status(self, connection, document_key):
        """GET api/documents/status/{key} -> Status, RejectCode, ResultCode, Match; key is BOG's UniqueKey."""
        return self._call(connection, f"documents/status/{document_key}", soft=True)

    def delete_document(self, connection, document_key):
        """DELETE api/documents/{key} - cancel a document that is not yet signed."""
        return self._call(connection, f"documents/{document_key}", method='DELETE',
                          soft=True, money=True)

    def upload_file(self, connection, file_name, content):
        """POST api/files/upload (multipart) -> externalFileHash, which goes into AttachmentIds."""
        extension = (file_name or '').rsplit('.', 1)[-1].lower() if '.' in (file_name or '') else ''
        if extension not in BOG_ALLOWED_UPLOAD_EXTENSIONS:
            raise UserError(_("Bank of Georgia does not accept '.%(ext)s' files. Allowed: %(list)s",
                              ext=extension or '?',
                              list=', '.join(sorted(BOG_ALLOWED_UPLOAD_EXTENSIONS))))
        files = {'file': (file_name, content)}
        result = self._call(connection, 'files/upload', method='POST', files=files,
                            soft=True, timeout=TRANSFER_TIMEOUT)
        http_status = result.get('http_status', 0)
        if not (http_status and 200 <= http_status < 300):
            raise UserError(_("Bank of Georgia refused the upload of %(name)s: %(error)s",
                              name=file_name,
                              error=result.get('error_text') or http_status or _("no response")))
        data = result.get('data')
        # The body is a bare quoted string.
        file_hash = (data.get('externalFileHash') or data.get('ExternalFileHash')) if isinstance(data, dict) else data
        if isinstance(file_hash, str) and file_hash.strip():
            return file_hash.strip()
        raise UserError(_("Bank of Georgia returned no file hash for %s.") % file_name)

    def _record_log(self, connection, endpoint, request_payload, response_text,
                    http_status, error_message, start_monotonic, correlation_id='',
                    result_code=None, retry_after=0, money=False):
        self._write_log(dict(
            self._log_vals(connection, endpoint, request_payload, response_text,
                           http_status, error_message, start_monotonic),
            result_code=result_code or 0, correlation_id=correlation_id or '',
            retry_after=retry_after or 0, is_money_movement=money))
