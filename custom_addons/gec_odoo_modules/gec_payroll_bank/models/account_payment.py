from odoo import _, models
from odoo.exceptions import UserError

from .account_batch_payment import GEC_PAYROLL_BATCH_WRITE_TOKEN


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def write(self, vals):
        """Keep a generated payroll payment as the run made it: batch and booked fields stay fixed.
        Core does not push edits into a posted entry, so the bank would get what accounting never saw;
        the bridge's token lifts the guard."""
        internal = (self.env.context.get('gec_payroll_batch_write_token') is GEC_PAYROLL_BATCH_WRITE_TOKEN)
        if not internal:
            if 'batch_payment_id' in vals:
                target = self.env['account.batch.payment'].browse(vals.get('batch_payment_id')).exists()
                if (self.batch_payment_id | target).filtered('gec_payroll_is_batch'):
                    raise UserError(_("A payment cannot be added to or removed from a generated payroll batch."))
            if self._gec_payroll_protected_fields() & set(vals):
                locked = self.filtered(lambda payment: payment.batch_payment_id.gec_payroll_is_batch)
                if locked:
                    raise UserError(_("The amount, recipient, bank account, currency, accounts, journal and date of a payment in a generated payroll "
                        "batch cannot be changed: %s", ', '.join(locked.mapped('display_name'))))
        return super().write(vals)

    def _gec_payroll_protected_fields(self):
        """Core's own list of the fields that define the booking, plus the channel."""
        return set(self._get_trigger_fields_to_synchronize()) | {'payment_method_line_id'}
