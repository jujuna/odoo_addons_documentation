from odoo import models
from odoo.exceptions import RedirectWarning


class AccountMoveSendBatchWizard(models.TransientModel):
    _inherit = 'account.move.send.batch.wizard'

    def action_send_and_print(self, allow_fallback_pdf=False):
        # EXTEND account
        self.ensure_one()
        wrong_moves, error_messages = self.move_ids.filtered(lambda move: move.partner_id.invoice_edi_format == 'finvoice')._check_finvoice_requirement()

        if wrong_moves:
            raise RedirectWarning(
                message="\n".join([self.env._("Some entries are missing crucial information:\n"), *error_messages]),
                action=wrong_moves._get_records_action(name=self.env._("Wrong entries")),
                button_text=self.env._("View entries"),
            )
        return super().action_send_and_print(allow_fallback_pdf=allow_fallback_pdf)
