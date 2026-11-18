from odoo import _, models
from odoo.exceptions import LockError, UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        """Serialise payroll payments so two concurrent runs cannot pay twice.
        A line partly reconciled with other payslip entries (correction netted with its refund) is payable;
        one partly paid by anything else is refused."""
        if self._gec_payroll_is_payroll_run():
            try:
                self.line_ids.lock_for_update()
            except LockError:
                raise UserError(_("These salary lines are being paid right now by someone else. Try again in a moment."))
            self.line_ids.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled'])
            snapshot = self.env.context.get('gec_payroll_residual_snapshot') or {}
            changed = self.env['account.move.line']
            for line in self.line_ids:
                expected = snapshot.get(line.id, snapshot.get(str(line.id)))
                if (expected is not None and not line.company_currency_id.is_zero(line.amount_residual - expected)):
                    changed |= line
            if changed:
                raise UserError(_("These payroll amounts changed while you were working; nothing was created. Reopen the payment wizard and try "
                    "again: %s", ', '.join(sorted(set(changed.move_id.mapped('display_name'))))))
            partial = self.line_ids.filtered(lambda line: not line.company_currency_id.is_zero(line.amount_residual - line.balance))
            if partial:
                counterparts = (partial.matched_debit_ids.debit_move_id | partial.matched_credit_ids.credit_move_id)
                # sudo: same reason as in _gec_payroll_is_payroll_run.
                payslip_moves = self.env['hr.payslip'].sudo().search([('move_id', 'in', counterparts.move_id.ids)]).move_id
                partial = partial.filtered(lambda line: (
                    line.matched_debit_ids.debit_move_id
                    | line.matched_credit_ids.credit_move_id).move_id - payslip_moves)
            if partial:
                raise UserError(_("Partially paid payroll lines are not supported; nothing was created. Resolve the partial payment first: %s",
                    ', '.join(sorted(set(partial.move_id.mapped('display_name'))))))
            settled = self.line_ids.filtered(
                lambda line: (line.currency_id or line.company_currency_id).is_zero(
                    line.amount_residual_currency if line.currency_id else line.amount_residual))
            if settled:
                raise UserError(_("These salary lines were paid while you were working; nothing was created. Reopen the payslips and start again: %s",
                    ', '.join(sorted(set(settled.move_id.mapped('display_name'))))))
        return super()._create_payments()

    def _gec_payroll_is_payroll_run(self):
        if self.env.context.get('gec_payroll_run'):
            return True
        moves = self.line_ids.move_id
        if not moves:
            return False
        # sudo: runs on every payment registration; plain accountants cannot read hr.payslip.
        return bool(self.env['hr.payslip'].sudo().search_count([('move_id', 'in', moves.ids)], limit=1))
