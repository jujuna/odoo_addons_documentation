from odoo import api, fields, models

from .gec_user_audit_rule import DEFAULT_EXCLUDED, excluded_from_text

VENDOR_EXCLUDED = frozenset(DEFAULT_EXCLUDED) - {'gec.user.audit.log', '*.line'} | {'gec.user.audit.*'}


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gec_audit_keep_days = fields.Integer(string='Keep the Logs (days)', config_parameter='gec_user_audit.keep_days', default=90,
        help="Older lines are deleted every night. 0 keeps them forever.")
    gec_audit_keep_sign_in_days = fields.Integer(string='Keep the Sign-ins (days)', config_parameter='gec_user_audit.keep_sign_in_days',
        help="Sign-ins, sign-outs and ended sessions. Left at 0, they follow the logs.")
    gec_audit_log_reads = fields.Boolean(string='Log Reads', default=False,
        help="Reads are the most frequent event: they are logged only when you turn this on, for the data no rule names. A rule with Read ticked "
        "always logs them.")
    gec_audit_excluded_models = fields.Char(string='Never Logged',
        help="Technical data never logged when no rule names it: technical names separated by commas, * for any part (ir.*, bus.*). Left empty, the "
        "default list applies.")
    gec_audit_sign_in_mail = fields.Selection([('none', 'Nobody'), ('user', 'The user'), ('admins', 'The administrators'), ('both', 'Both')],
        string='Sign-in Emails To', config_parameter='gec_user_audit.sign_in_mail', default='none')
    gec_audit_sign_in_mail_new_only = fields.Boolean(string='Only From a New Device', config_parameter='gec_user_audit.sign_in_mail_new_only',
        help="Only when the user signs in from an address and a browser not seen for 90 days.")
    gec_audit_idle_minutes = fields.Integer(string='End Idle Sessions After (minutes)', config_parameter='gec_user_audit.idle_minutes',
        help="A session without a request for this long is ended. 0 never ends one.")
    gec_audit_lines_today = fields.Integer(string='Lines in the Last 24 Hours', compute='_compute_gec_audit_lines_today')

    def _compute_gec_audit_lines_today(self):
        count = self.env['gec.user.audit.log'].sudo()._gec_lines_per_day()
        for settings in self:
            settings.gec_audit_lines_today = count

    @api.model
    def _gec_vendor_era(self):
        """ True when the stored "Never Logged" list is the vendor's old default (compared as a set), so the saved
        pair is a copy of the vendor's defaults, not a choice. """
        params = self.env['ir.config_parameter'].sudo()
        return set(excluded_from_text(params.get_str('gec_user_audit.excluded_models'))) == VENDOR_EXCLUDED

    @api.model
    def get_values(self):
        """ Shows the fork defaults when the stored pair is vendor-era. A log_reads 'True' counts only next to the
        vendor list: the first save deletes that list, so a value set on purpose later is shown as stored. """
        values = super().get_values()
        params = self.env['ir.config_parameter'].sudo()
        if self._gec_vendor_era():
            values['gec_audit_log_reads'] = False
            values['gec_audit_excluded_models'] = ', '.join(DEFAULT_EXCLUDED)
            return values
        values['gec_audit_log_reads'] = params.get_bool('gec_user_audit.log_reads', False)
        values['gec_audit_excluded_models'] = (params.get_str('gec_user_audit.excluded_models') or ', '.join(DEFAULT_EXCLUDED))
        return values

    def set_values(self):
        """ Store log_reads and excluded_models only when they differ from the code default (lists compared as sets),
        so a saved copy of the default never freezes it. set_str(key, None) would leave an empty row: it is deleted. """
        super().set_values()
        params = self.env['ir.config_parameter'].sudo()
        if self.gec_audit_log_reads:
            params.set_bool('gec_user_audit.log_reads', True)
        else:
            params.search([('key', '=', 'gec_user_audit.log_reads')]).unlink()
        if set(excluded_from_text(self.gec_audit_excluded_models or '')) != set(DEFAULT_EXCLUDED):
            params.set_str('gec_user_audit.excluded_models', self.gec_audit_excluded_models)
        else:
            params.search([('key', '=', 'gec_user_audit.excluded_models')]).unlink()
