from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    gec_can_pay = fields.Boolean(compute='_compute_gec_can_pay')

    @api.depends('parent_state', 'move_type', 'journal_id.type', 'payment_id', 'statement_line_id', 'account_id.account_type', 'balance',
        'reconciled', 'amount_residual', 'amount_residual_currency', 'company_currency_id', 'currency_id',
        'partner_id', 'company_id')
    def _compute_gec_can_pay(self):
        """Show Pay on an open payable credit line of a posted general-journal entry.
        Payment and bank statement entries and bill withholding lines have their own Pay flow."""
        for line in self:
            currency = line.company_currency_id
            line.gec_can_pay = bool(
                line.parent_state == 'posted'
                and line.move_type == 'entry'
                and line.journal_id.type == 'general'
                and not line.payment_id
                and not line.statement_line_id
                and line.account_id.account_type == 'liability_payable'
                and currency.compare_amounts(line.balance, 0) < 0
                and line._gec_is_open()
                and line.partner_id
                and line.company_id._gec_is_georgian()
            )

    def _gec_is_open(self):
        """Return whether this line still has an amount to settle, as the Pay wizard tests it.
        A foreign-currency line is open on its currency residual, any other on the company residual."""
        self.ensure_one()
        if self.currency_id:
            return not self.currency_id.is_zero(self.amount_residual_currency)
        return not self.company_currency_id.is_zero(self.amount_residual)

    def _gec_withholding_tax_lines(self):
        """Return the lines of ``self`` booking a withholding tax paid to the State Treasury.
        Today: tax lines of vendor bills and purchase receipts with a Georgian withholding tax;
        extend with ``super() | ...``."""
        return self.filtered(lambda line: line.tax_line_id.gec_is_withholding and line.move_id.is_purchase_document(include_receipts=True))

    def action_gec_pay_entry_line(self):
        """Open Pay for this payable line and its partner's other open lines on the account, as one payment.
        Refused: a line with no partner or another contact; residual and balance not both negative.
        Opens grouped, so a part amount needs no later write."""
        self.ensure_one()
        if not self.gec_can_pay:
            raise UserError(self.env._("This line cannot be paid from the journal entry."))
        currency = self.company_currency_id
        open_lines = self.move_id.line_ids.filtered(lambda line: line.account_id == self.account_id and line._gec_is_open())
        other_partner_lines = (open_lines - self).filtered(
            lambda line: not line.partner_id or (
                line.partner_id != self.partner_id
                and line.partner_id.commercial_partner_id == self.partner_id.commercial_partner_id))
        if other_partner_lines:
            raise UserError(self.env._("Lines %(lines)s are on the same account with no partner or another contact of %(partner)s. Reset the entry "
                "to draft, give each line its real partner (the State Treasury on tax lines), then pay again.",
                lines=', '.join(line.name or line.account_id.display_name for line in other_partner_lines),
                partner=self.partner_id.commercial_partner_id.display_name))
        lines = open_lines.filtered(lambda line: line.partner_id == self.partner_id)
        if len(lines.currency_id) > 1:
            raise UserError(self.env._("These lines are in different currencies, so one payment cannot settle them. Split the entry by currency."))
        if (currency.compare_amounts(sum(lines.mapped('amount_residual')), 0) >= 0 or currency.compare_amounts(sum(lines.mapped('balance')), 0) >= 0):
            raise UserError(self.env._("Nothing is owed to %(partner)s on this account: the debits of this entry cover the credit.",
                partner=self.partner_id.display_name))
        return lines.action_register_payment(ctx={'dont_redirect_to_payments': True, 'default_group_payment': True})

    def _gec_net_withholding_lines(self):
        """Net each bill withholding line with open debit lines on its account; return what is still open.
        Offsets: the bill's payments (kept on reset to draft), the same tax on its credit notes, and the open withholding
        left by any vendor credit note on the account (an overpayment the Treasury already holds)."""
        pool = self.search([
            ('company_id', 'in', self.company_id.ids),
            ('account_id', 'in', self.account_id.ids),
            ('move_id.move_type', '=', 'in_refund'),
            ('parent_state', '=', 'posted'),
            ('tax_line_id.gec_is_withholding', '=', True),
            ('reconciled', '=', False),
            ('balance', '>', 0),
        ])
        for line in self:
            currency = line.company_currency_id
            move = line.move_id
            credit_notes = move.reversal_move_ids.filtered(lambda m: m.state == 'posted')
            candidates = (move.matched_payment_ids.move_id.line_ids | pool
                | credit_notes.line_ids.filtered(lambda l: l.tax_line_id == line.tax_line_id))
            offsets = candidates.filtered(
                lambda l: l.account_id == line.account_id
                and l.parent_state == 'posted'
                and currency.compare_amounts(l.balance, 0) > 0
                and l._gec_is_open())
            if offsets:
                (line + offsets).reconcile()
        return self.filtered(lambda line: line._gec_is_open())

    def _gec_action_pay_withholding(self):
        """Open Pay for the withholding tax lines of ``self``, to the State Treasury, after netting them.
        When nothing is left open a warning is shown instead."""
        lines = self._gec_net_withholding_lines()
        if not lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': self.env._("This withholding tax is already paid or offset by credit notes."),
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }
        return lines.action_register_payment(ctx={'gec_wht_tax_line_payment': True, 'dont_redirect_to_payments': True, 'default_group_payment': True})

    def _get_computed_taxes(self):
        """Apply the partner's default tax, the version valid on the document date."""
        taxes = super()._get_computed_taxes()
        move = self.move_id
        if self.display_type != 'product':
            return taxes
        if move.is_sale_document(include_receipts=True):
            type_tax_use = 'sale'
        elif move.is_purchase_document(include_receipts=True):
            type_tax_use = 'purchase'
        else:
            return taxes
        AccountTax = self.env['account.tax']
        return AccountTax._ge_partner_product_taxes(taxes or AccountTax, move.partner_id, self.product_id, move.company_id, type_tax_use,
            move.fiscal_position_id, date=move.invoice_date or move.date or fields.Date.context_today(self))

    def _affect_tax_report(self):
        """A manual entry line with only Georgian withholding labels skips the tax report,
        so the entry can be re-dated past a Tax Return Lock Date."""
        self.ensure_one()
        move = self.move_id
        if (
            move.move_type == 'entry'
            and not move.origin_payment_id
            and not self.tax_line_id
            and self.tax_ids
            and all(self.tax_ids.mapped('gec_is_withholding'))
            and not self.tax_tag_ids.filtered(lambda tag: tag.applicability == 'taxes')
        ):
            return False
        return super()._affect_tax_report()
