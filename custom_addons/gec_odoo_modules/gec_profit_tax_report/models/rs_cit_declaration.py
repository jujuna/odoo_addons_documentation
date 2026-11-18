from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .res_company import COMPANY_STATUSES, SPECIAL_STATUSES

CIT_RATE = 0.15
REPRESENTATION_LIMIT = 0.01  # Tax Code art. 98.4: 1% of last year's income (or expenses, when higher)
CHARITY_LIMIT = 0.10  # Tax Code art. 98.3: donations to charities above 10% of last year's net profit
INCOME_TYPES = ('income', 'income_other')
EXPENSE_TYPES = ('expense', 'expense_other', 'expense_depreciation', 'expense_direct_cost')
SALE_TYPES = ('out_invoice', 'out_receipt')
PURCHASE_TYPES = ('in_invoice', 'in_receipt')
# Column 3 rate per Part I or special status (instruction art. 40.1.5). The 10% of research and development
# companies is provisional: the instruction names 5% and 10% without saying who pays 10%.
COL3_RATES = {'international': 0.05, 'investment': 0.05, 'startup': 0.15, 'innovative_sme': 0.15, 'research': 0.10}
# Statuses whose every object goes to column 3.
COL3_ONLY = ('startup', 'innovative_sme', 'research')
# Part IV rates: online casino, online betting (on stakes), gaming hall, foreign players' casino and betting.
GAMBLING_RATES = (0.20, 0.07, 0.20, 0.05, 0.05)
# Rows whose taxed amounts come back on line 27.1 or 27.2 when the money returns (Tax Code art. 98.2.7-8).
RECOVERY_ROWS = {'18.1.1': '27.1', '18.2': '27.1', '18.1.3': '27.2', '18.1.4': '27.2', '18.3': '27.2'}
# Loan accounts feed one of these rows; the contact decides which.
LOAN_ROWS = ('18.1.4', '18.3', '18.4')
# Rows filled by their own method rather than from the row of each journal item.
OWN_METHOD_ROWS = ('16.1', '20')
# Annex 3 rows: (sequence, account balance group, rs.ge row text, sign of the balance).
ANNEX3_ROWS = [
    (1, 'loan_given', "გაცემული სესხ(ებ)ი", 1),
    (2, 'loan_received', "მიღებული სესხ(ებ)ი", -1),
    (3, 'capital', "საწარმოს კაპიტალი", -1),
    (4, 'investment', "სხვა საწარმოში რიცხული კაპიტალი", 1),
]
# Typed annex values carried from the previous declaration: they change only when the history does.
CARRIED_FIELDS = ('a1_2', 'a1_3', 'a1_4', 'a13_2', 'a13_3', 'a13_4', 'a17_3')
# Annex amounts rs.ge lets the taxpayer type although Odoo can work them out: each keeps following Odoo's value
# (stored in <field>_auto) until someone types a different one.
FOLLOWED_FIELDS = ('a1_1', 'a13_1', 'a11_extra', 'a14_extra')
ANNEX_FIELDS = CARRIED_FIELDS + FOLLOWED_FIELDS + (
    'a11_1', 'a11_2', 'a11_3', 'a11_4', 'a14_1', 'a14_2', 'a14_3', 'a14_4', 'a17_2', 'col3_rate', 'company_status', 'special_status')


def gross_up(amount, rate):
    """Taxable amount of a net payment: the payment is what is left after the tax."""
    return amount / (1 - rate) if rate else 0.0


def tax_of(amount, rate):
    return gross_up(amount, rate) * rate


def credit_formula(row1, row2, row3, row4):
    """Annexes 1, 1.1, 1.3 and 1.4 line 5: row 1 x row 2 / (row 3 - row 4)."""
    base = row3 - row4
    return row1 * row2 / base if base > 0 else 0.0


# Formula rows in calculation order: a row is always computed after the rows it uses. Each formula gets the
# column's amounts and its rate. 16.1.3, 25.1, 25.3 and 27.4 come from the annexes: see _annex_amounts().
FORMULAS = [
    ('16.3', lambda a, r: a['16.3.1'] + a['16.3.2']),
    ('16.4', lambda a, r: a['16.4.1'] + a['16.4.2']),
    ('16', lambda a, r: a['16.1'] + a['16.2'] + a['16.3'] + a['16.4'] + a['16.5']),
    ('17', lambda a, r: a['17.1'] + a['17.2'] + a['17.3']),
    ('18.1', lambda a, r: a['18.1.1'] + a['18.1.2'] + a['18.1.3'] + a['18.1.4'] + a['18.1.5']),
    ('18', lambda a, r: a['18.1'] + a['18.2'] + a['18.3'] + a['18.4']),
    ('21', lambda a, r: a['16'] + a['17'] + a['18'] + a['19'] + a['20']),
    ('23', lambda a, r: gross_up(max(0.0, a['21'] - a['22']), r)),
    ('24', lambda a, r: a['23'] * r),
    ('25', lambda a, r: a['25.1'] + a['25.2'] + a['25.3']),
    ('26', lambda a, r: max(0.0, a['24'] - a['25'])),
    ('27', lambda a, r: tax_of(a['27.1'] + a['27.2'] + a['27.3'] + a['27.4'], r)),
    ('28', lambda a, r: max(0.0, a['26'] - a['27'])),
    ('29', lambda a, r: max(0.0, a['27'] - a['26'])),
]


