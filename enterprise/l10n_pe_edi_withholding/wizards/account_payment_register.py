from odoo import models
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        # EXTENDS 'account'
        for bill in self.line_ids.move_id.filtered(lambda m: m.country_code == 'PE' and m.is_purchase_document()):
            if error := bill._l10n_pe_edi_get_igv_withholding_error():
                raise UserError(error)
        return super()._create_payments()
