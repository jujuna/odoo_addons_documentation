import hashlib
import hmac
import secrets

from odoo import fields, models
from odoo.tools.urls import urljoin

from odoo.addons.pos_platform_order_wolt.utils import const


class PlatformOrderProvider(models.Model):
    _inherit = 'platform.order.provider'

    code = fields.Selection(selection_add=[('wolt', "Wolt")], ondelete={'wolt': 'set default'})

    wolt_client_id = fields.Char(string="Wolt Client ID", required_if_provider='wolt', copy=False,
        help="OAuth client ID issued by Wolt for this integration.")
    wolt_client_secret = fields.Char(string="Wolt Client Secret", required_if_provider='wolt', copy=False, groups='base.group_system')
    wolt_webhook_secret = fields.Char(string="Wolt Webhook Signing Secret", copy=False, readonly=True, groups='base.group_system',
        help="Give this secret to Wolt together with the webhook URL. Wolt signs every notification with it.")
    wolt_webhook_url = fields.Char(string="Wolt Webhook URL", compute='_compute_wolt_urls')
    wolt_redirect_url = fields.Char(string="Wolt Redirect URL", compute='_compute_wolt_urls')

    def _compute_wolt_urls(self):
        base_url = self.env.company.get_base_url()
        for provider in self:
            is_wolt = provider.code == const.PROVIDER_CODE
            provider.wolt_webhook_url = is_wolt and urljoin(base_url, const.WEBHOOK_ROUTE)
            provider.wolt_redirect_url = is_wolt and urljoin(base_url, const.OAUTH_CALLBACK_ROUTE)

    def _check_required_if_provider(self):
        # sudo: POS managers edit providers but cannot read the admin-only Wolt secret the check reads
        return super(PlatformOrderProvider, self.sudo())._check_required_if_provider()

    def action_wolt_generate_webhook_secret(self):
        """Generate a 256-bit signing secret (Wolt requires at least 128 bits)."""
        for provider in self:
            provider.wolt_webhook_secret = secrets.token_hex(32)

    def _wolt_check_signature(self, raw_body, signature):
        """Check Wolt's WOLT-SIGNATURE header: hex HMAC-SHA256 of the raw body."""
        self.ensure_one()
        secret = self.wolt_webhook_secret
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.lower())
