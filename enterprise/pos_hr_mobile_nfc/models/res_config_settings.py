from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_nfc_secure_login = fields.Boolean(related='pos_config_id.nfc_secure_login', readonly=False)
    pos_nfc_encoding_key = fields.Char(related='pos_config_id.nfc_encoding_key', readonly=False)
    pos_nfc_manager_pin_required = fields.Boolean(related='pos_config_id.nfc_manager_pin_required', readonly=False)
