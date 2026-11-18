from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    employee_registry_rs_sync_enabled = fields.Boolean(string='Enable Daily Sync', config_parameter='employee_registry_rs.sync_enabled',
        help="When disabled, the daily cron skips all employees.")

    def action_employee_registry_rs_sync_countries(self):
        self.ensure_one()
        total, matched = self.env['employee.registry.rs.service'].sync_countries_from_rs()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("RS Employee Registry"),
                'message': _("Fetched %(total)s countries, matched %(matched)s to Odoo records.", total=total, matched=matched),
                'sticky': False,
            },
        }
