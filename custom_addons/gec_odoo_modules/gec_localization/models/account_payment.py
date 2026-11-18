from odoo import api, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.model
    def _get_valid_payment_account_types(self):
        """Allow current liabilities as the counterpart: a withholding tax line is on a non-payable liability."""
        account_types = super()._get_valid_payment_account_types()
        if self.env.context.get('gec_wht_tax_line_payment'):
            account_types.append('liability_current')
        return account_types
