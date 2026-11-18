import logging

import requests

from odoo.exceptions import UserError
from odoo.tools.urls import urljoin

_logger = logging.getLogger(__name__)

BASE_URL = 'https://portal.signifyapp.com/integration-api/v2/'
OAUTH_URL = 'https://portal.signifyapp.com/oauth/'
OAUTH_SCOPE = 'ALL openid email'
START_ROUTE = '/signify/oauth/start'
CALLBACK_ROUTE = '/signify/oauth/callback'
TIMEOUT = 15
FILE_TIMEOUT = 60
SIGNATURE_WIDTH = 150
SIGNATURE_HEIGHT = 60
STATUS_BATCH_SIZE = 500


class SignifyError(UserError):
    """``status_code`` is Signify's ``statusCode``, if any."""

    context = {'exception_class': 'odoo.exceptions.UserError'}

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SignifyTransportError(UserError):
    """Timeout or connection failure: the request may or may not have reached Signify."""

    context = {'exception_class': 'odoo.exceptions.UserError'}


def oauth_redirect_uri(env):
    return urljoin(env['ir.config_parameter'].sudo().get_str('web.base.url'), CALLBACK_ROUTE)


def _send(env, method, url, **kwargs):
    try:
        return requests.request(method, url, **kwargs)
    except requests.Timeout:
        raise SignifyTransportError(env._("Signify did not answer in time. Please try again."))
    except requests.ConnectionError:
        raise SignifyTransportError(env._("Signify is unreachable."))
    except requests.RequestException:
        raise SignifyTransportError(env._("The request to Signify failed."))


def oauth_client_credentials(env):
    parameters = env['ir.config_parameter'].sudo()
    client_id, client_secret = parameters.get_str('signify.client_id'), parameters.get_str('signify.client_secret')
    if not client_id or not client_secret:
        raise UserError(env._("Signify is not set up: fill in the Client ID and Client Secret in Settings."))
    return client_id, client_secret


def oauth_call(env, endpoint, data=None, token=None):
    """Return the JSON body of a Signify OAuth endpoint, None when it is empty. A token makes it a GET (userinfo)."""
    if token:
        method, kwargs = 'GET', {'headers': {'Authorization': f'Bearer {token}'}}
    else:
        method, kwargs = 'POST', {'data': data, 'auth': oauth_client_credentials(env)}
    response = _send(env, method, OAUTH_URL + endpoint, timeout=TIMEOUT, **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = None
    if not 200 <= response.status_code < 300:
        error = body if isinstance(body, dict) else {}
        message = env._("Signify answered with HTTP %(code)s.", code=response.status_code)
        raise SignifyError(error.get('error_description') or error.get('error') or message, status_code=error.get('error'))
    return body


class SignifyAPI:

    def __init__(self, connection):
        if not connection:
            raise UserError(connection.env._("Connect your Signify account first (Signify > Configuration > Signify Accounts)."))
        self.env = connection.env
        self._language = 'ka' if (self.env.lang or '').startswith('ka') else 'en'
        self._connection = connection
        self._token = connection._get_access_token()

    def call(self, operation, payload, timeout=TIMEOUT):
        """Return the SUCCESS body; an expired token is renewed once."""
        response = self._post(operation, payload, timeout)
        if response.status_code == 401:
            self._token = self._connection._get_access_token(stale=self._token)
            response = self._post(operation, payload, timeout)
        return self._parse(operation, response)

    def _post(self, operation, payload, timeout):
        headers = {'X-Language': self._language, 'Content-Type': 'application/json', 'Authorization': f'Bearer {self._token}'}
        return _send(self.env, 'POST', BASE_URL + operation, json=payload, headers=headers, timeout=timeout)

    def _parse(self, operation, response):
        """Read the body before the HTTP code: Signify answers 400 with a JSON body."""
        try:
            body = response.json()
        except ValueError:
            body = None
        message = self.env._("Signify answered with HTTP %(code)s.", code=response.status_code)
        if not isinstance(body, dict):
            raise UserError(message)
        _logger.info("Signify %s: %s", operation, body.get('status'))
        if body.get('status') != 'SUCCESS':
            message = body.get('statusMessage') or message
            missing_signature = "At least one signature field should be added for each signer"
            if message in (missing_signature, f'{missing_signature}.'):
                message = self.env._("Check that each signer's Signature Keyword matches searchable text in the uploaded file.")
            raise SignifyError(message, status_code=body.get('statusCode'))
        return body
