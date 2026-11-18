from odoo import models


class GecBankSendable(models.AbstractModel):
    """Shared by the payment and batch mixins of every bank."""

    _name = 'gec.bank.sendable'
    _description = 'Bank Sendable Mixin'

    def _gec_bank_notify(self, title, message, level):
        """Return a display_notification action that also closes an open dialog."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': level,
                'sticky': level != 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
