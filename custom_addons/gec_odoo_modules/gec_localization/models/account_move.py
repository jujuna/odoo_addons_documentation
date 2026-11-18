from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    gec_show_pay_withholding = fields.Boolean(compute='_compute_gec_show_pay_withholding')

    def _gec_bills(self):
        """Return the vendor bills and purchase receipts of ``self``, without expense receipts (core's Pay flow)."""
        return self.filtered(lambda move: move.move_type in ('in_invoice', 'in_receipt') and not ('expense_ids' in move._fields and move.expense_ids))

    def _gec_open_withholding_lines(self):
        """Return the open withholding tax lines (credit, not reconciled) of the posted bills in ``self``."""
        lines = self.env['account.move.line']
        for move in self._gec_bills().filtered(lambda m: m.state == 'posted'):
            currency = move.company_currency_id
            lines |= move.line_ids._gec_withholding_tax_lines().filtered(
                lambda line: currency.compare_amounts(line.balance, 0) < 0 and line._gec_is_open())
        return lines

    @api.depends('state', 'payment_state', 'line_ids.amount_residual', 'line_ids.reconciled')
    def _compute_gec_show_pay_withholding(self):
        """Show Pay Withholding Tax when the vendor is paid but a withholding tax is open.
        Blocked and reversed bills do not show it."""
        for move in self:
            move.gec_show_pay_withholding = bool(move.state == 'posted' and move.payment_state == 'paid' and move._gec_open_withholding_lines())

    @api.onchange('partner_id')
    def _onchange_partner_id_default_taxes(self):
        self.filtered(lambda move: move.is_invoice(include_receipts=True) and move.company_id._gec_is_georgian()).invoice_line_ids._compute_tax_ids()

    def action_force_register_payment(self):
        """Ask what to pay first when a bill has an open withholding tax; else core's Pay.
        Non-accountants and expense receipts get core's dialog; gec_pay_choice_done stops it repeating."""
        action = super().action_force_register_payment()
        if self.env.context.get('dont_redirect_to_payments'):
            action['context'] = {**action['context'], 'dont_redirect_to_payments': True}
        if (
            self.env.context.get('gec_pay_choice_done')
            or not self.env.user.has_group('account.group_account_user')
            or self._gec_bills() != self
            or not self._gec_open_withholding_lines()
        ):
            return action
        return {
            'name': self.env._("Pay"),
            'type': 'ir.actions.act_window',
            'res_model': 'gec.bill.pay.choice',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {'default_move_ids': self.ids},
        }

    def action_gec_pay_withholding_tax(self):
        """Open Pay for the withholding tax of the bills, to the State Treasury, with no question first."""
        return self._gec_open_withholding_lines()._gec_action_pay_withholding()
