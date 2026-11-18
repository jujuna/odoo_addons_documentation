# Part of the GEC Georgian translation modules.
from odoo import models

from ..hooks import force_apply_translations


class ResLang(models.Model):
    _inherit = 'res.lang'

    def action_gec_force_georgian(self):
        """Force-apply every GEC Georgian area file; the server action behind Apply Georgian Translations (GEC)."""
        self.env['ir.module.module'].check_access('write')
        count = force_apply_translations(self.env)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if count else 'warning',
                'sticky': False,
                'message': (
                    'Georgian translations re-applied from %d file(s). '
                    'Hard-refresh (Ctrl+Shift+R) to drop cached assets.' % count
                ) if count else 'Nothing to apply: ka_GE is not active.',
            },
        }
