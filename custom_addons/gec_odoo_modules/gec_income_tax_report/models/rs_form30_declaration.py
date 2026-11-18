import re
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import Command, api, fields, models
from odoo.exceptions import LockError, UserError, ValidationError
from odoo.tools import BinaryBytes, float_compare, float_is_zero

from .rs_form30_warning import ISSUE_RANK, WARNING_PATTERNS, _localize_warning

SS_NS = 'urn:schemas-microsoft-com:office:spreadsheet'
SS = '{%s}' % SS_NS
NSMAP = {
    None: SS_NS,
    'o': 'urn:schemas-microsoft-com:office:office',
    'x': 'urn:schemas-microsoft-com:office:excel',
    'ss': SS_NS,
    'html': 'http://www.w3.org/TR/REC-html40',
}
AUTONOMOUS_REPUBLICS = [('adjara', 'Adjara A.R.'), ('abkhazia', 'Abkhazia A.R.')]
USAGE_LABELS = {'salary': 'payslips', 'entry': 'journal entries', 'bill': 'vendor bills'}


def _number(value):
    return ('%.2f' % (value or 0.0)).rstrip('0').rstrip('.') or '0'


def _refuse_in_file_rows(rows):
    if rows.env.context.get('rs_form30_export'):
        return
    locked = rows.filtered(lambda row: row.in_file and row.declaration_id.state == 'exported')[:1]
    if locked:
        name = f"{locked.first_name or ''} {locked.last_name or ''}".strip() or locked.identification or str(locked.id)
        raise UserError(rows.env._("%(row)s is in the exported file of %(declaration)s: reset the declaration to draft first.", row=name,
            declaration=locked.declaration_id.display_name))


def _refuse_exported_rows(rows):
    if rows.env.context.get('rs_form30_export'):
        return
    locked = rows.filtered(lambda row: row.declaration_id.state == 'exported')[:1]
    if locked:
        raise UserError(rows.env._("%s is exported: reset it to draft before changing its rows.", locked.declaration_id.display_name))


