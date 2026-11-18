from odoo import api, models
from odoo.fields import Domain

BOG_METHOD_CODE = 'bog_transfer'
# Answers BOG gives before processing a document (failed login, rate limit): nothing was created.
BOG_NOT_PROCESSED_STATUSES = (401, 429)

BOG_BANK_BIC = 'BAGAGE22'


class AccountPaymentMethod(models.Model):
    _inherit = 'account.payment.method'

    @api.model
    def _get_payment_method_information(self):
        res = super()._get_payment_method_information()
        res[BOG_METHOD_CODE] = {'mode':'multi','type': ('bank',)}
        return res

    @api.model
    def _get_payment_method_domain(self, code, with_currency=True, with_country=True):
        domain = super()._get_payment_method_domain(code, with_currency, with_country)
        if code == BOG_METHOD_CODE:
            # The wildcard also matches the 11-char branch BIC.
            domain &= Domain('bank_account_id.bank_bic', '=ilike', BOG_BANK_BIC + '%')
        return domain