class RsCitDeclaration(models.Model):
    """One monthly profit tax declaration of one company."""
    _name = 'rs.cit.declaration'
    _description = 'rs.ge Monthly Profit Tax Declaration'
    _order = 'date_from desc, version desc, id desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date(string='Month', required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1) - relativedelta(months=1))
    date_to = fields.Date(compute='_compute_date_to', store=True)
    period_label = fields.Char(string='Period', compute='_compute_period_label', help="The month as rs.ge prints it: 2026/10.")
    version = fields.Integer(default=1, required=True, readonly=True, copy=False,
                             help="1 for the primary declaration, 2 and up for each corrected one.")
    declaration_type = fields.Selection([('primary', 'Primary'),
                                         ('corrected', 'Corrected')],
                                        compute='_compute_declaration_type', store=True)
    state = fields.Selection([('draft', 'Draft'),
                              ('confirmed', 'Confirmed')],
                             required=True, default='draft', copy=False)
    line_ids = fields.One2many('rs.cit.declaration.line', 'declaration_id', copy=False,
                               default=lambda self: self._default_line_ids())

    # Part I
    company_status = fields.Selection(COMPANY_STATUSES, string='Enterprise Status', required=True,
                                      compute='_compute_header', store=True, readonly=False, precompute=True)
    special_status = fields.Selection(SPECIAL_STATUSES, string='Special Status', compute='_compute_header',
                                      store=True, readonly=False, precompute=True,
                                      help="Not printed in Part I: decides column 3, line 16.1.4 and annex 1.7.")
    col3_rate = fields.Float(string='Column 3 Rate', digits=(4, 4), compute='_compute_col3_rate', store=True,
                             readonly=False, precompute=True,
                             help="Profit tax rate of column 3: 5% for international and investment companies, 15% "
                                  "for innovative startups and innovative small or medium companies.")

    # Values Recalculate reads from accounting for the formulas and annexes.
    dividend_total = fields.Monetary(readonly=True, copy=False,
                                     help="Dividends paid this month and taxed, withholding tax included.")
    dividend_unmatched = fields.Integer(readonly=True, copy=False,
                                        help="Dividend payments not matched with their declaration entry: any "
                                             "withholding tax kept from them is missing from line 16.1.")
    unclassified_count = fields.Integer(readonly=True, copy=False,
                                        help="Journal items on line 18 accounts without a contact.")
    charity_taxed = fields.Monetary(readonly=True, copy=False,
                                    help="Donations to charities taxed on line 19 by this declaration.")
    representation_founding_year = fields.Boolean(readonly=True, copy=False)

    # Annex 1: credit for profit tax paid on 2008-2016 profits (insurers 2015-2023), line 25.1.
    a1_1 = fields.Monetary(string='Annex 1 Line 1', help="Dividends of the month out of the old profits: line 16.1.1 "
                                                         "until you type another amount.")
    a1_1_auto = fields.Monetary(readonly=True)
    a1_2 = fields.Monetary(string='Annex 1 Line 2', help="Profit tax accrued and paid for the old periods.")
    a1_3 = fields.Monetary(string='Annex 1 Line 3', help="Net profit of the old periods in total, losses included.")
    a1_4 = fields.Monetary(string='Annex 1 Line 4',
                           help="Own shares given to partners instead of dividends out of the old net profit.")
    a1_5 = fields.Monetary(compute='_compute_annexes', string='Annex 1 Line 5')
    # Annex 1.1: correction of that credit, Part II and III (Part I is in annex lines).
    a11_1 = fields.Monetary(string='Annex 1.1 Part II Line 1')
    a11_2 = fields.Monetary(string='Annex 1.1 Part II Line 2')
    a11_3 = fields.Monetary(string='Annex 1.1 Part II Line 3')
    a11_4 = fields.Monetary(string='Annex 1.1 Part II Line 4')
    a11_5 = fields.Monetary(compute='_compute_annexes', string='Annex 1.1 Part II Line 5')
    a11_extra = fields.Monetary(string='Annex 1.1 Part III',
                                help="Additional credit, booked on the personal account card by rs.ge. Odoo's formula "
                                     "until you type another amount.")
    a11_extra_auto = fields.Monetary(readonly=True)
    # Annex 1.3: credit for profit tax paid in the Tax Code art. 309.94 period, line 25.3.
    a13_1 = fields.Monetary(string='Annex 1.3 Line 1', help="Line 16.1.2 until you type another amount.")
    a13_1_auto = fields.Monetary(readonly=True)
    a13_2 = fields.Monetary(string='Annex 1.3 Line 2')
    a13_3 = fields.Monetary(string='Annex 1.3 Line 3')
    a13_4 = fields.Monetary(string='Annex 1.3 Line 4')
    a13_5 = fields.Monetary(compute='_compute_annexes', string='Annex 1.3 Line 5')
    # Annex 1.4: correction of the annex 1.3 credit.
    a14_1 = fields.Monetary(string='Annex 1.4 Part II Line 1')
    a14_2 = fields.Monetary(string='Annex 1.4 Part II Line 2')
    a14_3 = fields.Monetary(string='Annex 1.4 Part II Line 3')
    a14_4 = fields.Monetary(string='Annex 1.4 Part II Line 4')
    a14_5 = fields.Monetary(compute='_compute_annexes', string='Annex 1.4 Part II Line 5')
    a14_extra = fields.Monetary(string='Annex 1.4 Part III', help="Odoo's formula until you type another amount.")
    a14_extra_auto = fields.Monetary(readonly=True)
    # Annex 1.7: innovative small or medium company, research and development expenses x3.
    a17_1 = fields.Monetary(compute='_compute_annexes', string='Annex 1.7 Column 1')
    a17_2 = fields.Monetary(string='Annex 1.7 Column 2',
                            help="Of column 1, dividends paid out of last financial year's net profit.")
    a17_3 = fields.Monetary(string='Annex 1.7 Column 3',
                            help="Three times last financial year's research and development expenses.")
    a17_4 = fields.Monetary(compute='_compute_annexes', string='Annex 1.7 Column 4')
    a17_5 = fields.Monetary(compute='_compute_annexes', string='Annex 1.7 Column 5')
    a17_6 = fields.Monetary(compute='_compute_annexes', string='Annex 1.7 Column 6')
    # Annex 2 (March): inventory and fixed assets at the end of last year.
    a2_inventory = fields.Monetary(string='Inventory at Year End', readonly=True, copy=False)
    a2_fixed = fields.Monetary(string='Fixed Assets at Year End', readonly=True, copy=False)
    # Annex 1.2 is the recovery register of this declaration; annexes 1.1/1.4 part I, 1.5, 1.6, 3 and 4 are lines.
    recovery_ids = fields.One2many('rs.cit.recovery', 'declaration_id', string='Annex 1.2', readonly=True)
    taxed_item_ids = fields.One2many('rs.cit.taxed.item', 'declaration_id', string='Taxed Items', readonly=True)
    annex_line_ids = fields.One2many('rs.cit.annex.line', 'declaration_id', copy=True)
    annex11_line_ids = fields.One2many('rs.cit.annex.line', 'declaration_id', domain=[('annex', '=', '1.1')])
    annex14_line_ids = fields.One2many('rs.cit.annex.line', 'declaration_id', domain=[('annex', '=', '1.4')])
    annex15_line_ids = fields.One2many('rs.cit.annex.line', 'declaration_id', domain=[('annex', '=', '1.5')])
    annex16_line_ids = fields.One2many('rs.cit.annex.line', 'declaration_id', domain=[('annex', '=', '1.6')])
    annex3_line_ids = fields.One2many('rs.cit.annex.line', 'declaration_id', domain=[('annex', '=', '3')],
                                      default=lambda self: self._default_annex3_lines())
    annex4_line_ids = fields.One2many('rs.cit.annex.line', 'declaration_id', domain=[('annex', '=', '4')])

    annex3_none = fields.Boolean(
        string='No Annex 3 Information',
        help="Ticked when the company has none of the information annex 3 asks for, as the rs.ge form requires.")

    # Part IV: gambling organisers.
    gambling = fields.Boolean(related='company_id.gec_cit_gambling')
    is_march = fields.Boolean(compute='_compute_is_march', help="Annexes 2 and 4 are filed with the March declaration.")
    g1 = fields.Monetary(string='Part IV Line 1', help="Online casino: stakes less winnings paid.")
    g2 = fields.Monetary(string='Part IV Line 2', help="Online betting: stakes received.")
    g3 = fields.Monetary(string='Part IV Line 3', help="Gaming hall: stakes less winnings paid.")
    g4 = fields.Monetary(string='Part IV Line 4', help="Online casino, foreign players: stakes less winnings paid.")
    g5 = fields.Monetary(string='Part IV Line 5', help="Online betting, foreign players: stakes less winnings paid.")
    g1_tax = fields.Monetary(compute='_compute_gambling', string='Part IV Tax 1')
    g2_tax = fields.Monetary(compute='_compute_gambling', string='Part IV Tax 2')
    g3_tax = fields.Monetary(compute='_compute_gambling', string='Part IV Tax 3')
    g4_tax = fields.Monetary(compute='_compute_gambling', string='Part IV Tax 4')
    g5_tax = fields.Monetary(compute='_compute_gambling', string='Part IV Tax 5')
    gambling_total = fields.Monetary(compute='_compute_gambling', string='Part IV Total')

    # Totals and booking.
    tax_payable = fields.Monetary(compute='_compute_totals', string='Tax Payable',
                                  help="Line 28 of both columns plus part IV.")
    tax_refund = fields.Monetary(compute='_compute_totals', string='Tax Refundable', help="Line 29 of both columns.")
    booking_amount = fields.Monetary(compute='_compute_totals', string='Tax to Book',
                                     help="Profit tax this declaration books: payable less refundable, less the "
                                          "dividend tax the CIT wizard books with the dividend.")
    booked_amount = fields.Monetary(readonly=True, copy=False,
                                    help="Amount of the entry posted by this declaration (a correction posts the "
                                         "difference).")
    move_id = fields.Many2one('account.move', string='Profit Tax Entry', readonly=True, copy=False,
                              check_company=True)
    checks = fields.Text(compute='_compute_checks', help="Things to look at before filing.")

    _company_month_version_uniq = models.Constraint(
        'UNIQUE(company_id, date_from, version)', 'One declaration per company, month and version.')

    @api.depends('company_id.name', 'date_from', 'version')
    def _compute_name(self):
        for declaration in self:
            month = declaration.date_from.strftime('%Y/%m') if declaration.date_from else ''
            suffix = f" ({declaration.version})" if declaration.version > 1 else ''
            declaration.name = f"Profit Tax {month}{suffix} {declaration.company_id.name or ''}".strip()

    @api.depends('date_from')
    def _compute_date_to(self):
        for declaration in self:
            start = declaration.date_from
            declaration.date_to = start + relativedelta(months=1, days=-1) if start else False

    @api.depends('date_from')
    def _compute_period_label(self):
        for declaration in self:
            declaration.period_label = declaration.date_from.strftime('%Y/%m') if declaration.date_from else False

    @api.depends('version')
    def _compute_declaration_type(self):
        for declaration in self:
            declaration.declaration_type = 'corrected' if declaration.version > 1 else 'primary'

    @api.depends('company_id')
    def _compute_header(self):
        for declaration in self:
            company = declaration.company_id
            declaration.company_status = company.gec_cit_company_status or 'resident'
            declaration.special_status = company.gec_cit_special_status

    @api.depends('date_from')
    def _compute_is_march(self):
        for declaration in self:
            declaration.is_march = bool(declaration.date_from) and declaration.date_from.month == 3

    @api.depends('company_status', 'special_status')
    def _compute_col3_rate(self):
        for declaration in self:
            declaration.col3_rate = COL3_RATES.get(declaration._cit_status(), 0.0)

    def _cit_status(self):
        """The status that decides column 3: the special status when there is one, else the Part I status."""
        self.ensure_one()
        return self.special_status or self.company_status

    @api.depends('g1', 'g2', 'g3', 'g4', 'g5')
    def _compute_gambling(self):
        for declaration in self:
            taxes = [declaration.currency_id.round(declaration[f'g{n}'] * rate)
                     for n, rate in enumerate(GAMBLING_RATES, 1)]
            for n, amount in enumerate(taxes, 1):
                declaration[f'g{n}_tax'] = amount
            declaration.gambling_total = sum(taxes)

    @api.depends('line_ids.amount', 'line_ids.amount3', 'gambling_total', 'col3_rate')
    def _compute_totals(self):
        for declaration in self:
            lines = {line.code: line for line in declaration.line_ids}
            if not lines:
                declaration.tax_payable = declaration.tax_refund = declaration.booking_amount = 0.0
                continue
            payable = lines['28'].amount + lines['28'].amount3 + declaration.gambling_total
            refund = lines['29'].amount + lines['29'].amount3
            dividend_tax = (
                max(0.0, tax_of(lines['16.1'].amount, CIT_RATE) - lines['25'].amount)
                + max(0.0, tax_of(lines['16.1'].amount3, declaration.col3_rate) - lines['25'].amount3))
            declaration.tax_payable = payable
            declaration.tax_refund = refund
            declaration.booking_amount = declaration.currency_id.round(payable - refund - dividend_tax)

    @api.depends('line_ids.amount', 'a1_1', 'a1_2', 'a1_3', 'a1_4', 'a13_1', 'a11_1', 'a11_2', 'a11_3', 'a11_4', 'a13_2', 'a13_3',
                 'a13_4', 'a14_1', 'a14_2', 'a14_3', 'a14_4', 'a17_2', 'a17_3', 'dividend_total',
                 'annex_line_ids.amount1', 'annex_line_ids.amount2')
    def _compute_annexes(self):
        for declaration in self:
            lines = {line.code: line for line in declaration.line_ids}
            amount = lambda code: lines[code].amount if code in lines else 0.0
            annex = lambda code: declaration.annex_line_ids.filtered(lambda l: l.annex == code)
            declaration.a1_5 = credit_formula(declaration.a1_1, declaration.a1_2, declaration.a1_3, declaration.a1_4)
            declaration.a13_5 = credit_formula(declaration.a13_1, declaration.a13_2, declaration.a13_3,
                                               declaration.a13_4)
            for prefix in ('a11', 'a14'):
                declaration[f'{prefix}_5'] = credit_formula(*(declaration[f'{prefix}_{n}'] for n in range(1, 5)))
            declaration.a17_1 = declaration.dividend_total if declaration.special_status == 'innovative_sme' else 0.0
            declaration.a17_4 = declaration._a17_used_before()
            declaration.a17_5 = max(0.0, declaration.a17_3 - declaration.a17_4)
            first, second, fifth = declaration.a17_1, declaration.a17_2, declaration.a17_5
            declaration.a17_6 = first - second if fifth >= second else first - fifth

    def _followed_suggestions(self):
        """Odoo's own value of each field in FOLLOWED_FIELDS."""
        self.ensure_one()
        amounts = {line.code: line.amount for line in self.line_ids}
        suggestions = {'a1_1': amounts.get('16.1.1', 0.0), 'a13_1': amounts.get('16.1.2', 0.0)}
        for prefix, code in (('a11', '1.1'), ('a14', '1.4')):
            lines = self.annex_line_ids.filtered(lambda l: l.annex == code)
            fifth = credit_formula(*(self[f'{prefix}_{n}'] for n in range(1, 5)))
            credited = sum(lines.mapped('amount1'))
            taxable = sum(lines.mapped('amount2'))
            suggestions[f'{prefix}_extra'] = max(0.0, min(fifth - credited, tax_of(taxable, CIT_RATE) - credited))
        return suggestions

    def _sync_followed(self):
        """Move each followed field to Odoo's new value, unless someone typed a different one."""
        for declaration in self.filtered(lambda d: d.state == 'draft'):
            round_ = declaration.currency_id.round
            vals = {}
            for fname, value in declaration._followed_suggestions().items():
                value = round_(value)
                if round_(declaration[fname] - declaration[f'{fname}_auto']) == 0 and declaration[fname] != value:
                    vals[fname] = value
                if declaration[f'{fname}_auto'] != value:
                    vals[f'{fname}_auto'] = value
            if vals:
                declaration.with_context(gec_cit_sync=True).write(vals)

    def _a17_used_before(self):
        """Annex 1.7 column 4: the R&D allowance earlier declarations of the year already used."""
        self.ensure_one()
        if not self.date_from:
            return 0.0
        return sum(min(declaration.a17_2, declaration.a17_5) for declaration in self._earlier_confirmed())

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('date_from'):
                vals['date_from'] = fields.Date.to_date(vals['date_from']).replace(day=1)
            company_id = vals.get('company_id') or self.env.company.id
            previous = self.search([('company_id', '=', company_id)], order='date_from desc, version desc', limit=1)
            for fname in CARRIED_FIELDS:
                if fname not in vals and previous:
                    vals[fname] = previous[fname]
        declarations = super().create(vals_list)
        cells = self.env['rs.cit.cell'].search([])
        for declaration in declarations:
            missing = cells - declaration.line_ids.cell_id
            if missing:
                declaration.line_ids = [Command.create({'cell_id': cell.id}) for cell in missing]
            if not declaration.annex3_line_ids:
                declaration.annex3_line_ids = self._default_annex3_lines()
        return declarations

    @api.model
    def _default_annex3_lines(self):
        """The four rows of annex 3, so a new declaration shows them before Recalculate fills them."""
        return [Command.create({'annex': '3', 'sequence': sequence, 'name': label})
                for sequence, _group, label, _sign in ANNEX3_ROWS]

    @api.model
    def _gec_cit_fill_annex3(self):
        """Give declarations saved before annex 3 rows existed by default their four rows (data file call)."""
        for declaration in self.search([('annex3_line_ids', '=', False)]):
            self.env['rs.cit.annex.line'].sudo().create([
                {'declaration_id': declaration.id, 'annex': '3', 'sequence': sequence, 'name': label}
                for sequence, _group, label, _sign in ANNEX3_ROWS])

    @api.model
    def _default_line_ids(self):
        """One line per form row, so a new declaration shows the whole of part III before it is saved."""
        return [Command.create({'cell_id': cell.id}) for cell in self.env['rs.cit.cell'].search([])]

    def write(self, vals):
        if 'date_from' in vals and vals['date_from']:
            vals['date_from'] = fields.Date.to_date(vals['date_from']).replace(day=1)
        if set(vals) - {'state', 'move_id', 'booked_amount'} and self.filtered(lambda d: d.state == 'confirmed'):
            raise UserError(_("A confirmed declaration cannot be changed. Set it back to draft first."))
        result = super().write(vals)
        if set(vals) & set(ANNEX_FIELDS) and not self.env.context.get('gec_cit_sync'):
            self._compute_formulas()
        return result

    def _check_draft(self):
        if self.filtered(lambda d: d.state == 'confirmed'):
            raise UserError(_("A confirmed declaration cannot be changed. Set it back to draft first."))

    # ------------------------------------------------------------------
    # Recalculate
    # ------------------------------------------------------------------

    def action_compute(self):
        self._check_draft()
        for declaration in self:
            declaration._compute_account_rows()
            declaration._compute_representation()
            declaration._compute_market_price_rows()
            declaration._compute_recoveries()
            declaration._compute_balance_annexes()
        self._compute_formulas()

    def _cit_items_domain(self, date_from, date_to):
        self.ensure_one()
        return [
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]

    def _cit_balance(self, domain):
        return self.env['account.move.line']._read_group(domain, aggregates=['balance:sum'])[0][0]

    def _earlier_confirmed(self):
        """The latest confirmed version of each earlier month of the same year."""
        self.ensure_one()
        year_start = self.date_from.replace(month=1, day=1)
        earlier = self.search([
            ('company_id', '=', self.company_id.id), ('state', '=', 'confirmed'),
            ('date_from', '>=', year_start), ('date_from', '<', self.date_from)])
        latest_by_month = {}
        for declaration in earlier.sorted('version'):
            latest_by_month[declaration.date_from] = declaration
        return self.browse([declaration.id for declaration in latest_by_month.values()])

    def _is_latest_confirmed(self):
        """Confirmed, and no later version of the same month is confirmed."""
        self.ensure_one()
        return self.state == 'confirmed' and not self.search_count([
            ('company_id', '=', self.company_id.id), ('date_from', '=', self.date_from),
            ('state', '=', 'confirmed'), ('version', '>', self.version)], limit=1)

    def _auto_vals(self, value, items):
        """Write a row read from accounting in column 2, or in column 3 for the statuses taxed there."""
        self.ensure_one()
        value = self.currency_id.round(value)
        col3 = self._cit_status() in COL3_ONLY
        return {
            'amount_auto': 0.0 if col3 else value,
            'amount3_auto': value if col3 else 0.0,
            'move_line_ids': [Command.set(items.ids)],
        }

    def _cit_partner_row(self, code, partner):
        """Row a journal item counts on when its row comes from its account: the contact decides whether it
        counts at all, and which loan row it feeds. Returns False when it does not count."""
        self.ensure_one()
        if not partner:
            return code if code in ('16.1', '19') or not code.startswith('18') else False
        status = partner.gec_cit_status
        preferential = partner._gec_cit_preferential()
        financial = self.company_id.gec_cit_financial
        if code == '16.1':
            # Dividends paid to a Georgian enterprise are not taxed (Tax Code art. 98.1.4.a).
            return False if status == 'enterprise' else code
        if code in ('18.1.1', '18.1.2', '18.1.3'):
            return code if preferential or status == 'exempt' else False
        if code == '18.1.5':
            return code if preferential or status in ('exempt', 'budget') else False
        if code == '18.2':
            if partner.gec_cit_listed_abroad:
                return False
            return code if partner._gec_cit_non_resident() or status == 'exempt' else False
        if code in LOAN_ROWS:
            if preferential or (status in ('exempt', 'budget') and not financial):
                return '18.1.4'
            if financial:
                share = partner.gec_cit_share
                shareholder = share and (partner._gec_cit_non_resident() or status in ('exempt', 'budget')
                                         or (not partner.is_company and share >= 1))
                return '18.4' if shareholder else False
            if partner.gec_cit_listed_abroad:
                return False
            return '18.3' if not partner.is_company or partner._gec_cit_non_resident() else False
        return code

    def _compute_account_rows(self):
        """Fill the rows read from accounting: each posted journal item of the month counts on the row it
        chose, or else on the row of its account when its contact makes it count."""
        self.ensure_one()
        AccountMoveLine = self.env['account.move.line']
        items = AccountMoveLine.search(self._cit_items_domain(self.date_from, self.date_to) + [
            '|', ('gec_cit_cell_id', '!=', False), ('account_id.gec_cit_cell_id', '!=', False)])
        lines = {line.code: line for line in self.line_ids}
        items_by_code = defaultdict(lambda: AccountMoveLine)
        charity = AccountMoveLine
        unclassified = 0
        for item in items:
            chosen = item.gec_cit_cell_id
            code = (chosen or item.account_id.gec_cit_cell_id).code
            line = lines.get(code)
            if not line or line.kind != 'auto' or code == '20' or line.cell_id.measure in ('market', 'register'):
                continue
            if not chosen:
                partner = item.partner_id.commercial_partner_id.with_company(self.company_id)
                if code == '19':
                    if partner.gec_cit_status in ('budget', 'nbg_dia'):
                        continue  # gifts to the state and public law entities are not taxed
                    if partner.gec_cit_charity:
                        charity |= item
                        continue
                elif code.startswith('18') and not partner:
                    unclassified += 1
                code = self._cit_partner_row(code, partner)
                if not code:
                    continue
            items_by_code[code] |= item
        items_by_code['17.3'] |= self._supplier_bill_items()
        # Row 19 includes its row 19.1 ("of which"): shortages count on both.
        items_by_code['19'] |= items_by_code['19.1']
        charity_taxed = self._charity_taxed()

        for line in self.line_ids.filtered(lambda l: l.kind == 'auto' and l.code not in OWN_METHOD_ROWS
                                           and l.cell_id.measure not in ('market', 'register')):
            cell_items = items_by_code[line.code]
            if line.cell_id.measure == 'debit':
                cell_items = cell_items.filtered(lambda item: item.debit)
                value = sum(cell_items.mapped('debit'))
            else:
                value = sum(cell_items.mapped('balance'))
            if line.code == '19':
                value += charity_taxed
                cell_items |= charity
            line.write(self._auto_vals(value, cell_items))

        dividends = items_by_code['16.1'].filtered(lambda item: item.debit)
        total, unmatched = self._dividend_base(dividends)
        lines['16.1'].move_line_ids = [Command.set(dividends.ids)]
        self.write({
            'dividend_total': self.currency_id.round(total),
            'dividend_unmatched': unmatched,
            'unclassified_count': unclassified,
            'charity_taxed': self.currency_id.round(charity_taxed),
        })

    def _supplier_bill_items(self):
        """Line 17.3: bill lines from micro business persons and fixed tax payers, unless the line or its
        account already feeds a row."""
        self.ensure_one()
        return self.env['account.move.line'].search(self._cit_items_domain(self.date_from, self.date_to) + [
            ('display_type', '=', 'product'),
            ('move_id.move_type', 'in', PURCHASE_TYPES + ('in_refund',)),
            ('gec_cit_cell_id', '=', False),
            ('account_id.gec_cit_cell_id', '=', False),
            '|', ('partner_id.commercial_partner_id.gec_cit_micro_business', '=', True),
                 ('partner_id.commercial_partner_id.gec_cit_fixed_tax', '=', True)])

    def _dividend_base(self, payments):
        """Dividends paid, withholding tax included. The CIT wizard credits the dividend account with the
        dividend less the withholding tax; a payment matched with that entry gets the tax added back."""
        total, unmatched = 0.0, 0
        for payment in payments:
            matched = 0.0
            for partial in payment.matched_credit_ids:
                accrual = partial.credit_move_id.move_id
                rate = sum(abs(tax.amount) for tax in accrual.line_ids.filtered('debit').tax_ids
                           if tax.amount_type == 'percent' and (tax.is_withholding_tax or tax.amount < 0)) / 100.0
                total += gross_up(partial.amount, rate) if 0 < rate < 1 else partial.amount
                matched += partial.amount
            rest = payment.debit - matched
            if not payment.company_currency_id.is_zero(rest):
                total += rest
                unmatched += 1
        return total, unmatched

    def _last_year_totals(self):
        """Income, expenses and net profit of last calendar year."""
        self.ensure_one()
        year_start = self.date_from.replace(month=1, day=1)
        last_year = (year_start - relativedelta(years=1), year_start - relativedelta(days=1))
        domain = lambda types: self._cit_items_domain(*last_year) + [('account_id.account_type', 'in', types)]
        income = -self._cit_balance(domain(INCOME_TYPES))
        expenses = self._cit_balance(domain(EXPENSE_TYPES))
        return income, expenses, income - expenses

    def _charity_taxed(self):
        """Donations to charities this year above 10% of last year's net profit, less what earlier months
        of the year already declared (Tax Code art. 98.3; instruction example 4)."""
        self.ensure_one()
        year_start = self.date_from.replace(month=1, day=1)
        row = self.line_ids.filtered(lambda l: l.code == '19').cell_id
        items = self.env['account.move.line'].search(self._cit_items_domain(year_start, self.date_to) + [
            ('gec_cit_cell_id', '=', False), ('account_id.gec_cit_cell_id', '=', row.id),
            ('partner_id.commercial_partner_id.gec_cit_charity', '=', True)])
        donated = sum(items.mapped('balance'))
        if not donated:
            return 0.0
        limit = max(0.0, self._last_year_totals()[2]) * CHARITY_LIMIT
        already = sum(self._earlier_confirmed().mapped('charity_taxed'))
        return max(0.0, donated - limit - already)

    def _compute_representation(self):
        """Row 20: representation expenses of the year so far above the limit, less what earlier months
        of the year already declared."""
        self.ensure_one()
        line = self.line_ids.filtered(lambda l: l.code == '20')
        year_start = self.date_from.replace(month=1, day=1)
        AccountMoveLine = self.env['account.move.line']
        items = AccountMoveLine.search(self._cit_items_domain(year_start, self.date_to) + [
            '|', ('gec_cit_cell_id', '=', line.cell_id.id),
            '&', ('gec_cit_cell_id', '=', False), ('account_id.gec_cit_cell_id', '=', line.cell_id.id)])
        spent = sum(items.mapped('balance'))
        founding_year = not AccountMoveLine.search_count([
            ('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted'), ('date', '<', year_start),
        ], limit=1)
        if founding_year:
            # The founding year's limit is 1% of that year's expenses; until December only the expenses so far
            # are known (instruction example 6).
            expenses = self._cit_balance(self._cit_items_domain(year_start, self.date_to) + [
                ('account_id.account_type', 'in', EXPENSE_TYPES)])
            limit = expenses * REPRESENTATION_LIMIT
        else:
            income, expenses, _profit = self._last_year_totals()
            limit = max(income, expenses) * REPRESENTATION_LIMIT
        already = sum(line.amount + line.amount3 for line in self._earlier_confirmed().line_ids
                      if line.code == '20')
        line.write(self._auto_vals(max(0.0, spent - limit - already) if spent else 0.0, items))
        self.representation_founding_year = founding_year

    def _compute_market_price_rows(self):
        """Lines 16.3 and 16.4: invoice lines with a market value, sold below it or bought above it. A person
        exempt from profit tax feeds 16.4; any other related party that is not a Georgian Enterprise feeds 16.3."""
        self.ensure_one()
        items = self.env['account.move.line'].search(self._cit_items_domain(self.date_from, self.date_to) + [
            ('display_type', '=', 'product'),
            ('gec_cit_market_value', '>', 0),
            ('move_id.move_type', 'in', SALE_TYPES + PURCHASE_TYPES)])
        amounts = defaultdict(float)
        items_by_code = defaultdict(lambda: self.env['account.move.line'])
        for item in items:
            partner = item.partner_id.commercial_partner_id.with_company(self.company_id)
            if partner.gec_cit_status == 'exempt':
                row = '16.4'
            elif partner.gec_cit_related_party and partner.gec_cit_status != 'enterprise':
                row = '16.3'
            else:
                continue
            if item.move_id.move_type in SALE_TYPES:
                code, difference = f'{row}.1', item.gec_cit_market_value + item.balance  # market - income
            else:
                code, difference = f'{row}.2', item.balance - item.gec_cit_market_value  # expense - market
            if difference > 0:
                amounts[code] += difference
                items_by_code[code] |= item
        for line in self.line_ids.filtered(lambda l: l.cell_id.measure == 'market'):
            line.write(self._auto_vals(amounts[line.code], items_by_code[line.code]))

    def _compute_recoveries(self):
        """Register what this month taxes on the recoverable lines, then lines 27.1 and 27.2 (annex 1.2):
        money coming back this month on amounts taxed earlier, matched by account and contact, oldest first."""
        self.ensure_one()
        TaxedItem = self.env['rs.cit.taxed.item']
        self.taxed_item_ids.unlink()
        lines = {line.code: line for line in self.line_ids}
        TaxedItem.create([{
            'declaration_id': self.id,
            'cell_id': lines[code].cell_id.id,
            'move_line_id': item.id,
            'amount': item.debit,
        } for code in RECOVERY_ROWS for item in lines[code].move_line_ids])

        candidates = TaxedItem.search([
            ('company_id', '=', self.company_id.id), ('date', '<=', self.date_to),
        ]).filtered(lambda t: t._counts_for(self)).sorted(lambda t: (t.date, t.id))
        credits = self.env['account.move.line'].search(self._cit_items_domain(self.date_from, self.date_to) + [
            ('credit', '>', 0), ('account_id', 'in', candidates.account_id.ids), ('partner_id', '!=', False)])
        available = {taxed: taxed._available_for(self) for taxed in candidates}
        recoveries = []
        for credit in credits.sorted(lambda c: (c.date, c.id)):
            left = credit.credit
            partner = credit.partner_id.commercial_partner_id
            for taxed in candidates:
                if left <= 0:
                    break
                if taxed.account_id != credit.account_id or taxed.partner_id != partner or available[taxed] <= 0:
                    continue
                amount = min(left, available[taxed])
                available[taxed] -= amount
                left -= amount
                recoveries.append({'declaration_id': self.id, 'taxed_item_id': taxed.id,
                                   'move_line_id': credit.id, 'amount': amount})
        self.recovery_ids = [Command.clear()] + [Command.create(vals) for vals in recoveries]
        for code in ('27.1', '27.2'):
            mine = self.recovery_ids.filtered(lambda r: r.code == code)
            lines[code].write(self._auto_vals(sum(mine.mapped('amount')), mine.move_line_id))

    def _compute_balance_annexes(self):
        """Annex 2 (March only: last year's closing inventory and fixed assets) and annex 3 (loans and
        capital of the month)."""
        self.ensure_one()
        balance = lambda group, domain: self._cit_balance(domain + [
            ('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted'),
            ('account_id.gec_cit_balance_group', '=', group)])
        if self.date_from.month == 3:
            year_end = self.date_from.replace(month=1, day=1) - relativedelta(days=1)
            self.a2_inventory = self.currency_id.round(balance('inventory', [('date', '<=', year_end)]))
            self.a2_fixed = self.currency_id.round(balance('fixed_asset', [('date', '<=', year_end)]))
        else:
            self.a2_inventory = self.a2_fixed = 0.0

        AccountMoveLine = self.env['account.move.line']
        exchange_journal = self.company_id.currency_exchange_journal_id
        loans = ('loan_given', 'loan_received')
        vals_list = []
        for sequence, group, label, sign in ANNEX3_ROWS:
            start = sign * balance(group, [('date', '<', self.date_from)])
            items = AccountMoveLine.search(self._cit_items_domain(self.date_from, self.date_to) + [
                ('account_id.gec_cit_balance_group', '=', group)])
            increase = items.filtered(lambda i: sign * i.balance > 0)
            decrease = items - increase
            revaluation = lambda lines: abs(sum(lines.filtered(
                lambda i: exchange_journal and i.journal_id == exchange_journal).mapped('balance')))
            up, down = abs(sum(increase.mapped('balance'))), abs(sum(decrease.mapped('balance')))
            vals_list.append({
                'declaration_id': self.id, 'annex': '3', 'sequence': sequence, 'name': label,
                'amount1': start, 'amount2': up, 'amount4': down, 'amount6': start + up - down,
                # rs.ge asks the revaluation part only for loans.
                'amount3': revaluation(increase) if group in loans else 0.0,
                'amount5': revaluation(decrease) if group in loans else 0.0,
            })
        existing = {line.sequence: line for line in self.annex3_line_ids}
        for vals in vals_list:
            line = existing.get(vals['sequence'])
            if not line:
                self.env['rs.cit.annex.line'].create(vals)
            elif not line.manual:
                line.with_context(gec_cit_auto=True).write(vals)

    def _annex_amounts(self, lines):
        """Amounts of the rows taken from the annexes and of line 16.1 split between the columns:
        {code: (column 2, column 3)}."""
        self.ensure_one()
        status = self._cit_status()
        dividends = self.dividend_total
        annex16 = self.annex16_line_ids
        line_1613 = sum(annex16.mapped('result2'))
        line_1614 = lines['16.1.4'].amount3
        if status == 'innovative_sme':
            line_161 = (0.0, self.a17_6)
        elif status in COL3_ONLY:
            line_161 = (0.0, dividends)
        elif status == 'international':
            line_161 = (dividends - sum(annex16.mapped('amount2')), line_1613)
        elif status == 'investment':
            line_161 = (dividends - line_1614, line_1614)
        else:
            line_161 = (dividends, 0.0)
        audit = sum(self.annex15_line_ids.mapped('amount1'))
        return {
            '16.1': line_161,
            '16.1.3': (0.0, line_1613),
            '25.1': (min(self.a1_5, tax_of(lines['16.1.1'].amount, CIT_RATE)), 0.0),
            '25.3': (min(self.a13_5, tax_of(lines['16.1.2'].amount, CIT_RATE)), 0.0),
            '27.4': (0.0, audit) if status in COL3_ONLY else (audit, 0.0),
        }

    def _compute_formulas(self):
        """Fill line 16.1, the annex rows and the formula rows of both columns, in FORMULAS order."""
        self._sync_followed()
        for declaration in self:
            lines = {line.code: line for line in declaration.line_ids}
            if not lines:
                continue
            round_ = declaration.currency_id.round
            for code, (col2, col3) in declaration._annex_amounts(lines).items():
                vals = {'amount_auto': round_(col2), 'amount3_auto': round_(col3)}
                if (lines[code].amount_auto, lines[code].amount3_auto) != (vals['amount_auto'], vals['amount3_auto']):
                    lines[code].write(vals)
            for field, total, rate in (('amount_auto', 'amount', CIT_RATE),
                                       ('amount3_auto', 'amount3', declaration.col3_rate)):
                amounts = {code: line[total] for code, line in lines.items()}
                for code, formula in FORMULAS:
                    value = round_(formula(amounts, rate))
                    amounts[code] = value
                    if lines[code][field] != value:
                        lines[code][field] = value

    # ------------------------------------------------------------------
    # Confirm, back to draft, corrections
    # ------------------------------------------------------------------

    def action_confirm(self):
        self.action_compute()
        for declaration in self:
            declaration.write({'state': 'confirmed'})
            declaration._post_tax_entry()

    def action_draft(self):
        for declaration in self.filtered(lambda d: d.state == 'confirmed'):
            if not declaration._is_latest_confirmed():
                raise UserError(_("A later corrected version of %s is confirmed: set that one back to draft instead.",
                                  declaration.date_from.strftime('%m/%Y')))
            used = declaration.taxed_item_ids.recovery_ids.filtered(
                lambda r: r.declaration_id != declaration and r.declaration_id.state == 'confirmed')
            if used:
                raise UserError(_(
                    "Confirmed declarations %(names)s already count money back on amounts this declaration taxed. "
                    "Set them back to draft first.", names=', '.join(used.declaration_id.mapped('name'))))
            if declaration.move_id:
                declaration.move_id._reverse_moves(cancel=True)
            declaration.write({'state': 'draft', 'move_id': False, 'booked_amount': 0.0})
            declaration.sudo().rs_entry_ids.entered = False

    def action_create_correction(self):
        """Start a corrected declaration of the same month, keeping typed amounts and annex lines."""
        self.ensure_one()
        latest = self.search([('company_id', '=', self.company_id.id), ('date_from', '=', self.date_from)],
                             order='version desc', limit=1)
        if latest.state != 'confirmed':
            raise UserError(_("%s is still a draft: finish or delete it first.", latest.name))
        correction = self.copy({'version': latest.version + 1, 'company_status': self.company_status,
                                'special_status': self.special_status,
                                'col3_rate': self.col3_rate})
        typed = {line.code: line for line in self.line_ids}
        for line in correction.line_ids:
            source = typed.get(line.code)
            if source and (source.amount_adjust or source.amount3_adjust):
                line.write({'amount_adjust': source.amount_adjust, 'amount3_adjust': source.amount3_adjust})
        correction.action_compute()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': correction.id,
            'view_mode': 'form',
        }

    def _post_tax_entry(self):
        """Post the profit tax this declaration adds, less what earlier versions of the month booked."""
        self.ensure_one()
        company = self.company_id
        if not company.gec_cit_post_entry:
            return
        if not (company.gec_cit_journal_id and company.gec_cit_expense_account_id
                and company.gec_cit_payable_account_id):
            raise UserError(_("Set the profit tax journal and accounts in Accounting > Settings, or turn off "
                              "Post Profit Tax Entry."))
        others = self.search([('company_id', '=', company.id), ('date_from', '=', self.date_from),
                              ('state', '=', 'confirmed'), ('id', '!=', self.id)])
        amount = self.currency_id.round(self.booking_amount - sum(others.mapped('booked_amount')))
        if self.currency_id.is_zero(amount):
            return
        debit, credit = (amount, 0.0) if amount > 0 else (0.0, -amount)
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': company.gec_cit_journal_id.id,
            'date': self.date_to,
            'company_id': company.id,
            'ref': self.name,
            'line_ids': [
                Command.create({'name': self.name, 'account_id': company.gec_cit_expense_account_id.id,
                                'debit': debit, 'credit': credit}),
                Command.create({'name': self.name, 'account_id': company.gec_cit_payable_account_id.id,
                                'debit': credit, 'credit': debit}),
            ],
        })
        move.action_post()
        self.write({'move_id': move.id, 'booked_amount': amount})

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _compute_checks(self):
        preferential_set = bool(self.env['res.country'].search_count([('gec_cit_preferential', '=', True)], limit=1))
        for declaration in self:
            notes = []
            lines = {line.code: line for line in declaration.line_ids}
            if not preferential_set:
                notes.append(_("No country is marked Preferential Taxation, so lines 18.1 cannot see such persons. "
                               "Tick the countries of the Government list in Contacts > Configuration > Localization > Countries."))
            if declaration.dividend_unmatched:
                notes.append(_("%s dividend payment(s) are not matched with their declaration entry: withholding tax "
                               "kept from them is missing from line 16.1. Match them, or adjust line 16.1.",
                               declaration.dividend_unmatched))
            if declaration.unclassified_count:
                notes.append(_("%s journal item(s) on line 18 accounts have no contact, so they count nowhere.",
                               declaration.unclassified_count))
            if lines and lines['25.2'].amount > max(0.0, tax_of(lines['16.1'].amount, CIT_RATE) - lines['25.1'].amount):
                notes.append(_("Line 25.2 is above the tax on line 16.1 less line 25.1, its upper limit."))
            if declaration.representation_founding_year and lines and lines['20'].amount + lines['20'].amount3:
                notes.append(_("Founding year: the representation limit is 1% of the year's expenses, known only in "
                               "December. Line 20 may stay empty until then (instruction example 6)."))
            if declaration.special_status == 'research':
                notes.append(_("Column 3 rate of research and development companies is set to 10%: check it."))
            if declaration.date_from and declaration.date_from.month == 3:
                if not (declaration.a2_inventory or declaration.a2_fixed):
                    notes.append(_("March: annex 2 is empty. Check the Profit Tax Balance Group of the inventory "
                                   "and fixed asset accounts."))
                if not declaration.annex4_line_ids:
                    notes.append(_("March: fill annex 4 if last year's international controlled transactions "
                                   "exceeded 500,000 GEL."))
            declaration.checks = '\n'.join(f"• {note}" for note in notes) or False


