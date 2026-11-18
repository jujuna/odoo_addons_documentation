from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _gec_bank_recipient_account(self, journal_bic=''):
        """A payslip line that names the employee's bank account keeps it, whichever bank
        pays; the same-bank preference applies to every other line."""
        if self.employee_bank_account_id:
            return self.employee_bank_account_id
        return super()._gec_bank_recipient_account(journal_bic)
