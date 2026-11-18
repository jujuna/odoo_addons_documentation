from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    rs_form30_proposed_tax_id = fields.Many2one('account.tax', string='Proposed Withholding Tax', readonly=True, ondelete='set null',
        check_company=True, index='btree_not_null',
        help="The Withholding Tax Odoo proposed for this line from the Form 30 account rules. Odoo proposes again at posting or on Detect Again only "
        "while the withholding taxes on every line of the entry still match Odoo's proposal; a withholding tax picked, changed or removed by hand on "
        "any line keeps the whole entry as it is. Copied with the line, so a duplicate keeps the same state.")

    def _gec_withholding_tax_lines(self):
        res = super()._gec_withholding_tax_lines()
        extra = self.browse()
        plain = self.move_id._rs_form30_plain_entries()
        for moves in plain.grouped(lambda move: move.company_id.root_id).values():
            rules = moves._rs_form30_get_rules()
            for move in moves:
                matched = move._rs_form30_match(rules)[1]
                extra |= (self & move.line_ids).filtered(
                    lambda line: line.balance < 0
                    and line.account_id in matched.tax_account_ids
                    and (line.account_id not in matched.liability_account_ids or not line.partner_id))
        return res | extra

    def _rs_form30_cash_parts(self):
        """Split what settled each credit line into cash parts (bank, payment or offset entry) and other parts. Returns {line:
        {'cash': [...], 'other': [...]}}. Own entry, own reversals and exchange differences are ignored. A part is dated no earlier than
        the settled document (invoice date, else entry date): a payment made before it is kind 'advance' and counts in the document's month."""
        parts = {}
        credit_lines = self.filtered(lambda line: line.credit > 0)
        # sudo: the accountant may lack access to the entries, payments and bank journals that settled the lines
        plain = credit_lines.sudo().matched_debit_ids.debit_move_id.move_id._rs_form30_plain_entries()
        for credit_line in credit_lines:
            line = credit_line.sudo()
            own_moves = line.move_id | line.move_id.reversal_move_ids
            floor = line.move_id.invoice_date or line.date
            cash, other = [], []
            for partial in line.matched_debit_ids:
                counterpart = partial.debit_move_id
                move = counterpart.move_id
                if move in own_moves or move.exchange_diff_partial_ids:
                    continue
                payment = counterpart.payment_id
                statement_line = counterpart.statement_line_id
                others = move.line_ids.account_id - line.account_id
                if move.state == 'posted' and statement_line:
                    cash.append({
                        'amount': partial.amount,
                        'date': max(statement_line.date, floor),
                        'kind': 'advance' if statement_line.date < floor else 'bank',
                        'payment': payment,
                        'statement_line': statement_line,
                        'matched': True,
                        'withheld_at_payment': False,
                        'offset': move.browse(),
                    })
                elif move.state == 'posted' and payment.state in ('paid', 'reconciled'):
                    statements = payment.reconciled_statement_line_ids
                    matched = payment.is_matched
                    paid_on = max(statements.mapped('date')) if matched and statements else payment.date
                    cash.append({
                        'amount': partial.amount,
                        'date': max(paid_on, floor),
                        'kind': 'advance' if paid_on < floor else 'payment',
                        'payment': payment,
                        'statement_line': statements,
                        'matched': matched,
                        'withheld_at_payment': bool(payment.withholding_line_ids) and payment.withhold != 'payment',
                        'offset': move.browse(),
                    })
                elif move in plain and set(others.mapped('internal_group')) == {'asset'} and 'asset_cash' not in others.mapped('account_type'):
                    cash.append({
                        'amount': partial.amount,
                        'date': max(move.date, floor),
                        'kind': 'offset',
                        'payment': self.env['account.payment'],
                        'statement_line': self.env['account.bank.statement.line'],
                        'matched': True,
                        'withheld_at_payment': False,
                        'offset': move,
                    })
                else:
                    other.append({'amount': partial.amount, 'date': move.date, 'move': move})
            parts[credit_line] = {'cash': cash, 'other': other}
        return parts
