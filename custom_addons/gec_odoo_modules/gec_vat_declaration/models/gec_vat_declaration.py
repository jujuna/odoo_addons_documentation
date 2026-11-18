import io
import re
import zlib
from collections import Counter
from datetime import datetime
from math import floor

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL, float_compare, float_is_zero, float_round, format_date
from odoo.tools.pdf import DependencyError, PdfReader, PdfReadError

from odoo.addons.rs_einvoice.models.account_move import RS_ACCEPTED
from odoo.addons.rs_einvoice.models.account_move_sync import RS_STANDARD_TAX_CATEGORY

ODOO_SOURCE = {
    '355_1': ('ge_1', 'base'),
    '355_2': ('ge_3', 'base'),
    '355_3': ('ge_4', 'base'),
    '355_4': ('ge_5', 'base'),
    '355_5': ('ge_6', 'base'),
    '355_6': ('ge_7', 'base'),
    '355_6_1': ('ge_8', 'base'),
    '355_7': ('ge_9', 'base'),
    '355_7_1': ('ge_10', 'base'),
    '355_8': ('ge_11', 'base'),
    '355_1_5': ('ge_1', 'tax'),
    '355_2_5': ('ge_3', 'tax'),
    '355_3_5': ('ge_4', 'tax'),
    '355_4_5': ('ge_5', 'tax'),
    '355_5_5': ('ge_6', 'tax'),
    '355_6_5': ('ge_7', 'tax'),
    '355_6_1_5': ('ge_8', 'tax'),
    '355_7_5': ('ge_9', 'tax'),
    '355_7_1_5': ('ge_10', 'tax'),
    '355_8_5': ('ge_11', 'tax'),
    '355_1_1_5': ('ge_2', 'tax'),
    '355_9': ('ge_12', 'base'),
    '355_10': ('ge_13', 'base'),
    '355_11': ('ge_14', 'base'),
    '355_12': ('ge_15', 'base'),
    '355_13': ('ge_16', 'base'),
    '355_14': ('ge_17', 'base'),
    '355_14_1': ('ge_18', 'base'),
    '355_14_2': ('ge_19', 'base'),
    '355_14_3': ('ge_20', 'base'),
    '356_1': ('ge_21', 'base'),
    '356_2': ('ge_22', 'base'),
    '356_3': ('ge_23', 'base'),
    '356_15': ('ge_21', 'tax'),
    '356_25': ('ge_22', 'tax'),
    '356_35': ('ge_23', 'tax'),
    '353_13': ('ge_24', 'tax'),
    '353_23': ('ge_25', 'tax'),
    '353_33': ('ge_26', 'tax'),
    '353_43': ('ge_27', 'tax'),
    '353_43_1': ('ge_28', 'tax'),
    '353_53': ('ge_29', 'tax'),
    '353_73': ('ge_32', 'tax'),
    '353_83': ('ge_33', 'tax'),
    '353_63': ('ge_30', 'tax'),
    '353_613': ('ge_31', 'tax'),
}
NET_VAT_SOURCE = ('ge_35', 'tax')
VAT_RATE = 18.0  # the portal's fixed formula rate, on both forms; not read from a tax
GEORGIA = 'GE'
REPLACEMENT_REVERSAL = Domain([('rs_einv_skip_reason', '=', 'replacement'), ('state', '=', 'posted')])

COLUMN4_SOURCE = {
    '353_14': ('353_13', '353_15'),
    '353_24': ('353_23', '353_25'),
    '353_34': ('353_33', '353_35'),
    '353_44': ('353_43', '353_45'),
    '353_44_1': ('353_43_1', '353_45_1'),
    '353_54': ('353_53', '353_55'),
    '353_74': ('353_73', '353_75'),
    '353_84': ('353_83', '353_85'),
}
# Rows 4 and 4¹ are left out: a reverse-charge credit note lowers A II and A III row 4 by the same amount, both read as 0 and cancel.
DEDUCTION_DECREASE_SOURCE = ('353_14', '353_24', '353_34', '353_54', '353_74', '353_84')
DEDUCTION_DECREASE_CELL = '358_12'
FIXED_ASSET_SOURCE = {'353_15': 'ge_24', '353_35': 'ge_26', '353_45': 'ge_27', '353_55': 'ge_29', '353_75': 'ge_32', '353_85': 'ge_33'}

A1_ROWS = ('1', '2', '3', '4', '5', '6', '6_1', '7', '7_1', '8')
A2_ROWS = ('1', '2', '3')
A3_ROWS = (
    ('353_13', '353_14', '353_15'),
    ('353_23', '353_24', '353_25'),
    ('353_33', '353_34', '353_35'),
    ('353_43', '353_44', '353_45'),
    ('353_43_1', '353_44_1', '353_45_1'),
    ('353_53', '353_54', '353_55'),
    ('353_63', '353_64', '353_65'),
    ('353_613', '353_614', '353_615'),
    ('353_73', '353_74', '353_75'),
    ('353_83', '353_84', '353_85'),
)
MARGIN_ROWS = ('1', '2', '3', '4')
MARGIN_SCHEME_ROW = {'second_hand': '1', 'art': '2', 'collectible': '3', 'antique': '4'}
MARGIN_CODES = frozenset(code for row in MARGIN_ROWS for code in ('359_%s' % row, '359_%s_4' % row))
AUDIT_CODES = frozenset(ODOO_SOURCE) | frozenset(FIXED_ASSET_SOURCE) | frozenset(COLUMN4_SOURCE) | MARGIN_CODES

PDF_ERRORS = (ValueError, PdfReadError, TypeError, zlib.error, NotImplementedError, DependencyError, ArithmeticError, LookupError)
PDF_SHOW_OPERATORS = (b'Tj', b'TJ', b"'", b'"')
CUSTOMS_ORGAN_LABEL = 'საგადასახადო ორგანო'
CUSTOMS_NUMBER_LABEL = 'შეფასების'
CUSTOMS_TOTAL_LABEL = 'გადახდილია სულ'
CUSTOMS_CODE_RE = re.compile(r'\d+')
CUSTOMS_NUMBER_RE = re.compile(r'[A-Z]?\d+')
CUSTOMS_DATE_RE = re.compile(r'\d{2}/\d{2}/\d{4}')
CUSTOMS_AMOUNT_RE = re.compile(r'\d{1,3}(?:[\s,]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?')
CUSTOMS_SAME_LINE = 3
CUSTOMS_CODE_BOX = (15, 25)
FORM4_NUMBER_LABEL = 'დეკლარაციის რეგისტრაციის'
FORM4_DATE_LABEL = 'რეგისტრაციის თარიღი'
FORM4_NUMBER_RE = re.compile(r'\d+/\d+')
FORM4_DATE_RE = re.compile(r'\d{2}\.\d{2}\.\d{4}(?:\s.*)?')
FORM4_VAT_RE = re.compile(r'დღგ\s*[-‐–—]\s*სახაზ\.\s*კოდი\s+(\d+)\s+(%s)' % CUSTOMS_AMOUNT_RE.pattern)
FORM4_NUMBER_BOX = (60, 30)
FORM4_DATE_BOX = (110, 30)


def round_2(value):
    """Round to 2 decimals, half up, as the portal's round_2."""
    return float_round(value, precision_digits=2)


def portal_vat(base):
    """VAT of a base at the portal's rate, rounded as the portal rounds it."""
    return round_2(base * VAT_RATE / 100)


def name_list(env, names, limit=20):
    """Names for a warning line, cut after ``limit`` to keep the banner short."""
    if len(names) <= limit:
        return ', '.join(names)
    return env._("%(names)s and %(count)s more", names=', '.join(names[:limit]), count=len(names) - limit)


def check_earlier_months_filed(declaration):
    """Filing locks every earlier month: refused while one has a declaration and no filed one, as core's tax return refuses
    (account_return.py:1535-1545). An adjusted draft of a filed month does not count."""
    earlier = declaration.search([('company_id', '=', declaration.company_id.id), ('date_from', '<', declaration.date_from)], order='date_from, id')
    filed_months = earlier.filtered(lambda decl: decl.state == 'filed').mapped('date_from')
    unfiled = earlier.filtered(lambda decl: decl.date_from not in filed_months)
    if unfiled:
        raise UserError(declaration.env._("%(name)s: %(names)s of earlier months are not filed yet, and marking as filed locks every earlier "
            "month; file or delete them first.", name=declaration.name, names=name_list(declaration.env, unfiled.mapped('name'))))


