from odoo import api, models

from .account_payment_method_line import bic_prefix


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    @api.model
    def _get_line_batch_key(self, line):
        """Pay a recipient into its account at the bank we pay from; active only with ``gec_bank_journal_bic``
        in context. Core calls this on the whole recordset (no ``self.journal_id``); core's choice stands
        unless at that bank."""
        res = super()._get_line_batch_key(line)
        journal_bic = self.env.context.get('gec_bank_journal_bic')
        if not journal_bic or not line.partner_id:
            return res
        bank = line._gec_bank_recipient_account(journal_bic)
        if bank and bic_prefix(bank.bank_bic) == journal_bic:
            res['partner_bank_id'] = bank.id
        return res
