from odoo import api, models


class AccountBatchPayment(models.Model):
    _name = 'account.batch.payment'
    _inherit = ['account.batch.payment', 'gec.bank.guard.mixin']

    @api.ondelete(at_uninstall=False)
    def _unlink_except_payment_held_by_bank(self):
        """A batch cannot be deleted while the bank holds one of its payments unbooked."""
        self.payment_ids._gec_bank_check_not_held()