def list_action(records, name):
    return {
        'type': 'ir.actions.act_window',
        'name': name,
        'res_model': records._name,
        'views': [(False, 'list'), (False, 'form')],
        'domain': [('id', 'in', records.ids)],
        'context': {'active_test': False},
    }


def compute_cells(values, b9_amount):
    """Apply portal formulas in dependency order to {code: value}; locked cells start at 0.0. A III rows 6/6¹ columns
    4/5 have no formula (0, typed in December); column 3 stays 4+5. Part III cell 10 is the ბ IX total, cells 17/18 are
    whole lari; negative margin-row VAT counts as 0."""
    v = dict(values)
    for row in MARGIN_ROWS:
        v['359_%s_5' % row] = max(round_2((v['359_%s_4' % row] - v['359_%s' % row]) * VAT_RATE / (100 + VAT_RATE)), 0.0)
    v['359_5'] = round_2(sum(v['359_%s_5' % row] for row in MARGIN_ROWS))
    v['355_1_1_5'] = v['359_5']
    for row in A1_ROWS:
        v['355_%s_5' % row] = portal_vat(v['355_%s' % row])
    v['355_15'] = round_2(sum(v['355_%s_5' % row] for row in A1_ROWS) + v['355_1_1_5'])
    for row in A2_ROWS:
        v['356_%s5' % row] = portal_vat(v['356_%s' % row])
    v['356_4'] = round_2(sum(v['356_%s5' % row] for row in A2_ROWS))
    for total, goods, fixed in A3_ROWS:
        v[total] = round_2(v[goods] + v[fixed])
    v['353_93'] = round_2(sum(v[total] for total, _goods, _fixed in A3_ROWS))
    v['353_94'] = round_2(sum(v[goods] for _total, goods, _fixed in A3_ROWS))
    v['353_95'] = round_2(sum(v[fixed] for _total, _goods, fixed in A3_ROWS))
    v['358_1'] = v['355_15']
    v['358_2'] = round_2(sum(v['355_%s' % row] for row in A1_ROWS))
    v['358_3'] = round_2(sum(v['355_%s' % row] for row in ('9', '10', '11', '12', '13', '14')))
    v['358_5'] = round_2(v['355_14_1'] + v['355_14_2'] + v['355_14_3'])
    v['358_8'] = v['356_4']
    v['358_10'] = b9_amount
    v['358_11'] = v['353_93']
    v['358_15'] = round_2(v['358_1'] + v['358_6'] + v['358_8'] + v['358_9'] + v['358_12'] + v['358_14'])
    v['358_16'] = round_2(v['358_7'] + v['358_10'] + v['358_11'] + v['358_13'])
    difference = round_2(v['358_15'] - v['358_16'])
    v['358_17'] = float(floor(difference)) if difference > 0 else 0.0
    v['358_18'] = float(floor(-difference)) if difference < 0 else 0.0
    return v