class RsForm30Declaration(models.Model):
    _name = 'rs.form30.declaration'
    _inherit = ['mail.thread']
    _description = 'rs.ge Form 30 Monthly Withholding Declaration'
    _order = 'date_from desc, id desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict', default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date(string='Month', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1) - relativedelta(months=1))
    date_to = fields.Date(compute='_compute_period', store=True)
    period = fields.Integer(compute='_compute_period', store=True, help="YYYYMM, used for classifier validity")
    state = fields.Selection([('draft', 'Draft'), ('exported', 'Exported')], required=True, default='draft', copy=False, tracking=True)
    line_ids = fields.One2many('rs.form30.line', 'declaration_id', copy=False)
    export_warned_rows = fields.Boolean(string='Export rows with warnings', copy=False,
        help="Rows with a warning are left out of the files and the main part until you tick this. Rows with a blocker are never exported; notes and "
        "manual rows always are.")
    line_count = fields.Integer(compute='_compute_totals')
    warning_count = fields.Integer(compute='_compute_totals')
    blocker_count = fields.Integer(compute='_compute_totals')
    file_line_count = fields.Integer(compute='_compute_totals')
    left_out_count = fields.Integer(compute='_compute_totals')
    left_out_service_count = fields.Integer(compute='_compute_totals')
    unpaid_count = fields.Integer(compute='_compute_totals')
    total_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    total_tax = fields.Monetary(string='Total Withheld Tax', compute='_compute_totals', currency_field='currency_id')
    total_pension = fields.Monetary(string='Total Pension 2%', compute='_compute_totals', currency_field='currency_id')
    car_line_ids = fields.One2many('rs.form30.car.line', 'declaration_id', copy=False)
    export_file = fields.Binary(string='Annex A File', readonly=True, copy=False)
    export_filename = fields.Char(readonly=True, copy=False)
    service_line_ids = fields.One2many('rs.form30.service.line', 'declaration_id', copy=False)
    summary_line_ids = fields.One2many('rs.form30.summary.line', 'declaration_id', copy=False)
    export_file_d = fields.Binary(string='Annex D File', readonly=True, copy=False)
    export_filename_d = fields.Char(readonly=True, copy=False)
    export_file_e = fields.Binary(string='Annex E File', readonly=True, copy=False)
    export_filename_e = fields.Char(readonly=True, copy=False)
    unpaid_move_ids = fields.Many2many('account.move', 'rs_form30_declaration_unpaid_move_rel', 'declaration_id', 'move_id', string="Unpaid Entries",
        readonly=True, copy=False, check_company=True,
        help="Journal entries with a Withholding Tax and payslip entries, dated up to the end of the month, whose recipient had no payment or bank "
        "transaction by then. Form 30 declares them in the month the recipient is paid.")
    not_payable_move_ids = fields.Many2many('account.move', 'rs_form30_declaration_not_payable_move_rel', 'declaration_id', 'move_id',
        string="Entries Without a Payable Recipient", readonly=True, copy=False, check_company=True,
        help="Entries with a Withholding Tax dated in the month whose recipient is on an account that is not reconcilable, or that have no recipient "
        "line. Form 30 cannot follow their payment: declare them by hand.")
    missing_tax_move_ids = fields.Many2many('account.move', 'rs_form30_declaration_missing_move_rel', 'declaration_id', 'move_id',
        string="Entries Missing a Withholding Tax", readonly=True, copy=False, check_company=True,
        help="Entries that credit a withholding-tax account without a Withholding Tax, dated in the last 12 months. Form 30 does not declare them "
        "until the tax is set.")
    generation_warnings = fields.Text(string="Generation Warnings", readonly=True, copy=False)
    generation_warnings_display = fields.Text(compute='_compute_generation_warnings_display')
    has_in_file = fields.Boolean(compute='_compute_has_in_file')

    _company_month_uniq = models.Constraint('UNIQUE(company_id, date_from)', 'One declaration per company and month.')

    @api.depends('company_id.name', 'date_from')
    def _compute_name(self):
        for declaration in self:
            month = declaration.date_from.strftime('%Y/%m') if declaration.date_from else ''
            declaration.name = f"Form 30 {month} {declaration.company_id.name or ''}".strip()

    @api.depends('date_from')
    def _compute_period(self):
        for declaration in self:
            start = declaration.date_from
            declaration.date_to = start + relativedelta(months=1, days=-1) if start else False
            declaration.period = start.year * 100 + start.month if start else 0

    @api.depends('state', 'export_warned_rows', 'unpaid_move_ids', 'line_ids.amount', 'line_ids.tax_amount', 'line_ids.pension_amount',
        'line_ids.issue_level', 'line_ids.in_file', 'service_line_ids.issue_level', 'service_line_ids.in_file')
    def _compute_totals(self):
        for declaration in self:
            lines = declaration.line_ids
            file_lines = declaration._rs_form30_file_lines()
            file_services = declaration._rs_form30_file_service_lines()
            file_count = len(file_lines) + len(file_services)
            declaration.line_count = len(lines)
            declaration.warning_count = len(lines.filtered(lambda line: line.issue_level == 'warning'))
            declaration.blocker_count = len(lines.filtered(lambda line: line.issue_level == 'blocker'))
            declaration.file_line_count = file_count
            declaration.left_out_count = len(lines) - len(file_lines)
            declaration.left_out_service_count = len(declaration.service_line_ids) - len(file_services)
            declaration.unpaid_count = len(declaration.unpaid_move_ids)
            declaration.total_amount = sum(file_lines.mapped('amount'))
            declaration.total_tax = sum(file_lines.mapped('tax_amount'))
            declaration.total_pension = sum(file_lines.mapped('pension_amount'))

    @api.depends('line_ids.in_file', 'service_line_ids.in_file')
    def _compute_has_in_file(self):
        for declaration in self:
            declaration.has_in_file = bool(declaration.line_ids.filtered('in_file') or declaration.service_line_ids.filtered('in_file'))

    @api.depends('generation_warnings')
    @api.depends_context('lang')
    def _compute_generation_warnings_display(self):
        for declaration in self:
            declaration.generation_warnings_display = '\n'.join(
                _localize_warning(declaration.env, text) for text in (declaration.generation_warnings or '').splitlines())

    @api.constrains('date_from')
    def _check_date_from(self):
        for declaration in self:
            if declaration.date_from and declaration.date_from.day != 1:
                raise ValidationError(self.env._("The declaration month must start on the first day of the month."))
        self.line_ids._check_matrix()

    @api.model_create_multi
    def create(self, vals_list):
        declarations = super().create(vals_list)
        for declaration in declarations:
            declaration._sync_summary_lines()
        return declarations

    def write(self, vals):
        if 'company_id' in vals and any(declaration.company_id.id != vals['company_id'] and declaration.line_ids for declaration in self):
            raise UserError(self.env._("You cannot change the company of a declaration that has lines. Create a declaration for the other company."))
        if vals.get('state') == 'draft' and not self.env.user.has_group('account.group_account_manager') and 'exported' in self.mapped('state'):
            raise UserError(self.env._("Only an Accounting Administrator can reset an exported declaration."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_file_rows(self):
        if any(declaration.line_ids.filtered('in_file') or declaration.service_line_ids.filtered('in_file') for declaration in self):
            raise UserError(self.env._("This declaration holds rows of an exported file; it cannot be deleted."))

    @api.model
    def _rs_form30_mark_filed_rows(self):
        """Called from data/rs_form30_data.xml; marks rows of exported declarations as In File."""
        for declaration in self.search([('state', '=', 'exported')]):
            if declaration.line_ids.filtered('in_file') or declaration.service_line_ids.filtered('in_file'):
                continue
            exported_on = declaration.write_date.date()
            for rows, file in ((declaration.line_ids, declaration.export_file), (declaration.service_line_ids, declaration.export_file_e)):
                if file:
                    rows.with_context(rs_form30_export=True).write({'in_file': True, 'exported_on': exported_on})

    def action_generate(self):
        """Manual and In File rows are kept; cash already in a file is not declared again."""
        for declaration in self:
            if declaration.state != 'draft':
                raise UserError(self.env._("Reset the declaration to draft before regenerating it."))
            declaration.line_ids.filtered(lambda line: line.source != 'manual' and not line.in_file).unlink()
            declaration.service_line_ids.filtered(lambda line: not line.in_file).unlink()
            declaration._rs_form30_mark_stale()
            declared = declaration._rs_form30_declared()
            entries = declaration._rs_form30_entry_vals(declared)
            bills = declaration._rs_form30_bill_vals(declared)
            salary = declaration._rs_form30_salary_data(declared)
            vals_list = declaration._rs_form30_drop_filed(
                salary['lines'] + declaration._payment_line_vals() + entries['lines'] + bills['lines'], declared)
            services = declaration._rs_form30_drop_filed(declaration._service_line_vals() + entries['services'] + bills['services'], declared)
            manual = {(line.partner_id.id,
                line.income_type_id.id) for line in declaration.line_ids.filtered(lambda line: line.source == 'manual' and line.partner_id)}
            for vals in vals_list:
                if (vals.get('partner_id'), vals.get('income_type_id')) in manual:
                    declaration._rs_form30_add_warning(
                        vals, "A manual row exists for this recipient and income type: check for a double declaration.")
            allowed = self.env['rs.form30.rate.rule']._allowed_rates(declaration.period)
            Line = self.env['rs.form30.line']
            for vals in vals_list:
                if Line.new(vals)._matrix_problems(allowed, declaration.period):
                    declaration._rs_form30_add_warning(vals, "The rs.ge classifier does not allow this category, income type and rate for the month.")
            declaration.write({
                'line_ids': [Command.create(vals) for vals in vals_list],
                'service_line_ids': [Command.create(vals) for vals in services],
                'unpaid_move_ids': [Command.set((entries['unpaid'] | salary['unpaid']).ids)],
                'not_payable_move_ids': [Command.set(entries['not_payable'].ids)],
                'missing_tax_move_ids': [Command.set(entries['missing_tax'].ids)],
                'generation_warnings': '\n'.join(dict.fromkeys(salary['warnings'] + entries['warnings'] + declared['warnings'])) or False,
            })
            declaration._sync_summary_lines()
        return True

    def _rs_form30_declared(self):
        """Return what In File rows declare (documents, sources, payslip_filed, warnings); own rows win."""
        self.ensure_one()
        domain = [('company_id', '=', self.company_id.id), ('in_file', '=', True)]
        rows = [*self.env['rs.form30.line'].search(domain), *self.env['rs.form30.service.line'].search(domain)]
        documents, sources, payslip_filed = {}, {}, defaultdict(lambda: [0.0, 0.0, 0.0])
        for row in sorted(rows, key=lambda row: row.declaration_id == self):
            payslip = getattr(row, 'payslip_id', False)
            root = payslip._rs_form30_family_root() if payslip else payslip
            if payslip and row.declaration_id.date_from <= self.date_from:
                figures = (row.amount, row.tax_amount, row.pension_amount)
                payslip_filed[root.id] = [total + value for total, value in zip(payslip_filed[root.id], figures)]
            source = self._rs_form30_source(payslip, row.move_id, row.partner_id)
            keys = [(('payment', pid), source) for pid in row.settlement_payment_ids.ids]
            keys += [(('statement', sid), source) for sid in row.settlement_statement_line_ids.ids]
            keys += [(('offset', mid), source) for mid in row.settlement_move_ids.ids]
            if keys:
                documents.update(dict.fromkeys(keys, row.declaration_id))
                continue
            if payslip:
                sources[('payslip', root.id)] = row.declaration_id
                for item in payslip._rs_form30_net_lines()._rs_form30_cash_parts().values():
                    for part in item['cash']:
                        documents.update(dict.fromkeys(self._rs_form30_part_keys(part, source), row.declaration_id))
            elif row.withholding_line_id:
                sources[('withholding', row.withholding_line_id.id)] = row.declaration_id
        return {'documents': documents, 'sources': sources, 'payslip_filed': payslip_filed, 'warnings': []}

    def _rs_form30_declared_warning(self, label, declaration, paid_on):
        return "%s: already declared in %s, paid in %s: correct one of the declarations." % (
            label, declaration.date_from.strftime('%Y/%m'), paid_on.strftime('%Y/%m'))

    @api.model
    def _rs_form30_source(self, payslip=None, move=None, partner=None):
        """Return the source a document is declared for, so one payment settling two entries marks only one."""
        if payslip:
            return ('family', payslip._rs_form30_family_root().id)
        if move and partner:
            return ('entry' if move.move_type == 'entry' else 'bill', move.id, partner.commercial_partner_id.id)
        return False

    def _rs_form30_part_keys(self, part, source):
        """Return the declared['documents'] keys of a cash ``part`` for ``source``."""
        keys = [(('payment', pid), source) for pid in part['payment'].ids] + [(('statement', sid), source) for sid in part['statement_line'].ids]
        return keys + [(('offset', mid), source) for mid in part['offset'].ids]

    def _rs_form30_part_declaration(self, part, declared, source):
        """Return the declaration whose In File row already holds a document of cash ``part``, or empty."""
        keys = self._rs_form30_part_keys(part, source)
        return next((declared['documents'][key] for key in keys if key in declared['documents']), self.browse())

    def _rs_form30_drop_filed(self, vals_list, declared):
        self.ensure_one()
        kept = []
        for vals in vals_list:
            documents = [('payment', pid) for command in vals.get('settlement_payment_ids', []) for pid in command[2]]
            documents += [('statement', sid) for command in vals.get('settlement_statement_line_ids', []) for sid in command[2]]
            documents += [('offset', mid) for command in vals.get('settlement_move_ids', []) for mid in command[2]]
            if documents:
                source = self._rs_form30_source(self.env['hr.payslip'].browse(vals.get('payslip_id')),
                    self.env['account.move'].browse(vals.get('move_id')), self.env['res.partner'].browse(vals.get('partner_id')))
                keys = [(document, source) for document in documents]
                filed = [declared['documents'][key] for key in keys if key in declared['documents']]
            else:
                key = (('payslip', self.env['hr.payslip'].browse(vals['payslip_id'])._rs_form30_family_root().id)
                       if vals.get('payslip_id') else ('withholding', vals.get('withholding_line_id')))
                filed = [declared['sources'][key]] if key in declared['sources'] else []
            if self in filed:
                continue
            if filed:
                label = (f"{vals.get('first_name') or ''} {vals.get('last_name') or ''}".strip() or vals.get('identification') or '')
                declared['warnings'].append(self._rs_form30_declared_warning(label, filed[0], vals.get('date') or self.date_from))
                continue
            kept.append(vals)
        return kept

    def _rs_form30_mark_stale(self):
        """Block In File rows whose payment or source changed after export (so a re-export never repeats them): payment
        unpaid, source reversed, payslip not validated or paid, entry not posted. A bill counts a credit note only if
        dated after the first payment."""
        self.ensure_one()
        message = "Filed, but its payment or source changed after the export: check this row."
        for row in [*self.line_ids.filtered('in_file'), *self.service_line_ids.filtered('in_file')]:
            # sudo: the accountant may lack access to the payments, entries and payslips behind the row
            source = row.sudo()
            payslip = getattr(source, 'payslip_id', False)
            withheld = source.withholding_line_id.payment_id
            has_documents = source.settlement_payment_ids or source.settlement_statement_line_ids or source.settlement_move_ids
            origin = payslip._rs_form30_family().move_id if payslip and source.settlement_move_ids else source.move_id
            entry_row = (not payslip and not source.withholding_line_id and getattr(source, 'source', 'entry') in ('entry', 'bill'))
            if source.move_id.move_type in ('in_invoice', 'in_receipt'):
                reversed_after = bool(source.move_id.reversal_move_ids) and source.move_id._rs_form30_reversed_after_payment()
            else:
                reversed_after = any(reversal.state == 'posted' for reversal in source.move_id.reversal_move_ids)
            stale = (
                any(payment.state not in ('paid', 'reconciled') for payment in source.settlement_payment_ids)
                or any(move.state != 'posted' for move in source.settlement_move_ids)
                or source.settlement_move_ids - origin.line_ids.matched_debit_ids.debit_move_id.move_id
                or reversed_after
                or (payslip and payslip.state not in ('validated', 'paid'))
                or (withheld and withheld.state not in ('paid', 'reconciled'))
                or (payslip and not has_documents and payslip.state != 'paid'
                    and float_compare(payslip.net_wage, 0.0, precision_rounding=row.currency_id.rounding) > 0)
                or (entry_row and source.move_id.state != 'posted'))
            if stale and message not in (row.warning or ''):
                row.with_context(rs_form30_export=True).write({'warning': ' '.join(filter(None, [row.warning, message])), 'issue_level': 'blocker'})

    def action_export(self):
        try:
            self.lock_for_update()
        except LockError:
            raise UserError(self.env._("Another export of this declaration is running. Try again in a moment."))
        if any(declaration.state != 'draft' for declaration in self):
            raise UserError(self.env._("This declaration is already exported."))
        for declaration in self.with_context(rs_form30_export=True):
            if not (declaration.line_ids or declaration.car_line_ids or declaration.service_line_ids):
                raise UserError(self.env._("There is nothing to export."))
            declaration._rs_form30_mark_stale()
            lines = declaration._rs_form30_file_lines()
            services = declaration._rs_form30_file_service_lines()
            cars = declaration.car_line_ids
            if not (lines or services or cars):
                raise UserError(self.env._("Nothing selected for the file: every row has a blocker or a warning. Tick Export rows with warnings or "
                    "fix the rows."))
            declaration._sync_summary_lines()
            if lines:
                declaration._check_lines(lines)
            if cars:
                declaration._check_car_lines()
            if services:
                declaration._check_service_lines(services)
            declaration._rs_form30_export_exempt(lines)
            declaration.write({
                'state': 'exported',
                'export_file': BinaryBytes(declaration._build_xml(lines)) if lines else False,
                'export_filename': 'form30_a_%s.xml' % declaration.period if lines else False,
                'export_file_d': BinaryBytes(declaration._build_xml(cars)) if cars else False,
                'export_filename_d': 'form30_d_%s.xml' % declaration.period if cars else False,
                'export_file_e': BinaryBytes(declaration._build_xml(services)) if services else False,
                'export_filename_e': 'form30_e_%s.xml' % declaration.period if services else False,
            })
            today = fields.Date.context_today(declaration)
            for selected, rows in ((lines, declaration.line_ids), (services, declaration.service_line_ids)):
                selected.write({'in_file': True, 'exported_on': today})
                (rows - selected).write({'in_file': False, 'exported_on': False})
            declaration._store_explanation()
        return True

    def _rs_form30_export_exempt(self, selected):
        """Contacts are locked first so two exports cannot over-draw the same allowance."""
        self.ensure_one()
        self._rs_form30_release_exempt(self.line_ids - selected)
        todo = selected.filtered(lambda line: line.source != 'manual') - self.env['rs.form30.exempt.usage'].search(
            [('line_id', 'in', selected.ids)]).line_id
        partners = todo.partner_id.filtered(lambda partner: not float_is_zero(partner.rs_form30_exempt_limit, precision_rounding=0.01))
        if partners:
            try:
                partners.lock_for_update(allow_referencing=True)
            except LockError:
                raise UserError(self.env._("Another export is drawing the treaty allowance of %s. Try again in a moment.",
                    ', '.join(partners.mapped('display_name'))))
            # sudo: technical stamp; the accountant exporting may lack write access to contacts
            partners.sudo().write({'rs_form30_exempt_stamp': fields.Datetime.now()})
        todo._rs_form30_draw_exempt()

    def _rs_form30_release_exempt(self, rows):
        """Give back the treaty allowance drawn by ``rows`` and clear file column 12."""
        usages = self.env['rs.form30.exempt.usage'].search([('line_id', 'in', rows.ids)])
        usages.line_id.write({'international_agreement_exempt_tax': 0.0})
        usages.unlink()

    def action_draft(self):
        """Back to draft; In File marks stay, the allowance of rows not in file is released."""
        for declaration in self:
            declaration._rs_form30_release_exempt(declaration.line_ids.filtered(lambda line: not line.in_file))
        self.write({'state': 'draft'})
        return True

    def action_clear_in_file(self):
        """Generate keeps In File rows, so clear the marks to rebuild them."""
        if any(declaration.state != 'draft' for declaration in self):
            raise UserError(self.env._("Reset the declaration to draft before clearing the In File marks."))
        for rows in (self.line_ids, self.service_line_ids):
            rows.write({'in_file': False, 'exported_on': False})
        return True

    def action_add_manual_row(self):
        """Generate never touches manual rows."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(self.env._("Reset the declaration to draft before adding a manual row."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Add Manual Row"),
            'res_model': 'rs.form30.line',
            'views': [(self.env.ref('gec_income_tax_report.view_rs_form30_line_manual_form').id, 'form')],
            'target': 'new',
            'context': {'default_declaration_id': self.id, 'default_source': 'manual', 'dialog_size': 'large'},
        }

    @api.model
    def _rs_form30_issue_level(self, warnings):
        levels = [next((level for pattern, _source, level in WARNING_PATTERNS if pattern.fullmatch(text)), 'warning') for text in warnings]
        return max(levels, key=ISSUE_RANK.get) if levels else False

    def _rs_form30_file_rows(self, rows):
        self.ensure_one()
        if self.state == 'exported':
            return rows.filtered('in_file')
        left_out = ('blocker',) if self.export_warned_rows else ('blocker', 'warning')
        return rows.filtered(lambda row: row.issue_level not in left_out)

    def _rs_form30_file_lines(self):
        return self._rs_form30_file_rows(self.line_ids)

    def _rs_form30_file_service_lines(self):
        return self._rs_form30_file_rows(self.service_line_ids)

    def _rs_form30_recipient_vals(self, partner):
        Line = self.env['rs.form30.line']
        first_name, last_name = Line._split_name(partner.name, partner.is_company)
        return {
            'partner_id': partner.id,
            'identification': Line._clean_identification(partner.vat),
            'first_name': first_name,
            'last_name': last_name,
            'address': partner._display_address(without_name=True, separator=' '),
        }

    def _rs_form30_row_tax(self, booked, date):
        """Return the version of ``booked`` valid on ``date`` (``booked`` itself when none is) and its warnings."""
        version = booked._rs_form30_version_on(date)
        tax = version or booked
        warnings = []
        if not version:
            warnings.append("No version of %s is valid for Form 30 on the payment date." % booked.name)
        elif version != booked:
            warnings.append("Booked with an old tax version: this row uses %s, valid on the payment date." % version.name)
        if not tax.rs_form30_income_type_id:
            warnings.append("Tax %s has no Form 30 income type." % tax.name)
        return tax, warnings

    def _rs_form30_settlement_warnings(self, parts, other):
        warnings = []
        if any(not part['matched'] for part in parts):
            warnings.append("Payment not matched with a bank transaction yet: dated on the payment date.")
        if any(part['offset'] for part in parts):
            warnings.append("Settled by an offset entry: declare it in this month unless the advance was already taxed, "
                "and keep the signed offset act.")
        if any(part['kind'] == 'advance' for part in parts):
            warnings.append("Paid in advance, before the document: declared in the document's month unless the advance was already taxed.")
        if other:
            warnings.append("Partly settled without a payment (write-off or another entry): check the amount.")
        return warnings

    def _recipient_classification(self, partner, payment_date, *, salary=False, nationality=None, usage=None):
        """``usage`` is 'salary', 'entry' or 'bill'; a category not meant for it only adds a warning."""
        category = partner._rs_form30_category_on(payment_date)
        residency = partner.country_id or nationality or self.env['res.country']
        missing_category = not category and not partner.rs_form30_category_history_ids
        warnings = []
        if not category and not missing_category:
            warnings.append("No Form 30 category covers the payment date; update the partner's category history.")
        if salary:
            if missing_category:
                category = self.env.ref('gec_income_tax_report.category_4')
            if missing_category or not residency:
                warnings.append("Category/residency defaulted to 1.1/Georgia, confirm on the employee contact.")
            residency = residency or self.env.ref('base.ge')
        elif missing_category or not residency:
            warnings.append("Set the Form 30 category and residency on the partner.")
        if category and residency and category.display_code != '4':
            non_resident = category.display_code.startswith('3.')
            if non_resident == (residency.rs_form30_code == '268'):
                warnings.append("Residency and category disagree: non-resident categories (3.x) need a foreign country, resident ones Georgia.")
        if usage and category and not category[f'use_{usage}']:
            warnings.append("Category %s is not meant for %s (category guide)." % (category.display_code, USAGE_LABELS[usage]))
        return {'category_id': category.id, 'country_id': residency.id}, warnings

    def _rs_form30_month_share(self, cash, net, declared, label, source):
        """A month declares the share of ``net`` paid through it minus the share paid before it."""
        month, before = [], 0.0
        for part in cash:
            filed = self._rs_form30_part_declaration(part, declared, source)
            in_month = self.date_from <= part['date'] <= self.date_to
            if filed == self:
                before += part['amount']
            elif filed and in_month:
                declared['warnings'].append(self._rs_form30_declared_warning(label, filed, part['date']))
                before += part['amount']
            elif in_month:
                month.append(part)
            elif part['date'] < self.date_from:
                before += part['amount']
        through = before + sum(part['amount'] for part in month)
        return month, min(before / net, 1.0), min(through / net, 1.0)

    def _rs_form30_month_amounts(self, amounts, share_before, share_through):
        currency = self.currency_id
        return [currency.round(amount * share_through) - currency.round(amount * share_before) for amount in amounts]

    def _check_service_lines(self, lines=None):
        self.ensure_one()
        errors = []
        for line in self.service_line_ids if lines is None else lines:
            name = f"{line.first_name or ''} {line.last_name or ''}".strip() or line.identification
            missing = [label for field_name, label in zip(('identification', 'service_type_id', 'country_id'),
                (self.env._("ID number"), self.env._("service type"), self.env._("residency"))) if not line[field_name]]
            if missing:
                errors.append(self.env._("%(name)s: missing %(fields)s", name=name, fields=', '.join(missing)))
            elif not line.country_id.rs_form30_code:
                errors.append(self.env._("%(name)s: %(country)s has no rs.ge country code", name=name, country=line.country_id.name))
        if errors:
            raise UserError(self.env._("Fix these annex E rows before exporting:\n%s", '\n'.join(errors[:40])))

    def _check_lines(self, lines=None):
        self.ensure_one()
        allowed = self.env['rs.form30.rate.rule']._allowed_rates(self.period)
        errors = []
        for line in self.line_ids if lines is None else lines:
            errors.extend(line._validation_errors(allowed, self.period, self.date_from, self.date_to))
        if errors:
            raise UserError(self.env._("Fix these lines before exporting:\n%s", '\n'.join(errors[:40])))

    def _check_car_lines(self):
        self.ensure_one()
        errors = []
        for line in self.car_line_ids:
            missing = [label for field_name, label in zip(('license_plate', 'name', 'identification'),
                (self.env._("registration number"), self.env._("surname, name"), self.env._("personal number"))) if not line[field_name]]
            if missing:
                errors.append(self.env._("%(car)s: missing %(fields)s", car=line.license_plate or line.name or line.id, fields=', '.join(missing)))
            elif not re.fullmatch(r'\d{9}|\d{11}', line.identification):
                errors.append(self.env._("%s: a Georgian personal number must have 9 or 11 digits", line.license_plate or line.name))
        if errors:
            raise UserError(self.env._("Fix these annex D rows before exporting:\n%s", '\n'.join(errors[:40])))

    def _build_xml(self, lines):
        """Excel 2003 SpreadsheetML expected by the portal."""
        self.ensure_one()
        workbook = etree.Element(SS + 'Workbook', nsmap=NSMAP)
        style = etree.SubElement(etree.SubElement(workbook, SS + 'Styles'), SS + 'Style', {SS + 'ID': 's62'})
        etree.SubElement(style, SS + 'NumberFormat', {SS + 'Format': '@'})
        worksheet = etree.SubElement(workbook, SS + 'Worksheet', {SS + 'Name': 'data'})
        table = etree.SubElement(worksheet, SS + 'Table', {SS + 'StyleID': 's62'})
        for values in [lines._rs_form30_headers()] + [line._export_values() for line in lines]:
            row = etree.SubElement(table, SS + 'Row')
            for value in values:
                data = etree.SubElement(etree.SubElement(row, SS + 'Cell'), SS + 'Data', {SS + 'Type': 'String'})
                data.text = value or ' '
        body = etree.tostring(workbook, encoding='UTF-8', xml_declaration=False)
        return b'<?xml version="1.0"?>\n<?mso-application progid="Excel.Sheet"?>\n' + body
