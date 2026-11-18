from odoo import fields, models

from ..tools.signify_api import oauth_redirect_uri


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    signify_client_id = fields.Char(config_parameter='signify.client_id')
    signify_client_secret = fields.Char(config_parameter='signify.client_secret')
    signify_redirect_url = fields.Char(compute='_compute_signify_redirect_url',
        help="Give this URL to Signify to whitelist. Set the system parameter web.base.url.freeze so it does not change.")
    signify_reminder_frequency = fields.Selection(related='company_id.signify_reminder_frequency', readonly=False)
    signify_reminder_max_count = fields.Integer(related='company_id.signify_reminder_max_count', readonly=False)

    def _compute_signify_redirect_url(self):
        redirect_uri = oauth_redirect_uri(self.env)
        for settings in self:
            settings.signify_redirect_url = redirect_uri