class GecVatDeclaration(models.Model):
    """Monthly rs.ge VAT declaration: the cell tabs, proposed from the l10n_ge VAT report."""
    _name = 'gec.vat.declaration'
    _description = 'rs.ge VAT Declaration'
    _order = 'date_from desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict', default=lambda self: self.env.company)
    date_from = fields.Date(string='Month', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1) - relativedelta(months=1))
    date_to = fields.Date(compute='_compute_date_to', store=True)
    decl_type = fields.Selection([('primary', 'Primary'), ('adjusted', 'Adjusted')], string='Type', compute='_compute_decl_type', store=True,
        readonly=False, precompute=True, required=True, copy=False)
    portal_number = fields.Char(string='Portal Number', copy=False, help="The declaration number the rs.ge portal gave.")
    state = fields.Selection([('draft', 'Draft'), ('filed', 'Filed')], required=True, default='draft', copy=False)
    line_ids = fields.One2many('gec.vat.declaration.line', 'declaration_id', copy=True)
    tab1_line_ids = fields.One2many('gec.vat.declaration.line', 'declaration_id', domain=[('tab', '=', '1')], copy=False)
    tab2_line_ids = fields.One2many('gec.vat.declaration.line', 'declaration_id', domain=[('tab', '=', '2')], copy=False)
    tab3_line_ids = fields.One2many('gec.vat.declaration.line', 'declaration_id', domain=[('tab', '=', '3')], copy=False)
    tab16_line_ids = fields.One2many('gec.vat.declaration.line', 'declaration_id', domain=[('tab', '=', '16')], copy=False)
    tab17_line_ids = fields.One2many('gec.vat.declaration.line', 'declaration_id', domain=[('tab', '=', '17')], copy=False)
    invoice_line_ids = fields.One2many('gec.vat.invoice.line', 'declaration_id', domain=[('part', '=', 'sale')], copy=True)
    advance_line_ids = fields.One2many('gec.vat.advance.line', 'declaration_id', domain=[('part', '=', 'sale')], copy=True)
    purchase_line_ids = fields.One2many('gec.vat.invoice.line', 'declaration_id', domain=[('part', '=', 'purchase')], copy=True)
    purchase_advance_line_ids = fields.One2many('gec.vat.advance.line', 'declaration_id', domain=[('part', '=', 'purchase')], copy=True)
    spec_line_ids = fields.One2many('gec.vat.invoice.line', 'declaration_id', string='Tab 13 Invoices', domain=[('part', '=', 'spec_sale')],
        copy=True)
    spec_advance_line_ids = fields.One2many('gec.vat.advance.line', 'declaration_id', string='Tab 13 Advances', domain=[('part', '=', 'spec_sale')],
        copy=True)
    spec_purchase_line_ids = fields.One2many('gec.vat.invoice.line', 'declaration_id', string='Tab 14 Invoices',
        domain=[('part', '=', 'spec_purchase')], copy=True)
    spec_purchase_advance_line_ids = fields.One2many('gec.vat.advance.line', 'declaration_id', string='Tab 14 Advances',
        domain=[('part', '=', 'spec_purchase')], copy=True)
    stock_line_ids = fields.One2many('gec.vat.stock.line', 'declaration_id', string='Tab 15 Stock Balances', copy=True)
    customs_line_ids = fields.One2many('gec.vat.customs.line', 'declaration_id', copy=True)
    b4_line_ids = fields.One2many('gec.vat.ref.line', 'declaration_id', domain=[('grid', '=', 'b4')], copy=True)
    b5_line_ids = fields.One2many('gec.vat.ref.line', 'declaration_id', domain=[('grid', '=', 'b5')], copy=True)
    b8_line_ids = fields.One2many('gec.vat.ref.line', 'declaration_id', domain=[('grid', '=', 'b8')], context={'default_grid': 'b8'}, copy=True)
    b9_line_ids = fields.One2many('gec.vat.ref.line', 'declaration_id', domain=[('grid', '=', 'b9')], context={'default_grid': 'b9'}, copy=True)
    b1_amount = fields.Float(string='B I VAT Payable', compute='_compute_annex_b_totals')
    b1_reduce_amount = fields.Float(string='B I VAT Reduced', compute='_compute_annex_b_totals')
    b1_advance_amount = fields.Float(string='B I Advance VAT', compute='_compute_annex_b_totals')
    b2_amount = fields.Float(string='B II VAT Creditable', compute='_compute_annex_b_totals')
    b2_reduce_amount = fields.Float(string='B II VAT Reduced', compute='_compute_annex_b_totals')
    b2_advance_amount = fields.Float(string='B II Advance VAT', compute='_compute_annex_b_totals')
    b13_amount = fields.Float(string='Tab 13 VAT Payable', compute='_compute_annex_b_totals')
    b13_reduce_amount = fields.Float(string='Tab 13 VAT Reduced', compute='_compute_annex_b_totals')
    b13_advance_amount = fields.Float(string='Tab 13 Advance VAT', compute='_compute_annex_b_totals')
    b14_amount = fields.Float(string='Tab 14 VAT Creditable', compute='_compute_annex_b_totals')
    b14_reduce_amount = fields.Float(string='Tab 14 VAT Reduced', compute='_compute_annex_b_totals')
    b14_advance_amount = fields.Float(string='Tab 14 Advance VAT', compute='_compute_annex_b_totals')
    b3_amount = fields.Float(string='B III VAT', compute='_compute_annex_b_totals')
    b4_amount = fields.Float(string='B IV VAT', compute='_compute_annex_b_totals')
    b5_amount = fields.Float(string='B V VAT', compute='_compute_annex_b_totals')
    b8_amount = fields.Float(string='B VIII VAT', compute='_compute_annex_b_totals')
    b9_amount = fields.Float(string='B IX VAT', compute='_compute_annex_b_totals')
    generation_warnings = fields.Text(compute='_compute_generation_warnings')
    scan_warnings = fields.Text(readonly=True, copy=False)
    odoo_net_vat = fields.Float(string='Odoo Net VAT', readonly=True,
        help="Net VAT of the l10n_ge VAT report at the last Generate, to compare with Part III.")
    vat_payable = fields.Float(string='VAT Payable', compute='_compute_vat_result')
    vat_refund = fields.Float(string='VAT Refund', compute='_compute_vat_result')

    @api.depends('company_id.name', 'date_from')
    def _compute_name(self):
        for declaration in self:
            month = declaration.date_from.strftime('%Y/%m') if declaration.date_from else ''
            declaration.name = f"დღგ {month} {declaration.company_id.name or ''}".strip()

    @api.depends('company_id', 'date_from')
    def _compute_decl_type(self):
        """A declaration of a month that already has a filed one is an adjusted one."""
        for declaration in self:
            filed = self.search_count([
                ('company_id', '=', declaration.company_id.id),
                ('date_from', '=', declaration.date_from),
                ('state', '=', 'filed'),
            ], limit=1)
            declaration.decl_type = 'adjusted' if filed else 'primary'

    @api.depends('date_from')
    def _compute_date_to(self):
        for declaration in self:
            start = declaration.date_from
            declaration.date_to = start + relativedelta(months=1, days=-1) if start else False

    @api.depends('line_ids.value')
    def _compute_vat_result(self):
        """Part III cells 17 (to pay) and 18 (to reduce), for the list and form header."""
        for declaration in self:
            values = {line.code: line.value for line in declaration.line_ids if line.code in ('358_17', '358_18')}
            declaration.vat_payable = values.get('358_17', 0.0)
            declaration.vat_refund = values.get('358_18', 0.0)

    @api.depends('company_id', 'date_from', 'scan_warnings', 'line_ids.value', 'line_ids.odoo_value', 'invoice_line_ids.move_id',
        'invoice_line_ids.amount', 'invoice_line_ids.reduce_amount', 'spec_line_ids.move_id', 'spec_line_ids.amount', 'spec_line_ids.reduce_amount',
        'purchase_line_ids.move_id', 'purchase_line_ids.amount', 'purchase_line_ids.reduce_amount', 'spec_purchase_line_ids.move_id',
        'spec_purchase_line_ids.amount', 'spec_purchase_line_ids.reduce_amount', 'customs_line_ids.attachment_id',
        'customs_line_ids.assessment_number', 'customs_line_ids.assessment_date', 'customs_line_ids.amount', 'b4_line_ids.amount',
        'b5_line_ids.amount', 'b8_line_ids.amount')
    def _compute_generation_warnings(self):
        """The cell checks, live, then what the last Generate found in the invoices and assets (scan_warnings)."""
        for declaration in self:
            warnings = declaration._gec_warnings() if declaration.line_ids and declaration.date_from else []
            warnings += (declaration.scan_warnings or '').splitlines()
            declaration.generation_warnings = '\n'.join(warnings) or False

    @api.depends('invoice_line_ids.amount', 'invoice_line_ids.reduce_amount', 'advance_line_ids.amount', 'purchase_line_ids.amount',
        'purchase_line_ids.reduce_amount', 'purchase_advance_line_ids.amount', 'spec_line_ids.amount', 'spec_line_ids.reduce_amount',
        'spec_advance_line_ids.amount', 'spec_purchase_line_ids.amount', 'spec_purchase_line_ids.reduce_amount',
        'spec_purchase_advance_line_ids.amount', 'customs_line_ids.amount', 'b4_line_ids.amount', 'b5_line_ids.amount',
        'b8_line_ids.amount', 'b9_line_ids.amount')
    def _compute_annex_b_totals(self):
        """Column totals of annexes ბ I to ბ V, ბ VIII, ბ IX and tabs 13 / 14, and the advance offsets of ბ I and ბ II."""
        for declaration in self:
            declaration.b1_amount = round_2(sum(declaration.invoice_line_ids.mapped('amount')))
            declaration.b1_reduce_amount = round_2(sum(declaration.invoice_line_ids.mapped('reduce_amount')))
            declaration.b1_advance_amount = round_2(sum(declaration.advance_line_ids.mapped('amount')))
            declaration.b2_amount = round_2(sum(declaration.purchase_line_ids.mapped('amount')))
            declaration.b2_reduce_amount = round_2(sum(declaration.purchase_line_ids.mapped('reduce_amount')))
            declaration.b2_advance_amount = round_2(sum(declaration.purchase_advance_line_ids.mapped('amount')))
            declaration.b13_amount = round_2(sum(declaration.spec_line_ids.mapped('amount')))
            declaration.b13_reduce_amount = round_2(sum(declaration.spec_line_ids.mapped('reduce_amount')))
            declaration.b13_advance_amount = round_2(sum(declaration.spec_advance_line_ids.mapped('amount')))
            declaration.b14_amount = round_2(sum(declaration.spec_purchase_line_ids.mapped('amount')))
            declaration.b14_reduce_amount = round_2(sum(declaration.spec_purchase_line_ids.mapped('reduce_amount')))
            declaration.b14_advance_amount = round_2(sum(declaration.spec_purchase_advance_line_ids.mapped('amount')))
            declaration.b3_amount = round_2(sum(declaration.customs_line_ids.mapped('amount')))
            declaration.b4_amount = round_2(sum(declaration.b4_line_ids.mapped('amount')))
            declaration.b5_amount = round_2(sum(declaration.b5_line_ids.mapped('amount')))
            declaration.b8_amount = round_2(sum(declaration.b8_line_ids.mapped('amount')))
            declaration.b9_amount = round_2(sum(declaration.b9_line_ids.mapped('amount')))

    @api.constrains('date_from')
    def _check_date_from(self):
        for declaration in self:
            if declaration.date_from and declaration.date_from.day != 1:
                raise ValidationError(self.env._("The declaration month must start on the first day of the month."))

    @api.model_create_multi
    def create(self, vals_list):
        """Create the declaration with one value line per catalog cell."""
        filed = [vals.get('state') == 'filed' for vals in vals_list]
        declarations = super().create([{**vals, 'state': 'draft'} if is_filed else vals for vals, is_filed in zip(vals_list, filed)])
        for declaration in declarations:
            declaration._gec_sync_cell_lines()
        declarations.browse([declaration.id for declaration, is_filed in zip(declarations, filed) if is_filed]).write({'state': 'filed'})
        return declarations

    def write(self, vals):
        """Refuse a company or month change once values exist; after a tab save, refresh the cells."""
        to_file = self.filtered(lambda declaration: declaration.state != 'filed') if vals.get('state') == 'filed' else self.browse()
        if vals.keys() - {'state', 'portal_number'}:
            self._check_draft()
        if 'company_id' in vals or 'date_from' in vals:
            for declaration in self:
                company_changed = 'company_id' in vals and declaration.company_id.id != vals['company_id']
                month_changed = 'date_from' in vals and declaration.date_from != fields.Date.to_date(vals['date_from'])
                if (company_changed or month_changed) and any(declaration.line_ids.mapped('value')):
                    raise UserError(self.env._("You cannot change the company or the month of a declaration that has values. Create a new "
                        "declaration."))
        result = super().write(vals)
        if {'line_ids', 'tab1_line_ids', 'tab2_line_ids', 'tab3_line_ids', 'tab16_line_ids', 'tab17_line_ids', 'b9_line_ids'} & vals.keys():
            for declaration in self.filtered(lambda decl: decl.state == 'draft'):
                declaration._gec_sync_cell_lines()
        to_file._gec_file()
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_filed(self):
        if any(declaration.state == 'filed' for declaration in self):
            raise UserError(self.env._("A filed declaration cannot be deleted: reset it to draft first."))

    def _check_draft(self):
        if any(declaration.state == 'filed' for declaration in self):
            raise UserError(self.env._("This declaration is filed: reset it to draft before changing it."))

    def action_generate(self):
        """Read the month from the l10n_ge VAT report, propose the editable cells, recompute the locked ones. Typed
        cells and changed proposals are kept; warnings never block the declaration. The first sync adds the cells the catalog
        gained since the declaration was created, so every cell gets its Odoo value."""
        self.check_access('write')
        for declaration in self:
            if declaration.state != 'draft':
                raise UserError(self.env._("Reset the declaration to draft before regenerating it."))
            declaration._gec_sync_cell_lines()
            totals = declaration._gec_report_totals()
            margin_values, margin_warnings, _sources = declaration._gec_margin_scan()
            extra = margin_values | declaration._gec_fixed_asset_vat(totals)
            for line in declaration.line_ids:
                source = ODOO_SOURCE.get(line.code)
                value = (totals.get(source) or 0.0) if source else extra.get(line.code, 0.0)
                if float_compare(line.odoo_value, value, precision_rounding=0.01) != 0:
                    line.odoo_value = value
            declaration.odoo_net_vat = totals.get(NET_VAT_SOURCE) or 0.0
            warnings = declaration._gec_build_annex_b1() + declaration._gec_build_annex_b2() + margin_warnings
            declaration.scan_warnings = '\n'.join(warnings) or False
            declaration._gec_sync_cell_lines()
        return True

    def action_mark_filed(self):
        """Lock the month's books as core's tax return does: later postings into a filed month change its figures."""
        self.check_access('write')
        self.write({'state': 'filed'})
        return True

    def _gec_file(self):
        for declaration in self:
            if declaration.date_to >= fields.Date.context_today(self):
                raise UserError(self.env._("%s can be marked as filed only after its month has ended.", declaration.name))
            check_earlier_months_filed(declaration)
        for declaration in self:
            declaration.company_id._gec_vat_companies()._gec_lock_tax_month(declaration.date_to)

    def action_draft(self):
        self.write({'state': 'draft'})
        return True

    def _gec_report_options(self):
        """The l10n_ge VAT report and its options for the month, as core's tax return: posted entries of the company
        and its same-VAT branches. Sudo (branches may be unreadable) on one object for options and report; caller
        checked read access."""
        self.ensure_one()
        companies = self.env['res.company'].sudo().search([('id', 'child_of', self.company_id.id)])
        report = self.env.ref('l10n_ge.tax_report_ge').sudo().with_context(allowed_company_ids=companies.ids).with_company(self.company_id)
        options = report.get_options(previous_options={
            'tax_unit': 'company_only',
            'date': {'date_from': fields.Date.to_string(self.date_from), 'date_to': fields.Date.to_string(self.date_to), 'period_type': 'month'},
        })
        return report, options

    def _gec_report_totals(self):
        """Totals of every l10n_ge VAT report expression for the month, {(line code, label): value}."""
        report, options = self._gec_report_options()
        totals = report._compute_expression_totals_for_each_column_group(report.line_ids.expression_ids, options)[0]
        return {(expr.report_line_id.code, expr.label): result['value'] for expr, result in totals.items()}

    def _gec_fixed_asset_tax_lines(self):
        """{column 5 code: (VAT, tax line ids)} of the month's bill lines on the fixed-asset accounts, or booked to the
        fixed-assets input VAT account. Archived accounts count, so an old month regenerates the same."""
        company = self.company_id
        companies = (company._gec_vat_companies() | company.root_id).with_context(active_test=False)
        accounts = companies.gec_vat_fixed_asset_account_ids
        tax_account = self.env['account.chart.template'].with_company(company).ref(
            'gec_account_334011', raise_if_not_found=False) or self.env['account.account']
        if not accounts and not tax_account:
            return {}
        report, options = self._gec_report_options()
        query = report._get_report_query(options, 'strict_range')
        tax_details = self.env['account.move.line']._get_query_tax_details(query)
        code_by_tag = {tag.id: code for code, line_code in FIXED_ASSET_SOURCE.items() for tag in self._gec_tax_tags((line_code, 'tax'))}
        rows = self.env.execute_query(SQL(
            """
            SELECT rel.account_account_tag_id, SUM(tdr.tax_amount), ARRAY_AGG(DISTINCT tdr.tax_line_id)
            FROM (%(tax_details)s) AS tdr
            JOIN account_move_line tax_aml ON tax_aml.id = tdr.tax_line_id
            JOIN account_account_tag_account_move_line_rel rel ON rel.account_move_line_id = tdr.tax_line_id
            WHERE tdr.tax_exigible
              AND (tdr.base_account_id = ANY(%(accounts)s) OR tax_aml.account_id = ANY(%(tax_accounts)s))
              AND rel.account_account_tag_id = ANY(%(tags)s)
            GROUP BY rel.account_account_tag_id
            """,
            tax_details=tax_details, accounts=accounts.ids, tax_accounts=tax_account.ids, tags=list(code_by_tag)))
        return {code_by_tag[tag_id]: (amount, line_ids) for tag_id, amount, line_ids in rows}

    def _gec_fixed_asset_vat(self, totals):
        """{column 5 code: VAT of the fixed-asset lines}, between 0 and the Odoo row total: a negative line (down
        payment, discount) sharing the tax line would give the asset all of it."""
        fixed = {}
        for code, (amount, _line_ids) in self._gec_fixed_asset_tax_lines().items():
            fixed[code] = round_2(max(min(amount, totals.get((FIXED_ASSET_SOURCE[code], 'tax')) or 0.0), 0.0))
        return fixed

    def _gec_proposal(self, line, lines_by_code):
        """What Odoo proposes for a proposed cell. A III column 4 is Odoo's total minus column 5 (fixed assets), so the
        row total stays Odoo's. Part III row 12 is the negative part of the A III column 4 cells, which the portal reads as 0."""
        if line.code == DEDUCTION_DECREASE_CELL:
            return round_2(sum(max(-lines_by_code[code].value, 0.0) for code in DEDUCTION_DECREASE_SOURCE))
        if line.code in COLUMN4_SOURCE:
            total, fixed = COLUMN4_SOURCE[line.code]
            return round_2(lines_by_code[total].odoo_value - max(lines_by_code[fixed].value, 0.0))
        return line.odoo_value

    def _gec_sync_cell_lines(self):
        """One line per catalog cell: proposals first (A III column 5, then column 4, then Part III row 12, each reading the one before),
        then portal formulas on the merged values. A proposed cell follows Odoo only while it equals the last proposal; typed cells are never
        touched. Writes only changes."""
        self.ensure_one()
        lines = self.line_ids
        missing = self.env['gec.vat.cell'].search([('id', 'not in', lines.cell_id.ids)])
        if missing:
            lines |= self.env['gec.vat.declaration.line'].create([{'declaration_id': self.id, 'cell_id': cell.id} for cell in missing])
        by_code = {line.code: line for line in lines}
        for line in lines.filtered('proposed').sorted(lambda line: (line.code == DEDUCTION_DECREASE_CELL, line.code in COLUMN4_SOURCE)):
            proposal = self._gec_proposal(line, by_code)
            vals = {}
            if float_compare(line.value, line.proposed_value, precision_rounding=0.01) == 0:
                vals['value'] = proposal
            if float_compare(line.proposed_value, proposal, precision_rounding=0.01) != 0:
                vals['proposed_value'] = proposal
            vals = {field: value for field, value in vals.items() if float_compare(line[field], value, precision_rounding=0.01) != 0}
            if vals:
                line.write(vals)
        values = {line.code: 0.0 if line.locked else max(line.value, 0.0) for line in lines}
        result = compute_cells(values, self.b9_amount)
        for line in lines.filtered('locked'):
            if float_compare(line.value, result[line.code], precision_rounding=0.01) != 0:
                line.value = result[line.code]

    def _gec_b1_month(self, move):
        """First day of the month a customer invoice counts in on annex ბ I; a correction counts in the month the buyer
        accepted it (rs_einvoice reverses the earlier-month original then, dated that month)."""
        reversal = move.rs_einv_replaces_id.reversal_move_ids.filtered_domain(REPLACEMENT_REVERSAL)[:1]
        if move.rs_einv_replacement_mode == 'correction' and reversal:
            return reversal.date.replace(day=1)
        return move.invoice_date.replace(day=1)

    def _gec_rs_vat(self, move):
        """VAT in company currency as rs.ge holds it: standard-rate (category S) tax lines only, positive on an invoice or a bill."""
        vat = sum(move.line_ids.filtered(lambda line: line.tax_line_id.ubl_cii_tax_category_code == RS_STANDARD_TAX_CATEGORY).mapped('balance'))
        return -vat if move.is_sale_document(include_receipts=True) else vat

    def _gec_period_domain(self, field='date'):
        """The declaration's month on ``field``, in its company and same-VAT branches."""
        return [('company_id', 'in', self.company_id._gec_vat_companies().ids), (field, '>=', self.date_from), (field, '<=', self.date_to)]

    def _gec_tax_tags(self, source):
        """Tax tags of a l10n_ge VAT report expression, source = (line code, label). Sudo: accountants may not read the report."""
        expressions = self.env.ref('l10n_ge.tax_report_ge').sudo().line_ids.expression_ids
        return expressions.filtered(lambda expr: (expr.report_line_id.code, expr.label) == source)._get_matching_tags()

    def _gec_b1_scan(self, spec=False):
        """Annex ბ I of the month: (row values, row invoices, warnings for invoices left out). Rows: rs.ge-accepted
        invoices (2, 3, 8) plus originals cancelled once corrected; a correction row is its change. Companies as the VAT
        report, sudo. Petroleum invoices (ნსაფ) are excluded. With spec=True, the petroleum invoices for tab 13."""
        self.ensure_one()
        tab = '13' if spec else self.env._("B I")
        Move = self.env['account.move'].sudo()
        companies = self.company_id._gec_vat_companies()
        in_month = self._gec_period_domain('invoice_date') + [('move_type', '=', 'out_invoice'), ('rs_einv_is_spec', '=', spec)]
        accepted = [
            ('rs_einv_number', '!=', False),
            ('rs_einv_status', 'in', RS_ACCEPTED),
            ('state', 'in', ('posted', 'cancel')),
            ('rs_einv_is_spec', '=', spec),
        ]
        reversals = Move.search(Domain(self._gec_period_domain() + [('move_type', '=', 'out_refund')]) & REPLACEMENT_REVERSAL)
        replaced = reversals.reversed_entry_id.rs_einv_replaced_by_id.filtered_domain(accepted)
        candidates = Move.search(in_month + accepted) | replaced
        moves = candidates.filtered(lambda move: self._gec_b1_month(move) == self.date_from).sorted(lambda move: (move.invoice_date, move.id))
        status_label = dict(Move._fields['rs_einv_status']._description_selection(self.env))
        rows, warnings = [], []
        for move in moves:
            original = move.rs_einv_replaces_id if move.rs_einv_replacement_mode == 'correction' else Move
            vat = self._gec_rs_vat(move) - self._gec_rs_vat(original)
            rows.append({
                'declaration_id': self.id,
                'move_id': move.id,
                'series': move.rs_einv_series,
                'number': move.rs_einv_number,
                'operation_month': move.invoice_date.replace(day=1),
                'partner_tin': move.rs_einv_buyer_tin,
                'amount': round_2(max(vat, 0.0)),
                'reduce_amount': round_2(max(-vat, 0.0)),
                'korect_series': original.rs_einv_series or False,
                'korect_number': original.rs_einv_number or False,
            })
            if move.state == 'cancel' and move.rs_einv_status == '2':
                warnings.append(self.env._("%(tab)s: %(name)s is cancelled in Odoo but still confirmed on rs.ge.", tab=tab, name=move.name))
        left_out = Move.search(in_month + [('state', '=', 'posted'), ('partner_id.vat', '!=', False), ('rs_einv_skip', '=', False)]) - moves
        candidate_ids = set(candidates.ids)
        not_sent, by_status = [], {}
        for move in left_out.sorted(lambda move: (move.invoice_date, move.id)):
            if move.id in candidate_ids:
                warnings.append(self.env._("%(tab)s: correction %(name)s counts in %(month)s, the month the buyer accepted it.", tab=tab,
                    name=move.name, month=self._gec_b1_month(move).strftime('%m/%Y')))
            elif not move.rs_einv_number:
                not_sent.append(move.name)
            else:
                by_status.setdefault(status_label.get(move.rs_einv_status, move.rs_einv_status), []).append(move.name)
        if not_sent:
            warnings.append(self.env._("%(tab)s: not on rs.ge: %(names)s.", tab=tab, names=name_list(self.env, not_sent)))
        for status, names in by_status.items():
            warnings.append(self.env._("%(tab)s: left out, rs.ge status %(status)s: %(names)s.", tab=tab, status=status,
                names=name_list(self.env, names)))
        late = Move.search(self._gec_period_domain() + accepted + [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '<', self.date_from),
        ], order='date, id') - moves
        late = late.filtered(self._gec_rs_vat)
        if late:
            warnings.append(self.env._("%(tab)s: %(names)s are dated on rs.ge in an earlier month but booked in this one: their VAT is in this "
                "month's A I and on that month's B I; file an adjusted declaration for that month.", tab=tab,
                names=name_list(self.env, late.mapped('name'))))
        drafts = Move.search([
            ('company_id', 'in', companies.ids),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'draft'),
            ('rs_einv_replacement_mode', '=', 'correction'),
            ('rs_einv_status', '=', '8'),
            ('rs_einv_is_spec', '=', spec),
            ('invoice_date', '<=', self.date_to),
        ], order='invoice_date, id')
        if drafts:
            warnings.append(self.env._("%(tab)s: corrections accepted on rs.ge but still drafts in Odoo, so their VAT is not counted: %(names)s.",
                tab=tab, names=name_list(self.env, [self._gec_doc_label(move) for move in drafts])))
        warnings += self._gec_correction_warnings(tab, spec)
        return rows, moves, warnings

    def _gec_build_annex_b1(self):
        """Rebuild the Odoo rows of annex ბ I and its advance offsets; typed rows are kept. Offsets are the settlements
        rs.ge accepted (status 200), read sudo like the branch invoices."""
        self.ensure_one()
        rows, moves, warnings = self._gec_b1_scan()
        self.invoice_line_ids.filtered('move_id').unlink()
        self.env['gec.vat.invoice.line'].create(rows)
        self.advance_line_ids.filtered('settlement_id').unlink()
        latest = {}
        for settlement in self.env['rs.einvoice.advance.settlement'].sudo().search(
                [('final_move_id', 'in', moves.ids), ('rs_status', '=', '200')], order='synced_at desc, id desc'):
            latest.setdefault((settlement.final_move_id, settlement.advance_move_id), settlement)
        self.env['gec.vat.advance.line'].create([{
            'declaration_id': self.id,
            'settlement_id': settlement.id,
            'delivery_series': settlement.final_move_id.rs_einv_series,
            'delivery_number': settlement.final_move_id.rs_einv_number,
            'advance_series': settlement.advance_move_id.rs_einv_series,
            'advance_number': settlement.advance_move_id.rs_einv_number,
            'amount': settlement.vat_amount,
        } for settlement in latest.values()])
        return warnings

    def _gec_doc_label(self, move):
        """Odoo number, or rs.ge series and number when a draft has none."""
        return move.name or f"{move.rs_einv_series or ''} {move.rs_einv_number or ''}".strip() or move.display_name

    def _gec_b2_scan(self, spec=False):
        """Annex ბ II of the month: (row values, warnings), from vendor bills linked to rs.ge, each in its
        accounting-date month (where Odoo credits its VAT), petroleum bills excluded. A bill replacing another is a
        correction (supplier corrections only); its row is the change. Sudo. spec=True: petroleum bills, tab 14."""
        self.ensure_one()
        tab = '14' if spec else self.env._("B II")
        Move = self.env['account.move'].sudo()
        period = self._gec_period_domain()
        in_month = period + [('move_type', '=', 'in_invoice'), ('rs_einv_is_spec', '=', spec)]
        moves = Move.search(in_month + [('rs_einv_number', '!=', False), ('rs_einv_status', 'in', RS_ACCEPTED)], order='date, id')
        status_label = dict(Move._fields['rs_einv_status']._description_selection(self.env))
        rows, warnings, drafts = [], [], []
        for move in moves:
            original = move.rs_einv_replaces_id
            vat = self._gec_rs_vat(move) - self._gec_rs_vat(original)
            rows.append({
                'declaration_id': self.id,
                'part': 'purchase',
                'move_id': move.id,
                'series': move.rs_einv_series,
                'number': move.rs_einv_number,
                'operation_month': (move.invoice_date or move.date).replace(day=1),
                'partner_tin': move.rs_einv_seller_tin,
                'amount': round_2(max(vat, 0.0)),
                'reduce_amount': round_2(max(-vat, 0.0)),
                'korect_series': original.rs_einv_series or False,
                'korect_number': original.rs_einv_number or False,
            })
            if move.state == 'draft':
                drafts.append(self._gec_doc_label(move))
            elif move.state == 'cancel' and move.rs_einv_status == '2':
                warnings.append(self.env._("%(tab)s: %(name)s is cancelled in Odoo but still confirmed on rs.ge.", tab=tab,
                    name=self._gec_doc_label(move)))
            if original and move.state == 'posted' and original.state == 'cancel' and original.date < self.date_from:
                warnings.append(self.env._("%(tab)s: correction %(name)s: Odoo cancelled %(original)s of %(month)s, so Odoo's VAT of that month "
                    "dropped and this month credits the full VAT; rs.ge counts only the change here.", tab=tab, name=self._gec_doc_label(move),
                    original=self._gec_doc_label(original), month=original.date.strftime('%m/%Y')))
        if drafts:
            warnings.append(self.env._("%(tab)s: accepted on rs.ge but still drafts in Odoo, so their VAT is not credited: %(names)s.", tab=tab,
                names=name_list(self.env, drafts)))
        pending = Move.search(in_month + [
            ('state', '!=', 'cancel'),
            ('rs_einv_number', '!=', False),
            ('rs_einv_status', 'not in', RS_ACCEPTED),
            ('rs_einv_skip', '=', False),
        ], order='date, id')
        by_status = {}
        for move in pending:
            label = status_label.get(move.rs_einv_status, move.rs_einv_status)
            by_status.setdefault(label, []).append(self._gec_doc_label(move))
        for status, names in by_status.items():
            warnings.append(self.env._("%(tab)s: left out, rs.ge status %(status)s: %(names)s.", tab=tab, status=status,
                names=name_list(self.env, names)))
        warnings += self._gec_correction_warnings(tab, spec, purchase=True)
        if spec:
            return rows, warnings
        not_linked = Move.search(period + [
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('state', '=', 'posted'),
            ('rs_einv_id', '=', False),
            ('rs_einv_skip', '=', False),
            ('rs_einv_is_spec', '=', False),
            ('commercial_partner_id.country_id.code', '=', GEORGIA),
            ('commercial_partner_id.vat', '!=', False),
        ], order='date, id').filtered(self._gec_rs_vat)
        if not_linked:
            warnings.append(self.env._("B II: bills and credit notes with VAT from Georgian suppliers not linked to an rs.ge invoice: %(names)s.",
                names=name_list(self.env, not_linked.mapped('name'))))
        return rows, warnings

    def _gec_correction_warnings(self, tab, spec=False, purchase=False):
        """Corrections Odoo counts apart from rs.ge, which counts only the change: the original still counts, or its reversal is in another month."""
        self.ensure_one()
        Move = self.env['account.move'].sudo()
        row = self.env._("A III") if purchase else self.env._("A I")
        mode = [] if purchase else [('rs_einv_replacement_mode', '=', 'correction')]
        period = self._gec_period_domain() + [('state', '=', 'posted')]
        corrections = Move.search(period + [
            ('move_type', '=', 'in_invoice' if purchase else 'out_invoice'),
            ('rs_einv_is_spec', '=', spec),
            ('rs_einv_replaces_id', '!=', False),
        ] + mode)
        reversals = Move.search(Domain(period + [('move_type', '=', 'in_refund' if purchase else 'out_refund')]) & REPLACEMENT_REVERSAL)
        late = reversals.reversed_entry_id.rs_einv_replaced_by_id.filtered_domain([('state', '!=', 'cancel'), ('rs_einv_is_spec', '=', spec)] + mode)
        warnings = []
        for move in (corrections | late).sorted(lambda move: (move.date, move.id)):
            original = move.rs_einv_replaces_id
            reversal = original.reversal_move_ids.filtered_domain(REPLACEMENT_REVERSAL)[:1]
            name, original_name = self._gec_doc_label(move), self._gec_doc_label(original)
            if move in corrections and original.rs_einv_correction_in_flight:
                if move.rs_einv_status == '8':
                    warnings.append(self.env._("%(tab)s: correction %(name)s is accepted on rs.ge but %(original)s still counts in Odoo: run Check "
                        "Status on it (unreconcile its payments first).", tab=tab, name=name, original=original_name))
                else:
                    warnings.append(self.env._("%(tab)s: correction %(name)s is posted but not accepted on rs.ge yet, and %(original)s still counts "
                        "in Odoo: Odoo's VAT holds both until it is accepted.", tab=tab, name=name, original=original_name))
            elif reversal and reversal.date.replace(day=1) != move.date.replace(day=1) and (purchase or move in late):
                warnings.append(self.env._("%(tab)s: correction %(name)s is dated %(month)s and the reversal of %(original)s %(reversal_month)s, so "
                    "%(row)s row 1 of both months differs from rs.ge, which counts only the change.", tab=tab, name=name,
                    month=move.date.strftime('%m/%Y'), original=original_name, reversal_month=reversal.date.strftime('%m/%Y'), row=row))
        return warnings

    def _gec_build_annex_b2(self):
        """Rebuild the Odoo rows of annex ბ II; typed rows are kept. rs.ge advance offsets exist only for sales."""
        self.ensure_one()
        self.purchase_line_ids.filtered('move_id').unlink()
        rows, warnings = self._gec_b2_scan()
        self.env['gec.vat.invoice.line'].create(rows)
        return warnings

    def _gec_margin_scan(self):
        """Annex III-19⁶ of the month: ({cell code: price}, warnings, {cell code: lines or assets behind it}), from
        posted invoice lines linked to an asset by its Sell action. Sale price: the lines; purchase price: the asset's
        Asset Value, counted with a credited sale or in the month of its first non-credited linked line. Sudo."""
        self.ensure_one()
        Line = self.env['account.move.line'].sudo()
        Move = self.env['account.move'].sudo()
        period = self._gec_period_domain()
        lines = Line.search(period + [('parent_state', '=', 'posted'), ('gec_sold_asset_id', '!=', False)])
        refunds = Move.search(period + [
            ('move_type', '=', 'out_refund'),
            ('state', '=', 'posted'),
            ('reversed_entry_id.line_ids.gec_sold_asset_id.gec_margin_scheme', '!=', False),
        ])
        entries = Move.search(period + [
            ('asset_move_type', 'in', ('sale', 'disposal')),
            ('state', '!=', 'cancel'),
            ('asset_variant_id.asset_id.gec_margin_scheme', '!=', False),
        ])
        assets = lines.gec_sold_asset_id | entries.asset_variant_id.asset_id
        first = dict(Line._read_group([
            ('gec_sold_asset_id', 'in', assets.ids),
            ('parent_state', '=', 'posted'),
            ('move_id.reversal_move_ids', 'not any', [('state', '=', 'posted')]),
        ], ['gec_sold_asset_id'], ['date:min']))
        values = dict.fromkeys(MARGIN_CODES, 0.0)
        sources = {'359_%s' % row: self.env['account.asset'].sudo() for row in MARGIN_ROWS}
        sources |= {'359_%s_4' % row: Line for row in MARGIN_ROWS}
        taxed, not_closed, no_price, no_category, counted = [], [], [], [], []
        for asset, asset_lines in lines.grouped('gec_sold_asset_id').items():
            if not asset.gec_margin_scheme:
                if not asset_lines.tax_ids:
                    no_category.append(asset.display_name)
                continue
            row = MARGIN_SCHEME_ROW[asset.gec_margin_scheme]
            values['359_%s_4' % row] -= sum(asset_lines.mapped('balance'))
            sources['359_%s_4' % row] |= asset_lines
            open_lines = asset_lines.filtered(lambda line: not line.move_id.reversal_move_ids.filtered(lambda move: move.state == 'posted'))
            if not open_lines or first[asset] >= self.date_from:
                values['359_%s' % row] += asset.original_value
                sources['359_%s' % row] |= asset
                if asset.currency_id.is_zero(asset.original_value):
                    no_price.append(asset.display_name)
            else:
                counted.append(asset.display_name)
            taxed += asset_lines.filtered('tax_ids').move_id.mapped('name')
            if asset.state != 'close':
                not_closed.append(asset.display_name)
        other_month, no_line = [], []
        for asset in entries.asset_variant_id.asset_id - lines.gec_sold_asset_id:
            if asset in first:
                other_month.append('%s (%s)' % (asset.display_name, first[asset].strftime('%m/%Y')))
            else:
                no_line.append(asset.display_name)
        warnings = []
        if taxed:
            warnings.append(self.env._("III-19⁶: margin-scheme goods sold with a tax (%(names)s): the sale price here leaves the tax out, and a VAT "
                "tax on these lines also reaches Odoo's VAT report; check their taxes.", names=name_list(self.env, sorted(set(taxed)))))
        if not_closed:
            warnings.append(self.env._("III-19⁶: assets sold on this month's invoices are no longer closed (%(names)s): the sale was undone; check "
                "the row.", names=name_list(self.env, sorted(not_closed))))
        if refunds:
            warnings.append(self.env._("III-19⁶: credit notes (%(names)s) cancel margin-scheme sales; correct the row by hand.",
                names=name_list(self.env, sorted(refunds.mapped('name')))))
        if no_price:
            warnings.append(self.env._("III-19⁶: assets without a purchase price (%(names)s): Asset Value is 0, so VAT is charged on the full sale "
                "price.", names=name_list(self.env, sorted(no_price))))
        if no_category:
            warnings.append(self.env._("III-19⁶: assets sold without VAT and without a margin-scheme category (%(names)s): set the category on the "
                "asset or check the invoice.", names=name_list(self.env, sorted(no_category))))
        if counted:
            warnings.append(self.env._("III-19⁶: purchase price already counted in the month of the first invoice of the sale (%(names)s); only the "
                "sale price counts here.", names=name_list(self.env, sorted(counted))))
        if no_line:
            warnings.append(self.env._("III-19⁶: assets sold or disposed this month without a posted invoice line linked to them (%(names)s) — "
                "receipt, Point of Sale or cancelled invoice: type the row if it was a margin-scheme sale.",
                names=name_list(self.env, sorted(no_line))))
        if other_month:
            warnings.append(self.env._("III-19⁶: assets sold this month on an invoice of another month (%(names)s); they are declared in the "
                "invoice's month.", names=name_list(self.env, sorted(other_month))))
        return {code: round_2(value) for code, value in values.items()}, warnings, sources

    def action_gec_customs_upload(self, attachment_ids):
        """Add one annex ბ III row per uploaded customs declaration or Form 4 PDF; file the PDFs on the declaration."""
        self.ensure_one()
        self.check_access('write')
        if self.state != 'draft':
            raise UserError(self.env._("Reset the declaration to draft before uploading customs declarations."))
        attachments = self.env['ir.attachment'].browse(attachment_ids).filtered(lambda att: not att.res_model)
        rows = []
        for attachment in attachments:
            try:
                parsed = self._gec_parse_pdf(attachment.raw.content)
            except PDF_ERRORS:
                raise UserError(self.env._("%s is not a readable PDF.", attachment.name))
            rows.append(self._gec_customs_row_vals(attachment, parsed))
        self.env['gec.vat.customs.line'].create(rows)
        attachments.write({
            'res_model': self._name,
            'res_id': self.id,
            'company_id': self.company_id.id,
        })
        return True

    def _gec_customs_row_vals(self, attachment, parsed):
        self.ensure_one()
        return {**parsed, 'declaration_id': self.id, 'attachment_id': attachment.id}

    @api.model
    def _gec_parse_pdf(self, raw):
        """Read the type and the four values of a customs declaration or Form 4 PDF by text position: the text order
        of the stream glues neighbouring cells. A value that is not found is False; a PDF of neither type has none."""
        items = []
        position = [0.0, 0.0]

        def before(operator, args, cm, tm):
            if operator in PDF_SHOW_OPERATORS:
                position[:] = (tm[4] * cm[0] + tm[5] * cm[2] + cm[4], tm[4] * cm[1] + tm[5] * cm[3] + cm[5])

        def visit(text, cm, tm, font_dict, font_size):
            if text.strip():
                items.append((position[0], position[1], text.strip()))

        PdfReader(io.BytesIO(raw), strict=False).pages[0].extract_text(visitor_text=visit, visitor_operand_before=before)

        def label_of(label_text):
            return next((item for item in items if label_text in item[2]), None)

        def right_of(label_text, pattern):
            label = label_of(label_text)
            found = [
                item for item in items if label and item[0] > label[0] and pattern.fullmatch(item[2])
                and abs(item[1] - label[1]) <= CUSTOMS_SAME_LINE]
            return min(found)[2] if found else False

        def below(label_text, pattern, box):
            label = label_of(label_text)
            found = [
                item for item in items if label and pattern.fullmatch(item[2]) and abs(item[0] - label[0]) <= box[0]
                and 0 < label[1] - item[1] <= box[1]]
            return max(found, key=lambda item: item[1])[2] if found else False

        pdf_type = number = code = date = amount = False
        date_format = '%d/%m/%Y'
        if label_of(FORM4_NUMBER_LABEL):
            pdf_type, date_format = 'form4', '%d.%m.%Y'
            number = below(FORM4_NUMBER_LABEL, FORM4_NUMBER_RE, FORM4_NUMBER_BOX)
            date = below(FORM4_DATE_LABEL, FORM4_DATE_RE, FORM4_DATE_BOX)
            vat = next(filter(None, [FORM4_VAT_RE.fullmatch(item[2]) for item in items]), None)
            code, amount = vat.groups() if vat else (False, False)
        elif label_of(CUSTOMS_NUMBER_LABEL):
            pdf_type = 'customs'
            number = right_of(CUSTOMS_NUMBER_LABEL, CUSTOMS_NUMBER_RE)
            date = right_of(CUSTOMS_NUMBER_LABEL, CUSTOMS_DATE_RE)
            code = below(CUSTOMS_ORGAN_LABEL, CUSTOMS_CODE_RE, CUSTOMS_CODE_BOX)
            amount = right_of(CUSTOMS_TOTAL_LABEL, CUSTOMS_AMOUNT_RE)
        try:
            assessment_date = datetime.strptime(date[:10], date_format).date() if date else False
        except ValueError:
            assessment_date = False
        return {
            'pdf_type': pdf_type,
            'assessment_number': number,
            'customs_code': code,
            'assessment_date': assessment_date,
            'amount': float(re.sub(r'[\s,]', '', amount)) if amount else False,
        }

    def _gec_warnings(self):
        """The cell checks shown on the form; none blocks the declaration. A PDF's name is read sudo: a file pulled
        from Documents may be unreadable. Bills, credit notes, the report and the companies are read sudo as in the
        scans: the user may not see the same-VAT branches."""
        self.ensure_one()
        warnings = []
        others = self.search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '=', self.date_from),
            ('decl_type', '=', self.decl_type),
            ('id', 'not in', self.ids),
        ])
        if others:
            warnings.append(self.env._("Another declaration of this type exists for this company and month: %(names)s.",
                names=', '.join(others.mapped('name'))))
        branch_warning = self.company_id._gec_vat_branch_warning()
        if branch_warning:
            warnings.append(branch_warning)
        lines = self.line_ids
        by_code = {line.code: line for line in lines}
        for line in lines:
            source = ODOO_SOURCE.get(line.code)
            if not (source and line.computed and line.tab in ('1', '2') and line.code != '355_1_1_5'):
                continue
            # Only a row whose base still equals Odoo's: a typed base makes the comparison meaningless.
            base = by_code[line.code[:-2] if line.tab == '1' else line.code[:-1]]
            if (float_compare(base.value, base.odoo_value, precision_rounding=0.01) == 0
                    and float_compare(line.odoo_value, line.value, precision_rounding=0.01) != 0):
                warnings.append(self.env._("%(tab)s row %(row)s: Odoo VAT is %(odoo).2f, the portal's 18%% gives %(portal).2f; check its taxes "
                    "with the magnifier on the VAT cell, or keep the portal figure if the gap is only rounding.",
                    tab=self.env._("A I") if line.tab == '1' else self.env._("A II"), row=line.row, odoo=line.odoo_value, portal=line.value))
        december = self.date_from.month == 12
        for code in ('353_63', '353_613'):
            line = by_code[code]
            if float_is_zero(line.odoo_value, precision_rounding=0.01):
                continue
            if december:
                warnings.append(self.env._("A III row %(row)s: Odoo has %(amount).2f; type the figure in this row.", row=line.row,
                    amount=line.odoo_value))
            else:
                warnings.append(self.env._("A III row %(row)s: Odoo has %(amount).2f; the portal fills this row only in December.", row=line.row,
                    amount=line.odoo_value))
        margin_cell = by_code['355_1_1_5']
        if (not float_is_zero(margin_cell.odoo_value, precision_rounding=0.01)
                and float_compare(margin_cell.odoo_value, by_code['359_5'].value, precision_rounding=0.01) != 0):
            warnings.append(self.env._("Margin scheme: Odoo VAT is %(odoo).2f, III-19⁶ gives %(portal).2f.", odoo=margin_cell.odoo_value,
                portal=by_code['359_5'].value))
        for line in lines.filtered(lambda cell: not cell.locked and cell.value < 0):
            if line.code in DEDUCTION_DECREASE_SOURCE:
                warnings.append(self.env._("A III row %(row)s column 4 is negative: the portal reads it as 0, and Odoo proposes the amount in "
                    "Part III row 12.", row=line.row))
            else:
                columns = dict(line._fields['column']._description_selection(self.env))
                warnings.append(self.env._("Tab %(tab)s, row %(row)s, column %(column)s (%(name)s) is negative: the portal reads a negative "
                    "value as 0.", tab=line.tab, row=line.row, column=columns[line.column], name=line.name))
        b2_vat = round_2(self.b2_amount - self.b2_reduce_amount + self.b14_amount - self.b14_reduce_amount)
        a3_vat = round_2(by_code['353_14'].value + by_code['353_15'].value)
        if float_compare(b2_vat, a3_vat, precision_rounding=0.01) != 0:
            warnings.append(self.env._("B II and tab 14: the received invoices carry %(b2).2f VAT, A III row 1 claims %(a3).2f; row 1 is the VAT of "
                "tax invoices received, so check the bills that have no rs.ge invoice.", b2=b2_vat, a3=a3_vat))
        without_b2 = self.env['account.move.line'].sudo()._read_group(self._gec_period_domain() + [
            ('parent_state', '=', 'posted'),
            ('move_id.move_type', '=', 'in_invoice'),
            ('tax_tag_ids', 'in', self._gec_tax_tags(ODOO_SOURCE['353_13']).ids),
            ('move_id', 'not in', (self.purchase_line_ids | self.spec_purchase_line_ids).move_id.ids),
        ], ['move_id'], ['balance:sum'])
        if without_b2:
            warnings.append(self.env._("A III row 1 holds VAT without an rs.ge tax invoice in B II: %(bills)s.",
                bills=name_list(self.env, ['%s (%.2f)' % (move.name, vat) for move, vat in without_b2])))
        a3_imports = by_code['353_23'].value
        if float_compare(self.b3_amount, a3_imports, precision_rounding=0.01) != 0:
            warnings.append(self.env._("B III: the customs declarations carry %(b3).2f VAT, A III row 2 claims %(a3).2f; row 2 is the VAT paid on "
                "imports: upload the customs declarations missing here, or book the import VAT of those listed.", b3=self.b3_amount, a3=a3_imports))
        customs_rows = self.customs_line_ids
        for row in customs_rows.filtered('attachment_id'):
            if not (row.assessment_number and row.assessment_date and row.amount):
                warnings.append(self.env._("B III: %(file)s: the number, the date or the VAT was not found in the PDF; type it.",
                    file=row.attachment_id.sudo().name))
        for number, count in Counter(customs_rows.filtered('assessment_number').mapped('assessment_number')).items():
            if count > 1:
                warnings.append(self.env._("B III: assessment number %(number)s is listed %(count)s times; delete the duplicate row.",
                    number=number, count=count))
        for row in customs_rows.filtered('assessment_date'):
            if not self.date_from <= row.assessment_date <= self.date_to:
                warnings.append(self.env._("B III: assessment %(number)s is dated %(date)s, outside the declaration month.",
                    number=row.assessment_number or '', date=format_date(self.env, row.assessment_date)))
        a3_auction, a3_barter = by_code['353_83'].value, by_code['353_73'].value
        if float_compare(a3_auction, self.b4_amount, precision_rounding=0.01) > 0:
            warnings.append(self.env._("A III row 8 claims %(a3).2f, more than B IV (%(b4).2f).", a3=a3_auction, b4=self.b4_amount))
        if float_compare(a3_barter, self.b5_amount, precision_rounding=0.01) > 0:
            warnings.append(self.env._("A III row 7 claims %(a3).2f, more than B V (%(b5).2f).", a3=a3_barter, b5=self.b5_amount))
        b1_vat = round_2(self.b1_amount - self.b1_reduce_amount + self.b13_amount - self.b13_reduce_amount)
        a1_vat = round_2(sum(by_code[code].value for code in ('355_1_5', '355_2_5', '355_3_5')))
        if float_compare(b1_vat, a1_vat, precision_rounding=0.01) > 0:
            warnings.append(self.env._("B I and tab 13: the invoices carry %(b1).2f VAT, more than A I rows 1-3 (%(a1).2f); the portal requires "
                "rows 1-3 to cover the invoices of the month.", b1=b1_vat, a1=a1_vat))
        cell7, base = by_code['358_7'].value, by_code['355_1']
        cell7_cap = round_2(self.b1_reduce_amount + self.b13_reduce_amount + self.b8_amount)
        if float_compare(cell7, cell7_cap, precision_rounding=0.01) > 0:
            warnings.append(self.env._("Cell 7 holds %(cell7).2f, more than the VAT reduced in B I, tab 13 and B VIII (%(cap).2f); per the "
                "portal, cell 7 must not exceed that sum.", cell7=cell7, cap=cell7_cap))
        if float_compare(cell7, 0.0, precision_rounding=0.01) > 0 and float_compare(base.value, base.odoo_value, precision_rounding=0.01) == 0:
            credit_notes = self.env['account.move'].sudo().search(self._gec_period_domain() + [
                ('move_type', '=', 'out_refund'),
                ('state', '=', 'posted'),
                '|',
                ('reversed_entry_id', '=', False),
                ('reversed_entry_id.rs_einv_replaced_by_id', '=', False),
            ]).filtered(self._gec_rs_vat)
            if sum((self.invoice_line_ids | self.spec_line_ids).filtered('move_id').mapped('reduce_amount')) or credit_notes:
                warnings.append(self.env._("Cell 7 holds %(cell7).2f, but A I row 1 is Odoo's figure, which already subtracts the month's credit "
                    "notes and corrections: type in cell 7 only decreases not booked in Odoo.", cell7=cell7))
        if self.state == 'draft':
            branches = self.env['res.company'].sudo().search([('id', 'child_of', self.company_id.id)]) - self.company_id._gec_vat_companies()
            branches = branches.filtered(lambda branch: not branch.tax_lock_date or branch.tax_lock_date < self.date_to)
            if branches:
                warnings.append(self.env._("Mark as Filed also locks this month for %(names)s (own Tax ID): file their declarations first.",
                    names=', '.join(branches.mapped('name'))))
        return warnings
