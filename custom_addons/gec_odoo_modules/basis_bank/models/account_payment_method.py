from odoo import api, models
from odoo.fields import Domain


BASISBANK_METHOD_CODE = 'basisbank_transfer'
BASIS_BANK_BIC = 'CBASGE22'


class AccountPaymentMethod(models.Model):
    _inherit = 'account.payment.method'

    @api.model
    def _get_payment_method_information(self):
        res = super()._get_payment_method_information()
        res[BASISBANK_METHOD_CODE] = {'mode': 'multi', 'type': ('bank',)}
        return res

    @api.model
    def _get_payment_method_domain(self, code, with_currency=True, with_country=True):
        domain = super()._get_payment_method_domain(code, with_currency, with_country)
        if code == BASISBANK_METHOD_CODE:
            domain &= Domain('bank_account_id.bank_bic', '=ilike', BASIS_BANK_BIC + '%')
        return domain
