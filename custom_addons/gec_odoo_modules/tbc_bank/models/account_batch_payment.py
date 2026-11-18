from odoo import _, fields, models
from odoo.exceptions import UserError

from .account_payment_method import TBC_METHOD_CODE


class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    tbc_processing_mode = fields.Selection(related='journal_id.tbc_connection_id.processing_mode', string='TBC Processing Mode')

    def action_tbc_submit_approval(self):
        """Submit every pending TBC transfer of the batch for approval in one click."""
        self.ensure_one()
        return self.payment_ids.action_tbc_submit_approval()

    def action_tbc_approve(self):
        """Approve every TBC transfer of the batch awaiting approval, by the payment form's rules."""
        self.ensure_one()
        return self.payment_ids.action_tbc_approve()

    def action_tbc_send_batch(self):
        """Send every outbound TBC payment in the batch, one single-transfer call each, each in its own
        savepoint. A payment at the bank or with an unknown outcome is skipped: Recover from TBC, never a
        resend."""
        self.ensure_one()
        self.check_access('write')
        self.env['account.payment']._gec_bank_check_user(TBC_METHOD_CODE)
        if not self.journal_id.is_tbc:
            raise UserError(_("This batch is not on a TBC Bank journal."))
        sendable = {'pending'} | self.payment_ids._gec_bank_state_groups()['in_approval']
        payments = self.payment_ids._gec_bank_own(TBC_METHOD_CODE).filtered(lambda p: p.gec_bank_state in sendable)
        if not payments:
            raise UserError(_("No sendable TBC transfers in this batch."))
        done, errors, _notice = payments._gec_bank_send_each(TBC_METHOD_CODE)
        return payments._gec_bank_report_sends(TBC_METHOD_CODE, done, errors)
