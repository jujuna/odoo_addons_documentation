from odoo import fields, models, api


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_l10n_be_blackbox_be_id = fields.Many2one(related="pos_config_id.l10n_be_blackbox_be_id", readonly=False)
    pos_l10n_be_training_mode = fields.Boolean(related="pos_config_id.l10n_be_training_mode", readonly=False)
    pos_l10n_be_country_code = fields.Char(string="POS Country Code", related="pos_config_id.company_id.country_id.code", readonly=True)
    pos_establishment_number = fields.Char(string="POS Establishment Number", related="pos_config_id.establishment_number", readonly=False)
    pos_l10n_be_pos_id = fields.Char(string="POS ID", related="pos_config_id.l10n_be_pos_id", readonly=False)
    pos_use_blackbox = fields.Boolean(related="pos_config_id.use_blackbox", readonly=True)

    @api.onchange('pos_l10n_be_blackbox_be_id')
    def _onchange_pos_l10n_be_blackbox_be_id(self):
        for res_config in self:
            if res_config.pos_l10n_be_blackbox_be_id:
                res_config.pos_iface_print_auto = True

    def action_request_pos_id(self):
        self.ensure_one()
        if not self.pos_config_id:
            return
        return self.pos_config_id.action_request_pos_id()
