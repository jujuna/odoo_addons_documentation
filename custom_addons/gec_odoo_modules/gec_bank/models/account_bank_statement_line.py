from odoo import SUPERUSER_ID, api, fields, models
from odoo.fields import Domain


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    # The bank's references for the transfer this line executed, space-separated.
    # Which payment fields they match is the bank's choice (_gec_bank_match_key_fields).
    gec_bank_match_keys = fields.Char(string='Bank Match Keys', index=True)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._gec_bank_auto_match()
        return lines

    def _gec_bank_auto_match(self):
        """Confirm a sent transfer from its statement debit: a line key equals the bank's payment key field,
        debit for the payment's amount (a reference may be a reversal). Sets Confirmed (statement),
        reconciled; unmatched Confirmed too."""
        lines = self.filtered('gec_bank_match_keys')
        Payment = self.env['account.payment']
        open_states = list(Payment._gec_bank_state_groups()['open'])
        for journal, journal_lines in lines.grouped('journal_id').items():
            key_fields = journal._gec_bank_match_key_fields()
            if not key_fields:
                continue
            keys = list({key for line in journal_lines for key in line.gec_bank_match_keys.split()})
            payments = Payment.search(
                Domain('journal_id', '=', journal.id)
                & (Domain('gec_bank_state', 'in', open_states)
                   | (Domain('gec_bank_state', '=', 'confirmed') & Domain('is_matched', '=', False)))
                & Domain.OR(Domain(field, 'in', keys) for field in key_fields))
            by_key = {}
            for payment in payments:
                for field in key_fields:
                    if payment[field]:
                        by_key.setdefault(payment[field], payment)
            matched = Payment
            for line in journal_lines:
                for key in line.gec_bank_match_keys.split():
                    payment = by_key.get(key)
                    if payment and payment not in matched and line._gec_bank_matches_payment(payment):
                        matched |= payment
                        if payment.gec_bank_state != 'confirmed':
                            payment._gec_bank_internal_write(dict(
                                {'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'statement',
                                 'gec_bank_error': False},
                                **payment._gec_bank_payment_state_vals('confirmed')))
                        line._gec_bank_reconcile_payment(payment)
                        break

    def _gec_bank_matches_payment(self, payment):
        """True when this line can be the debit of ``payment``: money out, for its amount, converted at the
        line date or on the foreign amount when that is the payment's currency."""
        self.ensure_one()
        if self.amount >= 0:
            return False
        payment_currency = payment.currency_id
        if self.foreign_currency_id and self.foreign_currency_id == payment_currency:
            amount = abs(self.amount_currency)
        else:
            line_currency = self.currency_id or self.company_id.currency_id
            amount = abs(self.amount)
            if line_currency != payment_currency:
                amount = line_currency._convert(amount, payment_currency, self.company_id, self.date)
        return payment_currency.compare_amounts(amount, payment.amount) == 0

    def _gec_bank_reconcile_payment(self, payment):
        """Reconcile this line with the payment's open Outstanding line, as core's end-to-end matching
        does (_end_to_end_uuid). Runs as superuser, as there: an importer may lack reconciliation rights."""
        self.ensure_one()
        if self.is_reconciled:
            return
        open_lines = payment._seek_for_lines()[0].filtered(
            lambda line: line.account_id.reconcile and not line.reconciled)
        if open_lines:
            self.with_company(self.company_id).with_user(SUPERUSER_ID).set_line_bank_statement_line(
                open_lines.ids)
