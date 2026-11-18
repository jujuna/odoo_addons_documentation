import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import formatLang

from .rs_form30_declaration import AUTONOMOUS_REPUBLICS, _number, _refuse_in_file_rows
from .rs_form30_warning import _localize_warning

HEADERS = ['საიდენტიფიკაციო ნომერი (პირადი ნომერი)', 'თანხის მიმღების სახელი/სამართლებრივი ფორმა', 'თანხის მიმღების გვარი/დასახელება', 'მისამართი',
    'პირის რეზიდენტობა (ქვეყანა)', 'შემოსავლის მიმღებ პირთა კატეგორია', 'განაცემის სახე', 'განაცემი თანხა (ლარი)', 'სხვა შეღავათები',
    'გაცემის თარიღი', 'წყაროსთან დასაკავებელი გადასახადის განაკვეთი',
    'საერთაშორისო ხელშეკრულების საფუძველზე გათავისუფლებას ან შემცირებას დაქვემდებარებული გადასახადის თანხა',
    'ორმაგი დაბეგვრის თავიდან აცილების შესახებ ხელშეკრულების საფუძველზე ჩათვლას დაქვემდებარებული, უცხო ქვეყანაში გადახდილი გადასახადის თანხა',
    'გაცემულია ხაზინიდან']
LEGAL_FORMS = {'შპს', 'სს', 'იმ', 'ი/მ', 'ააიპ', 'ა(ა)იპ', 'კს', 'სპს', 'სსიპ', 'კოოპერატივი', 'llc', 'ltd', 'jsc'}
HOTEL_CATEGORIES = {'1.3', '3.10'}
NON_SERVICE_TYPES = {'5', '16', '21', '22', '23'}
NON_RESIDENT_RATES = {4.0, 5.0, 10.0, 15.0}


