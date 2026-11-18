import json
import logging
import time

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BASE_URL = "https://eapi.rs.ge"
SAVE_EMPLOYEE_PATH = "/Employees/SaveEmployee"
GET_EMPLOYEE_PATH = "/Employees/GetEmployee"
LIST_EMPLOYEES_PATH = "/Employees/ListEmployees"
GET_COUNTRIES_PATH = "/Employees/GetCountries"

DEFAULT_TIMEOUT = 30

TRANSIENT_STATUS_IDS = frozenset([-1])
PERMISSION_STATUS_IDS = frozenset([-104, -105])
TRANSIENT_BACKOFF_SECONDS = (1, 3, 8)


class EmployeeRegistryRsService(models.AbstractModel):
    _name = 'employee.registry.rs.service'
    _description = 'RS Employee Registry API Client'

    def _raw_post(self, path, payload, token, employee_id=None):
        url = BASE_URL + path
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'bearer {token}'

        request_body = json.dumps(payload, ensure_ascii=False)
        response_body = ''
        status_id = None
        status_text = None
        error_message = None
        try:
            response = requests.post(url, data=request_body.encode('utf-8'), headers=headers, timeout=DEFAULT_TIMEOUT)
            response_body = response.text or ''
            parsed = None
            try:
                parsed = response.json()
            except ValueError:
                parsed = None
            if parsed:
                status = parsed.get('STATUS') or {}
                status_id = status.get('ID')
                status_text = status.get('TEXT')

            if response.status_code == 401 or status_id in PERMISSION_STATUS_IDS:
                raise _UnauthorizedError(status_id=status_id, status_text=status_text)

            if response.status_code >= 500 or status_id in TRANSIENT_STATUS_IDS:
                raise _TransientError(status_id=status_id, status_text=status_text, http_status=response.status_code)

            # Structured RS business error (e.g. HTTP 400 + STATUS.ID=-30): show its Georgian text.
            if status_id is not None and status_id != 0:
                raise UserError(_("RS Employee Registry error on %(path)s: [%(id)s] %(text)s", path=path, id=status_id, text=status_text or ''))

            response.raise_for_status()
            if not parsed:
                raise UserError(_("RS Employee Registry returned a non-JSON response: %s", response_body[:200]))
            return parsed.get('DATA') or {}
        except (_UnauthorizedError, _TransientError) as e:
            error_message = str(e)
            raise
        except UserError:
            if not error_message:
                error_message = status_text or 'UserError'
            raise
        except requests.RequestException as e:
            error_message = f"Transport error: {e}"
            raise UserError(_("RS Employee Registry transport error: %s", e))
        finally:
            self._write_log(endpoint=path, employee_id=employee_id, request_payload=request_body, response_payload=response_body, status_id=status_id,
                status_text=status_text, error_message=error_message)

    def _request(self, path, payload, employee_id=None):
        """POST to rs.ge with the login and token of the employee's legal entity (root company).
        One REST session serves one employer, so the call uses that company whatever is active."""
        # rs_base_methods cannot be a manifest dependency (cycle), so check here for a clear message.
        if not hasattr(self.env['res.users'], '_get_rs_rest_token'):
            raise UserError(_("Install the RS Base Methods app under Apps: it holds the rs.ge logins this action needs."))
        user = self.env.user
        if employee_id:
            company = self.env['hr.employee'].browse(employee_id).sudo().company_id.root_id
            if company:
                user = user.with_company(company)
        token = user._get_rs_rest_token()

        _logger.info("RS Employee Registry: POST %s as user %s (id=%s) employee_id=%s", path, user.login, user.id, employee_id)

        auth_retry_done = False
        transient_attempts = 0

        while True:
            try:
                return self._raw_post(path, payload, token, employee_id=employee_id)
            except _UnauthorizedError as e:
                if auth_retry_done:
                    if e.status_id in PERMISSION_STATUS_IDS:
                        raise UserError(_(
                            "Revenue Service refused the operation: [%(id)s] %(text)s\n\n"
                            "The authenticated user has no permission for %(path)s. "
                            "Enable the 'დაქირავებულ პირთა რეესტრი' service on the rs.ge "
                            "account that corresponds to user '%(login)s'.",
                            id=e.status_id, text=e.status_text or '',
                            path=path, login=user.login,
                        ))
                    raise UserError(_("Revenue Service keeps rejecting the token for user '%s' on %s. Verify credentials and service permissions on "
                        "rs.ge.", user.login, path))
                auth_retry_done = True
                _logger.info("RS Employee Registry: token rejected (status=%s) on %s — re-authenticating as %s.", e.status_id, path, user.login)
                token = user._rs_rest_authenticate(force=True)
                continue
            except _TransientError as e:
                if transient_attempts >= len(TRANSIENT_BACKOFF_SECONDS):
                    raise UserError(_(
                        "Revenue Service keeps returning a system error on %(path)s after "
                        "%(attempts)s retries: [%(id)s] %(text)s\n\n"
                        "This is typically an RS-side issue — try again later or contact "
                        "api-support@rs.ge.",
                        path=path, attempts=transient_attempts,
                        id=e.status_id, text=e.status_text or '',
                    ))
                delay = TRANSIENT_BACKOFF_SECONDS[transient_attempts]
                transient_attempts += 1
                _logger.info("RS Employee Registry: transient error on %s (status=%s, http=%s). Retry %s/%s after %ss.", path, e.status_id,
                    e.http_status, transient_attempts, len(TRANSIENT_BACKOFF_SECONDS), delay)
                time.sleep(delay)
                continue

    def _write_log(self, **vals):
        """Store one API call on its own cursor, so it survives the caller's rollback.
        Readable by the employee's company (else the active one); read with sudo so no filter drops an audit row."""
        try:
            employee = self.env['hr.employee'].sudo().browse(vals.get('employee_id'))
            vals['company_id'] = employee.company_id.id or self.env.company.id
            with self.env.registry.cursor() as new_cr:
                self.env(cr=new_cr, context={}, su=True)['employee.registry.rs.log'].create(vals)
        except Exception:
            _logger.exception("Failed to write RS Employee Registry log row")

    @api.private
    def save_employee(self, employee_payload, employee_id=None):
        return self._request(SAVE_EMPLOYEE_PATH, employee_payload, employee_id=employee_id)

    @api.private
    def get_employee(self, rs_id, employee_id=None):
        return self._request(GET_EMPLOYEE_PATH, {'ID': int(rs_id)}, employee_id=employee_id)

    @api.private
    def list_employees(self, filters=None):
        return self._request(LIST_EMPLOYEES_PATH, filters or {})

    @api.private
    def get_countries(self, country_name=None, country_id=None):
        payload = {}
        if country_name:
            payload['COUNTRY_NAME'] = country_name
        if country_id:
            payload['COUNTRY_ID'] = country_id
        return self._request(GET_COUNTRIES_PATH, payload)

    @api.private
    def sync_countries_from_rs(self):
        """Fetch RS's country list into `res.country.rs_country_code`; returns (total_received, matched_to_odoo).
        Matches by Georgian name in ka_GE, whatever the user's language."""
        if not self.env['res.lang']._lang_get('ka_GE'):
            raise UserError(_("Activate the Georgian language first (Settings > Languages): RS.GE countries are matched by their Georgian names."))
        data = self.get_countries()
        countries = data.get('COUNTRIES') or []
        matched = 0
        Country = self.env['res.country'].sudo().with_context(lang='ka_GE')
        for row in countries:
            code = (row.get('country_id') or '').strip()
            name = (row.get('name') or '').strip()
            if not code or not name:
                continue
            country = Country.search([('name', '=', name)], limit=1)
            if country and country.rs_country_code != code:
                country.rs_country_code = code
                matched += 1
        return len(countries), matched

    @api.private
    def ensure_country_codes(self):
        """Fill RS country codes if none exist yet; runs on the first foreigner sync."""
        has_any = self.env['res.country'].sudo().search_count([('rs_country_code', '!=', False)])
        if has_any:
            return False
        self.sync_countries_from_rs()
        return True


class _UnauthorizedError(Exception):
    def __init__(self, status_id=None, status_text=None):
        super().__init__(f"401 Unauthorized (status_id={status_id})")
        self.status_id = status_id
        self.status_text = status_text


class _TransientError(Exception):
    def __init__(self, status_id=None, status_text=None, http_status=None):
        super().__init__(f"Transient error (http={http_status}, status_id={status_id})")
        self.status_id = status_id
        self.status_text = status_text
        self.http_status = http_status
