# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from datetime import date
from lxml import etree

from dateutil.relativedelta import relativedelta
from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import BinaryBytes, format_date
from odoo.tools.misc import file_path
from odoo.addons.l10n_be_hr_payroll.models.utils import round_eurocent, to_eurocent


class L10n_Be273Xx(models.Model):
    _name = 'l10n_be.273_xx'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = '273.XX Sheets'
    _order = 'period'

    @api.model
    def default_get(self, fields):
        if self.env.company.country_id.code != "BE":
            raise UserError(self.env._('This feature seems to be as exclusive as Belgian chocolates. You must be logged in to a Belgian company to use it.'))
        return super().default_get(fields)

    def _get_default_company_id(self):
        company = self.env.company
        if company.parent_id:
            raise UserError(self.env._("273.XX reports can only be generated from a top-level company"))
        return company

    active = fields.Boolean(default=True)
    year = fields.Integer(required=True, compute='_compute_year_month', store=True, readonly=False, recursive=True)
    month = fields.Selection([
        ('1', 'January'),
        ('2', 'February'),
        ('3', 'March'),
        ('4', 'April'),
        ('5', 'May'),
        ('6', 'June'),
        ('7', 'July'),
        ('8', 'August'),
        ('9', 'September'),
        ('10', 'October'),
        ('11', 'November'),
        ('12', 'December'),
    ], required=True, compute='_compute_year_month', store=True, readonly=False, recursive=True)
    period = fields.Date('Period', compute='_compute_period', store=True)
    company_id = fields.Many2one('res.company', default=_get_default_company_id, required=True)
    branch_ids = fields.One2many('res.company', compute="_compute_branch_ids", compute_sudo=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], default='draft', tracking=True)
    line_ids = fields.One2many('l10n_be.273_xx.line', 'sheet_id', string='Declaration Lines')
    line_273S_ids = fields.One2many('l10n_be.273_xx.line', 'sheet_id', compute='_compute_report_line_ids', string='Intellectual Property Lines')
    line_273_part_ids = fields.One2many('l10n_be.273_xx.line', 'sheet_id', compute='_compute_report_line_ids', string='Employee Participation Lines')
    origin_id = fields.Many2one('l10n_be.273_xx', string='Original',
        domain="[('id', '!=', id), ('state', '=', 'done'), ('company_id', '=', company_id)]")
    pdf_273s_file = fields.Binary('273S PDF File')
    pdf_273s_filename = fields.Char('273S PDF Filename')
    pdf_273_part_file = fields.Binary('273 Part PDF File')
    pdf_273_part_filename = fields.Char('273 Part PDF Filename')
    xml_file = fields.Binary('XML File')
    xml_filename = fields.Char('XML Filename')
    xml_validation_state = fields.Selection([
        ('normal', 'N/A'),
        ('done', 'Valid'),
        ('invalid', 'Invalid'),
    ], default='normal', compute='_compute_validation_state', store=True)
    type = fields.Selection([
        ('original', 'Original'),
        ('correction', 'Correction'),
    ], default='original')
    belcotax_reference = fields.Char('Reference', tracking=True)
    is_correction_needed = fields.Boolean()

    @api.depends('line_ids', 'line_ids.report_type')
    def _compute_report_line_ids(self):
        for report in self:
            report.line_273S_ids = report.line_ids.filtered(lambda l: l.report_type == 'ip')
            report.line_273_part_ids = report.line_ids.filtered(lambda l: l.report_type == 'part')

    @api.depends('company_id')
    def _compute_branch_ids(self):
        report_companies = self.mapped('company_id')
        branches_by_root = self.env['res.company'].search([
            ('id', 'child_of', report_companies.ids),
        ]).grouped('root_id')

        for report in self:
            report.branch_ids = branches_by_root.get(report.company_id, report.company_id)

    @api.depends('period', 'type', 'origin_id')
    def _compute_display_name(self):
        for report in self:
            period_str = format_date(self.env, report.period, date_format="MMMM y", lang_code=self.env.user.lang)
            if report.type == 'correction' and report.origin_id:
                report.display_name = self.env._("Correction of %s", report.origin_id.display_name)
            else:
                report.display_name = self.env._("273.XX Sheets - %s", period_str)

    @api.depends('year', 'month')
    def _compute_period(self):
        for report in self:
            report.period = date(report.year, int(report.month), 1)

    @api.depends('xml_file')
    def _compute_validation_state(self):
        no_xml_file_reports = self.filtered(lambda report: not report.xml_file)
        no_xml_file_reports.update({
            'xml_validation_state': 'normal',
        })
        for report in self - no_xml_file_reports:
            report.xml_validation_state = 'invalid' if report._get_xml_validation_error() else 'done'

    def _get_xml_validation_error(self):
        """Return the reason why the XML file does not match the schema of the declaration, if any."""
        self.ensure_one()
        if not self.xml_file:
            return False
        xsd_schema_file_path = file_path('l10n_be_hr_payroll/data/withholdingTaxDeclarationOriginal_202012.xsd')
        schema = etree.XMLSchema(etree.parse(xsd_schema_file_path))
        try:
            schema.assertValid(etree.fromstring(self.xml_file.content))
        except etree.DocumentInvalid as err:
            return str(err)
        return False

    @api.depends('type', 'origin_id.year', 'origin_id.month')
    def _compute_year_month(self):
        for report in self:
            if report.type == 'correction' and report.origin_id:
                report.year = report.origin_id.year
                report.month = report.origin_id.month
            else:
                date = fields.Date.context_today(self) - relativedelta(months=1)
                report.month = str(date.month)
                report.year = date.year

    @api.constrains('type', 'origin_id')
    def _check_origin_id(self):
        for report in self:
            if report.type == 'correction' and (not report.origin_id or report.origin_id.state != 'done'):
                raise ValidationError(self.env._(
                    "The original report must be specified for a correction and be in the Done state."
                ))

    def action_populate(self):
        """
        Populate payslips for the report period.

        - Includes (validated/paid) payslips for the company from Jan 1st of the year to the report end date.
        - Excludes payslips already linked to other finalized reports (ready/done),except the current and origin reports.
        """
        self.ensure_one()
        payslips_ip = self._get_payslips('ip')
        payslips_part = self._get_payslips('part')
        if not payslips_ip and not payslips_part:
            raise UserError(self.env._("No unreported payslips were found for the selected period."))

        lines_to_create = []
        for slip in payslips_ip:
            lines_to_create.append(Command.create({
                'payslip_id': slip.id,
                'report_type': 'ip',
            }))

        line_values = payslips_part._get_line_values([
            'PROFITSHARINGHIGH', 'PROFITSHARINGHIGH.PP', 'PROFITSHARINGLOW', 'PROFITSHARINGLOW.PP'
        ], compute_sum=True, extra_domain=self._get_fiscal_line_domain())
        for slip in payslips_part:
            lines_to_create.append(Command.create({
                'payslip_id': slip.id,
                'report_type': 'part',
                'profit_sharing_15_gross': line_values['PROFITSHARINGHIGH'][slip.id]['total'],
                'profit_sharing_15_tax': - line_values['PROFITSHARINGHIGH.PP'][slip.id]['total'],
                'profit_sharing_7_gross': line_values['PROFITSHARINGLOW'][slip.id]['total'],
                'profit_sharing_7_tax': - line_values['PROFITSHARINGLOW.PP'][slip.id]['total'],
            }))

        self.write({
            'line_ids': [Command.clear()] + lines_to_create,
        })

    def _check_employees_niss(self):
        self.ensure_one()
        invalid_employees = self.line_ids.payslip_id.employee_id.filtered(lambda e: not e._is_niss_valid())
        if invalid_employees:
            raise UserError(self.env._('Invalid NISS number for those employees:\n %s', '\n'.join(invalid_employees.mapped('name'))))

    def action_generate(self):
        self.ensure_one()
        payslips = self.line_ids.payslip_id
        self._check_employees_niss()
        # Another report may have declared some payslips since this one was populated
        finalized_reports = self.search(self._get_other_finalized_reports_domain())
        declared_payslips = payslips.filtered(lambda p: p.l10n_be_273_line_ids.sheet_id & finalized_reports)
        if declared_payslips:
            raise UserError(self.env._(
                'Those payslips are already declared in another 273.XX report, populate this report again:\n %s',
                '\n'.join(declared_payslips.mapped('name'))))

        self._generate_xml()
        if self.xml_validation_state == 'invalid':
            # e.g. negative amounts, when the refunds of a declared month outweigh the income of the month
            raise UserError(self.env._(
                'The XML file of the 273.XX report does not match the schema of the declaration. '
                'Check that no amount is negative: the refunds of a declared month are declared with a correction of that month.\n\n'
                'Error: %(error)s', error=self._get_xml_validation_error()))
        self._generate_pdf()
        self.state = 'ready'

    def action_set_to_draft(self):
        self.ensure_one()
        if self.state != 'ready':
            raise UserError(self.env._('Only reports in "Ready" state can be set to draft.'))
        self._clear_files()
        self.state = 'draft'
        self.is_correction_needed = False

    def action_mark_as_done(self):
        self.ensure_one()
        if self.state != 'ready':
            raise UserError(self.env._('Only reports in "Ready" state can be marked as done.'))
        if not self.belcotax_reference:
            raise UserError(self.env._('The 273.XX sheet must have a Belcotax reference to be completed.'))
        self.state = 'done'

    def action_correct(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError(self.env._('Only reports in "Done" state can be corrected.'))
        if not self.belcotax_reference:
            raise UserError(self.env._('The 273.XX sheet must have a Belcotax reference to be corrected.'))
        self.is_correction_needed = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_be.273_xx',
            'view_mode': 'form',
            'context': {
                'default_year': self.year,
                'default_month': self.month,
                'default_company_id': self.company_id.id,
                'default_type': 'correction',
                'default_origin_id': self.id,
            }
        }

    def action_cancel(self):
        self.ensure_one()
        if bool(self.env['l10n_be.273_xx'].search_count([('origin_id', '=', self.id), ('state', '!=', 'cancelled')], limit=1)):
            raise UserError(self.env._('You cannot cancel a report that has already been corrected. Please cancel the correction report first.'))
        self._clear_files()
        self.write({
            'line_ids': [Command.clear()],
            'state': "cancelled"
        })

    def action_generate_xml_and_download_data(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_populate()
            self._check_employees_niss()
            self._generate_xml()
        return {
            'model': self._name,
            'id': self.id,
            'field': 'xml_file',
            'filename': self.xml_filename,
            'filename_field': 'xml_filename',
            'download': True,
        }

    def action_force_done(self):
        self.ensure_one()
        self.action_populate()
        self.state = 'done'

    def _get_salary_rule_codes_from_tag(self, tag):
        self.ensure_one()
        mapping = self.env['l10n.be.281.mapping']._search_for_tag('273S', tag, self.year)
        return mapping._get_codes()

    def _get_fiscal_line_domain(self):
        self.ensure_one()
        date_from, date_to = self._get_report_period()
        return self.env['hr.payslip']._l10n_be_get_fiscal_line_domain(date_from, date_to)

    def _get_rendering_data_273S(self):
        """ The 273S declares, per beneficiary, the gross income (col. b), the deductible costs
        (col. c: the lump-sum costs) and the taxable income (col. d) on which the withholding tax
        is computed. The taxable income is the withholding base of the payslips: the IP minus its
        personal social contributions minus the lump-sum costs, deducted according to the date of
        each payslip (see `hr.payslip._get_be_ip_deduction` and `_l10n_be_has_ip_flat_rate_costs`).
        """
        self.ensure_one()
        payslips = self.line_273S_ids.payslip_id

        gross_codes = self._get_salary_rule_codes_from_tag('273s_gross_income')
        withholding_codes = self._get_salary_rule_codes_from_tag('273s_withholding_tax')
        # The personal social contributions on the IP, deducted from the withholding base
        onss_codes = self.env['l10n.be.281.mapping']._get_codes_for_tag('273S', '273s_ip_onss', self.year)
        line_values = payslips._get_line_values(
            gross_codes + withholding_codes + onss_codes, compute_sum=True, extra_domain=self._get_fiscal_line_domain())
        year_ip_by_payslip = self._get_273S_previous_year_ip(payslips, gross_codes)

        mapped_ip = defaultdict(lambda: {'gross': 0.0, 'withholding': 0.0, 'onss': 0.0, 'costs': 0.0, 'taxable': 0.0})
        employee_by_beneficiary = {}
        for payslip in payslips.sudo():
            payslip_gross = sum(line_values[code][payslip.id]['total'] for code in gross_codes)
            payslip_withholding = sum(line_values[code][payslip.id]['total'] for code in withholding_codes)
            # Either side alone still keeps the beneficiary, or its amount has no line to sit under.
            if not (payslip_gross or payslip_withholding):
                continue
            payslip_onss = sum(line_values[code][payslip.id]['total'] for code in onss_codes)
            payslip_costs = 0.0
            if payslip_gross and payslip._l10n_be_has_ip_flat_rate_costs():
                # a refund (negative IP) cancels the costs of the refunded payslip: same period, so same IP paid
                # earlier in the year
                payslip_costs = payslip._get_be_ip_flat_rate_costs(None, None, {
                    'values': {'ip': abs(payslip_gross)},
                    'year_total': year_ip_by_payslip[payslip],
                })
                if payslip_gross < 0:
                    payslip_costs = -payslip_costs
            # One beneficiary per person: the same person can be employed by several companies of the report
            beneficiary = (payslip.employee_id.niss or '').replace('-', '').replace('.', '') or payslip.employee_id
            employee = employee_by_beneficiary.setdefault(beneficiary, payslip.employee_id)
            values = mapped_ip[employee]
            values['gross'] += payslip_gross
            values['withholding'] += payslip_withholding
            values['onss'] += payslip_onss
            values['costs'] += payslip_costs

        # The costs are rounded to the cent, so that the costs, the taxable amount and the IP ONSS add up to the
        # gross amount (declared to the cent)
        for values in mapped_ip.values():
            values['costs'] = round_eurocent(values['costs'])
            values['taxable'] = round_eurocent(values['gross'] - values['onss'] - values['costs'])

        return {
            'declaration': {
                'gross_amount': sum(values['gross'] for values in mapped_ip.values()),
                'deductable_costs':  {
                    'fixed': sum(values['costs'] for values in mapped_ip.values()),
                    'actual': 0,
                },
                'taxable_amount': sum(values['taxable'] for values in mapped_ip.values()),
                'rate': 15.0,
                'tax_amount': -sum(values['withholding'] for values in mapped_ip.values()),
            },
            'beneficiaries': [
                {
                    'employee': employee,
                    'identification': {
                        'nature': "Citizen",
                        'name': employee.legal_name,
                        'street': employee.private_street,
                        'city': employee.private_city,
                        'zip': employee.private_zip,
                        'country': employee.private_country_id.code,
                        'nationality': employee.country_id.code,
                        'identification': employee.niss.replace('-', '').replace('.', ''),
                    },
                    'gross_amount': values['gross'],
                    'deductable_costs': {
                        'fixed': values['costs'],
                        'actual': 0,
                    },
                    'taxable_amount': values['taxable'],
                    'tax_amount': values['withholding'],
                # Sorted by postal code, then by name (form 273 S, note 17)
                } for employee, values in sorted(
                    mapped_ip.items(), key=lambda item: (item[0].private_zip or '', item[0].legal_name or ''))],
        }

    def _get_273S_previous_year_ip(self, payslips, gross_codes):
        """ The IP paid earlier in the year, by payslip with lump-sum costs: these costs depend on the
        yearly IP (brackets), as when the payslip was computed.
        """
        year_ip_by_payslip = defaultdict(float)
        costs_payslips = payslips.sudo().filtered(lambda payslip: payslip._l10n_be_has_ip_flat_rate_costs())
        if not costs_payslips or not gross_codes:
            return year_ip_by_payslip
        years = {payslip.date_to.year for payslip in costs_payslips}
        lines_by_employee = defaultdict(list)
        for line in self.env['hr.payslip.line'].sudo().search_read([
            ('employee_id', 'in', costs_payslips.employee_id.ids),
            ('code', 'in', gross_codes),
            ('slip_id.state', 'in', ('validated', 'paid')),
            ('date_to', '>=', date(min(years), 1, 1)),
            ('date_to', '<=', date(max(years), 12, 31)),
        ], ['employee_id', 'date_to', 'slip_id', 'total']):
            lines_by_employee[line['employee_id'][0]].append(line)
        for payslip in costs_payslips:
            year_ip_by_payslip[payslip] = sum(
                line['total'] for line in lines_by_employee[payslip.employee_id.id]
                if line['date_to'].year == payslip.date_to.year
                and line['date_to'] < payslip.date_to
                and line['slip_id'][0] != payslip.id
            )
        return year_ip_by_payslip

    def _get_rendering_data_273_part(self):
        self.ensure_one()
        gross_15 = sum(self.line_273_part_ids.mapped('profit_sharing_15_gross'))
        tax_15 = sum(self.line_273_part_ids.mapped('profit_sharing_15_tax'))
        gross_7 = sum(self.line_273_part_ids.mapped('profit_sharing_7_gross'))
        tax_7 = sum(self.line_273_part_ids.mapped('profit_sharing_7_tax'))

        return {
            'declaration_15': {
                'gross_amount': gross_15,
                'tax_amount': tax_15,
            },
            'declaration_7': {
                'gross_amount': gross_7,
                'tax_amount': tax_7,
            },
            'incomes': [
                {
                    'taxable_amount': gross_15,
                    'rate': 15.0,
                    'tax_amount': tax_15,
                    'final_tax_amount': tax_15,
                },
                {
                    'taxable_amount': gross_7,
                    'rate': 7.0,
                    'tax_amount': tax_7,
                    'final_tax_amount': tax_7,
                },
            ],
            'tax_amount': tax_15 + tax_7,
        }

    def _get_rendering_data(self):
        self.ensure_one()
        data = {
            'company_info': {
                'identification': f"BE{self.company_id._get_payroll_config(self.period).l10n_be_company_number}",
                'name': self.company_id.name,
                'address': self.company_id.partner_id.contact_address,
                'phone': self.company_id.phone,
                'email': self.company_id.email,
            },
            # Attribution date of the declared income: the end of the declared month, which a
            # correction shares with its origin, whatever the day the files are generated.
            'period': self.period + relativedelta(day=31),
            'declaration_273S': self._get_rendering_data_273S(),
            'declaration_273_part': self._get_rendering_data_273_part(),
            'to_eurocent': lambda amount: str(to_eurocent(amount)),
            'to_monetary': lambda amount: '%.2f %s' % (amount, self.company_id.currency_id.symbol),
        }
        return data

    def _get_report_period(self):
        self.ensure_one()
        return date(self.year, 1, 1), self.period + relativedelta(day=31)

    def _get_ancestor_reports(self):
        self.ensure_one()
        ancestor_reports = self
        origin_report = self.origin_id
        while origin_report:
            ancestor_reports |= origin_report
            origin_report = origin_report.origin_id
        return ancestor_reports

    def _get_other_finalized_reports_domain(self):
        self.ensure_one()
        return Domain([
            ('id', 'not in', self._get_ancestor_reports().ids),
            ('year', '=', self.year),
            ('state', 'in', ['ready', 'done']),
            ('company_id', 'in', self.branch_ids.ids),
        ])

    def _get_payslips(self, report_type):
        self.ensure_one()
        date_from, date_to = self._get_report_period()
        finalized_reports = self._search(self._get_other_finalized_reports_domain())
        domain = Domain([
            ('state', 'in', ['validated', 'paid']),
            ('company_id', 'in', self.branch_ids.ids),
            '!', ('l10n_be_273_line_ids.sheet_id', 'in', finalized_reports),
        ]) & self.env['hr.payslip']._l10n_be_get_fiscal_period_domain(date_from, date_to)
        if report_type == 'ip':
            codes = self._get_salary_rule_codes_from_tag('273s_gross_income') + self._get_salary_rule_codes_from_tag('273s_withholding_tax')
            domain &= Domain([('line_ids.code', 'in', codes)])
        else:
            domain &= Domain([('line_ids.code', 'in', ['PROFITSHARINGHIGH', 'PROFITSHARINGLOW'])])
        return self.env['hr.payslip'].search(domain)

    def _generate_273S_pdf(self, data):
        self.ensure_one()
        report = self.env.ref('l10n_be_hr_payroll.action_report_ip_273S').sudo()
        export_273S_pdf, _ = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            report, res_ids=self.ids, data=data
        )
        self.pdf_273s_filename = '%s-273S_report.pdf' % (self.period.strftime('%B%Y'))
        self.pdf_273s_file = BinaryBytes(export_273S_pdf)

    def _generate_273_part_pdf(self, data):
        self.ensure_one()
        report = self.env.ref('l10n_be_hr_payroll.action_report_273_part').sudo()
        export_273_part_pdf, _ = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            report, res_ids=self.ids, data=data
        )
        self.pdf_273_part_filename = '%s-273_part_report.pdf' % (self.period.strftime('%B%Y'))
        self.pdf_273_part_file = BinaryBytes(export_273_part_pdf)

    def _generate_pdf(self):
        self.ensure_one()
        data = self._get_rendering_data()
        self._generate_273S_pdf(data)
        self._generate_273_part_pdf(data)

    def _generate_xml(self):
        self.ensure_one()
        qweb = self.env['ir.qweb']
        self.xml_filename = '%s-273_XX_report.xml' % (self.period.strftime('%B%Y'))
        xml_str = qweb._render('l10n_be_hr_payroll.273_xx_xml_report', self._get_rendering_data())

        # Prettify xml string
        root = etree.fromstring(xml_str, parser=etree.XMLParser(remove_blank_text=True, resolve_entities=False))
        xml_formatted_str = etree.tostring(root, pretty_print=True, encoding='utf-8', xml_declaration=True)

        self.xml_file = BinaryBytes(xml_formatted_str)

    def _clear_files(self):
        self.ensure_one()
        self.pdf_273s_file = False
        self.pdf_273s_filename = False
        self.pdf_273_part_file = False
        self.pdf_273_part_filename = False
        self.xml_file = False
        self.xml_filename = False
        self.xml_validation_state = 'normal'


class L10n_Be273_XxLine(models.Model):
    _name = 'l10n_be.273_xx.line'
    _description = '273.XX Line'

    sheet_id = fields.Many2one('l10n_be.273_xx', required=True, ondelete='cascade', index=True)
    payslip_id = fields.Many2one('hr.payslip', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', related='payslip_id.employee_id', store=True)
    company_id = fields.Many2one('res.company', related='sheet_id.company_id')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    date_start = fields.Date(related='payslip_id.date_from')
    date_end = fields.Date(related='payslip_id.date_to')
    report_type = fields.Selection([
        ('ip', 'Intellectual Property'),
        ('part', 'Employee Participation'),
    ], required=True)
    profit_sharing_15_gross = fields.Monetary(string="Profit Sharing Bonus 15%")
    profit_sharing_15_tax = fields.Monetary(string="Withholding Tax 15%")
    profit_sharing_7_gross = fields.Monetary(string="Profit Sharing Bonus 7%")
    profit_sharing_7_tax = fields.Monetary(string="Withholding Tax 7%")