class RsForm30Line(models.Model):
    _name = 'rs.form30.line'
    _description = 'rs.ge Form 30 Declaration Line'
    _order = 'date, id'

    declaration_id = fields.Many2one('rs.form30.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    source = fields.Selection([
        ('payslip', 'Payslip'),
        ('payment', 'Payment'),
        ('entry', 'Journal Entry'),
        ('bill', 'Vendor Bill'),
        ('manual', 'Manual'),
    ], required=True, default='manual')
    payslip_id = fields.Many2one('hr.payslip', ondelete='set null')
    withholding_line_id = fields.Many2one('account.payment.withholding.line', string='Withholding Line', ondelete='set null')
    payment_id = fields.Many2one('account.payment', related='withholding_line_id.payment_id', string='Payment')
    move_id = fields.Many2one('account.move', string='Journal Entry', ondelete='set null', index='btree_not_null', readonly=True,
        help="The journal entry this row declares; can belong to a branch of the declaration's company (payments are reconciled within one root "
        "company).")
    settlement_payment_ids = fields.Many2many('account.payment', 'rs_form30_line_payment_rel', 'line_id', 'payment_id', string='Payments',
        readonly=True, copy=False,
        help="The payments whose cash this row declares; can belong to a branch of the declaration's company (payments are reconciled within one "
        "root company).")
    settlement_statement_line_ids = fields.Many2many('account.bank.statement.line', 'rs_form30_line_statement_rel', 'line_id', 'statement_line_id',
        string='Bank Transactions', readonly=True, copy=False,
        help="The bank transactions whose cash this row declares; can belong to a branch of the declaration's company (payments are reconciled "
        "within one root company).")
    settlement_move_ids = fields.Many2many('account.move', 'rs_form30_line_move_rel', 'line_id', 'move_id', string='Offset Entries',
        readonly=True, copy=False, help="The offset entries whose settlement this row declares; can belong to a branch of the declaration's company.")
    partner_id = fields.Many2one('res.partner', string='Recipient', ondelete='set null')
    identification = fields.Char(string='ID Number')
    first_name = fields.Char(string='First Name / Legal Form')
    last_name = fields.Char(string='Last Name / Company Name')
    address = fields.Char()
    country_id = fields.Many2one('res.country', string='Residency', ondelete='restrict')
    category_id = fields.Many2one('rs.form30.category', string='Category', ondelete='restrict')
    income_type_id = fields.Many2one('rs.form30.income.type', string='Income Type', ondelete='restrict')
    amount = fields.Monetary(string='Gross Amount', currency_field='currency_id')
    other_relief = fields.Monetary(currency_field='currency_id')
    date = fields.Date(string='Payment Date')
    rate = fields.Float(string='Rate %', digits=(5, 2))
    international_agreement_exempt_tax = fields.Monetary(string='Exempt or Reduced Under an International Agreement', currency_field='currency_id')
    foreign_tax_credit = fields.Monetary(currency_field='currency_id')
    from_treasury = fields.Boolean()
    pension_amount = fields.Monetary(string='Pension 2% (control)', currency_field='currency_id')
    tax_amount = fields.Monetary(string='Withheld Tax (control)', currency_field='currency_id')
    warning = fields.Char()
    warning_display = fields.Char(compute='_compute_warning_display')
    issue_level = fields.Selection([('note', 'Note'), ('warning', 'Warning'), ('blocker', 'Blocker')], string='Issue', readonly=True)
    in_file = fields.Boolean(string='In File', readonly=True, copy=False, help="This row went into the last exported file of its declaration.")
    exported_on = fields.Date(string='Exported On', readonly=True, copy=False)
    autonomous_republic = fields.Selection(AUTONOMOUS_REPUBLICS,
        help="Work location of the employee when it lies in an autonomous republic; feeds cell 57¹ or 57².")

    @api.depends('warning')
    @api.depends_context('lang')
    def _compute_warning_display(self):
        for line in self:
            line.warning_display = _localize_warning(line.env, line.warning)

    def write(self, vals):
        _refuse_in_file_rows(self)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_file(self):
        _refuse_in_file_rows(self)

    def _rs_form30_draw_exempt(self):
        remaining = {}
        usage_vals = []
        for line in self:
            partner = line.partner_id
            if not partner or float_is_zero(partner.rs_form30_exempt_limit, precision_rounding=0.01):
                continue
            if partner.id not in remaining:
                remaining[partner.id] = partner.rs_form30_exempt_remaining
            exempt = min(max(0.0, line.tax_amount), max(0.0, remaining[partner.id]))
            if float_is_zero(exempt, precision_rounding=0.01):
                continue
            line.international_agreement_exempt_tax = exempt
            before = remaining[partner.id]
            remaining[partner.id] = before - exempt
            usage_vals.append({
                'partner_id': partner.id,
                'line_id': line.id,
                'amount': exempt,
                'balance_before': before,
                'balance_after': remaining[partner.id],
            })
        self.env['rs.form30.exempt.usage'].create(usage_vals)

    @api.depends('first_name', 'last_name', 'identification', 'payslip_id', 'withholding_line_id', 'move_id')
    def _compute_display_name(self):
        for line in self:
            line.display_name = line._label()

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        partner = self.partner_id
        if not partner:
            return
        first_name, last_name = self._split_name(partner.name, partner.is_company)
        self.update({
            'identification': self._clean_identification(partner.vat),
            'first_name': first_name,
            'last_name': last_name,
            'address': partner._display_address(without_name=True, separator=' '),
            'country_id': partner.country_id,
        })

    @api.onchange('partner_id', 'date')
    def _onchange_category_date(self):
        # Keep identity and manual relief edits when only the payment date changes.
        self.category_id = self.partner_id._rs_form30_category_on(self.date)

    @api.model
    def _rs_form30_headers(self):
        return HEADERS

    @api.model
    def _split_name(self, name, is_company):
        """(first name, last name) for people; (legal form, company name) for companies."""
        parts = (name or '').split()
        if not parts:
            return '', ''
        if is_company:
            if parts[0].strip('.').lower() in LEGAL_FORMS and len(parts) > 1:
                return parts[0], ' '.join(parts[1:])
            return '', ' '.join(parts)
        return parts[0], ' '.join(parts[1:])

    @api.model
    def _clean_identification(self, value):
        value = (value or '').replace(' ', '')
        return re.sub(r'^GE(?=\d+$)', '', value, flags=re.IGNORECASE)

    def _label(self):
        self.ensure_one()
        name = f"{self.first_name or ''} {self.last_name or ''}".strip() or self.identification or self.env._("line %s", self.id)
        # sudo: only the payslip name is read, the accountant has no payroll access
        reference = self.sudo().payslip_id.name or self.payment_id.name or self.move_id.name
        return f"{name} ({reference})" if reference else name

    def _taxable_base(self):
        """Portal column 7 minus 8 minus 9: amount less pension less other relief."""
        self.ensure_one()
        return self.amount - self.pension_amount - self.other_relief

    def _portal_tax(self):
        """Portal column 12: the taxable base at the row's rate."""
        self.ensure_one()
        return self.currency_id.round(self._taxable_base() * self.rate / 100)

    def _trace_item(self, kind, value):
        """Return this row's contribution to a main-part cell, with its arithmetic."""
        self.ensure_one()
        money = lambda amount: formatLang(self.env, amount, digits=2)
        rate = f"{_number(self.rate)}%"
        math = {
            'base': self.env._("%(amount)s − pension %(pension)s − relief %(relief)s", amount=money(self.amount), pension=money(self.pension_amount),
                relief=money(self.other_relief)),
            'tax': self.env._("base %(base)s × %(rate)s", base=money(self._taxable_base()), rate=rate),
            'credit': self.env._("foreign tax credit"),
        }.get(kind, self.env._("rate %s", rate))
        # sudo: only the payslip link is built; the accountant has no payroll access
        record = self.sudo().payslip_id if self.payslip_id else self.payment_id or self.move_id
        who = f"{self.category_id.name or '?'} · {self.income_type_id.name or '?'}"
        return self.declaration_id._trace_item(self._label(), value, who, record, math)

    def _main_part_cells(self):
        """(cell taking the amount, cell taking the taxable base) of this row in the portal's main part."""
        self.ensure_one()
        category, kind, rate = self.category_id, self.income_type_id.code, round(self.rate, 2)
        code = category.display_code or ''
        if kind == '1':
            return '16', '17'
        if category.is_organization:
            if code == '3.1' and kind != '2':
                return '45', '53'
            if code == '3.8':
                return '42', '50'
            if code == '3.7':
                return '43', '51'
            if kind == '2':
                return '46', '54'
            if kind == '3':
                return '47', '55'
            if kind == '17' and rate == 5:
                return '41', '49'
            return '44', '52'
        if kind == '2':
            return '22', '23'
        if kind == '3':
            return '24', '25'
        if code in HOTEL_CATEGORIES:
            return None, '26'
        if kind in NON_SERVICE_TYPES:
            return None, '21'
        if code.startswith('3.') and rate in NON_RESIDENT_RATES:
            if code == '3.2':
                return '32', '38'
            if code == '3.6':
                return '29', '35'
            if code == '3.5':
                return '30', '36'
            if kind == '17' and rate == 5:
                return '28', '34'
            return '31', '37'
        if rate == 3:
            return None, '20_1'
        if rate == 5:
            return None, '20'
        return None, '19'

    def _matrix_problems(self, allowed, period):
        self.ensure_one()
        problems = []
        for classifier in (self.category_id, self.income_type_id):
            if classifier and not classifier._is_valid(period):
                problems.append(self.env._("%s is not valid for this period", classifier.display_name))
        if self.category_id and self.income_type_id:
            rates = allowed.get((self.category_id.id, self.income_type_id.id), [])
            if not rates:
                problems.append(self.env._("category/income type combination not allowed"))
            elif not any(float_compare(self.rate, rate, precision_digits=2) == 0 for rate in rates):
                problems.append(self.env._("rate %s not allowed (allowed: %s)", _number(self.rate), ', '.join(_number(r) for r in rates)))
        return problems

    @api.constrains('category_id', 'income_type_id', 'rate', 'declaration_id')
    def _check_matrix(self):
        """Refuse a manual line the rs.ge matrix does not allow; generated rows get a blocker instead."""
        allowed = {}
        errors = []
        for line in self:
            if line.source != 'manual':
                continue
            period = line.declaration_id.period
            if period not in allowed:
                allowed[period] = self.env['rs.form30.rate.rule']._allowed_rates(period)
            problems = line._matrix_problems(allowed[period], period)
            if problems:
                label = line._label()
                errors.extend(f"{label}: {problem}" for problem in problems)
        if errors:
            raise ValidationError(self.env._("These lines are not allowed by the rs.ge classifier for the declaration period:\n%s",
                '\n'.join(errors[:40])))

    def _validation_errors(self, allowed, period, date_from, date_to):
        self.ensure_one()
        problems = []
        missing = [label for field_name, label in zip(('identification', 'country_id', 'category_id', 'income_type_id', 'date'),
            (self.env._("ID number"), self.env._("residency"), self.env._("category"), self.env._("income type"), self.env._("date")))
            if not self[field_name]]
        if missing:
            problems.append(self.env._("missing %s", ', '.join(missing)))
        if self.country_id and not self.country_id.rs_form30_code:
            problems.append(self.env._("%s has no rs.ge country code", self.country_id.name))
        if self.country_id.rs_form30_code == '268' and self.identification and not re.fullmatch(r'\d{9}|\d{11}', self.identification):
            problems.append(self.env._("a Georgian ID number must have 9 or 11 digits"))
        if self.date and not date_from <= self.date <= date_to:
            problems.append(self.env._("date outside the declaration month"))
        if float_compare(self.amount, 0.0, precision_rounding=0.01) <= 0:
            problems.append(self.env._("amount must be positive"))
        problems += self._matrix_problems(allowed, period)
        if not problems:
            return []
        label = self._label()
        return [f"{label}: {problem}" for problem in problems]

    def _export_values(self):
        """The 14 cells of one annex row, in portal column order."""
        self.ensure_one()
        return [self.identification or '', self.first_name or '', self.last_name or '', self.address or '', self.country_id.rs_form30_code or '',
            self.category_id.code or '', self.income_type_id.code or '', _number(self.amount), _number(self.other_relief),
            self.date.strftime('%d.%m.%Y') if self.date else '', _number(self.rate), _number(self.international_agreement_exempt_tax),
            _number(self.foreign_tax_credit), '1' if self.from_treasury else '']
