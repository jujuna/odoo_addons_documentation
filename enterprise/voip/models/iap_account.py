from odoo import api, models

from odoo.addons.voip.models.phone_service_api import CLIENT_UUID_PARAM, PHONE_SERVICE_NAME


class IapAccount(models.Model):
    _inherit = "iap.account"

    @api.model_create_multi
    def create(self, vals_list):
        accounts = super().create(vals_list)
        accounts._voip_sync_phone_service_account_token()
        return accounts

    def write(self, vals):
        res = super().write(vals)
        if "account_token" in vals:
            self._voip_sync_phone_service_account_token()
        return res

    def _voip_sync_phone_service_account_token(self):
        icp = self.env["ir.config_parameter"].sudo()
        # Without credentials (never registered, or neutralized), registration sends the token.
        if any(account.service_name == PHONE_SERVICE_NAME for account in self) and icp.get_str(CLIENT_UUID_PARAM):
            icp._voip_try_sync_webhook_event_url(notify_user=True)
