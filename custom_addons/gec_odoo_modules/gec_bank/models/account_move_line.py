from odoo import models

from .account_payment_method_line import bic_prefix


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _gec_bank_recipient_account(self, journal_bic=''):
        """The recipient bank account for a payment of this line: the partner's account at the paying bank
        (compared by BIC) when it has one, else its first account."""
        self.ensure_one()
        banks = self.partner_id.commercial_partner_id.bank_ids.filtered(
            lambda bank: not bank.company_id or bank.company_id == self.company_id)
        if journal_bic:
            matched = banks.filtered(lambda bank: bic_prefix(bank.bank_bic) == journal_bic)
            if matched:
                return matched.sorted('sequence')[:1]
        return banks.sorted('sequence')[:1]
