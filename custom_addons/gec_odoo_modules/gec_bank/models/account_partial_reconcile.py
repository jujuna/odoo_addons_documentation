from odoo import api, models


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.ondelete(at_uninstall=False)
    def _unlink_except_payment_held_by_bank(self):
        """A match is not undone while the bank holds the payment unbooked, or the bill would
        be paid again. Statement matching and unmatching are not affected."""
        partials = self.filtered(
            lambda partial: not (partial.debit_move_id | partial.credit_move_id).statement_line_id)
        payments = (partials.debit_move_id | partials.credit_move_id).move_id.origin_payment_id
        payments._gec_bank_check_not_held()
