from odoo import _, models
from odoo.exceptions import UserError

# Records a status-poll cron reads per run; each is one BOG call, so a run must fit the worker time limit.
BOG_STATUS_POLL_LIMIT = 100


class BogSendable(models.AbstractModel):
    _name = 'bog.sendable'
    _description = 'Bank of Georgia Sendable Mixin'
    _inherit = 'gec.bank.sendable'

    def _bog_connection(self):
        """The journal's BOG connection; raises if missing or blocked."""
        self.ensure_one()
        # sudo: connection state is configuration, and the service sudoes it for the credentials anyway.
        connection = self.journal_id.bog_connection_id[:1].sudo()
        errors = connection._gec_bank_unusable_errors(self.journal_id.company_id)
        if errors:
            raise UserError(errors[0])
        return connection

    def _bog_notify(self, message, level):
        return self._gec_bank_notify(_("Bank of Georgia"), message, level)
