from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    geoeid_language = fields.Selection(selection=[('ka', 'Georgian'), ('en', 'English')], string="Georgian ID App Language", default='ka',
        config_parameter='id_ge_sign.language')
