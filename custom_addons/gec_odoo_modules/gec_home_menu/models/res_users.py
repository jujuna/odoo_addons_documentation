from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _format_activity_group(self, model_name, activities):
        """Add `gec_app_id` (app root menu of the model, or None) to the group, for the home menu tile counts.

        Hooked here because project_todo and mass_mailing_sms build their split groups through this method."""
        group = super()._format_activity_group(model_name, activities)
        if model_name != 'mail.activity':
            group['gec_app_id'] = self.env['ir.ui.menu']._gec_app_menu_for_model(model_name)
        return group
