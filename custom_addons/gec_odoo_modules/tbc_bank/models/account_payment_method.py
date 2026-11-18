from odoo import api, models
from odoo.fields import Domain

TBC_METHOD_CODE = 'tbc_transfer'
# 8-char institution BIC; compare on the first 8 characters, the 11-char branch form (TBCBGE22XXX) also exists.
TBC_BANK_BIC = 'TBCBGE22'


class AccountPaymentMethod(models.Model):
    _inherit = 'account.payment.method'

    @api.model
    def _get_payment_method_information(self):
        res = super()._get_payment_method_information()
        res[TBC_METHOD_CODE] = {'mode': 'multi', 'type': ('bank',)}
        return res

    @api.model
    def _get_payment_method_domain(self, code, with_currency=True, with_country=True):
        domain = super()._get_payment_method_domain(code, with_currency, with_country)
        if code == TBC_METHOD_CODE:
            domain &= Domain('bank_account_id.bank_bic', '=ilike', TBC_BANK_BIC + '%')
        return domain

