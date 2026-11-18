from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_compare

from .gec_vat_declaration import GEORGIA, check_earlier_months_filed, list_action, name_list, portal_vat, round_2

RC_TAX_XMLID = 'ge_tax_p_rc_18_nonvatreg'
RC_SERVICE_TAX_XMLID = 'ge_rcvat_18_ser'
EXCLUDED_TAX_CATEGORIES = ('E', 'Z', 'O')
PARTS = ('services', 'goods')
FOREIGN_VENDOR = Domain('commercial_partner_id.country_id', 'any', [('code', '!=', GEORGIA)])
FOREIGN_LINE = Domain('move_id', 'any', FOREIGN_VENDOR)
SERVICE_LINE = Domain('product_id.type', '=', 'service')
BILL_LINE = Domain([('move_id.move_type', '=', 'in_invoice'), ('display_type', '=', 'product')])
IN_SCOPE = Domain('tax_ids', 'not any', [('ubl_cii_tax_category_code', 'in', EXCLUDED_TAX_CATEGORIES)])
QUALIFYING = BILL_LINE & FOREIGN_LINE & SERVICE_LINE & IN_SCOPE & Domain('balance', '>', 0)


class GecVatRcDeclaration(models.Model):
    _name = 'gec.vat.rc.declaration'
    _description = 'Reverse-charge VAT Calculation'
    _order = 'date_from desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict', default=lambda self: self.env.company)
    date_from = fields.Date(string='Month', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1) - relativedelta(months=1))
    date_to = fields.Date(compute='_compute_date_to', store=True)
    decl_type = fields.Selection([('primary', 'Primary'), ('adjusted', 'Adjusted')], string='Type', compute='_compute_decl_type', store=True,
        readonly=False, precompute=True, required=True, copy=False)
    portal_number = fields.Char(string='Portal Number', copy=False, help="The calculation number the rs.ge portal gave.")
    state = fields.Selection([('draft', 'Draft'), ('filed', 'Filed')], required=True, default='draft', copy=False)
    generation_warnings = fields.Text(readonly=True, copy=False)
    line_ids = fields.One2many('gec.vat.rc.line', 'declaration_id', copy=False)
    services_line_ids = fields.One2many('gec.vat.rc.line', 'declaration_id', domain=[('part', '=', 'services')], copy=False)
    goods_line_ids = fields.One2many('gec.vat.rc.line', 'declaration_id', domain=[('part', '=', 'goods')], copy=False)
    services_vat_before = fields.Float(string='Services VAT Before Correction', copy=False)
    services_vat_after = fields.Float(string='Services VAT After Correction', copy=False)
    services_vat_before_proposed = fields.Float(copy=False, help="What Generate last proposed; the value follows only while it is unchanged.")
    services_vat_after_proposed = fields.Float(copy=False, help="What Generate last proposed; the value follows only while it is unchanged.")
    goods_vat_before = fields.Float(string='Goods VAT Before Correction', copy=False)
    goods_vat_after = fields.Float(string='Goods VAT After Correction', copy=False)
    services_amount_total = fields.Float(string='Services Amount Total', compute='_compute_vat_rows')
    services_vat_total = fields.Float(string='Services VAT Total', compute='_compute_vat_rows')
    services_vat_increase = fields.Float(string='Services VAT Increase', compute='_compute_vat_rows')
    services_vat_decrease = fields.Float(string='Services VAT Decrease', compute='_compute_vat_rows')
    services_vat_payable = fields.Float(string='Services VAT Payable', compute='_compute_vat_rows')
    services_vat_refund = fields.Float(string='Services VAT Refund', compute='_compute_vat_rows')
    goods_amount_total = fields.Float(string='Goods Amount Total', compute='_compute_vat_rows')
    goods_vat_total = fields.Float(string='Goods VAT Total', compute='_compute_vat_rows')
    goods_vat_increase = fields.Float(string='Goods VAT Increase', compute='_compute_vat_rows')
    goods_vat_decrease = fields.Float(string='Goods VAT Decrease', compute='_compute_vat_rows')
    goods_vat_payable = fields.Float(string='Goods VAT Payable', compute='_compute_vat_rows')
    goods_vat_refund = fields.Float(string='Goods VAT Refund', compute='_compute_vat_rows')
    vat_accrued = fields.Float(string='VAT Accrued', compute='_compute_vat_rows')
    vat_reduced = fields.Float(string='VAT Reduced', compute='_compute_vat_rows')

    @api.depends('company_id.name', 'date_from')
    def _compute_name(self):
        for declaration in self:
            month = declaration.date_from.strftime('%Y/%m') if declaration.date_from else ''
            declaration.name = f"უკუდაბეგვრა {month} {declaration.company_id.name or ''}".strip()

    @api.depends('company_id', 'date_from')
    def _compute_decl_type(self):
        """A calculation of a month that already has a filed one is an adjusted one."""
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

    @api.depends('services_line_ids.amount', 'services_line_ids.vat', 'goods_line_ids.amount', 'goods_line_ids.vat', 'services_vat_before',
        'services_vat_after', 'goods_vat_before', 'goods_vat_after')
    def _compute_vat_rows(self):
        """Rows 3 and 6-9 of Part II and Part IV by the portal formulas; a negative typed VAT counts as 0."""
        for declaration in self:
            accrued = reduced = 0.0
            for part in PARTS:
                lines = declaration[f'{part}_line_ids']
                before = round_2(max(declaration[f'{part}_vat_before'], 0.0))
                after = round_2(max(declaration[f'{part}_vat_after'], 0.0))
                total = round_2(sum(lines.mapped('vat')))
                increase = round_2(max(after - before, 0.0))
                decrease = round_2(max(before - after, 0.0))
                if decrease > total:
                    payable, refund = 0.0, round_2(decrease - total)
                else:
                    payable, refund = round_2(total + increase - decrease), 0.0
                declaration[f'{part}_amount_total'] = round_2(sum(lines.mapped('amount')))
                declaration[f'{part}_vat_total'] = total
                declaration[f'{part}_vat_increase'] = increase
                declaration[f'{part}_vat_decrease'] = decrease
                declaration[f'{part}_vat_payable'] = payable
                declaration[f'{part}_vat_refund'] = refund
                accrued += payable
                reduced += refund
            declaration.vat_accrued = round_2(accrued)
            declaration.vat_reduced = round_2(reduced)

    @api.constrains('date_from')
    def _check_date_from(self):
        for declaration in self:
            if declaration.date_from and declaration.date_from.day != 1:
                raise ValidationError(self.env._("The declaration month must start on the first day of the month."))

    @api.model_create_multi
    def create(self, vals_list):
        filed = [vals.get('state') == 'filed' for vals in vals_list]
        declarations = super().create([{**vals, 'state': 'draft'} if is_filed else vals for vals, is_filed in zip(vals_list, filed)])
        declarations.browse([declaration.id for declaration, is_filed in zip(declarations, filed) if is_filed]).write({'state': 'filed'})
        return declarations

    def write(self, vals):
        to_file = self.filtered(lambda declaration: declaration.state != 'filed') if vals.get('state') == 'filed' else self.browse()
        if set(vals) - {'state', 'portal_number'}:
            self._check_draft()
        if 'company_id' in vals or 'date_from' in vals:
            for declaration in self:
                company_changed = 'company_id' in vals and declaration.company_id.id != vals['company_id']
                month_changed = 'date_from' in vals and declaration.date_from != fields.Date.to_date(vals['date_from'])
                if (company_changed or month_changed) and declaration.line_ids:
                    raise UserError(self.env._("You cannot change the company or the month of a "
                        "calculation that has rows. Create a new calculation."))
        result = super().write(vals)
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
        """Rebuild the Part I rows linked to Odoo bills, rows 4/5 of Part II when this month has a correction, and the
        warnings; typed rows are kept."""
        self.check_access('write')
        rows = []
        for declaration in self:
            if declaration.state != 'draft':
                raise UserError(self.env._("Reset the declaration to draft before regenerating it."))
            lines, left_out = declaration._gec_rc_part1_lines()
            dropped, vat45, warnings, _lines = declaration._gec_rc_corrections(lines.move_id)
            declared = lines.filtered(lambda line: line.move_id not in dropped)
            rows += [{
                'declaration_id': declaration.id,
                'part': 'services',
                'move_id': line.move_id.id,
                'partner_name': line.move_id.commercial_partner_id.name,
                'description': line.gec_rc_service or line.product_id.name,
                'date': line.date,
                'amount': round_2(line.balance),
            } for line in declared]
            warnings = declaration._gec_rc_warnings(left_out, declared) + warnings
            declaration.write({**vat45, 'generation_warnings': '\n'.join(warnings) or False})
        self.services_line_ids.filtered('move_id').unlink()
        self.env['gec.vat.rc.line'].create(rows)
        return True

    def action_mark_filed(self):
        """Lock the calculation once it is filed on the portal."""
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

    def action_gec_open_before(self):
        self.ensure_one()
        self.check_access('read')
        lines = self._gec_rc_corrections(self._gec_rc_part1_lines()[0].move_id)[3]
        return list_action(lines[0], self.env._("Lines of the corrected bills"))

    def action_gec_open_after(self):
        self.ensure_one()
        self.check_access('read')
        lines = self._gec_rc_corrections(self._gec_rc_part1_lines()[0].move_id)[3]
        return list_action(lines[1], self.env._("Lines of the replacement bills"))

    def _gec_rc_tax(self, *xmlids):
        self.ensure_one()
        template = self.env['account.chart.template'].with_company(self.company_id)
        return self.env['account.tax'].union(template.ref(xmlid, raise_if_not_found=False) or self.env['account.tax'] for xmlid in xmlids)

    def _gec_rc_part1_lines(self):
        """The qualifying service lines of the month and the "BILL (reason)" items of the lines left out. Sudo: company
        rules hide the bills of same-VAT branches that are not ticked in the company switcher."""
        Line = self.env['account.move.line'].sudo()
        company = Domain('company_id', 'in', self.company_id._gec_vat_companies().ids)
        month = Domain([('parent_state', '=', 'posted'), ('date', '>=', self.date_from), ('date', '<=', self.date_to)])
        rc_taxes = self._gec_rc_tax(RC_TAX_XMLID, RC_SERVICE_TAX_XMLID)
        no_country = SERVICE_LINE & Domain('move_id.commercial_partner_id.country_id', '=', False)
        not_service = Domain([('tax_ids', 'in', rc_taxes.ids), ('product_id', 'any', [('type', '!=', 'service')])])
        reasons = {
            self.env._("vendor has no country"): no_country,
            self.env._("no product"): FOREIGN_LINE & Domain('product_id', '=', False),
            self.env._("product is not a service"): FOREIGN_LINE & not_service,
            self.env._("zero or negative amount"): FOREIGN_LINE & SERVICE_LINE & Domain('balance', '<=', 0),
        }
        bill_lines = BILL_LINE & company & month
        left_out = set()
        for reason, domain in reasons.items():
            left_out.update(f"{line.move_id.name} ({reason})" for line in Line.search(bill_lines & domain))
        return Line.search(QUALIFYING & company & month, order='date, id'), sorted(left_out)

    def _gec_rc_corrections(self, bills):
        """Credit notes and bills made together (Reverse and Create Invoice) form a correction group: the credit notes'
        originals are corrected, the new bills replace them; only posted moves count. Returns (bills leaving Part I,
        rows 4/5 values, warnings, (row 4 lines, row 5 lines)). Sudo: company rules hide unticked same-VAT branches."""
        Line, Move = self.env['account.move.line'].sudo(), self.env['account.move'].sudo()
        month = Domain([('date', '>=', self.date_from), ('date', '<=', self.date_to)])
        base = Domain([('company_id', 'in', self.company_id._gec_vat_companies().ids), ('state', '=', 'posted')])
        dates = bills.mapped('create_date')
        seeds = month | Domain('reversed_entry_id', 'in', bills.ids) | Domain('create_date', 'in', dates)
        credit_notes = Move.search(base & FOREIGN_VENDOR & Domain('move_type', '=', 'in_refund') & seeds)
        linked = credit_notes.filtered('reversed_entry_id')
        new_bills = Move.search(base & Domain([('move_type', '=', 'in_invoice'), ('create_date', 'in', linked.mapped('create_date'))]))

        def batch(move):
            return move.create_date, move.commercial_partner_id

        corrected = replacements = month_corrected = month_replacements = Move
        new_by_batch = new_bills.grouped(batch)
        for key, group in linked.grouped(batch).items():
            new = new_by_batch.get(key, Move) - group.reversed_entry_id
            if new:
                corrected |= group.reversed_entry_id
                replacements |= new
                if group.filtered_domain(month):
                    month_corrected |= group.reversed_entry_id
                    month_replacements |= new

        warnings, before, after = [], 0.0, 0.0
        before_lines = after_lines = Line
        if month_corrected:
            kept = month_replacements - (self._gec_rc_reversed_in_full(month_replacements) - corrected)
            lines = Line.search(QUALIFYING & Domain([('parent_state', '!=', 'cancel'), ('move_id', 'in', (month_corrected | kept).ids)]))
            if lines:
                sides = (month_corrected - kept, kept - month_corrected)
                before_lines, after_lines = (lines.filtered(lambda line: line.move_id in side) for side in sides)
                before, after = (
                    round_2(sum(portal_vat(round_2(line.balance)) for line in side_lines))
                    for side_lines in (before_lines, after_lines))
                warnings.append(self.env._("Part II rows 4/5 were filled from the corrections of this month: %(names)s.",
                    names=name_list(self.env, sorted(month_corrected.mapped('name')))))
        vat45 = {}
        for row, field, proposal in (('4', 'services_vat_before', before), ('5', 'services_vat_after', after)):
            if float_compare(self[field], self[f'{field}_proposed'], precision_rounding=0.01) == 0:
                vat45[field] = proposal
            elif float_compare(self[field], proposal, precision_rounding=0.01) != 0:
                warnings.append(self.env._("Part II row %(row)s keeps the typed %(typed).2f; Odoo calculates %(odoo).2f from this month's "
                    "corrections.", row=row, typed=self[field], odoo=proposal))
            vat45[f'{field}_proposed'] = proposal
        month_notes = credit_notes.filtered_domain(month)
        warnings += self._gec_rc_credit_note_warnings(month_notes, corrected)
        dropped = replacements | (self._gec_rc_reversed_in_full(bills) - corrected)
        return dropped, vat45, warnings, (before_lines, after_lines)

    def _gec_rc_reversed_in_full(self, bills):
        """The bills whose posted credit notes cover their total."""
        def covered(bill):
            posted = bill.reversal_move_ids.filtered(lambda move: move.state == 'posted')
            total = sum(posted.mapped('amount_total'))
            return bool(posted) and bill.currency_id.compare_amounts(total, bill.amount_total) >= 0

        return bills.filtered(covered)

    def _gec_rc_credit_note_warnings(self, notes, corrected):
        """Credit notes of the month that reverse only part of a bill, or a whole bill of an earlier month. Sudo: as in
        _gec_rc_corrections."""
        Line = self.env['account.move.line'].sudo()
        cancelled = self._gec_rc_reversed_in_full(notes.reversed_entry_id)
        targets = notes.mapped(lambda note: note.reversed_entry_id or note)
        service_lines = FOREIGN_LINE & SERVICE_LINE & IN_SCOPE & Domain('move_id', 'in', targets.ids)
        with_service = Line.search(service_lines).move_id
        partial = notes.filtered(lambda note: note.reversed_entry_id not in cancelled and (note.reversed_entry_id or note) in with_service)
        warnings = []
        if partial:
            warnings.append(self.env._("Credit notes of foreign vendors that do not reverse a whole bill, so Part I may be too high: %(names)s.",
                names=name_list(self.env, sorted(partial.mapped('name')))))
        for bill in cancelled - corrected:
            if bill.date < self.date_from and bill in with_service:
                warnings.append(self.env._("Bill %(name)s of %(month)s was cancelled: file an adjusted calculation for %(month)s.",
                    name=bill.display_name, month=bill.date.strftime('%m/%Y')))
        return warnings

    def _gec_rc_warnings(self, left_out, lines):
        rc_tax = self._gec_rc_tax(RC_TAX_XMLID)
        warnings = []
        if not rc_tax:
            warnings.append(self.env._("The tax Reverse Charge 18% Non-Deductible is missing: update gec_localization."))
        if self.company_id.partner_id.gec_vat_payer:
            warnings.append(self.env._("This company is a VAT payer: reverse charge belongs "
                "to its monthly VAT declaration, not to this calculation."))
        branch_warning = self.company_id._gec_vat_branch_warning()
        if branch_warning:
            warnings.append(branch_warning)
        others = self.search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '=', self.date_from),
            ('decl_type', '=', self.decl_type),
            ('id', '!=', self.id),
        ])
        if others:
            warnings.append(self.env._("Another calculation exists for this company, month and type: %(names)s.",
                names=', '.join(others.mapped('name'))))
        if left_out:
            warnings.append(self.env._("Left out of Part I: %(items)s.", items=name_list(self.env, left_out)))
        rc_taxes = self._gec_rc_tax(RC_TAX_XMLID, RC_SERVICE_TAX_XMLID)
        untaxed = lines.filtered(lambda line: not line.tax_ids & rc_taxes).move_id
        if rc_tax and untaxed:
            warnings.append(self.env._("%(bills)s are declared in Part I, but their lines have no reverse-charge tax, so Odoo books no VAT for "
                "them: reset them to draft and add the tax %(tax)s to their lines.", bills=name_list(self.env, untaxed.mapped('name')),
                tax=rc_tax.name))
        return warnings


class GecVatRcLine(models.Model):
    _name = 'gec.vat.rc.line'
    _inherit = 'gec.vat.declaration.row'
    _description = 'Reverse-charge VAT Calculation Row'
    _order = 'declaration_id, id'

    declaration_id = fields.Many2one('gec.vat.rc.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    part = fields.Selection([('services', 'Services'), ('goods', 'Goods')], required=True, default='services')
    move_id = fields.Many2one('account.move', string='Odoo Bill', readonly=True, ondelete='cascade', index=True,
        help="Set on rows built by Generate; a row without it was typed.")
    partner_name = fields.Char()
    description = fields.Char()
    date = fields.Date()
    amount = fields.Float()
    vat = fields.Float(string='VAT', compute='_compute_vat', store=True)

    @api.constrains('amount')
    def _check_amount(self):
        if any(line.amount < 0 for line in self):
            raise ValidationError(self.env._("A row amount cannot be negative: enter corrections in Part II or IV rows 4 and 5."))

    @api.depends('amount')
    def _compute_vat(self):
        """Every row carries 18% of its amount, as the portal locks it."""
        for line in self:
            line.vat = portal_vat(line.amount)
