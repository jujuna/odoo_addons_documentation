from odoo import models
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        """Without an Outstanding Payments account no entry posts, so the payslip stays open and gets paid again."""
        if (self.env.context.get('gec_payslip_register_payment') and not self.payment_method_line_id.payment_account_id):
            raise UserError(self.env._("Payment method %(method)s of %(journal)s has no Outstanding Payments account, so this payment would not "
                "settle the payslip. Set one on the journal's Outgoing Payments tab.", method=self.payment_method_line_id.name,
                journal=self.journal_id.display_name))
        return super()._create_payments()

    def _reconcile_payments(self, to_process, edit_mode=False):
        """Mark paid slips and their correction family paid once the NET lines are settled.
        A correction is marked with its origin only when no other correction is still open."""
        res = super()._reconcile_payments(to_process, edit_mode=edit_mode)
        if not self.env.context.get('hr_payroll_payment_register'):
            return res
        slips = self.env['hr.payslip']
        for vals in to_process:
            slips |= vals['to_reconcile'].move_id.payslip_ids
        family = slips | slips.origin_payslip_id | slips.origin_payslip_id.related_payslip_ids
        family._gec_mark_settled_paid(self.payment_date, paid_slips=slips)
        return res
