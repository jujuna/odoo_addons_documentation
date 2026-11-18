from collections import defaultdict

from odoo import Command, models
from odoo.tools import float_compare

SUMMARY_SUMS = {
    '27': ('28', '29', '30', '31', '32'),
    '33': ('34', '35', '36', '37', '38'),
    '40': ('41', '42', '43', '44', '45', '46', '47'),
    '48': ('49', '50', '51', '52', '53', '54', '55'),
}


class RsForm30DeclarationSummary(models.Model):
    _inherit = 'rs.form30.declaration'

    def _trace_item(self, label, value, detail='', record=None, math=''):
        """One contribution to a main-part cell, as the explanation page shows it."""
        return {'label': label, 'value': value, 'detail': detail, 'math': math, 'url': f"/odoo/{record._name}/{record.id}" if record else ''}

    def _summary_values(self, trace=None):
        self.ensure_one()
        cells = defaultdict(float)
        persons = defaultdict(float)
        names = {}

        def add(code, value, line=None, kind='amount', label='', detail='', record=None):
            cells[code] += value
            if trace is not None:
                trace[code].append(line._trace_item(kind, value) if line else self._trace_item(label, value, detail, record))

        lines = self._rs_form30_file_lines()
        for line in lines:
            category, kind = line.category_id, line.income_type_id.code
            gross_cell, base_cell = line._main_part_cells()
            if gross_cell:
                add(gross_cell, line.amount, line)
            if base_cell:
                add(base_cell, line._taxable_base(), line, 'base')
            if kind == '17' and not category.is_organization and not (category.display_code or '').startswith('3.'):
                add('18', line.amount, line)
            tax = line._portal_tax()
            add('56' if category.is_organization else '39', tax, line, 'tax')
            if kind == '1':
                key = line.identification or line.partner_id.id or line.id
                persons[key] += line.amount
                names[key] = f"{line.first_name or ''} {line.last_name or ''}".strip() or str(key)
                if line.autonomous_republic:
                    add('57_1' if line.autonomous_republic == 'adjara' else '57_2', tax, line, 'tax')
        for total, parts in SUMMARY_SUMS.items():
            for part in parts:
                add(total, cells[part], label=self.env._("Cell %s", part))
        arrears = next((line.value for line in self.summary_line_ids if line.code == '56_1'), 0.0)
        add('56_2', arrears * 0.12, label=self.env._("Cell 56¹, typed"), detail=self.env._("× 12%"))
        for code in ('39', '56', '56_2'):
            add('57', cells[code], label=self.env._("Cell %s", code))
        for car in self.car_line_ids:
            add('57', car.amount, label=self.env._("Annex D: %s", car.license_plate or car.name or car.id), detail=self.env._("car benefit tax"))
        for line in lines.filtered('foreign_tax_credit'):
            add('57', -line.foreign_tax_credit, line, 'credit')
        for key, total in sorted(persons.items(), key=lambda pair: pair[1]):
            if trace is not None:
                item = self._trace_item(names[key], total)
                trace['61'].append(item)
                trace['65'].append(item)
                trace['66'].append(item)
        cells['61'] = len(persons)
        cells['65'] = max(persons.values(), default=0.0)
        cells['66'] = min((total for total in persons.values() if total > 0), default=0.0)
        values = {code: self.currency_id.round(value) for code, value in cells.items()}
        values.update(self._ledger_values(trace))
        return values

    def _ledger_values(self, trace=None):
        self.ensure_one()
        company = self.company_id
        MoveLine = self.env['account.move.line']
        posted = [('company_id', '=', company.id), ('parent_state', '=', 'posted')]
        month = posted + [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        income = month + [('account_id.account_type', '=', 'income')]
        expense = month + [('account_id.internal_group', '=', 'expense')]

        def balance(domain):
            return MoveLine._read_group(domain, aggregates=['balance:sum'])[0][0] or 0.0

        cash_accounts = self.env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'cash')]).default_account_id
        cash = posted + [('date', '<=', self.date_to), ('account_id', 'in', cash_accounts.ids)]
        cash_receipts = self.env['account.payment'].search([
            ('company_id', '=', company.id),
            ('journal_id.type', '=', 'cash'),
            ('payment_type', '=', 'inbound'),
            ('state', 'in', ('paid', 'reconciled')),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        advances = self.env['account.chart.template'].with_company(company).ref('gec_account_140311', raise_if_not_found=False)
        balances = MoveLine._read_group(posted + [('date', '<=', self.date_to), ('account_id', '=', advances.id)], groupby=['partner_id'],
            aggregates=['balance:sum']) if advances else []
        unreturned = [total for _partner, total in balances if total > 0]
        if trace is not None:
            for account, total in MoveLine._read_group(income, groupby=['account_id'], aggregates=['balance:sum']):
                trace['58'].append(self._trace_item(account.display_name, -total))
            trace['59'].append(self._trace_item(self.env._("%s posted expense lines in the month", MoveLine.search_count(expense)), None))
            for payment in cash_receipts:
                trace['63'].append(self._trace_item(f"{payment.name} · {payment.partner_id.display_name}",
                                                    payment.amount_company_currency_signed, record=payment))
            for account, total in MoveLine._read_group(cash, groupby=['account_id'], aggregates=['balance:sum']):
                trace['67'].append(self._trace_item(account.display_name, total))
            for partner, total in balances:
                detail = '' if total > 0 else self.env._("ignored: credit balance")
                trace['68'].append(self._trace_item(partner.display_name or self.env._("no partner"), total, detail, partner))
                if total > 0:
                    trace['69'].append(self._trace_item(partner.display_name, None, record=partner))
        return {
            '58': -balance(income),
            '59': bool(MoveLine.search_count(expense, limit=1)),
            '63': sum(cash_receipts.mapped('amount_company_currency_signed')),
            '67': balance(cash),
            '68': sum(unreturned),
            '69': len(unreturned),
        }

    def _sync_summary_lines(self):
        """One row per rs.ge cell: computed cells follow our data, proposed ones until overwritten, typed ones never."""
        self.ensure_one()
        values = self._summary_values()
        existing = {line.cell_id.id: line for line in self.summary_line_ids}
        commands = []
        for cell in self.env['rs.form30.summary.cell'].search([]):
            field = 'value_bool' if cell.is_boolean else 'value'
            value = values.get(cell.code, False if cell.is_boolean else 0.0)
            line = existing.get(cell.id)
            if not line:
                vals = {'cell_id': cell.id, field: value}
                if cell.proposed and not cell.is_boolean:
                    vals['proposed_value'] = value
                commands.append(Command.create(vals))
            elif cell.computed or (cell.proposed and cell.is_boolean):
                line[field] = value
            elif cell.proposed:
                if float_compare(line.value, line.proposed_value, precision_rounding=0.01) == 0:
                    line.value = value
                line.proposed_value = value
        if commands:
            self.write({'summary_line_ids': commands})