class RsCitDeclarationLine(models.Model):
    """The amounts of one form row in one declaration: column 2 (15%) and column 3 (5%, 10% or status)."""
    _name = 'rs.cit.declaration.line'
    _description = 'rs.ge Profit Tax Declaration Line'
    _order = 'sequence, id'

    declaration_id = fields.Many2one('rs.cit.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    cell_id = fields.Many2one('rs.cit.cell', required=True, ondelete='restrict')
    sequence = fields.Integer(related='cell_id.sequence', store=True)
    code = fields.Char(related='cell_id.code')
    name = fields.Char(related='cell_id.name')
    kind = fields.Selection(related='cell_id.kind')
    columns = fields.Selection(related='cell_id.columns')
    move_line_count = fields.Integer(compute='_compute_move_line_count')
    level = fields.Integer(compute='_compute_level', help="0 for 16, 1 for 16.1, 2 for 16.1.1: used to indent.")
    amount_auto = fields.Monetary(string='Calculated', readonly=True, currency_field='currency_id',
                                  help="Column 2: what Odoo calculated from accounting or from other rows.")
    amount_adjust = fields.Monetary(string='Adjustment', currency_field='currency_id',
                                    help="Column 2, typed by the accountant: the whole amount on typed-in rows, "
                                         "a correction of the calculated amount on the others.")
    amount = fields.Monetary(string='Column 2', compute='_compute_amount', store=True, currency_field='currency_id')
    amount3_auto = fields.Monetary(string='Calculated (Col. 3)', readonly=True, currency_field='currency_id')
    amount3_adjust = fields.Monetary(string='Adjustment (Col. 3)', currency_field='currency_id')
    amount3 = fields.Monetary(string='Column 3', compute='_compute_amount', store=True, currency_field='currency_id')
    move_line_ids = fields.Many2many('account.move.line', string='Journal Items', readonly=True, copy=False,
                                     help="The journal items the calculated amount was read from.")

    _declaration_cell_uniq = models.Constraint(
        'UNIQUE(declaration_id, cell_id)', 'Each form row appears once per declaration.')

    @api.depends('cell_id.code')
    def _compute_level(self):
        for line in self:
            line.level = (line.code or '').count('.')

    @api.depends('move_line_ids')
    def _compute_move_line_count(self):
        for line in self:
            line.move_line_count = len(line.move_line_ids)

    @api.depends('amount_auto', 'amount_adjust', 'amount3_auto', 'amount3_adjust')
    def _compute_amount(self):
        for line in self:
            line.amount = line.amount_auto + line.amount_adjust
            line.amount3 = line.amount3_auto + line.amount3_adjust

    def write(self, vals):
        adjusted = {'amount_adjust', 'amount3_adjust'} & set(vals)
        if adjusted and self.declaration_id.filtered(lambda d: d.state == 'confirmed'):
            raise UserError(_("A confirmed declaration cannot be changed. Set it back to draft first."))
        result = super().write(vals)
        if adjusted:
            self.declaration_id._compute_formulas()
        return result

    def action_open_move_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Row %s', self.code),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.move_line_ids.ids)],
            'context': {'create': False},
        }
