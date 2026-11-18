import logging
import time
import uuid
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RS_REST_BASE_URL = "https://eapi.rs.ge"
RS_REST_AUTH_PATH = "/Users/Authenticate"
RS_REST_AUTH_PIN_PATH = "/Users/AuthenticatePin"
RS_REST_SIGNOUT_PATH = "/Users/SignOut"
RS_REST_TIMEOUT = 30
RS_REST_TOKEN_REFRESH_BUFFER_SECONDS = 60

# STATUS.ID values meaning auth rejected: the token is dead, re-authenticate
_RS_REST_AUTH_REJECTED_STATUS_IDS = frozenset([-104, -105])
# STATUS.ID values meaning a transient server error: retry with backoff
_RS_REST_TRANSIENT_STATUS_IDS = frozenset([-1])
_RS_REST_TRANSIENT_BACKOFF_SECONDS = (1, 3, 8)

# Hints only for error codes that mean the same on every endpoint
_RS_REST_ERROR_HINTS = {
    -1: "სისტემური შეცდომა RS-ის მხარეს. სცადეთ მოგვიანებით.",
    -2: "არასწორი ქმედება — შეამოწმეთ მოთხოვნის პარამეტრები.",
    -104: "ავტორიზაცია უარყოფილია — token არასწორია ან ვადაგასულია, ან მომხმარებელს არ აქვს ამ სერვისზე წვდომა.",
    -105: "ავტორიზაცია უარყოფილია — RS-ზე ანგარიშზე ეს სერვისი არ არის ჩართული.",
}

# rs.ge fields stored per company on res.users.settings and proxied on res.users
RS_SETTINGS_FIELDS = ('rs_username', 'rs_password', 'rs_user_id', 'rs_un_id', 'rs_is_responsible', 'rs_access_token', 'rs_token_expiry',
    'rs_device_code', 'rs_device_paired_on')


def _rs_settings_inverse(fname):
    """Build the inverse of one proxy field; one per field, since a shared inverse would write False over the others."""
    def _inverse(self):
        for user in self:
            self.env['res.users.settings']._find_or_create_for_user(user)[fname] = user[fname]
    return _inverse


