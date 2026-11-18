from odoo import fields, models


class ResUsersSettings(models.Model):
    """Per-user home menu layout: pinned apps and chosen view."""
    _inherit = 'res.users.settings'

    gec_home_menu_config = fields.Json(string="Home Menu Layout", readonly=True)
