import re
from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_compare
from odoo.tools.misc import formatLang
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

# {t<code>} is replaced by the income type's name, {c<portal number>} by the category's name, at render time.
FORMULAS = {
    '16': _lt("Σ amount of annex A rows with income type {t1}"),
    '17': _lt("Σ base of the same rows: amount − pension − other relief"),
    '18': _lt("Σ amount of {t17} rows paid to resident natural persons; shown for information, never added into cell 39"),
    '19': _lt("Σ base of natural-person rows taxed at 20% with income type {t6}, {t7}, {t17}, {t19} or {t20}, plus any natural-person row no other "
        "cell takes"),
    '20': _lt("Σ base of the same kinds of rows taxed at 5%, hotel-asset owners excepted"),
    '20_1': _lt("Σ base of the same kinds of rows taxed at 3%"),
    '21': _lt("Σ base of natural-person rows with income type {t5}, {t16}, {t21}, {t22} or {t23}"),
    '22': _lt("Σ amount of {t2} rows paid to natural persons"),
    '23': _lt("Σ base of the same rows"),
    '24': _lt("Σ amount of {t3} rows paid to natural persons"),
    '25': _lt("Σ base of the same rows"),
    '26': _lt("Σ base of rows paid to {c1.3} or to {c3.10}"),
    '27': _lt("Cells 28 + 29 + 30 + 31 + 32"),
    '28': _lt("Σ amount of {t17} rows paid to non-resident natural persons at 5%"),
    '29': _lt("Σ amount of rows paid to {c3.6}"),
    '30': _lt("Σ amount of rows paid to {c3.5}"),
    '31': _lt("Σ amount of rows paid to {c3.4} at 10%"),
    '32': _lt("Σ amount of rows paid to {c3.2} at 15%"),
    '33': _lt("Cells 34 + 35 + 36 + 37 + 38"),
    '34': _lt("Σ base of the rows counted in cell 28"),
    '35': _lt("Σ base of the rows counted in cell 29"),
    '36': _lt("Σ base of the rows counted in cell 30"),
    '37': _lt("Σ base of the rows counted in cell 31"),
    '38': _lt("Σ base of the rows counted in cell 32"),
    '39': _lt("Σ tax (base × rate) of every row paid to a natural person, salary rows included. Natural person = every category except {orgs}"),
    '40': _lt("Cells 41 + 42 + 43 + 44 + 45 + 46 + 47"),
    '41': _lt("Σ amount of {t17} rows paid to organizations at 5%"),
    '42': _lt("Σ amount of rows paid to {c3.8}"),
    '43': _lt("Σ amount of rows paid to {c3.7}"),
    '44': _lt("Σ amount of rows paid to {c3.3} at 10%"),
    '45': _lt("Σ amount of rows paid to {c3.1}, dividends excepted"),
    '46': _lt("Σ amount of {t2} rows paid to organizations"),
    '47': _lt("Σ amount of {t3} rows paid to organizations at 5%"),
    '48': _lt("Cells 49 + 50 + 51 + 52 + 53 + 54 + 55"),
    '49': _lt("Σ base of the rows counted in cell 41"),
    '50': _lt("Σ base of the rows counted in cell 42"),
    '51': _lt("Σ base of the rows counted in cell 43"),
    '52': _lt("Σ base of the rows counted in cell 44"),
    '53': _lt("Σ base of the rows counted in cell 45"),
    '54': _lt("Σ base of the rows counted in cell 46"),
    '55': _lt("Σ base of the rows counted in cell 47"),
    '56': _lt("Σ tax (base × rate) of every row paid to an organization. Organizations: {orgs}"),
    '56_1': _lt("Typed by you: salaries accrued before 2008 and paid this month"),
    '56_2': _lt("12% of cell 56¹"),
    '57': _lt("Cell 39 + cell 56 + cell 56² + the car tax of annex D − the foreign tax credit column of annex A"),
    '57_1': _lt("Σ tax of salary rows of employees whose work location is marked Adjara"),
    '57_2': _lt("Σ tax of salary rows of employees whose work location is marked Abkhazia"),
    '58': _lt("Credit minus debit of posted journal items on income accounts, dated in the month"),
    '59': _lt("Ticked when at least one posted expense line is dated in the month"),
    '60': _lt("Typed by you: shortage found by a tax-authority stock count"),
    '61': _lt("Number of different persons among the salary rows"),
    '62': _lt("Typed by you: non-taxable payments to non-employees"),
    '63': _lt("Σ inbound payments received in cash journals, dated in the month"),
    '64': _lt("Typed by you: the part of cell 63 that went through a cash register"),
    '65': _lt("Highest salary total per person in the month"),
    '66': _lt("Lowest salary total per person in the month, above zero"),
    '67': _lt("Balance of the cash journals' accounts at the last day of the month"),
    '68': _lt("Σ positive per-person balances on account 140311 Settlements with Accountable Persons at the last day of the month"),
    '69': _lt("Number of persons counted in cell 68"),
}


