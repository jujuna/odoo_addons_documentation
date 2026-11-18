from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_wolt_drive_venue_id = fields.Char(related='pos_config_id.wolt_drive_venue_id', readonly=False)
    pos_wolt_drive_merchant_id = fields.Char(related='pos_config_id.wolt_drive_merchant_id', readonly=False)
    pos_wolt_drive_api_key = fields.Char(related='pos_config_id.wolt_drive_api_key', readonly=False)
    pos_wolt_drive_test_mode = fields.Boolean(related='pos_config_id.wolt_drive_test_mode', readonly=False)
    pos_wolt_drive_webhook_ready = fields.Boolean(related='pos_config_id.wolt_drive_webhook_ready')
    pos_wolt_drive_preparation_minutes = fields.Integer(
        related='pos_config_id.wolt_drive_preparation_minutes', readonly=False)

    def action_wolt_drive_register_webhook(self):
        self.ensure_one()
        return self.pos_config_id.action_wolt_drive_register_webhook()
