# Part of the GEC Georgian translation modules.
from odoo import models

from .ir_module import _refresh_industries


class ResLang(models.Model):
    _inherit = 'res.lang'

    def action_gec_force_georgian(self):
        """Also run the industry pass, which gec_i18n_base's shared pass cannot replace."""
        action = super().action_gec_force_georgian()
        _refresh_industries(self.env)
        return action
