import logging
import time
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, LockError, UserError
from odoo.fields import Domain

from ..tools.signify_api import START_ROUTE, SignifyError, SignifyTransportError, oauth_call, oauth_client_credentials

_logger = logging.getLogger(__name__)


class SignifyConnection(models.Model):
    _name = 'signify.connection'
    _description = 'Signify Account'
    _rec_name = 'email'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade', default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade', default=lambda self: self.env.company)
    signify_sub = fields.Char(string="Signify Account ID", required=True, readonly=True)
    email = fields.Char(readonly=True)
    active = fields.Boolean(default=True)
    access_token = fields.Char(copy=False, groups='base.group_system')
    refresh_token = fields.Char(copy=False, groups='base.group_system')
    expiry = fields.Datetime(copy=False, groups='base.group_system')
    connected = fields.Boolean(compute='_compute_connected', compute_sudo=True)

    _unique_account = models.Constraint('UNIQUE(user_id, company_id, signify_sub)', "This Signify account is already connected.")
    _unique_active = models.UniqueIndex('(user_id, company_id) WHERE active')

    @api.depends('refresh_token')
    def _compute_connected(self):
        for connection in self:
            connection.connected = bool(connection.refresh_token)

    def action_connect(self):
        if not self.env.user.has_group('signify.group_signify_user'):
            raise AccessError(self.env._("Only Signify users can connect a Signify account."))
        oauth_client_credentials(self.env)  # stops here, inside Odoo, when Signify is not set up
        return {'type': 'ir.actions.act_url', 'url': f'{START_ROUTE}?company_id={self.env.company.id}', 'target': 'self'}

    @api.model
    def _signify_connect(self, company, code, verifier, redirect_uri):
        token = oauth_call(self.env, 'token', {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'code_verifier': verifier,
        })
        info = oauth_call(self.env, 'userinfo', token=token['access_token'])
        # sudo: users cannot write connections; the controller checked the user and the company
        connections = self.sudo().with_context(active_test=False).search([('user_id', '=', self.env.uid), ('company_id', '=', company.id)])
        connections.filtered(lambda connection: connection.active and connection.signify_sub != info['sub']).action_archive()
        connections.flush_recordset(['active'])  # the unique index on active allows one row, so the archive goes first
        vals = {
            'email': info.get('email'),
            'active': True,
            **self._token_values(token),
        }
        connection = connections.filtered(lambda connection: connection.signify_sub == info['sub'])
        if connection:
            connection.write(vals)
        else:
            connection = connections.create({
                'user_id': self.env.uid,
                'company_id': company.id,
                'signify_sub': info['sub'],
                **vals,
            })
        return connection

    @api.model
    def _token_values(self, response):
        return {
            'access_token': response['access_token'],
            'refresh_token': response['refresh_token'],
            'expiry': fields.Datetime.now() + timedelta(seconds=response.get('expires_in', 1800)),
        }

    def _is_valid(self, stale):
        return self.access_token and self.access_token != stale and self.expiry > fields.Datetime.now() + timedelta(minutes=1)

    def _get_access_token(self, stale=None):
        """Refresh tokens may be single-use: the refresh runs under a row lock in its own cursor and is committed at once."""
        connection = self.sudo()
        connection.ensure_one()
        if connection._is_valid(stale):
            return connection.access_token
        with self.env.registry.cursor() as token_cr:
            token = connection.with_env(connection.env(cr=token_cr))
            for _attempt in range(40):
                try:
                    token.lock_for_update(allow_referencing=True)
                    break
                except LockError:
                    token_cr.rollback()  # new snapshot, so the next read sees the other worker's refresh
                    time.sleep(0.5)
            else:
                raise UserError(self.env._("Signify token refresh is busy, please retry."))
            if not token._is_valid(stale):
                response = None
                if token.refresh_token:
                    try:
                        response = oauth_call(self.env, 'token', {'grant_type': 'refresh_token', 'refresh_token': token.refresh_token})
                    except SignifyError as exc:
                        if exc.status_code != 'invalid_grant':
                            raise
                    except SignifyTransportError as exc:  # a plain UserError: action_send reads SignifyTransportError as "share outcome unknown"
                        raise UserError(exc.args[0]) from exc
                if response:
                    token.write(self._token_values({'refresh_token': token.refresh_token, **response}))
                else:
                    token.write({
                        'access_token': False,
                        'refresh_token': False,
                        'expiry': False,
                    })
            values = token.read(['access_token', 'refresh_token', 'expiry'])[0]
        # this transaction's snapshot predates the commit above: a re-read would return the old token
        connection._update_cache(values)
        if not values['access_token']:
            raise UserError(self.env._(
                "The Signify account %(email)s of %(user)s has expired: %(user)s must connect it again in Signify > Configuration > Signify Accounts.",
                email=connection.email, user=connection.user_id.name))
        return values['access_token']

    def action_disconnect(self):
        if not self.env.is_system() and self.user_id != self.env.user:
            raise AccessError(self.env._("You can only disconnect your own Signify account."))
        # sudo: a user reads only own documents, and the check covers the documents of every user
        Document = self.env['signify.document'].sudo()
        if Document.search_count(Domain('connection_id', 'in', self.ids) & Document._signify_in_progress_domain(), limit=1):
            raise UserError(self.env._("Documents sent with this account are still in progress in Signify."))
        # sudo: the token fields are system-only and a user cannot write a connection
        connections = self.sudo()
        for connection in connections.filtered('refresh_token'):
            try:
                oauth_call(self.env, 'revoke', {'token': connection.refresh_token, 'token_type_hint': 'refresh_token'})
            except (SignifyError, SignifyTransportError) as exc:
                _logger.warning("Signify: could not revoke the token of account %s: %s", connection.id, exc)
        connections.write({
            'access_token': False,
            'refresh_token': False,
            'expiry': False,
            'active': False,
        })
        return True