class RsForm30Explain(models.TransientModel):
    """Read-only page that shows which rows and journal items make up a main-part cell."""
    _name = 'rs.form30.explain'
    _description = 'Form 30 Main Part Explanation'

    declaration_id = fields.Many2one('rs.form30.declaration', required=True, readonly=True, ondelete='cascade')
    cell_code = fields.Char(required=True, readonly=True)
    explanation = fields.Html(compute='_compute_explanation', sanitize=False)

    @api.depends('declaration_id', 'cell_code')
    def _compute_explanation(self):
        for wizard in self:
            wizard.explanation = self.env['ir.qweb']._render('gec_income_tax_report.main_part_explanation', wizard._explain_summary())

    @api.model
    def _formulas(self):
        names = {f"t{t.code}": t.name for t in self.env['rs.form30.income.type'].search([])}
        categories = self.env['rs.form30.category'].search([])
        names.update({f"c{c.display_code}": c.name for c in categories})
        names['orgs'] = '; '.join(categories.filtered('is_organization').mapped('name'))
        return {code: re.sub(r'\{(\w[^}]*)\}', lambda match: names.get(match.group(1), match.group(0)), self.env._(text))
                for code, text in FORMULAS.items()}

    @api.model
    def _cell_state(self, line, proposal):
        """Return (kind, sentence, stale) of a stored cell against the fresh value."""
        money = lambda value: formatLang(self.env, value, digits=2)
        if line.computed:
            stale = not line.is_boolean and float_compare(line.value, proposal, precision_rounding=0.01) != 0
            state = (
                self.env._("Stored %s, a fresh calculation gives %s: press Generate Lines or Export to refresh.", money(line.value), money(proposal))
                if stale else self.env._("Locked: calculated from the annexes at every Generate Lines and Export."))
            return self.env._("Locked"), state, stale
        if line.proposed:
            edited = not line.is_boolean and float_compare(line.value, line.proposed_value, precision_rounding=0.01) != 0
            state = (self.env._("Typed by you; Odoo proposes %s.", money(proposal)) if edited
                     else self.env._("Proposed by Odoo from its records; type another value to override it."))
            return self.env._("Proposed by Odoo"), state, False
        return self.env._("Typed by you"), self.env._("Typed by you; Odoo has no source for it."), False

    def _explain_summary(self):
        self.ensure_one()
        declaration = self.declaration_id
        trace = defaultdict(list)
        fresh = declaration._summary_values(trace)
        line = declaration.summary_line_ids.filtered(lambda summary: summary.code == self.cell_code)[:1]
        money = lambda value: formatLang(self.env, value, digits=2)
        proposal = fresh.get(line.code, False if line.is_boolean else 0.0)
        _kind, state, stale = self._cell_state(line, proposal)
        return {
            'cell': {
                'code': line.code,
                'name': line.name,
                'note': line.note or '',
                'state': state,
                'stale': stale,
                'display': (self.env._("Yes") if line.value_bool else self.env._("No")) if line.is_boolean else money(line.value),
                'formula': self._formulas().get(line.code, ''),
                'items': [dict(item, display=money(item['value']) if item['value'] is not None else '') for item in trace.get(line.code, [])],
            },
        }
