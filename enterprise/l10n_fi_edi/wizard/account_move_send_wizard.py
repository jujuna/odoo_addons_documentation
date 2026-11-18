from odoo import models
from odoo.exceptions import UserError


class AccountMoveSendWizard(models.TransientModel):
    _inherit = 'account.move.send.wizard'

    def action_send_and_print(self, allow_fallback_pdf=False):
        # EXTEND account
        self.ensure_one()
        if self.invoice_edi_format == 'finvoice':
            _moves, error_messages = self.move_id._check_finvoice_requirement()
            if error_messages:
                raise UserError('\n'.join(error_messages))
        return super().action_send_and_print(allow_fallback_pdf=allow_fallback_pdf)
