import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import consteq

from ..tools.signify_api import CALLBACK_ROUTE, OAUTH_SCOPE, OAUTH_URL, START_ROUTE, oauth_client_credentials, oauth_redirect_uri

_logger = logging.getLogger(__name__)


class SignifyOAuthController(http.Controller):

    def _error_page(self, message):
        return request.render('signify.signify_oauth_error', {'error': message}, status=400)

    @http.route(START_ROUTE, type='http', auth='user', methods=['GET'])
    def signify_oauth_start(self, company_id=None):
        user = request.env.user
        company = user.company_ids.filtered(lambda company: str(company.id) == company_id)
        if not company or not user.has_group('signify.group_signify_user'):
            raise request.not_found()
        try:
            client_id, _client_secret = oauth_client_credentials(request.env)
        except UserError as exc:
            return self._error_page(exc.args[0])
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(24)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        redirect_uri = oauth_redirect_uri(request.env)
        request.session['signify_oauth'] = {
            'state': state,
            'verifier': verifier,
            'company_id': company.id,
            'redirect_uri': redirect_uri,
        }
        query = urlencode({
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': OAUTH_SCOPE,
            'state': state,
            'code_challenge_method': 'S256',
            'code_challenge': challenge,
        })
        return request.redirect(f'{OAUTH_URL}authorize?{query}', local=False)

    @http.route(CALLBACK_ROUTE, type='http', auth='user', methods=['GET'])
    def signify_oauth_callback(self, code=None, state=None, error=None, error_description=None):
        pending = request.session.pop('signify_oauth', None)
        user = request.env.user
        if not user.has_group('signify.group_signify_user'):
            raise request.not_found()
        if not (pending and state and consteq(pending['state'], state)):
            return self._error_page(request.env._(
                "This Signify connection attempt was not found. Start again from Signify Accounts; if it happens again, ask your administrator."))
        if error:
            return self._error_page(request.env._("Signify did not connect: %s", error_description or error))
        company = request.env['res.company'].browse(pending['company_id'])
        if company not in user.company_ids:
            raise request.not_found()
        try:
            request.env['signify.connection']._signify_connect(company, code, pending['verifier'], pending['redirect_uri'])
        except UserError as exc:
            _logger.warning("Signify: connecting user %s failed: %s", user.id, exc)
            return self._error_page(request.env._("Signify did not connect: %s", exc))
        return request.redirect('/odoo/action-signify.action_signify_connection')
