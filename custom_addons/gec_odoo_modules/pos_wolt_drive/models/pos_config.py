import base64
import hashlib
import hmac
import json
import logging
import secrets

from requests.exceptions import RequestException

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.urls import urljoin

from odoo.addons.pos_wolt_drive.utils.drive_request import DriveClient

_logger = logging.getLogger(__name__)

WEBHOOK_ROUTE = '/wolt_drive/webhook'


class PosConfig(models.Model):
    _inherit = 'pos.config'

    wolt_drive_venue_id = fields.Char(
        string="Wolt Drive Venue ID", copy=False,
        help="Venue of this shop in Wolt Drive. Leave empty to disable Wolt couriers in this POS.")
    wolt_drive_merchant_id = fields.Char(string="Wolt Drive Merchant ID", copy=False, groups='base.group_system')
    wolt_drive_api_key = fields.Char(string="Wolt Drive API Key", copy=False, groups='base.group_system')
    wolt_drive_test_mode = fields.Boolean(default=True, copy=False, groups='base.group_system')
    wolt_drive_preparation_minutes = fields.Integer(
        string="Wolt Drive Preparation Time", default=30, copy=False,
        help="Minutes needed before the courier can pick the order up (0-60).")
    wolt_drive_webhook_secret = fields.Char(copy=False, readonly=True, groups='base.group_system')
    wolt_drive_webhook_ready = fields.Boolean(string="Status Updates Set Up", compute='_compute_wolt_drive_webhook_ready', compute_sudo=True)

    @api.depends('wolt_drive_webhook_secret')
    def _compute_wolt_drive_webhook_ready(self):
        for config in self:
            config.wolt_drive_webhook_ready = bool(config.wolt_drive_webhook_secret)

    def write(self, vals):
        """A new merchant, key or test mode points to another Wolt account, so the registered webhook no longer applies."""
        names = {'wolt_drive_merchant_id', 'wolt_drive_api_key', 'wolt_drive_test_mode'} & vals.keys()
        changed = self.sudo().filtered(lambda config: any(config[name] != vals[name] for name in names))
        result = super().write(vals)
        changed.wolt_drive_webhook_secret = False
        return result

    def _wolt_drive_webhook_url(self):
        self.ensure_one()
        return urljoin(self.get_base_url(), f'{WEBHOOK_ROUTE}/{self.id}')

    def action_wolt_drive_register_webhook(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._("Only administrators can register the Wolt Drive webhook."))
        if not (self.wolt_drive_merchant_id and self.wolt_drive_api_key):
            raise UserError(self.env._("Set the Wolt Drive merchant ID and API key first."))
        secret = self.wolt_drive_webhook_secret or secrets.token_hex(32)
        client = DriveClient(self)
        callback_url = self._wolt_drive_webhook_url()
        try:
            response = client.register_webhook(callback_url, secret)
        except RequestException as error:
            raise UserError(self.env._("Wolt Drive cannot be reached: %s", error)) from error
        if not response.ok:
            raise UserError(self.env._("Wolt Drive refused the webhook: %s", response.text[:300]))
        self.wolt_drive_webhook_secret = secret
        try:  # Wolt has registered the webhook for good: a failed cleanup must not undo the saved secret
            if new_id := response.json().get('id'):
                for webhook in client.list_webhooks().json():
                    if webhook['callback_url'] == callback_url and webhook['id'] != new_id:
                        client.delete_webhook(webhook['id'])
        except (RequestException, ValueError, KeyError, TypeError):
            _logger.exception("Wolt Drive: cleaning up the old webhooks of POS %s failed", self.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'message': self.env._("Wolt Drive status updates are now sent to Odoo.")},
        }

    @api.model
    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        for record in read_records:
            for name in ('wolt_drive_merchant_id', 'wolt_drive_api_key', 'wolt_drive_test_mode', 'wolt_drive_webhook_secret'):
                record.pop(name, None)
        return read_records

    def _wolt_drive_decode_event(self, token):
        """Verify the HS256 JWT of a Drive webhook with this POS's secret and return its payload, else None."""
        self.ensure_one()
        secret = self.wolt_drive_webhook_secret
        try:
            header, payload, signature = token.split('.')
            if not secret or json.loads(_b64decode(header)).get('alg') != 'HS256':
                return None
            expected = hmac.new(secret.encode(), f'{header}.{payload}'.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _b64decode(signature)):
                return None
            event = json.loads(_b64decode(payload))
        except (AttributeError, ValueError, TypeError):
            return None
        return event if isinstance(event, dict) else None


def _b64decode(segment):
    return base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))
