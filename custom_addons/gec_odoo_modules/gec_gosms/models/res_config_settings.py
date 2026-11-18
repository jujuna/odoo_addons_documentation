from odoo import api, fields, models
from odoo.tools.urls import urljoin as url_join


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gosms_api_key = fields.Char(related='company_id.gosms_api_key', readonly=False)
    gosms_sms_enabled = fields.Boolean(related='company_id.gosms_sms_enabled', readonly=False)
    gosms_sender = fields.Char(related='company_id.gosms_sender', readonly=False)
    gosms_nosms_number = fields.Char(related='company_id.gosms_nosms_number', readonly=False)
    gosms_webhook_secret = fields.Char(related='company_id.gosms_webhook_secret', readonly=False)
    gosms_webhook_token = fields.Char(related='company_id.gosms_webhook_token', readonly=False)
    gosms_webhook_url = fields.Char("Webhook URL", compute='_compute_gosms_webhook_url')

    @api.depends('company_id')
    def _compute_gosms_webhook_url(self):
        for settings in self:
            settings.gosms_webhook_url = url_join(settings.company_id.get_base_url(), f'/gosms/webhook/{settings.company_id.id}')

    def _gosms_notify_success(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': message,
            },
        }

    def action_gosms_check_connection(self):
        balance = self.company_id._gosms_call('sms-balance', {})['balance']
        return self._gosms_notify_success(self.env._("GoSMS is connected. SMS balance: %s", balance))

    def action_gosms_register_sender(self):
        self.company_id._gosms_call('sender', {'name': self.gosms_sender})
        return self._gosms_notify_success(self.env._("The sender name %s is registered on GoSMS.", self.gosms_sender))
