from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    l10n_uk_hmrc_vat_token = fields.Char(related='company_id.l10n_uk_hmrc_vat_token')

    @api.model
    def hmrc_action_connect_callback(self):
        # Landing point after the HMRC login: fetch the tokens, then go back to the settings.
        self.check_access('write')
        self.env['hmrc.service']._login()
        return self.env['ir.actions.act_window']._for_xml_id('account.action_account_config')

    def hmrc_action_connect(self):
        self.check_access('write')
        return self.env['hmrc.service'].with_context(hmrc_redirect_to_settings=True)._login()

    def hmrc_action_disconnect(self):
        self.company_id.check_access('write')
        self.env['hmrc.service']._clean_tokens(self.company_id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._("HMRC Disconnected"),
                'message': self.env._("The HMRC connection for this company has been successfully removed."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }
