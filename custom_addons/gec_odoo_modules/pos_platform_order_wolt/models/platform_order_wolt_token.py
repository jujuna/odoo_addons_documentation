import datetime
import time

from requests.exceptions import HTTPError, RequestException

from odoo import fields, models
from odoo.exceptions import LockError, UserError

from odoo.addons.pos_platform_order_wolt.utils.wolt_request import WoltClient


class PlatformOrderWoltToken(models.Model):
    """OAuth tokens of one Wolt venue. Kept apart from the store row on purpose: a refresh is committed from its own
    cursor, and a later write to the same row in the caller's transaction would fail with a serialization error."""
    _name = 'platform.order.wolt.token'
    _description = 'Wolt Venue Token'
    _check_company_auto = True

    store_id = fields.Many2one('platform.order.entity', required=True, index=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='store_id.company_id', store=True, index=True)
    access_token = fields.Char(required=True, copy=False, groups='base.group_system')
    refresh_token = fields.Char(required=True, copy=False, groups='base.group_system')
    expiry = fields.Datetime(required=True)

    _store_uniq = models.Constraint('UNIQUE(store_id)', "A Wolt store has only one token pair.")

    def _is_valid(self):
        return self.expiry > fields.Datetime.now() + datetime.timedelta(minutes=1)

    def _get_access_token(self):
        """Return a valid access token, refreshing it when needed. Wolt refresh tokens are single-use: a reused one
        revokes the new pair, so the refresh runs under a row lock in its own cursor and is committed at once,
        whatever the caller does."""
        self.ensure_one()
        if self._is_valid():
            return self.access_token
        disconnected = self.env._("Wolt disconnected store %s: press Connect to Wolt on the store.", self.store_id.display_name)
        with self.env.registry.cursor() as token_cr:
            token = self.with_env(self.env(cr=token_cr))
            for _attempt in range(20):
                if not token.exists():
                    raise UserError(disconnected)
                try:
                    token.lock_for_update(allow_referencing=True)
                    break
                except LockError:
                    token_cr.rollback()  # new snapshot, so the next read sees the other worker's refresh
                    time.sleep(0.5)
            else:
                raise UserError(self.env._("Wolt token refresh is busy, please retry."))
            if not token._is_valid():
                try:
                    response = WoltClient.request_token(token.store_id.provider_id,
                        {'grant_type': 'refresh_token', 'refresh_token': token.refresh_token})
                except RequestException as error:
                    if isinstance(error, HTTPError) and error.response.status_code == 400 and 'invalid_grant' in error.response.text:
                        token.unlink()
                        token_cr.commit()
                        raise UserError(disconnected) from error
                    raise UserError(self.env._("Wolt token refresh failed for %(store)s, reconnect the store: %(error)s",
                        store=token.store_id.display_name, error=error)) from error
                token.write(self._prepare_values(response))
            values = token.read(['access_token', 'refresh_token', 'expiry'])[0]
        # this transaction's snapshot predates the commit above: a re-read would return the old token
        self._update_cache(values)
        return values['access_token']

    def _prepare_values(self, response):
        return {
            'access_token': response['access_token'],
            'refresh_token': response['refresh_token'],
            'expiry': fields.Datetime.now() + datetime.timedelta(seconds=response.get('expires_in', 3600)),
        }
