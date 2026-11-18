from dateutil.relativedelta import relativedelta

from odoo import Command, models
from odoo.tools import float_compare, float_is_zero

from .rs_form30_warning import ISSUE_RANK


class RsForm30DeclarationEntry(models.Model):
    _inherit = 'rs.form30.declaration'

    def _rs_form30_add_warning(self, vals, message):
        vals['warning'] = ' '.join(filter(None, [vals.get('warning'), message]))
        level = self._rs_form30_issue_level([message])
        if ISSUE_RANK.get(level, 0) > ISSUE_RANK.get(vals.get('issue_level'), 0):
            vals['issue_level'] = level

    def _rs_form30_entry_vals(self, declared):
        """No date bound on entries, so an advance or old entry paid in the month is found."""
        self.ensure_one()
        Move = self.env['account.move']
        moves = Move.search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'posted'),
            ('move_type', '=', 'entry'),
            ('line_ids.tax_ids.rs_form30_income_type_id', '!=', False),
        ], order='date, id')._rs_form30_plain_entries()
        result = {'lines': [], 'services': [], 'warnings': [], 'unpaid': Move, 'not_payable': Move}
        rules = moves._rs_form30_get_rules()
        splits = {move: move._rs_form30_entry_split(rules) for move in moves}
        parts = self.env['account.move.line'].concat(
            data['lines'] for split in splits.values() for data in split['recipients'].values())._rs_form30_cash_parts()
        for move in moves:
            rows = self._rs_form30_entry_rows(move, splits[move], parts, declared)
            result['lines'] += rows['lines']
            result['services'] += rows['services']
            result['warnings'] += rows['warnings']
            if rows['unpaid']:
                result['unpaid'] |= move
            if rows['not_payable']:
                result['not_payable'] |= move
        result['missing_tax'] = self._rs_form30_missing_tax_moves()
        return result

    def _rs_form30_missing_tax_moves(self):
        self.ensure_one()
        # sudo: the rules are configuration read by every user who posts; the root company is the filter
        rules = self.env['rs.form30.account.rule'].sudo().search([('company_id', 'in', self.company_id.root_id.ids)])
        moves = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'posted'),
            ('move_type', '=', 'entry'),
            ('journal_id.type', '=', 'general'),
            ('origin_payment_id', '=', False),
            ('statement_line_id', '=', False),
            ('reversed_entry_id', '=', False),
            ('date', '>=', self.date_from - relativedelta(months=12)),
            ('date', '<=', self.date_to),
            ('line_ids.account_id', 'in', rules.tax_account_ids.ids),
            ('line_ids', 'not any', [('tax_ids.rs_form30_income_type_id', '!=', False)]),
        ], order='date, id')
        return moves._rs_form30_plain_entries().filtered(lambda move: 'rs_form30_tax_missing' in move._rs_form30_get_alerts())

    def _rs_form30_entry_settlement(self, move, recipients, parts, has_posted_reversal):
        """Return cash and other settlement parts per recipient."""
        settlement = {}
        for partner, data in recipients.items():
            cash = [part for line in data['lines'] for part in parts.get(line, {}).get('cash', [])]
            other = [part for line in data['lines'] for part in parts.get(line, {}).get('other', [])]
            if has_posted_reversal and not cash:
                # sudo: the accountant may lack access to the payments that settled the entry
                payments = move.sudo().matched_payment_ids.filtered(lambda payment: payment.state in ('paid',
                    'reconciled') and payment.partner_id.commercial_partner_id == partner)
                for payment in payments:
                    open_lines = payment.move_id.line_ids.filtered(
                        lambda line: line.account_id in data['lines'].account_id
                        and line.partner_id.commercial_partner_id == partner)
                    amount = abs(sum(open_lines.mapped('amount_residual')))
                    if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
                        continue
                    statements = payment.reconciled_statement_line_ids
                    matched = payment.is_matched
                    cash.append({
                        'amount': amount,
                        'date': max(statements.mapped('date')) if matched and statements else payment.date,
                        'kind': 'payment',
                        'payment': payment,
                        'statement_line': statements,
                        'matched': matched,
                        'withheld_at_payment': bool(payment.withholding_line_ids) and payment.withhold != 'payment',
                        'offset': move.browse(),
                    })
            settlement[partner] = {'cash': cash, 'other': other}
        return settlement

    def _rs_form30_entry_shares(self, split):
        """Return {recipient: (gross, tax, pension)}."""
        currency = self.currency_id
        recipients = split['recipients']
        shares = {}
        tax_left, pension_left = split['tax_total'], split['pension_total']
        for index, (partner, data) in enumerate(recipients.items()):
            if index == len(recipients) - 1 and float_is_zero(split['not_payable_net'], precision_rounding=currency.rounding):
                tax, pension = tax_left, pension_left
            else:
                tax = currency.round(split['tax_total'] * data['net'] / split['net_total'])
                pension = currency.round(split['pension_total'] * data['net'] / split['net_total'])
            tax_left -= tax
            pension_left -= pension
            shares[partner] = (currency.round(data['net'] + tax + pension), tax, pension)
        return shares

    def _rs_form30_entry_rows(self, move, split, parts, declared):
        """Rows and list flags of one entry: a row carries the share settled in cash this month."""
        result = {'lines': [], 'services': [], 'warnings': [], 'unpaid': False, 'not_payable': False}
        recipients = split['recipients']
        reversals = move.reversal_move_ids.filtered(lambda reversal: reversal.state == 'posted')
        has_posted_reversal = bool(reversals)
        settlement = self._rs_form30_entry_settlement(move, recipients, parts, has_posted_reversal)
        if has_posted_reversal and not any(item['cash'] for item in settlement.values()):
            if any(self.date_from <= reversal.date <= self.date_to for reversal in reversals):
                result['warnings'].append("Entry %s was reversed and no payment of it was found: if its recipient was paid from the bank, declare "
                    "the payment by hand." % move.name)
            return result
        result['unpaid'] = move.date <= self.date_to and any(
            not any(part['date'] <= self.date_to for part in item['cash']) for item in settlement.values())
        result['not_payable'] = self.date_from <= move.date <= self.date_to and (split['not_payable'] or not recipients)
        if not recipients:
            return result
        shared = []
        if len(split['taxes']) > 1:
            shared.append("Several withholding taxes in one entry: split it per tax.")
        if len({partner._rs_form30_pays_own_tax() for partner in recipients}) > 1:
            shared.append("Recipients of different status in one entry (own tax and withheld): split the entry.")
        shares = self._rs_form30_entry_shares(split)
        for partner, data in recipients.items():
            item = settlement[partner]
            month, share_before, share_through = self._rs_form30_month_share(item['cash'], data['net'], declared,
                f"{partner.display_name} ({move.name})", self._rs_form30_source(move=move, partner=partner))
            if share_through - share_before <= 0:
                continue
            amounts = self._rs_form30_month_amounts(shares[partner], share_before, share_through)
            row = {
                'date': max(part['date'] for part in month),
                'gross': amounts[0],
                'tax': amounts[1],
                'pension': amounts[2],
                'payment_ids': sorted({payment_id for part in month for payment_id in part['payment'].ids}),
                'statement_ids': sorted({line_id for part in month for line_id in part['statement_line'].ids}),
                'move_ids': sorted({move_id for part in month for move_id in part['offset'].ids}),
            }
            warnings = shared + self._rs_form30_settlement_warnings(month, item['other'])
            if any(part['withheld_at_payment'] for part in month):
                warnings.append("Also withheld at payment: check for a double declaration.")
            if has_posted_reversal:
                warnings.append("Reversed after payment: correct the declaration.")
            if partner._rs_form30_pays_own_tax():
                result['services'].append(self._rs_form30_entry_service_vals(move, split, partner, row, warnings))
            else:
                result['lines'].append(self._rs_form30_entry_line_vals(move, split, partner, row, warnings))
        return result

    def _rs_form30_entry_line_vals(self, move, split, partner, row, warnings):
        """Annex A vals of one recipient and month."""
        currency = self.currency_id
        booked = split['taxes'][:1]
        tax, tax_warnings = self._rs_form30_row_tax(booked, row['date'])
        warnings = [*warnings, *tax_warnings]
        if tax.amount_type != 'percent':
            warnings.append("Tax %s is not a percentage, set the rate manually." % tax.name)
        classification, classification_warnings = self._recipient_classification(partner, row['date'], usage='entry')
        warnings.extend(classification_warnings)
        recipient = self._rs_form30_recipient_vals(partner)
        if partner.is_company and not recipient['first_name']:
            warnings.append("Legal form not detected in the company name.")
        if split['pension_below_zero']:
            warnings.append("Pension below zero on this entry: set to 0, check the pension accounts.")
        expected = currency.round((split['net_total'] + split['tax_total']) * abs(booked.amount) / 100)
        if float_compare(abs(expected - split['tax_total']), 0.01 * max(1, len(split['recipients'])), precision_digits=4) > 0:
            warnings.append("The booked tax differs from the Withholding Tax rate on net + tax.")
        if any(
                line.account_id.reconcile and not float_is_zero(line.amount_residual, precision_rounding=currency.rounding)
                for line in split['tax_lines']):
            warnings.append("Late: the tax was due with the payment on %s and is not paid yet." % row['date'].strftime('%d.%m.%Y'))
        vals = {
            **classification,
            'source': 'entry',
            'move_id': move.id,
            **recipient,
            'income_type_id': tax.rs_form30_income_type_id.id,
            'amount': row['gross'],
            'tax_amount': row['tax'],
            'pension_amount': row['pension'],
            'date': row['date'],
            'rate': abs(tax.amount) if tax.amount_type == 'percent' else 0.0,
            'settlement_payment_ids': [Command.set(row['payment_ids'])],
            'settlement_statement_line_ids': [Command.set(row['statement_ids'])],
            'settlement_move_ids': [Command.set(row['move_ids'])],
        }
        vals.update(warning=' '.join(warnings), issue_level=self._rs_form30_issue_level(warnings))
        return vals

    def _rs_form30_entry_service_vals(self, move, split, partner, row, warnings):
        """Annex E vals of one recipient who pays their own tax."""
        warnings = list(warnings)
        booked = split['taxes'][:1]
        version = booked._rs_form30_version_on(row['date']) or booked
        service_type = version.rs_form30_service_type_id or partner.rs_form30_service_type_id
        if not service_type:
            warnings.append("Set a Form 30 service type on the Withholding Tax or on the contact.")
        if float_compare(row.get('tax', 0.0), 0.0, precision_rounding=self.currency_id.rounding) > 0:
            warnings.append("Tax was withheld from a recipient who pays their own tax: it is not in annex E, check the document.")
        return {
            **self._rs_form30_recipient_vals(partner),
            'move_id': move.id,
            'country_id': partner.country_id.id,
            'service_type_id': service_type.id,
            'amount': row['gross'],
            'date': row['date'],
            'settlement_payment_ids': [Command.set(row['payment_ids'])],
            'settlement_statement_line_ids': [Command.set(row['statement_ids'])],
            'settlement_move_ids': [Command.set(row['move_ids'])],
            'warning': ' '.join(warnings),
            'issue_level': self._rs_form30_issue_level(warnings),
        }

    def _rs_form30_bill_moves(self):
        moves = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', ('in_invoice', 'in_receipt')),
            '|',
            ('line_ids', 'any', [('tax_line_id.gec_is_withholding', '=', True), ('tax_line_id.rs_form30_income_type_id', '!=', False)]),
            ('line_ids', 'any', [('tax_ids.rs_form30_annex_e', '=', True)]),
        ], order='date, id')
        if 'expense_ids' in moves._fields:
            # sudo: the accountant may lack access to employee expenses; only their existence matters
            moves = moves.filtered(lambda move: not move.sudo().expense_ids)
        return moves

    def _rs_form30_bill_vals(self, declared):
        """Annex A and E rows from vendor bills and receipts."""
        self.ensure_one()
        moves = self._rs_form30_bill_moves()
        result = {'lines': [], 'services': []}
        payables = {move: move.line_ids.filtered(lambda line: line.display_type == 'payment_term') for move in moves}
        parts = self.env['account.move.line'].concat(payables.values())._rs_form30_cash_parts()
        for move in moves:
            payable = payables[move]
            partner = move.commercial_partner_id
            net = -sum(payable.mapped('balance'))
            if float_compare(net, 0.0, precision_rounding=self.currency_id.rounding) <= 0:
                continue
            cash = [part for line in payable for part in parts.get(line, {}).get('cash', [])]
            other = [part for line in payable for part in parts.get(line, {}).get('other', [])]
            month, share_before, share_through = self._rs_form30_month_share(cash, net, declared, f"{partner.display_name} ({move.name})",
                self._rs_form30_source(move=move, partner=partner))
            if share_through - share_before <= 0:
                continue
            warnings = self._rs_form30_settlement_warnings(month, other)
            if any(part['withheld_at_payment'] for part in month):
                warnings.append("Also withheld at payment: check for a double declaration.")
            if move.reversal_move_ids and move._rs_form30_reversed_after_payment():
                warnings.append("Reversed after payment: correct the declaration.")
            own_tax = partner._rs_form30_pays_own_tax()
            payment_ids = sorted({payment_id for part in month for payment_id in part['payment'].ids})
            statement_ids = sorted({line_id for part in month for line_id in part['statement_line'].ids})
            move_ids = sorted({move_id for part in month for move_id in part['offset'].ids})
            for tax_line in move.line_ids.filtered(lambda line: line.tax_line_id.gec_is_withholding and line.tax_line_id.rs_form30_income_type_id):
                booked = tax_line.tax_line_id
                amounts = self._rs_form30_month_amounts([tax_line.tax_base_amount, -tax_line.balance,
                    self.currency_id.round(tax_line.tax_base_amount + tax_line.balance)], share_before, share_through)
                row = {
                    'date': max(part['date'] for part in month),
                    'gross': amounts[2] if own_tax and booked.price_include_override == 'tax_included' else amounts[0],
                    'tax': amounts[1],
                    'pension': 0.0,
                    'payment_ids': payment_ids,
                    'statement_ids': statement_ids,
                    'move_ids': move_ids,
                }
                if own_tax:
                    result['services'].append(self._rs_form30_entry_service_vals(move, {'taxes': booked}, partner, row, warnings))
                else:
                    result['lines'].append(self._rs_form30_bill_line_vals(move, booked, partner, row, warnings))
            labelled = move.invoice_line_ids.filtered(lambda line: line.display_type == 'product' and line.tax_ids.filtered('rs_form30_annex_e')
                    and not line.tax_ids.filtered(lambda tax: tax.gec_is_withholding and tax.amount < 0))
            if labelled:
                labels = labelled.tax_ids.filtered('rs_form30_annex_e')
                row = {
                    'date': max(part['date'] for part in month),
                    'gross': self._rs_form30_month_amounts([sum(labelled.mapped('balance'))], share_before, share_through)[0],
                    'payment_ids': payment_ids,
                    'statement_ids': statement_ids,
                    'move_ids': move_ids,
                }
                result['services'].append(self._rs_form30_entry_service_vals(move,
                    {'taxes': labels.filtered('rs_form30_service_type_id')[:1] or labels[:1]}, partner, row, warnings))
        return result

    def _rs_form30_bill_line_vals(self, move, booked, partner, row, warnings):
        """Annex A vals of one withholding tax line of a vendor bill."""
        tax, tax_warnings = self._rs_form30_row_tax(booked, row['date'])
        warnings = [*warnings, *tax_warnings]
        classification, classification_warnings = self._recipient_classification(partner, row['date'], usage='bill')
        warnings.extend(classification_warnings)
        recipient = self._rs_form30_recipient_vals(partner)
        if partner.is_company and not recipient['first_name']:
            warnings.append("Legal form not detected in the company name.")
        vals = {
            **classification,
            'source': 'bill',
            'move_id': move.id,
            **recipient,
            'income_type_id': tax.rs_form30_income_type_id.id,
            'amount': row['gross'],
            'tax_amount': row['tax'],
            'pension_amount': row['pension'],
            'date': row['date'],
            'rate': abs(tax.amount),
            'settlement_payment_ids': [Command.set(row['payment_ids'])],
            'settlement_statement_line_ids': [Command.set(row['statement_ids'])],
            'settlement_move_ids': [Command.set(row['move_ids'])],
        }
        vals.update(warning=' '.join(warnings), issue_level=self._rs_form30_issue_level(warnings))
        return vals
