from datetime import timedelta

from odoo import api, fields, models


class GecBankOauthMixin(models.AbstractModel):
    """Cached OAuth2 client-credentials token of a bank API. Only system administrators read it;
    the sudo writers are private, so not callable over RPC."""

    _name = 'gec.bank.oauth.mixin'
    _description = 'Bank OAuth Token Mixin'

    access_token = fields.Char(string='Access Token', readonly=True, copy=False, groups='base.group_system')
    token_expiry = fields.Datetime(string='Token Expiry', readonly=True, copy=False, groups='base.group_system')

    @api.private
    def token_is_valid(self):
        self.ensure_one()
        if not self.sudo().access_token or not self.sudo().token_expiry:
            return False
        return self.sudo().token_expiry > fields.Datetime.now() + timedelta(seconds=60)

    @api.private
    def store_token(self, access_token, lifetime_seconds, extra_vals=None):
        """Store the token, with ``extra_vals`` (the connection state), in one UPDATE on an own committed cursor."""
        self.ensure_one()
        self._gec_bank_write_connection(dict(
            extra_vals or {}, access_token=access_token,
            token_expiry=fields.Datetime.now() + timedelta(seconds=lifetime_seconds - 60)))

    @api.private
    def clear_token(self):
        for record in self:
            record._gec_bank_write_connection({'access_token': False, 'token_expiry': False})

    @api.private
    def _gec_bank_write_connection(self, vals):
        """Every login write (token, state, error) commits on an own cursor, never by ORM: an ORM UPDATE of the
        same row after that commit fails (REPEATABLE READ) and re-runs the request."""
        self.ensure_one()
        self.env['gec.bank.service']._durable_write(self.sudo(), vals)