class ResUsers(models.Model):
    _inherit = 'res.users'

    rs_username = fields.Char(string='RS Username', compute='_compute_rs_credentials', inverse='_inverse_rs_username', groups='base.group_user',
        user_writeable=True,
        help="Revenue Service (rs.ge) login for the company you are working in; switch company to fill in another company's login. The same login "
        "serves the SOAP e-invoice service and the REST employee-registry service.")
    rs_password = fields.Char(string='RS Password', compute='_compute_rs_credentials', inverse='_inverse_rs_password', groups='base.group_user',
        user_writeable=True, help="Revenue Service (rs.ge) password for the company you are working in.")
    rs_user_id = fields.Char(string='RS User ID (SOAP)', compute='_compute_rs_credentials', inverse='_inverse_rs_user_id',
        help="SOAP e-service user id, fetched automatically after a successful SOAP test.")
    rs_un_id = fields.Integer(string='RS Taxpayer ID', compute='_compute_rs_credentials', inverse='_inverse_rs_un_id',
        help="rs.ge id of this company's taxpayer, resolved from the company Tax ID by Test RS Credentials. Every document is filed for this "
        "taxpayer, whichever taxpayer the login belongs to.")
    rs_is_responsible = fields.Boolean(string='RS Responsible User', compute='_compute_rs_credentials', inverse='_inverse_rs_is_responsible',
        help="The user whose login runs the automated rs.ge operations of this company (buyer-invoice sync, status refresh, employee registry). One "
        "per company.")
    rs_access_token = fields.Char(string='RS Access Token (REST)', compute='_compute_rs_credentials', inverse='_inverse_rs_access_token',
        groups='base.group_system', help="Cached bearer token for the RS Employee Registry REST API (eapi.rs.ge).")
    rs_token_expiry = fields.Datetime(string='RS Token Expiry (REST)', compute='_compute_rs_credentials', inverse='_inverse_rs_token_expiry',
        help="When the cached REST token stops being valid.")
    rs_device_code = fields.Char(string='RS Device Code (REST)', compute='_compute_rs_credentials', inverse='_inverse_rs_device_code',
        groups='base.group_system',
        help="GUID generated during 2FA pairing. Sent on every /Users/Authenticate so RS skips the SMS step for this 'remembered' device. Cleared "
        "when creds change.")
    rs_device_paired_on = fields.Datetime(string='RS Device Paired On', compute='_compute_rs_credentials', inverse='_inverse_rs_device_paired_on',
        help="When the current rs_device_code was issued (useful for troubleshooting).")
    rs_company_id = fields.Many2one('res.company', string='Credentials for Company', compute='_compute_rs_company_id',
        help="The rs.ge fields on this form belong to this company, the one you are working in.")

    @api.depends(*['res_users_settings_id.%s' % fname for fname in RS_SETTINGS_FIELDS])
    @api.depends_context('uid', 'company')
    def _compute_rs_credentials(self):
        """Show the active company's rs.ge fields only where the user may
        edit; values sit on res.users.settings (owner and admins)."""
        for user in self:
            settings = user._filtered_access('write').res_users_settings_id
            for fname in RS_SETTINGS_FIELDS:
                user[fname] = settings[fname]

    _inverse_rs_username = _rs_settings_inverse('rs_username')
    _inverse_rs_password = _rs_settings_inverse('rs_password')
    _inverse_rs_user_id = _rs_settings_inverse('rs_user_id')
    _inverse_rs_un_id = _rs_settings_inverse('rs_un_id')
    _inverse_rs_is_responsible = _rs_settings_inverse('rs_is_responsible')
    _inverse_rs_access_token = _rs_settings_inverse('rs_access_token')
    _inverse_rs_token_expiry = _rs_settings_inverse('rs_token_expiry')
    _inverse_rs_device_code = _rs_settings_inverse('rs_device_code')
    _inverse_rs_device_paired_on = _rs_settings_inverse('rs_device_paired_on')

    @api.depends_context('company')
    def _compute_rs_company_id(self):
        """The company whose rs.ge fields the form shows: the active one."""
        self.rs_company_id = self.env.company

    def write(self, vals):
        """New credentials reset the REST token, SOAP user id, taxpayer
        id and paired device (sudo: users may not write them)."""
        res = super().write(vals)
        if 'rs_username' in vals or 'rs_password' in vals:
            reset = {fname: False for fname in ('rs_access_token', 'rs_token_expiry', 'rs_user_id', 'rs_un_id', 'rs_device_code',
                'rs_device_paired_on') if fname not in vals}
            if reset:
                self.sudo().write(reset)
        return res

    def _get_rs_credentials(self):
        """Return the user's rs.ge login for the active company as
        the SOAP services take it; raise UserError if missing."""
        self.ensure_one()
        if not self.rs_username or not self.rs_password:
            raise UserError(_("User %(user)s has no Revenue Service credentials for %(company)s. Switch to that company, open User Preferences and "
                "fill in RS Username and RS Password.", user=self.display_name, company=self.env.company.display_name))
        return {'su': self.rs_username, 'sp': self.rs_password, 'user_id': int(self.rs_user_id) if self.rs_user_id else 0}

    @api.model
    def _rs_responsible_user(self, company):
        """Return the active RS Responsible user of ``company`` with a login there, or empty."""
        settings = self.env['res.users.settings'].sudo().with_company(company).search([
            ('rs_is_responsible', '=', True),
            ('rs_username', '!=', False),
            ('rs_password', '!=', False),
            ('user_id.active', '=', True),
            ('user_id.company_ids', 'in', company.id),
        ], limit=1)
        return settings.user_id

    def action_rs_test_credentials(self):
        """Validate the SOAP login and store the rs.ge user id and taxpayer
        id; another taxpayer's login must pass a read for this company."""
        self.ensure_one()
        try:
            from zeep import Client  # noqa: F401, PLC0415
        except ImportError:
            raise UserError(_("Python package 'zeep' is required. Install it with: pip install zeep"))

        if not self.rs_username or not self.rs_password:
            raise UserError(_("Fill in RS Username and RS Password first."))
        company = self.env.company
        tin = (company.vat or '').strip()
        if not tin.isdigit():
            raise UserError(_("Company %s needs a numeric Tax ID before its rs.ge login can be tested.", company.display_name))

        # Calls below use the tested user's login, not the current user's
        service = self.env['rs.soap.service'].with_user(self)
        try:
            client = service._get_client()
            result = client.service.chek(su=self.rs_username, sp=self.rs_password, user_id=0)
        except Exception as e:
            _logger.exception("RS SOAP credential test failed for user %s", self.login)
            raise UserError(_("Could not reach the Revenue Service SOAP endpoint: %s", e))

        ok = getattr(result, 'chekResult', result)
        fetched_user_id = getattr(result, 'user_id', None)
        if not ok:
            raise UserError(_("SOAP authentication failed. Double-check the RS Username and RS Password."))

        if fetched_user_id:
            self.sudo().rs_user_id = str(fetched_user_id)

        try:
            own_un_id = int(service.get_seller_un_id() or 0)
            company_un_id = int(service.get_un_id_from_tin(tin))
        except Exception as e:
            raise UserError(_("Could not resolve the taxpayer of %(company)s (Tax ID %(tin)s) on rs.ge: %(err)s", company=company.display_name,
                tin=tin, err=e))
        representative = own_un_id != company_un_id
        if representative:
            end = fields.Datetime.now()
            try:
                service.get_user_invoices(un_id=company_un_id, last_update_s=end - timedelta(hours=1), last_update_e=end)
            except Exception as e:
                raise UserError(_("This rs.ge login belongs to another taxpayer and rs.ge did not let it act for %(company)s (Tax ID %(tin)s): "
                    "%(err)s", company=company.display_name, tin=tin, err=e))
        self.sudo().rs_un_id = company_un_id
        waybill_ok, waybill_reason = self._rs_test_waybill_soap()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if waybill_ok else 'warning',
                'title': _("Revenue Service (rs.ge)"),
                'message': _("Credentials valid for %(company)s (Tax ID %(tin)s). RS User ID: %(uid)s. %(kind)s %(waybill)s",
                    company=company.display_name, tin=tin, uid=self.rs_user_id or _('n/a'),
                    kind=(_("Representative login: its own taxpayer is another Tax ID.") if representative else _("Own login of this taxpayer.")),
                    waybill=(_("Waybill service: OK.") if waybill_ok else _("Waybill service: not available (%s).", waybill_reason))),
                'sticky': not waybill_ok,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _rs_test_waybill_soap(self):
        """Check the login on WayBillService; never raises, return (True, '') or (False, reason)."""
        self.ensure_one()
        try:
            client, su, sp, _history = self.env['rs.waybill.soap.service'].with_user(self)._get_client()
            result = client.service.chek_service_user(su=su, sp=sp)
        except Exception as e:
            _logger.warning("RS waybill login test failed for user %s: %s", self.login, e)
            return False, str(e)
        if not getattr(result, 'chek_service_userResult', False):
            return False, _("RS.GE refused this login for the waybill service.")
        return True, ''

    def _rs_rest_token_is_fresh(self):
        self.ensure_one()
        token = self.sudo().rs_access_token
        expiry = self.sudo().rs_token_expiry
        if not token or not expiry:
            return False
        return expiry > fields.Datetime.now() + timedelta(seconds=RS_REST_TOKEN_REFRESH_BUFFER_SECONDS)

    def _rs_rest_call(self, path, payload):
        """POST to an auth endpoint; return its DATA or raise UserError."""
        try:
            response = requests.post(RS_REST_BASE_URL + path, json=payload, headers={'Content-Type': 'application/json'}, timeout=RS_REST_TIMEOUT)
            response.raise_for_status()
            parsed = response.json()
        except requests.RequestException as e:
            _logger.exception("RS REST call failed at %s for user %s", path, self.login)
            raise UserError(_("Could not reach the Revenue Service REST endpoint: %s", e))
        except ValueError as e:
            raise UserError(_("Revenue Service returned invalid JSON: %s", e))

        status = parsed.get('STATUS') or {}
        if status.get('ID') != 0:
            raise UserError(_("REST call %(path)s failed: [%(id)s] %(text)s", path=path, id=status.get('ID'), text=status.get('TEXT') or ''))
        return parsed.get('DATA') or {}

    def _rs_rest_authenticate_step1(self):
        """Call /Users/Authenticate; return ('access', token, expires_in)
        or ('pin', pin_token, masked_mobile) when the SMS PIN is needed."""
        self.ensure_one()
        if not self.rs_username or not self.rs_password:
            raise UserError(_("User %s has no Revenue Service credentials. Open User Preferences and fill in RS Username and RS Password.",
                self.display_name))
        payload = {'USERNAME': self.rs_username, 'PASSWORD': self.rs_password, 'DEVICE_CODE': self.sudo().rs_device_code or None}
        data = self._rs_rest_call(RS_REST_AUTH_PATH, payload)
        token = data.get('ACCESS_TOKEN')
        if token:
            return 'access', token, int(data.get('EXPIRES_IN') or 2400)
        pin_token = data.get('PIN_TOKEN')
        if pin_token:
            return 'pin', pin_token, data.get('MASKED_MOBILE') or ''
        raise UserError(_("Authenticate returned neither ACCESS_TOKEN nor PIN_TOKEN."))

    def _rs_rest_complete_pin(self, pin_token, pin):
        """Call /Users/AuthenticatePin; store the token and device code so later logins skip the SMS."""
        self.ensure_one()
        device_code = str(uuid.uuid4())
        payload = {
            'PIN_TOKEN': pin_token,
            'PIN': pin,
            'DEVICE_CODE': device_code,
            'ADDRESS': _('Odoo'),
            'BROWSER': _('Odoo rs_base_methods'),
            'OPER_SYSTEM': _('server'),
        }
        data = self._rs_rest_call(RS_REST_AUTH_PIN_PATH, payload)
        token = data.get('ACCESS_TOKEN')
        if not token:
            raise UserError(_("AuthenticatePin returned no ACCESS_TOKEN."))
        expires_in = int(data.get('EXPIRES_IN') or 2400)
        self.sudo().write({
            'rs_access_token': token,
            'rs_token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in),
            'rs_device_code': device_code,
            'rs_device_paired_on': fields.Datetime.now(),
        })
        return token

    def _rs_rest_authenticate(self, force=False):
        """Return a valid token, from cache if fresh; raise UserError when 2FA
        needs a PIN (interactive callers use action_rs_test_rest_credentials)."""
        self.ensure_one()
        if not force and self._rs_rest_token_is_fresh():
            return self.sudo().rs_access_token

        kind, value, meta = self._rs_rest_authenticate_step1()
        if kind == 'access':
            token = value
            expires_in = meta
            self.sudo().write({'rs_access_token': token, 'rs_token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in)})
            return token

        if self.sudo().rs_device_code:
            _logger.warning("RS REST: DEVICE_CODE rejected for user %s — pairing needs renewal.", self.login)
            self.sudo().write({'rs_device_code': False, 'rs_device_paired_on': False})
        raise UserError(_("This RS account requires 2-step authentication. Open Settings > Users > %(user)s > Preferences > Revenue Service (rs.ge) "
            "and click 'Test REST (employee registry)' to enter the SMS PIN and pair this device.", user=self.display_name))

    def _get_rs_rest_token(self, force=False):
        """Return a fresh REST bearer token for this user."""
        self.ensure_one()
        return self._rs_rest_authenticate(force=force)

    def action_rs_test_rest_credentials(self):
        """Test the REST login; open the PIN wizard when 2FA needs a device pairing."""
        self.ensure_one()
        kind, value, meta = self._rs_rest_authenticate_step1()
        if kind == 'access':
            token = value
            expires_in = meta
            self.sudo().write({'rs_access_token': token, 'rs_token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in)})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _("Revenue Service — REST (employee registry)"),
                    'message': _("Credentials valid. Token expires at %s.", fields.Datetime.to_string(self.sudo().rs_token_expiry)),
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        if self.sudo().rs_device_code:
            self.sudo().write({'rs_device_code': False, 'rs_device_paired_on': False})
        wizard = self.env['rs.auth.pin.wizard'].create({
            'user_id': self.id,
            'company_id': self.env.company.id,
            'pin_token': value,
            'masked_mobile': meta,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('RS 2-Step Authentication'),
            'res_model': 'rs.auth.pin.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # Other modules call _rs_rest_authenticated_call.

    def _rs_rest_format_status_error(self, path, status_id, status_text):
        """Return the error text of an RS STATUS object, with a Georgian hint when the code has one."""
        hint = _RS_REST_ERROR_HINTS.get(status_id)
        if hint:
            return _("RS REST call %(path)s failed: [%(id)s] %(text)s\n%(hint)s", path=path, id=status_id, text=status_text or '', hint=hint)
        return _("RS REST call %(path)s failed: [%(id)s] %(text)s", path=path, id=status_id, text=status_text or '')

    def _rs_rest_authenticated_call(self, path, payload, method='POST'):
        """POST ``path`` with bearer token, return DATA. Re-authenticates once on HTTP 401 or STATUS.ID -104/-105;
        retries HTTP 5xx and STATUS.ID -1 with backoff (1s, 3s, 8s); else raises UserError. Never logs token or
        password. ``method='GET'`` is for GET-only endpoints (customs declarations); RS still reads the JSON body."""
        self.ensure_one()
        url = RS_REST_BASE_URL + path
        token = self._get_rs_rest_token()
        auth_retry_done = False
        transient_attempts = 0

        while True:
            headers = {'Content-Type': 'application/json', 'Authorization': 'bearer %s' % token}
            try:
                response = requests.request(method, url, json=payload, headers=headers, timeout=RS_REST_TIMEOUT)
            except requests.RequestException as e:
                _logger.exception("RS REST authenticated call failed at %s for user %s", path, self.login)
                raise UserError(_("Could not reach the Revenue Service REST endpoint at %(path)s: %(err)s", path=path, err=e))

            parsed = None
            try:
                parsed = response.json()
            except ValueError:
                parsed = None
            status = (parsed or {}).get('STATUS') or {}
            status_id = status.get('ID')
            status_text = status.get('TEXT')

            # Auth rejected: one forced re-auth, then give up
            is_auth_rejected = (response.status_code == 401 or status_id in _RS_REST_AUTH_REJECTED_STATUS_IDS)
            if is_auth_rejected:
                if auth_retry_done:
                    raise UserError(self._rs_rest_format_status_error(path, status_id, status_text or 'Unauthorized'))
                auth_retry_done = True
                _logger.info("RS REST: token rejected on %s (http=%s, status=%s) — re-authenticating as %s.", path, response.status_code, status_id,
                    self.login)
                token = self._rs_rest_authenticate(force=True)
                continue

            # Transient failure: retry with backoff
            is_transient = (response.status_code >= 500 or status_id in _RS_REST_TRANSIENT_STATUS_IDS)
            if is_transient and transient_attempts < len(_RS_REST_TRANSIENT_BACKOFF_SECONDS):
                delay = _RS_REST_TRANSIENT_BACKOFF_SECONDS[transient_attempts]
                transient_attempts += 1
                _logger.info("RS REST: transient failure on %s (http=%s, status=%s). Retry %s/%s after %ss.", path, response.status_code, status_id,
                    transient_attempts, len(_RS_REST_TRANSIENT_BACKOFF_SECONDS), delay)
                time.sleep(delay)
                continue

            if response.status_code >= 400 and status_id is None:
                raise UserError(_("RS REST call %(path)s returned HTTP %(code)s: %(text)s", path=path, code=response.status_code,
                    text=(response.text or '')[:200]))

            if parsed is None:
                raise UserError(_("RS REST call %(path)s returned a non-JSON response.", path=path))

            # Business error: not retryable
            if status_id is not None and status_id != 0:
                raise UserError(self._rs_rest_format_status_error(path, status_id, status_text))

            return parsed.get('DATA') or {}

    def _rs_rest_signout(self):
        """POST /Users/SignOut and clear the cached token; never raises,
        and keeps the device pairing (it survives sign-out on RS)."""
        self.ensure_one()
        token = self.sudo().rs_access_token
        if token:
            try:
                requests.post(RS_REST_BASE_URL + RS_REST_SIGNOUT_PATH, json={},
                    headers={'Content-Type': 'application/json', 'Authorization': 'bearer %s' % token}, timeout=RS_REST_TIMEOUT)
            except requests.RequestException:
                _logger.warning("RS REST: SignOut transport error for user %s — clearing cache anyway.", self.login)
        self.sudo().write({'rs_access_token': False, 'rs_token_expiry': False})

    def action_rs_signout_rest(self):
        """Sign out from REST button; administrators only."""
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only administrators can sign out other users from the RS REST API."))
        self._rs_rest_signout()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Revenue Service — REST"),
                'message': _("Signed out. Cached token cleared. Device pairing retained."),
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
