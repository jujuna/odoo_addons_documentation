from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def button_draft(self):
        """Apply the payment's bank guard to its journal entry too: cancelling the entry cancels the payment."""
        self.origin_payment_id._gec_bank_check_not_at_bank()
        return super().button_draft()

    def button_cancel(self):
        self.origin_payment_id._gec_bank_check_not_at_bank()
        return super().button_cancel()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        """Same guard as button_draft: reversing the entry would reopen what the bank paid."""
        self.origin_payment_id._gec_bank_check_not_at_bank()
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)
