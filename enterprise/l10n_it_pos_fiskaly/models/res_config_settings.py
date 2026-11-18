from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_it_fiskaly_taxpayer_id = fields.Char(related="company_id.l10n_it_fiskaly_taxpayer_id",
        string="Fiskaly Taxpayer")
    l10n_it_fiskaly_taxpayer_state = fields.Selection(related="company_id.l10n_it_fiskaly_taxpayer_state",
        string="Fiskaly Taxpayer State")
    l10n_it_fiskaly_location_id = fields.Char(related="company_id.l10n_it_fiskaly_location_id",
        string="Fiskaly Location")
    l10n_it_fiskaly_location_state = fields.Selection(related="company_id.l10n_it_fiskaly_location_state",
        string="Fiskaly Location State")
    pos_l10n_it_fiskaly_system_id = fields.Char(related="pos_config_id.l10n_it_fiskaly_system_id",
        string="Fiskaly System")
    pos_l10n_it_fiskaly_system_state = fields.Selection(related="pos_config_id.l10n_it_fiskaly_system_state",
        string="Fiskaly System State")

    def action_l10n_it_fiskaly_create_system(self):
        self.pos_config_id.action_l10n_it_fiskaly_create_system()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("%s is registered as a fiscal device with fiskaly.", self.pos_config_id.display_name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
