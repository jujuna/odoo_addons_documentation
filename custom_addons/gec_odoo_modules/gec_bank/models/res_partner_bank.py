from odoo import models


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    def write(self, vals):
        """A journal's bank comes from its bank account's BIC: the same guard as account.journal.write."""
        bank_change = {'bank_bic', 'account_number'} & set(vals)
        held = None
        if bank_change:
            journals = self.env['account.journal'].sudo().search([('bank_account_id', 'in', self.ids)])
            held = journals._gec_bank_payments_at_bank()
        res = super().write(vals)
        if held:
            held._gec_bank_check_bank_kept()
        return res
