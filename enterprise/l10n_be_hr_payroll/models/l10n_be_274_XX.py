# Part of Odoo. See LICENSE file for full copyright and licensing details.

import io
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import BinaryBytes, float_is_zero, format_date
from odoo.tools.misc import file_path
from odoo.addons.l10n_be_hr_payroll.models.utils import sum_values_by_group, to_eurocent


class L10n_Be274_Xx(models.Model):
    _name = 'l10n_be.274_xx'
    _description = '274.XX Sheets'
    _order = 'date_start'

    @api.model
    def default_get(self, fields):
        if self.env.company.country_id.code != "BE":
            raise UserError(_('This feature seems to be as exclusive as Belgian chocolates. You must be logged in to a Belgian company to use it.'))
        return super().default_get(fields)

    def _get_default_company_id(self):
        company = self.env.company
        if company.parent_id:
            raise UserError(self.env._('274.XX report can only be generated from a top-level company'))
        return company

    year = fields.Integer(required=True, default=lambda self: fields.Date.context_today(self).year, aggregator=None)
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
    ], aggregator=None)
    quarter = fields.Selection([
        ('1', 'Q1'),
        ('2', 'Q2'),
        ('3', 'Q3'),
        ('4', 'Q4'),
    ], aggregator=None)
    period = fields.Char(compute='_compute_period', store=True)
    date_start = fields.Date(
        'Start Period', store=True, readonly=False,
        compute='_compute_dates')
    date_end = fields.Date(
        'End Period', store=True, readonly=False,
        compute='_compute_dates')
    line_ids = fields.One2many(
        'l10n_be.274_xx.line', 'sheet_id',
        compute='_compute_line_ids', store=True, readonly=False, compute_sudo=True)
    payslip_ids = fields.Many2many(
        'hr.payslip', 'l10n_be_274_xx_hr_payslip_rel', 'sheet_id', 'payslip_id',
        string="Declared Payslips", compute='_compute_line_ids', store=True, copy=False)
    untaxed_employee_ids = fields.Many2many('hr.employee', store=True, compute='_compute_line_ids')
    line_274_10_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Employees")
    line_274_13_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Economic Unemployment")
    line_274_18_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Replacement Revenues")
    line_274_20_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Company Executives")
    line_274_30_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="presence Tokens")
    line_274_32_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Doctors / Civil Engineers")
    line_274_33_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Masters")
    line_274_34_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Bachelors")
    line_274_56_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="IPA Eligible Employees")
    line_274_62_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Starterjob")
    line_274_64_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Training")
    line_274_74_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="(Continuous) Team Shifts")
    line_274_75_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Night Shifts")
    training_employee_ids = fields.Many2many(
        comodel_name="hr.employee",
        relation="l10n_be_274_xx_training_employee_rel",
        column1="sheet_id",
        column2="employee_id",
        string="Trained Employees",
        help="Employees who followed an eligible training during the period. The withholding tax exemption (274.64) is computed for each of them.",
        domain="[('company_id', 'in', branch_ids)]",
    )
    line_274_81_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Aid Zone")
    line_274_extra_hours_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Extra Hours")
    company_id = fields.Many2one('res.company', default=_get_default_company_id, required=True)
    branch_ids = fields.One2many('res.company', compute='_compute_branch_ids', compute_sudo=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready'),
        ('done', 'Done'),
        ('canceled', 'Canceled')], default='draft')
    declaration_type = fields.Selection([
        ('original', 'Original'),
        ('modification', 'Modification'),
    ], default='original', required=True)
    parent_id = fields.Many2one(
        'l10n_be.274_xx', string='Original', index='btree_not_null',
        help="The declaration this one modifies.")
    children_ids = fields.One2many(
        'l10n_be.274_xx', 'parent_id', string="Modifications",
        help="The modifications filed against this declaration.")
    is_correction_needed = fields.Boolean(
        copy=False,
        help="Payslips of this period changed after the declaration was filed.")
    sheet_274_10 = fields.Binary('274.10 Sheet', readonly=True, attachment=False)
    sheet_274_10_filename = fields.Char()

    pp_amount_10 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_13 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_18 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_20 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_30 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_32 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_33 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_34 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_44 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_55 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_62 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_64 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_74 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_75 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    pp_amount_81 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)

    taxable_amount_10 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_13 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_18 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_20 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_30 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_32 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_33 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_34 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_44 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_55 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_62 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_64 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_74 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_75 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    taxable_amount_81 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)

    deducted_amount = fields.Monetary("Exempted Amount", compute='_compute_amounts', compute_sudo=True)
    deducted_amount_32 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_33 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_34 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_44 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_55 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_62 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_64 = fields.Monetary("Training Exempted Amount", compute='_compute_amounts', compute_sudo=True)
    deducted_amount_74 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_75 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)
    deducted_amount_81 = fields.Monetary(compute='_compute_amounts', compute_sudo=True)

    capped_amount_34 = fields.Monetary("Capped Amount", compute='_compute_amounts', compute_sudo=True)

    l10n_be_training_seniority_warning_message = fields.Char(compute='_compute_training_seniority_warning')

    amount_to_pay = fields.Monetary("Amount to Pay", compute="_compute_amounts", compute_sudo=True)
    is_ipa_reduction = fields.Boolean(compute='_compute_is_ipa_reduction')
    exemption_sme_status = fields.Selection([
        ('startup', "Startup / early stage"),
        ('micro', "Micro Entreprise"),
    ], compute="_compute_exemption_sme_status")
    sme_taxable_amount = fields.Monetary("SME Taxable Amount", compute='_compute_amounts', compute_sudo=True)
    sme_exemption_rate = fields.Float("SME Exemption Rate (%)", compute='_compute_amounts', compute_sudo=True)
    sme_exempted_amount = fields.Monetary("SME Exempted Amount", compute='_compute_amounts', compute_sudo=True)
    extra_hours_exempted_amount = fields.Monetary("Extra Hours Exempted Amount", compute='_compute_amounts', compute_sudo=True)
    extra_hours_cap_warning = fields.Char(compute='_compute_line_ids', store=True)

    total_pp_amount = fields.Monetary("Total Withholding Taxes", compute='_compute_amounts', compute_sudo=True)
    total_taxable_amount = fields.Monetary("Total Taxable Amount", compute='_compute_amounts', compute_sudo=True)

    is_cbe_expired = fields.Boolean(
        string="CBE Expired",
        compute="_compute_cbe_expiration"
    )
    startup_exempted_amount = fields.Monetary(compute="_compute_amounts", compute_sudo=True)
    startup_amount_to_pay = fields.Monetary(compute="_compute_amounts", compute_sudo=True)

    eligible_employee_count = fields.Integer("# of Employees", compute='_compute_eligible_employee_count')
    xml_file = fields.Binary(string="XML file")
    xml_filename = fields.Char()
    xml_validation_state = fields.Selection([
        ('normal', "N/A"),
        ('done', "Valid"),
        ('invalid', "Invalid"),
    ], default='normal', compute='_compute_validation_state', store=True)
    error_message = fields.Char(store=True, compute='_compute_validation_state')
    payment_reference = fields.Char('Withholding Tax Payment Reference')
    belcotax_reference = fields.Char('ID From Belcotax', copy=False)
    xls_file = fields.Binary(string="XLS file")
    xls_filename = fields.Char()
    declaration_frequency = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
    ], compute='_compute_declaration_frequency', store=True, readonly=True)
    extra_exempted_rate = fields.Float(compute='_compute_amounts', compute_sudo=True, string="Extra Hours Exempted Rate (%)", help="Only set for 274.44 and 274.55 lines: the exempted rate for extra hours.")

    @api.depends('company_id')
    def _compute_branch_ids(self):
        report_companies = self.mapped('company_id')
        branches_by_root = self.env['res.company'].search([
            ('id', 'child_of', report_companies.ids),
        ]).grouped('root_id')

        for report in self:
            report.branch_ids = branches_by_root.get(report.company_id, report.company_id)

    @api.depends('company_id.payroll_config_ids.l10n_be_ipa_reduction')
    def _compute_is_ipa_reduction(self):
        for record in self:
            record.is_ipa_reduction = record.company_id._get_payroll_config(record.date_start).l10n_be_ipa_reduction

    @api.depends('company_id.payroll_config_ids.exemption_sme_status')
    def _compute_exemption_sme_status(self):
        for record in self:
            record.exemption_sme_status = record.company_id._get_payroll_config(record.date_start).exemption_sme_status

    @api.depends('company_id.payroll_config_ids.l10n_be_declaration_frequency')
    def _compute_declaration_frequency(self):
        for record in self:
            if record.declaration_frequency and record.state != 'draft':
                continue
            record.declaration_frequency = record.company_id._get_payroll_config(record.date_start).l10n_be_declaration_frequency

    @api.depends('date_start', 'declaration_frequency', 'quarter', 'year')
    def _compute_display_name(self):
        for record in self:
            if record.declaration_frequency == 'monthly':
                record.display_name = format_date(self.env, record.date_start, date_format="MMMM y", lang_code=self.env.user.lang)
            elif record.declaration_frequency == 'quarterly':
                record.display_name = (
                    self.env._(
                        "%(quarter)s %(year)s",
                        quarter=record._fields["quarter"]._description_selection(self.env)[int(record.quarter) - 1][1],
                        year=record.year,
                    )
                    if record.quarter
                    else ""
                )

    @api.depends('month', 'declaration_frequency', 'quarter')
    def _compute_period(self):
        for record in self:
            if record.declaration_frequency == 'monthly' and record.month:
                record.period = record._fields['month']._description_selection(self.env)[int(record.month) - 1][1]
            elif record.declaration_frequency == 'quarterly' and record.quarter:
                record.period = record._fields['quarter']._description_selection(self.env)[int(record.quarter) - 1][1]

    @api.depends('year', 'month', 'quarter', 'declaration_frequency')
    def _compute_dates(self):
        for record in self:
            if record.declaration_frequency == 'monthly' and record.month:
                record.update({
                    'date_start': date(record.year, int(record.month), 1),
                    'date_end': date(record.year, int(record.month), 1) + relativedelta(day=31),
                })
            elif record.declaration_frequency == 'quarterly' and record.quarter:
                quarter_start_month = (int(record.quarter) - 1) * 3 + 1
                record.update({
                    'date_start': date(record.year, quarter_start_month, 1),
                    'date_end': date(record.year, quarter_start_month, 1) + relativedelta(months=2, day=31),
                })

    @api.depends('xml_file')
    def _compute_validation_state(self):
        xsd_schema_file_path = file_path('l10n_be_hr_payroll/data/finprof.xsd')
        xsd_root = etree.parse(xsd_schema_file_path)
        schema = etree.XMLSchema(xsd_root)
        for sheet in self:
            if not sheet.xml_file:
                sheet.xml_validation_state = 'normal'
                sheet.error_message = False
            else:
                xml_root = etree.fromstring(sheet.xml_file.content)
                try:
                    schema.assertValid(xml_root)
                    sheet.xml_validation_state = 'done'
                except etree.DocumentInvalid as err:
                    sheet.xml_validation_state = 'invalid'
                    sheet.error_message = str(err)

    def _refresh_draft(self):
        """Recompute what a draft declaration covers, before it is generated.

        Nothing links a declaration to the payslips of its period until it computes them, so its
        dependencies never fire when a payslip of that period is confirmed: a draft would otherwise
        be generated from the content it had when it was created. A filed one keeps its content
        on purpose.
        """
        if self.env.context.get('l10n_be_274_xx_no_refresh'):
            return
        drafts = self.filtered(lambda sheet: sheet.state == 'draft')
        if drafts:
            drafts.with_context(l10n_be_274_xx_no_refresh=True)._compute_line_ids()

    def _get_declared_payslips(self):
        """Payslips the filed declarations of this period already reported.

        A modification only has to declare what its predecessors left out, so their payslips
        stay out of its selection.
        """
        self.ensure_one()
        root = self._origin or self.parent_id
        while root.parent_id:
            root = root.parent_id
        if not root:
            return self.env['hr.payslip']
        predecessors = self.search([
            ('id', 'child_of', root.id),
            ('state', 'in', ['ready', 'done']),
        ]) - self._origin
        return predecessors.payslip_ids

    def _get_valid_payslips(self):
        domain = Domain([
            ('state', 'in', ['paid', 'validated']),
            ('company_id', 'in', self.branch_ids.ids),
        ]) & self.env['hr.payslip']._l10n_be_get_fiscal_period_domain(self.date_start, self.date_end)
        if declared_payslips := self._get_declared_payslips():
            domain &= Domain('id', 'not in', declared_payslips.ids)
        if self.env.context.get('wizard_274xx_force_employee_ids'):
            domain &= Domain('employee_id', 'in', self.env.context['wizard_274xx_force_employee_ids'])
        return self.env['hr.payslip'].search(domain)

    @api.constrains('company_id')
    def _check_l10n_be_company_number(self):
        for sheet in self:
            config = sheet.company_id._get_payroll_config(sheet.date_start)
            if not config.l10n_be_company_number or not config.l10n_be_revenue_code:
                raise ValidationError(_("Please configure the 'Company Number' and the 'Revenue Code' on the Payroll Settings."))

    @api.constrains('month', 'quarter', 'declaration_frequency')
    def _check_period_is_selected(self):
        for record in self:
            if record.declaration_frequency == 'monthly' and not record.month:
                raise ValidationError(_("Please select a month for the report."))
            elif record.declaration_frequency == 'quarterly' and not record.quarter:
                raise ValidationError(_("Please select a quarter for the report."))

    def _get_274_56_values(self, payslips):
        self.ensure_one()
        sme_rate_param = self.env['hr.rule.parameter']._get_parameter_from_code('sme_withholding_tax_exemption_rate', self.date_start, raise_if_not_found=False)
        sme_exemption_rate = sme_rate_param if sme_rate_param else 0.0012
        exemption_cap_multiplier = self.env['hr.rule.parameter']._get_parameter_from_code('l10n_be_274_witholding_tax_exemption_multiplier', self.date_start, raise_if_not_found=False) or 1.0
        # The base is read from the payslips of the declaration, for the amounts attached to its period
        category_codes = self.env['hr.payslip']._get_child_category_ids('IPA_REDUCTION_BASE')
        taxable_amount_by_employee = dict(self.env['hr.payslip.line']._read_group(
            Domain([
                ('slip_id', 'in', payslips.ids),
                ('salary_rule_id.category_ids.code', 'in', category_codes),
            ]) & self.env['hr.payslip']._l10n_be_get_fiscal_line_domain(self.date_start, self.date_end),
            ['employee_id'], ['total:sum'],
        ))
        result_per_employee = {}
        for employee in payslips.employee_id:
            taxable_amount = taxable_amount_by_employee.get(employee, 0.0)
            result_per_employee[employee] = (
                taxable_amount,
                taxable_amount * sme_exemption_rate * exemption_cap_multiplier,
            )
        return result_per_employee

    @api.model
    def _get_exemption_withholding_tax(self, payslips, line_values):
        # The withholding tax that the exemptions can reduce, as in the salary rule of the 274.81: the one of the
        # remuneration, without the ones of the replacement incomes, of the double holiday pay and of the presence
        # tokens. PPTOTAL is the total of all the withholding taxes, the others are negative lines.
        codes = ('PPTOTAL', 'REPLACEMENT_REVENUE.P.P', 'DH_PP', 'PRESENCE_TOKEN_WITHHOLDING_TAX')
        return sum(line_values[code][payslip.id]['total'] for payslip in payslips for code in codes)

    @api.model
    def _get_rd_basic_exemption_vals(self, employee_payslips, line_values, taxable_values=None):
        date_start = self.date_start or (employee_payslips and min(employee_payslips.mapped('date_from')))
        exemption_cap_multiplier = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_be_274_witholding_tax_exemption_multiplier', date_start, raise_if_not_found=False
        ) or 1.0

        def sum_line_totals(payslips, code):
            return sum(line_values[code][payslip.id]["total"] for payslip in payslips)

        def calculate_exemption(employee, structure_code, withholding_amount):
            rd_percentage = employee._get_average_rd_percentage(structure_code=structure_code, use_date=date_start)
            return rd_percentage * 0.8 * withholding_amount * exemption_cap_multiplier

        if taxable_values is not None:
            taxable_amount = sum(taxable_values[p.id] for p in employee_payslips)
        else:
            # Called from a salary rule, which has no declaration period to attribute amounts to.
            taxable_amount = sum(
                sum_line_totals(employee_payslips, code)
                for code in self.env["hr.payslip"]._get_gross_wage_line_codes()
            )

        payslips_by_structure = employee_payslips.grouped(lambda payslip: payslip.struct_id.code)

        monthly_payslips = payslips_by_structure.get("BEMONTHLY", self.env["hr.payslip"])
        double_pay_payslips = payslips_by_structure.get("BEDOUBLE", self.env["hr.payslip"])

        monthly_withholding = self._get_exemption_withholding_tax(monthly_payslips, line_values)

        double_pay_withholding = (-sum_line_totals(monthly_payslips, "DH_PP") + sum_line_totals(double_pay_payslips, "PPTOTAL"))

        withholding_by_structure = {
            "BEMONTHLY": monthly_withholding,
            "BEDOUBLE": double_pay_withholding,
        }

        for structure_code, structure_payslips in payslips_by_structure.items():
            if structure_code not in withholding_by_structure:
                withholding_by_structure.update({
                    structure_code: sum_line_totals(structure_payslips, "PPTOTAL")
                })

        withholding_tax_total = sum(withholding_by_structure.values())

        exemption_amount = sum(
            calculate_exemption(employee_payslips.employee_id, structure_code, withholding_amount)
            for structure_code, withholding_amount in withholding_by_structure.items()
        )

        return taxable_amount, withholding_tax_total, exemption_amount

    @api.model
    def _get_bachelor_rd_exemption_capping_ratio(self, total_32_33_exemption, total_bach_exemption, date):
        bachelor_rate = self._get_bachelor_exemption_rate(date)
        capped_bachelor_total = min(total_bach_exemption, total_32_33_exemption * bachelor_rate)
        if total_bach_exemption:
            return capped_bachelor_total / total_bach_exemption
        return 1

    def _get_valid_payslips_filters(self):
        # The payslips of the forms 274.10, 274.20 and 274.30 are the ones of the 281.10, 281.20 and 281.30
        return {
            # the tax on the profit sharing bonus is a withholding tax on movable income, declared on the 273S
            '274.10': lambda p: bool(p._l10n_be_filter_remuneration_form('281.10')) and p.struct_id.code != 'BEPROFITSHARING',
            '274.20': lambda p: bool(p._l10n_be_filter_remuneration_form('281.20')),
            '274.30': lambda p: bool(p._l10n_be_filter_remuneration_form('281.30')),
        }

    def _get_valid_274_32_payslips(self, payslips):
        concerned_payslips_structs = ['BEMONTHLY', 'BEDOUBLE', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1']
        date_from = min(payslips.mapped('date_from'), default=False)
        return payslips.filtered(
            lambda p: p.struct_id.code in concerned_payslips_structs
            and p.employee_id.certificate in ['doctor', 'civil_engineer']
            and p.employee_id._get_average_rd_percentage(p.struct_id.code, date_from) > 0
        )

    def _get_valid_274_33_payslips(self, payslips):
        concerned_payslips_structs = ['BEMONTHLY', 'BEDOUBLE', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1']
        date_from = min(payslips.mapped('date_from'), default=False)
        return payslips.filtered(
            lambda p: p.struct_id.code in concerned_payslips_structs
            and p.employee_id.certificate in ['master']
            and p.employee_id._get_average_rd_percentage(p.struct_id.code, date_from) > 0
        )

    def _get_valid_274_34_payslips(self, payslips):
        concerned_payslips_structs = ['BEMONTHLY', 'BEDOUBLE', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1']
        date_from = min(payslips.mapped('date_from'), default=False)
        return payslips.filtered(
            lambda p: p.struct_id.code in concerned_payslips_structs
            and p.employee_id.certificate in ['bachelor']
            and p.employee_id._get_average_rd_percentage(p.struct_id.code, date_from) > 0
        )

    @api.model
    def _is_team_exemption_eligible(self, payslip):
        # A reversal carries the negation of every hour and amount of the payslip it reverses, so
        # assessing it on its own figures lands on the wrong side of the comparison: dividing a
        # negative number of hours by three makes it larger, not smaller. It reverses exactly what
        # its origin declared, so it is assessed there.
        if payslip.is_refund_payslip and payslip.origin_payslip_id:
            payslip = payslip.origin_payslip_id
        team_rate = payslip._rule_parameter('cp_200_premium_pay_team_hourly_rate')
        contteam_rate = payslip._rule_parameter('cp_200_premium_pay_contteam_hourly_rate')
        team_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_TEAM')
        contteam_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_CONTTEAM')
        full_pay_hours = payslip._get_l10n_be_full_pay_worked_hours()

        valid_team = bool(team_rate) and team_rate >= 2 and bool(team_hours)
        valid_contteam = bool(contteam_rate) and contteam_rate >= 2 and bool(contteam_hours)
        total_team_hours = (team_hours if valid_team else 0) + (contteam_hours if valid_contteam else 0)

        return full_pay_hours and total_team_hours >= full_pay_hours / 3

    @api.model
    def _is_night_exemption_eligible(self, payslip):
        if payslip.is_refund_payslip and payslip.origin_payslip_id:
            payslip = payslip.origin_payslip_id
        if self._is_team_exemption_eligible(payslip):
            return False
        night_rate = payslip._rule_parameter('cp_200_premium_pay_night_hourly_rate')
        # WARNING: cp_200_premium_pay_night_hourly_rate is not a rate but a multiplication factor (e.g. 1.56 = 56%)
        night_rate = (night_rate - 1) * 100 if night_rate else 0
        night_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_NIGHT')
        if night_rate < 12 or not night_hours:
            return False

        full_pay_hours = payslip._get_l10n_be_full_pay_worked_hours()
        return full_pay_hours and night_hours >= full_pay_hours / 3

    @api.model
    def _get_team_shift_exemption_vals(self, payslip, taxable=None):
        """
        274.74 (Team / Continuous Team) individual theoretical withholding tax exemption.

        To be eligible, the Team (resp. Continuous Team) hourly bonus must be at least the
        legal rate, and the hours tagged with those premiums (summed together) must reach
        at least a third of the hours of the period that are paid at 100%. The exemption
        rate then applies to the taxable remuneration of the payslip (`taxable`, its GROSS
        line by default), the Continuous Team rate in the share of the Continuous Team hours.

        :return: (is_eligible, exemption_amount)
        """
        if payslip.is_refund_payslip and payslip.origin_payslip_id:
            eligible, exemption = self._get_team_shift_exemption_vals(payslip.origin_payslip_id)
            return eligible, -exemption
        if not self._is_team_exemption_eligible(payslip):
            return False, 0.0

        team_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_TEAM')
        contteam_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_CONTTEAM')
        team_exemption_rate = payslip._rule_parameter('l10n_be_274_74_team_exemption_rate')
        contteam_exemption_rate = payslip._rule_parameter('l10n_be_274_74_contteam_exemption_rate')
        exemption_rate = (
            (team_hours * team_exemption_rate + contteam_hours * contteam_exemption_rate) / (team_hours + contteam_hours)
        )
        exemption = self._get_shift_exemption_base(payslip, taxable) * exemption_rate / 100
        return True, self._round_shift_exemption(payslip, exemption)

    @api.model
    def _get_night_shift_exemption_vals(self, payslip, taxable=None):
        """
        274.75 (Night) individual theoretical withholding tax exemption: its rate on the
        taxable remuneration of the payslip (`taxable`, its GROSS line by default).

        An employee eligible for the Team/Continuous Team exemption (274.74) on this
        payslip can not also claim the Night exemption on it.

        :return: (is_eligible, exemption_amount)
        """
        if payslip.is_refund_payslip and payslip.origin_payslip_id:
            eligible, exemption = self._get_night_shift_exemption_vals(payslip.origin_payslip_id)
            return eligible, -exemption
        if not self._is_night_exemption_eligible(payslip):
            return False, 0

        exemption_rate = payslip._rule_parameter('l10n_be_274_75_night_exemption_rate')
        exemption = self._get_shift_exemption_base(payslip, taxable) * exemption_rate / 100
        return True, self._round_shift_exemption(payslip, exemption)

    @api.model
    def _round_shift_exemption(self, payslip, amount):
        """The theoretical exemption as its payslip line holds it (in cents): the pool the payslips share and the
        declaration's pool add the same amounts."""
        return payslip.company_id.currency_id.round(amount)

    @api.model
    def _get_shift_exemption_base(self, payslip, taxable=None):
        """The remuneration the team and night exemptions apply to: the taxable remuneration of the worker, the
        premiums included (CIR 92, art. 275/5: 22.8%, 25% in continuous teams, of the taxable remuneration, without
        the double holiday pay, the end-of-year premium and the arrears, which are paid on payslips of their own), i.e.
        the taxable salary of the payslip. From a salary rule the payslip has no lines yet: the rule gives it, rounded
        as the line will be, so that the declaration, which reads the line, finds the same amount."""
        if taxable is not None:
            return payslip.company_id.currency_id.round(taxable)
        return payslip._get_line_values(['GROSS'])['GROSS'][payslip.id]['total']

    def _get_274_32_33_34_values(self, payslips, line_values, taxable_values):
        """
        274.32, 274.33, 274.34 report is about withholding tax exemption for PhDs/Engineers, Masters and Bachelors
        Returns:
        {
            employee: (
                taxable_amount,
                withholding_tax_amount,
                exemption_amount,
            )
        }
        """
        self.ensure_one()
        result_per_employee = defaultdict(lambda: (0.0, 0.0, 0.0))
        total_exemption = 0
        for employee, employee_slips in payslips.grouped('employee_id').items():
            taxable_amount, withholding_tax_amount, exemption_amount = self._get_rd_basic_exemption_vals(
                employee_slips, line_values, taxable_values
            )
            current_taxable, current_withholding, current_exemption = result_per_employee[employee]
            result_per_employee[employee] = (
                current_taxable + taxable_amount,
                current_withholding + withholding_tax_amount,
                current_exemption + exemption_amount,
            )
            total_exemption += exemption_amount
        return result_per_employee

    def _get_274_64_values(self, payslips, line_values, taxable_values, rd_exemption_per_employee=None):
        """
        274.64 report is about the withholding tax exemption for worker training.The exemption equals a fixed percentage
        (11.75%) of the taxable salary (monthly remuneration + premium + benefit in kind, i.e. the GROSS line) of the
        month during which the training took place.

        The cumulative dispensation for one employee cannot exceed the withholding tax actually due for that employee,
        so the training exemption is floored to the withholding left after the R&D exemption (274.32/33/34, applied
        first) and never goes below 0. ``rd_exemption_per_employee`` maps each employee to that already-granted R&D
        exemption (0 when absent).
        Returns:
        {
            employee: (
                taxable_amount,
                withholding_tax_amount,
                exemption_amount,
            )
        }
        """
        self.ensure_one()
        rd_exemption_per_employee = rd_exemption_per_employee or {}
        rate = (
            self.env["hr.rule.parameter"]._get_parameter_from_code(
                "l10n_be_274_64_training_exemption_rate",
                self.date_start,
                raise_if_not_found=False,
            )
            or 0.1175
        )
        result_per_employee = defaultdict(lambda: (0.0, 0.0, 0.0))
        for employee, emp_slips in payslips.grouped("employee_id").items():
            taxable_amount = sum(taxable_values[p.id] for p in emp_slips)
            withholding_tax_amount = self._get_exemption_withholding_tax(emp_slips, line_values)
            remaining_withholding = withholding_tax_amount - rd_exemption_per_employee.get(employee, 0.0)
            result_per_employee[employee] = (
                taxable_amount,
                withholding_tax_amount,
                max(0.0, min(rate * taxable_amount, remaining_withholding)),
            )
        return result_per_employee

    def _get_274_74_values(self, payslips, line_values, taxable_values):
        """
        274.74 report is about withholding tax exemption for team shifts
        Returns:
        {
            employee: (
                taxable_amount,
                withholding_tax_amount,
                exemption_amount,
            )
        }
        """
        self.ensure_one()
        result_per_employee = {}
        exemption_to_report = 0
        for employee, employee_slips in payslips.grouped('employee_id').items():
            theoretical_exemption = 0
            for p in employee_slips:
                _, exemption = self._get_team_shift_exemption_vals(p)
                theoretical_exemption += exemption

            taxable_amount = sum(taxable_values[p.id] for p in employee_slips)
            withholding_tax_amount = self._get_exemption_withholding_tax(employee_slips, line_values)
            if withholding_tax_amount > theoretical_exemption:
                extra_amount = min(withholding_tax_amount - theoretical_exemption, exemption_to_report)
                exemption_to_report -= extra_amount
                theoretical_exemption += extra_amount
            else:
                exemption_to_report += theoretical_exemption - withholding_tax_amount

            result_per_employee[employee] = (
                taxable_amount,
                withholding_tax_amount,
                min(withholding_tax_amount, theoretical_exemption)
            )
        return result_per_employee

    def _get_274_75_values(self, payslips, line_values, taxable_values):
        """
        274.75 report is about withholding tax exemption for night shifts
        Returns:
        {
            employee: (
                taxable_amount,
                withholding_tax_amount,
                exemption_amount,
            )
        }
        """
        self.ensure_one()
        result_per_employee = {}
        exemption_to_report = 0
        for employee, employee_slips in payslips.grouped('employee_id').items():
            theoretical_exemption = 0
            for p in employee_slips:
                _, exemption = self._get_night_shift_exemption_vals(p)
                theoretical_exemption += exemption

            taxable_amount = sum(taxable_values[p.id] for p in employee_slips)
            withholding_tax_amount = self._get_exemption_withholding_tax(employee_slips, line_values)
            if withholding_tax_amount > theoretical_exemption:
                extra_amount = min(withholding_tax_amount - theoretical_exemption, exemption_to_report)
                exemption_to_report -= extra_amount
                theoretical_exemption += extra_amount
            else:
                exemption_to_report += theoretical_exemption - withholding_tax_amount

            result_per_employee[employee] = (
                taxable_amount,
                withholding_tax_amount,
                min(withholding_tax_amount, theoretical_exemption)
            )
        return result_per_employee

    def _get_274_81_values(self, payslips, line_values, taxable_values=None):
        self.ensure_one()
        result_per_employee = defaultdict(lambda: (0.0, 0.0, 0.0))
        if taxable_values is None:
            gross_codes = self.env['hr.payslip']._get_gross_wage_line_codes()
            taxable_values = {p.id: sum(line_values[code][p.id]['total'] for code in gross_codes) for p in payslips}
        for employee, emp_slips in payslips.grouped('employee_id').items():
            # the taxable salary of the declaration period, as for the 274.10
            taxable_amount = sum(taxable_values[p.id] for p in emp_slips)
            withholding_tax_amount = self._get_exemption_withholding_tax(emp_slips, line_values)
            exemption_amount = 0.25 * withholding_tax_amount
            current_taxable, current_withholding, current_exemption = result_per_employee[employee]
            result_per_employee[employee] = (
                current_taxable + taxable_amount,
                current_withholding + withholding_tax_amount,
                current_exemption + exemption_amount,
            )
        return result_per_employee

    def _get_bachelor_exemption_rate(self, date):
        """ Return the withholding tax exemption rate applicable to bachelor researchers for the given date. """
        # Companies with 50 or more employees get 25%, smaller ones get 50% (default to 25% when size is undefined).
        company = self.company_id if self else self.env.company
        config = company._get_payroll_config(date)
        if config.onss_importance_code and config.onss_importance_code not in ('5', '6', '7', '8', '9'):
            rate_code = 'scientific_research_withholding_taxes_bachelor_rate_small_company'
        else:
            rate_code = 'scientific_research_withholding_taxes_bachelor_rate'
        rate = self.env['hr.rule.parameter']._get_parameter_from_code(rate_code, date, raise_if_not_found=False)
        return rate if rate else 0.25

    @api.model
    def _get_extra_hours_lines_ids(self, payslips, date_start, line_values):
        # The overtime giving right to the legal overtime premium, voluntary overtime included, in both joint
        # committees (the hotel industry's included: SPF Finances, dispense secteur Horeca)
        overtime_category = self.env['hr.payslip']._l10n_be_get_overtime_category()

        def is_overtime(work_entry_type):
            return overtime_category in work_entry_type.category_ids

        payslips = payslips.filtered(lambda p: any(map(is_overtime, p.worked_days_line_ids.work_entry_type_id)))

        if not payslips:
            return [], False

        exemption_rate = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_be_extra_hours_exemption_rate', date_start, raise_if_not_found=False) or 0.4125
        # from a payslip's salary rule there is no declaration: the company is the payslips' own
        company = self.company_id or payslips.company_id[:1]

        cp200 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200')
        cp302 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')

        def get_joint_committee(version):
            # The joint committee of the payslip, as in the 281.10: the employee may have changed of joint committee
            jc = version.l10n_be_joint_committee_id
            if jc and jc.is_descendant_of(cp302):
                return '302'
            if jc and jc.is_descendant_of(cp200):
                return '200'
            return False

        worked_days_groups = self.env['hr.payslip.worked_days']._read_group(
            domain=[
                ('payslip_id.state', 'in', ['paid', 'validated']),
                ('payslip_id.company_id', '=', company.id),
                ('payslip_id.date_from', '>=', date(date_start.year, 1, 1)),
                ('payslip_id.date_to', '<', date_start),
                ('payslip_id.employee_id', 'in', payslips.mapped('employee_id').ids),
                ('work_entry_type_id.category_ids', 'in', overtime_category.ids),
            ],
            groupby=['payslip_id.employee_id', 'payslip_id.version_id'],
            aggregates=['number_of_hours:sum'],
        )
        consumed_by_employee_jc = defaultdict(float)
        for employee, version, hours in worked_days_groups:
            consumed_by_employee_jc[employee, get_joint_committee(version)] += hours

        payslips_by_employee_jc = payslips.grouped(lambda p: (p.employee_id, get_joint_committee(p.version_id)))

        line_ids_vals = []
        capped_employees = set()

        for (employee, joint_committee), emp_slips in payslips_by_employee_jc.items():
            if not joint_committee:
                continue
            is_cp200 = joint_committee == '200'
            nature = 44 if is_cp200 else 55

            if is_cp200:
                overtime_threshold_code = 'cp200_overtime_threshold'
            else:
                overtime_threshold_code = 'cp302_overtime_threshold_white_cash_register' if company._l10n_be_has_white_cash_register() else 'cp302_overtime_threshold_not_white_cash_register'

            overtime_cap = self.env['hr.rule.parameter']._get_parameter_from_code(overtime_threshold_code, date_start)

            consumed = consumed_by_employee_jc[employee, joint_committee]

            # Sort so which lines get (partially) capped is deterministic/auditable.
            worked_days_lines = emp_slips.mapped('worked_days_line_ids').sorted(
                lambda wd: wd.payslip_id.date_from
            )

            taxable_amount = 0.0
            for wd in worked_days_lines:
                if not is_overtime(wd.work_entry_type_id):
                    continue

                if consumed >= overtime_cap:
                    capped_employees.add(employee.name)
                    continue

                hours, amount, rate = wd.number_of_hours, wd.amount, wd.work_entry_type_id.amount_rate
                if consumed + hours > overtime_cap:
                    capped_employees.add(employee.name)

                added_hours = min(hours, overtime_cap - consumed)
                # Taxable amount is the amount of extra hours flagged as extra hours, but only 100% of it.
                taxable_amount += amount * added_hours / (hours * rate) if hours and rate else 0.0
                consumed += added_hours

            if taxable_amount:
                withholding_tax_amount = sum(
                    line_values["PPTOTAL"][p.id]["total"]
                    for p in emp_slips
                )
                line_ids_vals.append({
                    'sheet_id': self.id,
                    'employee_id': employee.id,
                    'amount': taxable_amount * exemption_rate,
                    'withholding_amount': withholding_tax_amount,
                    'taxable_amount': taxable_amount,
                    'nature_code': '274.%02d' % nature,
                })

        warning_msg = False
        if capped_employees:
            warning_msg = self.env._(
                "The following employees have reached or exceeded their extra hours cap this year: %s",
                ", ".join(capped_employees)
            )

        return line_ids_vals, warning_msg

    def _get_mapping_lines_by_code(self):
        self.ensure_one()
        mappings = self.env['l10n.be.281.mapping'].search([
            ('declaration_code', 'like', '274.%'),
            ('date_from', '<=', self.date_start),
            '|', ('date_to', '=', False), ('date_to', '>=', self.date_end),
        ])
        return mappings.grouped('declaration_code')

    @api.depends('date_start', 'date_end', 'company_id', 'company_id.payroll_config_ids.onss_importance_code', 'training_employee_ids')
    def _compute_line_ids(self):
        for sheet in self:
            line_ids_vals = []

            all_payslips = sheet._get_valid_payslips()
            sheet.payslip_ids = all_payslips
            payslips = all_payslips.filtered(lambda p: not p.version_id.no_withholding_taxes)
            gross_codes = self.env['hr.payslip']._get_gross_wage_line_codes()
            # The taxable salary is added up from the amounts it is made of, so that each one is
            # declared in the period it is attached to instead of following the aggregate line.
            base_values = {}
            for code, category_code in self.env['hr.payslip']._get_gross_wage_base_categories().items():
                if code not in gross_codes:
                    continue
                base_values[code] = payslips._l10n_be_get_declaration_base(
                    category_code, sheet.date_start, sheet.date_end)
            taxable_values = defaultdict(float)
            for code_values in base_values.values():
                for payslip_id, amount in code_values.items():
                    taxable_values[payslip_id] += amount
            gross_values = base_values.get('GROSS', defaultdict(float))

            all_codes = list(set(self.env['hr.salary.rule'].with_context(active_test=False).search([]).mapped('code')))
            line_values = payslips._get_line_values(
                all_codes,
                extra_domain=self.env['hr.payslip']._l10n_be_get_fiscal_line_domain(
                    sheet.date_start, sheet.date_end
                )
            )
            sheet.untaxed_employee_ids = (all_payslips - payslips).employee_id

            mapping_by_code = sheet._get_mapping_lines_by_code()
            valid_payslips_filters = sheet._get_valid_payslips_filters()
            for declaration_code, mapping_lines in mapping_by_code.items():
                if declaration_code == '274.13':
                    declaration_payslips = payslips._l10n_be_filter_economic_unemployment()
                else:
                    declaration_payslips = payslips.filtered(valid_payslips_filters.get(declaration_code, lambda p: True))
                if not declaration_payslips:
                    continue

                tag_prefix = declaration_code.replace('.', '_')
                evaluation_plan = mapping_lines._get_evaluation_plan()
                employee_payslips = declaration_payslips.grouped('employee_id')
                line_values_by_employee = sum_values_by_group(employee_payslips, line_values, all_codes)
                for employee, employee_slips in employee_payslips.items():
                    employee_line_values = line_values_by_employee[employee]
                    localdict = self.env['l10n.be.281.mapping']._get_localdict(
                        line_values=employee_line_values,
                        payslips=employee_slips,
                        taxable_values=taxable_values,
                    )

                    computed_values = mapping_lines._evaluate_batch(localdict, evaluation_plan)
                    taxable = computed_values.get(f"{tag_prefix}_taxable", 0.0)
                    withholding = computed_values.get(f"{tag_prefix}_withholding", 0.0)
                    if declaration_code == '274.18' and float_is_zero(taxable, precision_digits=2) \
                            and float_is_zero(withholding, precision_digits=2):
                        # Most payslips have no replacement revenue, and a refunded one cancels its origin
                        continue

                    line_ids_vals.append({
                        'sheet_id': sheet.id,
                        'employee_id': employee.id,
                        'amount': computed_values.get(f"{tag_prefix}_exempted", 0.0),
                        'withholding_amount': withholding,
                        'taxable_amount': taxable,
                        'nature_code': declaration_code,
                    })

            valid_payslips_32 = self._get_valid_274_32_payslips(payslips)
            result_274_32_per_employee = sheet._get_274_32_33_34_values(valid_payslips_32, line_values, taxable_values)
            for employee, res in result_274_32_per_employee.items():
                taxable, withholding, exemption = res
                line_ids_vals.append({
                    'sheet_id': sheet.id,
                    'employee_id': employee.id,
                    'amount': exemption,
                    'withholding_amount': withholding,
                    'taxable_amount': taxable,
                    'nature_code': '274.32'
                })

            valid_payslips_33 = self._get_valid_274_33_payslips(payslips)
            result_274_33_per_employee = sheet._get_274_32_33_34_values(valid_payslips_33, line_values, taxable_values)
            for employee, res in result_274_33_per_employee.items():
                taxable, withholding, exemption = res
                line_ids_vals.append({
                    'sheet_id': sheet.id,
                    'employee_id': employee.id,
                    'amount': exemption,
                    'withholding_amount': withholding,
                    'taxable_amount': taxable,
                    'nature_code': '274.33'
                })

            valid_payslips_34 = self._get_valid_274_34_payslips(payslips)
            result_274_34_per_employee = sheet._get_274_32_33_34_values(valid_payslips_34, line_values, taxable_values)
            bachelor_vals = []
            for employee, res in result_274_34_per_employee.items():
                taxable, withholding, exemption = res
                bachelor_vals.append({
                    'sheet_id': sheet.id,
                    'employee_id': employee.id,
                    'amount': exemption,
                    'raw_amount': exemption,
                    'withholding_amount': withholding,
                    'taxable_amount': taxable,
                    'nature_code': '274.34'
                })

            # Scale every employee's exempted amount down by that same ratio.
            # The raw_amount variable keeps the pre-cap value.
            raw_dm_total = sum(v['amount'] for v in line_ids_vals if v['nature_code'] in ('274.32', '274.33'))
            raw_bachelor_total = sum(v['amount'] for v in bachelor_vals)
            bachelor_rate = sheet._get_bachelor_exemption_rate(sheet.date_start)
            capped_bachelor_total = min(raw_bachelor_total, raw_dm_total * bachelor_rate)
            if raw_bachelor_total:
                ratio = capped_bachelor_total / raw_bachelor_total
                for vals in bachelor_vals:
                    vals['amount'] *= ratio

            line_ids_vals += bachelor_vals

            valid_payslips_56 = payslips.filtered(lambda p: not p.version_id.is_flexi())
            result_274_56_per_employee = sheet._get_274_56_values(valid_payslips_56)
            for employee, res in result_274_56_per_employee.items():
                taxable, exemption = res
                line_ids_vals.append({
                    'sheet_id': sheet.id,
                    'employee_id': employee.id,
                    'amount': exemption,
                    'taxable_amount': taxable,
                    'nature_code': '274.56'
                })

            # The R&D exemption (274.32/33/34) takes precedence over training: an employee's cumulative dispensation
            # cannot exceed their withholding, so training only claims what is left. The uncapped per-employee R&D
            # exemption is used here (the aggregate bachelor cap is only applied afterwards, per-line above and on
            # the total in _compute_amounts). This can only over-estimate R&D and therefore under-claim training,
            # never pushing amount_to_pay negative.
            rd_exemption_per_employee = defaultdict(float)
            for rd_result in (
                result_274_32_per_employee,
                result_274_33_per_employee,
                result_274_34_per_employee,
            ):
                for employee, (_taxable, _withholding, exemption) in rd_result.items():
                    rd_exemption_per_employee[employee] += exemption
            valid_payslips_62 = payslips.filtered(lambda p: p.version_id.l10n_be_is_starterjob)
            for employee, emp_slips in valid_payslips_62.grouped('employee_id').items():
                line_ids_vals.append({
                    'sheet_id': sheet.id,
                    'employee_id': employee.id,
                    'amount': sum(line_values['COMPSUPP'][p.id]['total'] for p in emp_slips),
                    'withholding_amount': sheet._get_exemption_withholding_tax(emp_slips, line_values),
                    'taxable_amount': sum(gross_values[p.id] for p in emp_slips),
                    'nature_code': '274.62'
                })
            valid_payslips_64 = payslips.filtered(
                lambda p: p.struct_id.code == "BEMONTHLY" and p.employee_id in sheet.training_employee_ids._origin,
            )
            result_274_64_per_employee = sheet._get_274_64_values(
                valid_payslips_64,
                line_values,
                gross_values,
                rd_exemption_per_employee,
            )
            for employee, res in result_274_64_per_employee.items():
                taxable, withholding, exemption = res
                line_ids_vals.append({
                    "sheet_id": sheet.id,
                    "employee_id": employee.id,
                    "amount": exemption,
                    "withholding_amount": withholding,
                    "taxable_amount": taxable,
                    "nature_code": "274.64",
                })

            valid_payslips_74 = payslips.filtered(self._is_team_exemption_eligible)
            result_274_74_per_employee = sheet._get_274_74_values(
                valid_payslips_74,
                line_values,
                gross_values,
            )
            for employee, res in result_274_74_per_employee.items():
                taxable, withholding, exemption = res
                line_ids_vals.append({
                    "sheet_id": sheet.id,
                    "employee_id": employee.id,
                    "amount": exemption,
                    "withholding_amount": withholding,
                    "taxable_amount": taxable,
                    "nature_code": "274.74",
                })

            valid_payslips_75 = payslips.filtered(self._is_night_exemption_eligible)
            result_274_75_per_employee = sheet._get_274_75_values(
                valid_payslips_75,
                line_values,
                gross_values,
            )
            for employee, res in result_274_75_per_employee.items():
                taxable, withholding, exemption = res
                line_ids_vals.append({
                    "sheet_id": sheet.id,
                    "employee_id": employee.id,
                    "amount": exemption,
                    "withholding_amount": withholding,
                    "taxable_amount": taxable,
                    "nature_code": "274.75",
                })

            valid_payslips_81 = payslips.filtered(
                lambda p: p.struct_id.code == 'BEMONTHLY' and p.version_id.l10n_be_is_aid_zone
            )
            result_274_81_per_employee = sheet._get_274_81_values(valid_payslips_81, line_values, taxable_values)
            for employee, res in result_274_81_per_employee.items():
                taxable, withholding, exemption = res
                line_ids_vals.append({
                    'sheet_id': sheet.id,
                    'employee_id': employee.id,
                    'amount': exemption,
                    'withholding_amount': withholding,
                    'taxable_amount': taxable,
                    'nature_code': '274.81'
                })
            if payslips:
                extra_hours_vals, warning_msg = sheet._get_extra_hours_lines_ids(payslips, sheet.date_start, line_values)
                line_ids_vals += extra_hours_vals
                sheet.extra_hours_cap_warning = warning_msg

            sheet.line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in line_ids_vals]

    @api.depends('line_ids')
    def _compute_nature_line_ids(self):
        for sheet in self:
            sheet.line_274_10_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.10')
            sheet.line_274_13_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.13')
            sheet.line_274_18_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.18')
            sheet.line_274_20_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.20')
            sheet.line_274_30_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.30')
            sheet.line_274_32_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.32')
            sheet.line_274_33_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.33')
            sheet.line_274_34_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.34')
            sheet.line_274_56_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.56')
            sheet.line_274_62_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.62')
            sheet.line_274_64_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.64')
            sheet.line_274_74_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.74')
            sheet.line_274_75_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.75')
            sheet.line_274_81_ids = sheet.line_ids.filtered(lambda l: l.nature_code == '274.81')
            sheet.line_274_extra_hours_ids = sheet.line_ids.filtered(lambda l: l.nature_code in ['274.44', '274.55'])

    @api.depends('line_ids')
    def _compute_eligible_employee_count(self):
        for sheet in self:
            sheet.eligible_employee_count = len(set(sheet.line_ids.employee_id.mapped('employee_id').ids))

    @api.depends("training_employee_ids", "date_start")
    def _compute_training_seniority_warning(self):
        for sheet in self:
            if not sheet.date_start:
                sheet.l10n_be_training_seniority_warning_message = False
                continue
            new_employees = sheet.training_employee_ids.filtered(
                # Seniority of the chain of contracts at the start of the declaration (not of today's contract)
                lambda e: e.contract_date_start and (
                    e._get_first_contract_date(sheet.date_start) or e.contract_date_start
                ) > sheet.date_start - relativedelta(months=6),
            )
            if new_employees:
                sheet.l10n_be_training_seniority_warning_message = self.env._(
                    "The following employees have less than 6 months of seniority at the start date of this declaration and may not be eligible for the training exemption: %s",
                    ", ".join(new_employees.mapped("name")),
                )
            else:
                sheet.l10n_be_training_seniority_warning_message = False

    @api.depends('date_start', 'date_end', 'company_id', 'training_employee_ids', 'company_id.payroll_config_ids.onss_importance_code')
    def _compute_amounts(self):
        for sheet in self:

            sheet.pp_amount_10 = sum(line.withholding_amount for line in sheet.line_274_10_ids)
            sheet.taxable_amount_10 = sum(line.taxable_amount for line in sheet.line_274_10_ids)

            sheet.pp_amount_13 = sum(line.withholding_amount for line in sheet.line_274_13_ids)
            sheet.taxable_amount_13 = sum(line.taxable_amount for line in sheet.line_274_13_ids)

            sheet.pp_amount_18 = sum(line.withholding_amount for line in sheet.line_274_18_ids)
            sheet.taxable_amount_18 = sum(line.taxable_amount for line in sheet.line_274_18_ids)

            sheet.pp_amount_20 = sum(line.withholding_amount for line in sheet.line_274_20_ids)
            sheet.taxable_amount_20 = sum(line.taxable_amount for line in sheet.line_274_20_ids)

            sheet.pp_amount_30 = sum(line.withholding_amount for line in sheet.line_274_30_ids)
            sheet.taxable_amount_30 = sum(line.taxable_amount for line in sheet.line_274_30_ids)

            sheet.pp_amount_32 = sum(line.withholding_amount for line in sheet.line_274_32_ids)
            sheet.taxable_amount_32 = sum(line.taxable_amount for line in sheet.line_274_32_ids)
            sheet.deducted_amount_32 = sum(line.amount for line in sheet.line_274_32_ids)

            sheet.pp_amount_33 = sum(line.withholding_amount for line in sheet.line_274_33_ids)
            sheet.taxable_amount_33 = sum(line.taxable_amount for line in sheet.line_274_33_ids)
            sheet.deducted_amount_33 = sum(line.amount for line in sheet.line_274_33_ids)

            sheet.pp_amount_34 = sum(line.withholding_amount for line in sheet.line_274_34_ids)
            sheet.taxable_amount_34 = sum(line.taxable_amount for line in sheet.line_274_34_ids)
            # Use raw_amount here to get the uncapped total the cap below is based on.
            sheet.deducted_amount_34 = sum(line.raw_amount for line in sheet.line_274_34_ids)

            line_274_44_ids = sheet.line_274_extra_hours_ids.filtered(lambda l: l.nature_code == '274.44')
            line_274_55_ids = sheet.line_274_extra_hours_ids.filtered(lambda l: l.nature_code == '274.55')
            sheet.pp_amount_44 = sum(line.withholding_amount for line in line_274_44_ids)
            sheet.taxable_amount_44 = sum(line.taxable_amount for line in line_274_44_ids)
            sheet.deducted_amount_44 = sum(line.amount for line in line_274_44_ids)

            sheet.pp_amount_55 = sum(line.withholding_amount for line in line_274_55_ids)
            sheet.taxable_amount_55 = sum(line.taxable_amount for line in line_274_55_ids)
            sheet.deducted_amount_55 = sum(line.amount for line in line_274_55_ids)

            sheet.pp_amount_62 = sum(line.withholding_amount for line in sheet.line_274_62_ids)
            sheet.taxable_amount_62 = sum(line.taxable_amount for line in sheet.line_274_62_ids)
            sheet.deducted_amount_62 = sum(line.amount for line in sheet.line_274_62_ids)

            sheet.pp_amount_64 = sum(line.withholding_amount for line in sheet.line_274_64_ids)
            sheet.taxable_amount_64 = sum(line.taxable_amount for line in sheet.line_274_64_ids)
            sheet.deducted_amount_64 = sum(line.amount for line in sheet.line_274_64_ids)

            sheet.extra_hours_exempted_amount = sum(line.amount for line in (line_274_44_ids + line_274_55_ids))
            sheet.extra_exempted_rate = self.env['hr.rule.parameter']._get_parameter_from_code('l10n_be_extra_hours_exemption_rate', raise_if_not_found=False) or 0.12
            # The total amount of the exemption from payment of the withholding tax granted to
            # researchers who have a bachelor's degree is limited to a percentage of the total amount of
            # the exemption from the payment of the withholding tax granted to researchers who have
            # a diploma qualifying as a doctorate or Master. This percentage is 25% for companies with
            # 50 or more employees, and doubled to 50% for smaller ones (article 15 §§, 1 to 6 of the
            # Companies Code). Companies whose size is not configured default to the 25% rate.
            # https://www.belspo.be/belspo/organisation/fisc_dipl_fr.stm
            # Same min(raw, dm * rate) formula as the per-employee scaling in _compute_line_ids, keep both in sync.
            bachelor_rate = sheet._get_bachelor_exemption_rate(sheet.date_start)
            sheet.capped_amount_34 = min(
                sheet.deducted_amount_34,
                (sheet.deducted_amount_32 + sheet.deducted_amount_33) * bachelor_rate)

            sheet.pp_amount_74 = sum(line.withholding_amount for line in sheet.line_274_74_ids)
            sheet.taxable_amount_74 = sum(line.taxable_amount for line in sheet.line_274_74_ids)
            sheet.deducted_amount_74 = sum(line.amount for line in sheet.line_274_74_ids)

            sheet.pp_amount_75 = sum(line.withholding_amount for line in sheet.line_274_75_ids)
            sheet.taxable_amount_75 = sum(line.taxable_amount for line in sheet.line_274_75_ids)
            sheet.deducted_amount_75 = sum(line.amount for line in sheet.line_274_75_ids)

            sheet.pp_amount_81 = sum(line.withholding_amount for line in sheet.line_274_81_ids)
            sheet.taxable_amount_81 = sum(line.taxable_amount for line in sheet.line_274_81_ids)
            sheet.deducted_amount_81 = sum(line.amount for line in sheet.line_274_81_ids)

            # SME (Small/Middle Company) Exemption
            if sheet.company_id._get_payroll_config(sheet.date_start).l10n_be_ipa_reduction:
                sheet.sme_taxable_amount = sum(line.taxable_amount for line in sheet.line_274_56_ids)
                sme_rate_param = self.env['hr.rule.parameter']._get_parameter_from_code(
                    'sme_withholding_tax_exemption_rate', sheet.date_start, raise_if_not_found=False)
                exemption_cap_multiplier = self.env['hr.rule.parameter']._get_parameter_from_code(
                    'l10n_be_274_witholding_tax_exemption_multiplier', sheet.date_start, raise_if_not_found=False
                ) or 1.0
                sheet.sme_exemption_rate = sme_rate_param if sme_rate_param else 0.0012
                sheet.sme_exempted_amount = round(
                    sheet.sme_taxable_amount * sheet.sme_exemption_rate * exemption_cap_multiplier, 2
                )
            else:
                sheet.sme_taxable_amount = 0
                sheet.sme_exemption_rate = 0
                sheet.sme_exempted_amount = 0

            # Startup/M-E Exemption
            if sheet.is_cbe_expired or not sheet.company_id._get_payroll_config(sheet.date_start).exemption_sme_status:
                sheet.startup_exempted_amount = 0.0
                sheet.startup_amount_to_pay = 0.0
            else:
                rate = 0.10 if sheet.company_id._get_payroll_config(sheet.date_start).exemption_sme_status == 'startup' else 0.20
                sheet.startup_exempted_amount = sheet.pp_amount_10 * rate
                sheet.startup_amount_to_pay = sheet.pp_amount_10 - sheet.startup_exempted_amount

            sheet.total_pp_amount = sheet.pp_amount_10 + sheet.pp_amount_13 + sheet.pp_amount_20 + sheet.pp_amount_18 + sheet.pp_amount_30
            sheet.total_taxable_amount = sheet.taxable_amount_10 + sheet.taxable_amount_13 + sheet.taxable_amount_20 + sheet.taxable_amount_18 + sheet.taxable_amount_30

            sheet.deducted_amount = sheet.deducted_amount_32 + sheet.deducted_amount_33 + sheet.capped_amount_34 + sheet.deducted_amount_62 + sheet.deducted_amount_64 + sheet.deducted_amount_74 + sheet.deducted_amount_75 + sheet.sme_exempted_amount + sheet.startup_exempted_amount + sheet.deducted_amount_81 + sheet.extra_hours_exempted_amount
            sheet.amount_to_pay = max(0, sheet.total_pp_amount - sheet.deducted_amount)

    @api.depends('date_start', 'company_id.l10n_be_cbe_inscription')
    def _compute_cbe_expiration(self):
        for record in self:
            cbe_date = record.company_id.l10n_be_cbe_inscription

            if not cbe_date:
                record.is_cbe_expired = True
                continue

            today = fields.Date.context_today(self)
            year = int(record.year) if record.year else today.year
            month = int(record.month) if record.month else today.month
            reference_date = date(year, month, 1)
            start_period = (cbe_date + relativedelta(months=+1)).replace(day=1)
            expiration_date = start_period + relativedelta(months=+48)
            record.is_cbe_expired = reference_date >= expiration_date

    def action_generate_pdf(self):
        self.ensure_one()
        self._refresh_draft()
        report_data = {
            'company_name': self.company_id.name,
            'company_address': ' '.join([self.company_id.street or '', self.company_id.street2 or '']),
            'company_zip': self.company_id.zip,
            'company_city': self.company_id.city,
            'company_phone': self.company_id.phone,
            'date_start': self.date_start.strftime("%d/%m/%Y"),
            'date_end': self.date_end.strftime("%d/%m/%Y"),
        }

        filename = '%s-%s-274_XX.pdf' % (self.date_start.strftime("%d%B%Y"), self.date_end.strftime("%d%B%Y"))
        result = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            self.env.ref('l10n_be_hr_payroll.action_report_employee_274_10'),
            res_ids=self.ids, data=report_data)
        export_274_sheet_pdf = result[0]

        self.sheet_274_10_filename = filename
        self.sheet_274_10 = BinaryBytes(export_274_sheet_pdf)
        self.state = 'ready'
        message = _("PDF generation started. It will be available shortly.")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': message,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload'
                }
            }
        }

    def _to_eurocent(self, amount):
        return str(to_eurocent(amount))

    def _get_rendering_data(self):
        # https://finances.belgium.be/sites/default/files/downloads/Sp%C3%A9cification%20XML.doc
        result = {
            'creation_date': fields.Date.context_today(self).strftime("%Y-%m-%d"),
            'last_period': self.date_start.strftime("%y%m"),
            'declarations': [],
            'positive_amount': 0,
            'positive_total': 0,
            'negative_amount': 0,
            'negative_total': 0,
        }
        payslips = self._get_valid_payslips()

        # payslips must all originate from the same top_level company
        if len(set(payslips.mapped('company_id.root_id'))) > 1:
            raise UserError(_('The payslips should be from the same company.'))
        if not payslips:
            raise UserError(_('There is no valid payslip to declare.'))

        year_period_code = {
            2: '6',
            3: '7',
            0: '8',
            1: '9',
        }
        config = self.company_id._get_payroll_config(self.date_start)
        reference_number = config.l10n_be_company_number
        # payment reference - 12 Characters
        first_10_characters = "%s%s%s" % (
            reference_number[1:8], # 1 - 7
            year_period_code[payslips[0].date_from.year % 4],  # 8
            str(payslips[0].date_from.month).zfill(2), # 9-10
        )
        payment_reference = "%s%s" % (
            first_10_characters,
            str(int(first_10_characters) % 97 or 97).zfill(2),
        )
        self.payment_reference = "+++ %s / %s / %s +++" % (
            payment_reference[0:3],
            payment_reference[3:7],
            payment_reference[7:12],
        )
        date_from = payslips[0].date_from
        date_to = payslips[0].date_to
        district = config.l10n_be_revenue_code[:2]
        office = config.l10n_be_revenue_code[-2:]

        invalid_payslips = payslips.filtered(lambda p: p.date_from != date_from or p.date_to != date_to)
        if invalid_payslips:
            raise UserError(_('The payslips should cover the same period:\n%s', '\n'.join(invalid_payslips.mapped('name'))))

        declaration_10 = {
            'declaration_number': 10000010,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 10,
            'taxable_revenue': self.taxable_amount_10,
            'prepayment': self.pp_amount_10,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_13 = {
            'declaration_number': 10000013,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 13,
            'taxable_revenue': self.taxable_amount_13,
            'prepayment': self.pp_amount_13,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_18 = {
            'declaration_number': 10000018,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 18,
            'taxable_revenue': self.taxable_amount_18,
            'prepayment': self.pp_amount_18,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_20 = {
            'declaration_number': 10000020,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 20,
            'taxable_revenue': self.taxable_amount_20,
            'prepayment': self.pp_amount_20,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_30 = {
            'declaration_number': 10000030,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 30,
            'taxable_revenue': self.taxable_amount_30,
            'prepayment': self.pp_amount_30,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_32 = {
            'declaration_number': 10000032,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 32,
            'taxable_revenue': self.taxable_amount_32,
            'prepayment': -self.deducted_amount_32,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_33 = {
            'declaration_number': 10000033,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 33,
            'taxable_revenue': self.taxable_amount_33,
            'prepayment': -self.deducted_amount_33,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_34 = {
            'declaration_number': 10000034,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 34,
            'taxable_revenue': self.taxable_amount_34,
            'prepayment': -self.capped_amount_34,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_44 = {
            'declaration_number': 10000044,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 44,
            'taxable_revenue': self.taxable_amount_44,
            'prepayment': -self.deducted_amount_44,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_55 = {
            'declaration_number': 10000055,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 55,
            'taxable_revenue': self.taxable_amount_55,
            'prepayment': -self.deducted_amount_55,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_56 = {
            'declaration_number': 10000056,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 56,
            'taxable_revenue': self.sme_taxable_amount,
            'prepayment': -self.sme_exempted_amount,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_62 = {
            'declaration_number': 10000062,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 62,
            'taxable_revenue': self.taxable_amount_62,
            'prepayment': -self.deducted_amount_62,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_64 = {
            'declaration_number': 10000064,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 64,
            'taxable_revenue': self.taxable_amount_64,
            'prepayment': -self.deducted_amount_64,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_74 = {
            'declaration_number': 10000074,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 74,
            'taxable_revenue': self.taxable_amount_74,
            'prepayment': -self.deducted_amount_74,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_75 = {
            'declaration_number': 10000075,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 75,
            'taxable_revenue': self.taxable_amount_75,
            'prepayment': -self.deducted_amount_75,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }
        declaration_81 = {
            'declaration_number': 10000081,
            'reference_number': reference_number,
            'year': date_from.strftime("%Y"),
            'period': '%s00' % (date_from.strftime("%m")),
            'revenue_nature': 81,
            'taxable_revenue': self.taxable_amount_81,
            'prepayment': -self.deducted_amount_81,
            'payment_reference': payment_reference,
            'district': district,
            'office': office,
        }

        declarations = [declaration_10, declaration_13, declaration_18, declaration_20, declaration_30, declaration_32, declaration_33, declaration_34, declaration_44, declaration_55, declaration_56, declaration_62, declaration_64, declaration_74, declaration_75, declaration_81]

        status_mapping = {'startup': 60, 'micro': 61}
        revenue_nature_startup = status_mapping.get(self.exemption_sme_status, False)
        declaration_6x = False
        if revenue_nature_startup and self.startup_exempted_amount > 0:
            declaration_6x = {
                'declaration_number': 10000000 + revenue_nature_startup,
                'reference_number': reference_number,
                'year': date_from.strftime("%Y"),
                'period': '%s00' % (date_from.strftime("%m")),
                'revenue_nature': revenue_nature_startup,
                'taxable_revenue': self.taxable_amount_10,
                'prepayment': -self.startup_exempted_amount,
                'payment_reference': payment_reference,
                'district': district,
                'office': office,
            }
            declarations.append(declaration_6x)

        result['positive_amount'] = len([d for d in declarations if d['prepayment'] >= 0])
        result['negative_amount'] = len([d for d in declarations if d['prepayment'] < 0])
        result['positive_total'] = str(
            sum(int(self._to_eurocent(d['prepayment']))
                for d in declarations if d['prepayment'] >= 0)
        )
        result['negative_total'] = str(
            sum(int(self._to_eurocent(d['prepayment']))
                for d in declarations if d['prepayment'] < 0)
        )
        for declaration in declarations:
            declaration['prepayment'] = self._to_eurocent(declaration['prepayment'])
            declaration['taxable_revenue'] = self._to_eurocent(declaration['taxable_revenue'])

        result['declarations'] = declarations
        return result

    def action_generate_xml(self):
        self._refresh_draft()
        filename = '%s-%s-finprof.xml' % (self.date_start.strftime("%d%B%Y"), self.date_end.strftime("%d%B%Y"))
        self.xml_filename = filename

        xml_str = self.env['ir.qweb']._render('l10n_be_hr_payroll.finprof_xml_report',
            self._get_rendering_data())

        # Prettify xml string
        root = etree.fromstring(xml_str, parser=etree.XMLParser(remove_blank_text=True))
        xml_formatted_str = etree.tostring(root, pretty_print=True, encoding='utf-8', xml_declaration=True)

        self.xml_file = BinaryBytes(xml_formatted_str)

        self.state = 'ready'
        message = _("XML generation started. It will be available shortly.")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': message,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload'
                }
            }
        }

    def action_generate_xls(self):
        self._refresh_draft()
        output = io.BytesIO()
        import xlsxwriter  # noqa: PLC0415
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        summary_worksheet = workbook.add_worksheet(self.env._('Exemption Summary'))
        if self.line_274_13_ids:
            unemployment_worksheet = workbook.add_worksheet(self.env._('Temporary Unemployment (274.13)'))
        replacement_revenue_worksheet = workbook.add_worksheet(self.env._('Replacement Revenues (274.18)'))
        if self.line_274_30_ids:
            presence_tokens_worksheet = workbook.add_worksheet(self.env._('Presence Tokens (274.30)'))
        doctors_worksheet = workbook.add_worksheet(self.env._('Doctors / Civil Engineers (274.32)'))
        masters_worksheet = workbook.add_worksheet(self.env._('Masters (274.33)'))
        bachelors_worksheet = workbook.add_worksheet(self.env._('Bachelors (274.34)'))
        aid_zone_worksheet = workbook.add_worksheet(self.env._('Aid Zone (274.81)'))
        extra_hours_worksheet = workbook.add_worksheet(self.env._('Extra Hours'))
        if self.is_ipa_reduction:
            ipa_worksheet = workbook.add_worksheet(self.env._('SME Exemption (274.56)'))
        if self.exemption_sme_status and not self.is_cbe_expired:
            startup_worksheet = workbook.add_worksheet(self.env._('Start-up (274.60) - M-E (275.61)'))
        starterjob_worksheet = workbook.add_worksheet(self.env._('Starterjob (274.62)'))
        training_worksheet = workbook.add_worksheet(self.env._('Training (274.64)'))
        team_shift_worksheet = workbook.add_worksheet(self.env._('(Continuous) Team Shifts (274.74)'))
        night_shift_worksheet = workbook.add_worksheet(self.env._('Night Shifts (274.75)'))

        style_header = workbook.add_format({'bold': True, 'pattern': 1, 'bg_color': '#E0E0E0', 'align': 'center'})
        style_vertical_header = workbook.add_format({'bold': True, 'pattern': 1, 'bg_color': '#E0E0E0', 'align': 'center', 'bottom': 1, 'right': 1})
        style_normal = workbook.add_format({'align': 'center'})
        style_currency = workbook.add_format({'align': 'center', 'num_format': '#,##0.00 €'})
        style_percentage = workbook.add_format({'num_format': '0.00%', 'align': 'center'})

        summary_headers = self.env._("Exempted Amounts")
        summary_worksheet.write(0, 0, summary_headers, style_header)
        summary_worksheet.write(0, 1, "", style_header)
        summary_worksheet.set_column(0, 1, 30)

        summary_data = {
            "274.34": {
                'header': self.env._("Bachelors (274.34)"),
                'value': self.capped_amount_34,
            },
            "274.33": {
                'header': self.env._("Masters (274.33)"),
                'value': self.deducted_amount_33,
            },
            "274.32": {
                'header': self.env._("Doctors / Civil Engineers (274.32)"),
                'value': self.deducted_amount_32,
            },
            "274.44": {
                'header': self.env._("Extra Hours (274.44)"),
                'value': self.deducted_amount_44,
            },
            "274.55": {
                'header': self.env._("Extra Hours (274.55)"),
                'value': self.deducted_amount_55,
            },
            "274.64": {
                'header': self.env._("Training (274.64)"),
                'value': self.deducted_amount_64,
            },
            "274.74": {
                'header': self.env._("(Continuous) Team Shifts (274.74)"),
                'value': self.deducted_amount_74,
            },
            "274.75": {
                'header': self.env._("Night Shifts (274.75)"),
                'value': self.deducted_amount_75,
            },
            "274.81": {
                'header': self.env._("Aid Zone (274.81)"),
                'value': self.deducted_amount_81,
            },
            "274.62": {
                'header': self.env._("Starterjob (274.62)"),
                'value': self.deducted_amount_62,
            },
        }
        if self.exemption_sme_status and not self.is_cbe_expired:
            summary_data["274.6"] = {
                'header': self.env._("Start-up (274.60) / M-E (274.61)"),
                'value': self.startup_exempted_amount,
            }
        summary_data["total"] = {
            'header': self.env._("Total"),
            'value': self.deducted_amount,
        }

        for row, data in enumerate(summary_data.values(), start=1):
            summary_worksheet.write(row, 0, data['header'], style_vertical_header)
            summary_worksheet.write(row, 1, data['value'], style_normal)

        if self.is_ipa_reduction:
            ipa_worksheet.set_column(0, 3, 30)
            ipa_headers = [
                self.env._("IPA Reductions"),
                self.env._("Taxable Amount"),
                self.env._("Exemption Rate"),
                self.env._("Exempted Amount")
            ]
            ipa_data = {
                '274.56': {
                    'header': self.env._("SME Exemption (274.56)"),
                    'taxable_amount': self.sme_taxable_amount,
                    'rate': self.sme_exemption_rate,
                    'exempted_amount': self.sme_exempted_amount,
                }
            }
            for col, header in enumerate(ipa_headers):
                ipa_worksheet.write(0, col, header, style_header)
                ipa_worksheet.set_column(col, col, 30)
            for row, ipa_row in enumerate(ipa_data.values(), start=1):
                for col, key in enumerate(['header', 'taxable_amount', 'rate', 'exempted_amount']):
                    if key == 'rate':
                        ipa_worksheet.write(row, col, ipa_row[key], style_percentage)
                    elif key == 'taxable_amount' or key == 'exempted_amount':
                        ipa_worksheet.write(row, col, ipa_row[key], style_currency)
                    else:
                        ipa_worksheet.write(row, col, ipa_row[key], style_normal)
        if self.exemption_sme_status and not self.is_cbe_expired:
            startup_worksheet.set_column(0, 4, 30)
        starterjob_worksheet.set_column(0, 4, 30)
        startup_headers = [
            self.env._("Exemption Category"),
            self.env._("Taxable Amount"),
            self.env._("Withholding Taxes"),
            self.env._("Exempted Amount"),
            self.env._("Amount to Pay")
        ]
        for col, header in enumerate(startup_headers):
            if self.exemption_sme_status and not self.is_cbe_expired:
                startup_worksheet.write(0, col, header, style_header)
            starterjob_worksheet.write(0, col, header, style_header)
        startup_row = {
            'header': self.env._("Start-up / Micro-enterprise Exemption"),
            'taxable_amount': self.taxable_amount_10,
            'withholding_taxes': self.pp_amount_10,
            'exempted_amount': self.startup_exempted_amount,
            'amount_to_pay': self.startup_amount_to_pay,
        }
        starterjob_row = {
            'header': self.env._("Starterjob"),
            'taxable_amount': self.taxable_amount_62,
            'withholding_taxes': self.pp_amount_62,
            'exempted_amount': self.deducted_amount_62,
            'amount_to_pay': self.pp_amount_62 - self.deducted_amount_62
        }
        fields_order = ['header', 'taxable_amount', 'withholding_taxes', 'exempted_amount', 'amount_to_pay']
        for col, key in enumerate(fields_order):
            if key == 'header':
                if self.exemption_sme_status and not self.is_cbe_expired:
                    startup_worksheet.write(1, col, startup_row[key], style_normal)
                starterjob_worksheet.write(1, col, starterjob_row[key], style_normal)
            else:
                if self.exemption_sme_status and not self.is_cbe_expired:
                    startup_worksheet.write(1, col, startup_row[key], style_currency)
                starterjob_worksheet.write(1, col, starterjob_row[key], style_currency)

        nature_headers = [
            self.env._("Full Name"),
            self.env._("National Number"),
            self.env._("Department"),
            self.env._("Entry Date"),
            self.env._("Departure Date"),
            self.env._("Certificate"),
            self.env._("Position"),
            self.env._("Scientific Research %"),
            self.env._("Nature"),
            self.env._("Taxable Amount"),
            self.env._("Professional Withholding Tax"),
            self.env._("Scientific Research Withholding Exemption"),
        ]
        certificate_selection_vals = {
            elem[0]: elem[1] for elem in self.env['hr.employee']._fields['certificate']._description_selection(self.env)
        }

        def _write_employee_data(line_ids, worksheet):
            rows = []
            for line in line_ids:
                employee = line.employee_id.sudo()
                rows.append((
                    employee.legal_name,
                    employee.version_id.identification_id,
                    employee.department_id.name or employee.version_id.department_id.name,
                    employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else '',
                    employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else '',
                    certificate_selection_vals.get(employee.certificate, ''),
                    employee.job_title or employee.job_id.name,
                    employee.version_id.rd_percentage,
                    line.nature_code,
                    line.taxable_amount,
                    line.withholding_amount,
                    line.amount,
                ))

            for col, header in enumerate(nature_headers):
                worksheet.write(0, col, header, style_header)
                worksheet.set_column(col, col, 30)

            for row, employee_row in enumerate(rows, start=1):
                for col, employee_data in enumerate(employee_row):
                    if col == 7:
                        worksheet.write(row, col, employee_data, style_percentage)
                    else:
                        worksheet.write(row, col, employee_data, style_normal)

        _write_employee_data(self.line_274_32_ids, doctors_worksheet)
        _write_employee_data(self.line_274_33_ids, masters_worksheet)
        _write_employee_data(self.line_274_34_ids, bachelors_worksheet)
        _write_employee_data(self.line_274_extra_hours_ids, extra_hours_worksheet)

        # 274.18 (Replacement Revenues)
        rr_headers = [
            self.env._("Full Name"),
            self.env._("National Number"),
            self.env._("Department"),
            self.env._("Entry Date"),
            self.env._("Departure Date"),
            self.env._("Position"),
            self.env._("Nature"),
            self.env._("Taxable Amount"),
            self.env._("Professional Withholding Tax"),
        ]
        for col, header in enumerate(rr_headers):
            replacement_revenue_worksheet.write(0, col, header, style_header)
            replacement_revenue_worksheet.set_column(col, col, 30)

        for row, line in enumerate(self.line_274_18_ids, start=1):
            employee = line.employee_id.sudo()
            rr_row = (
                employee.legal_name,
                employee.version_id.identification_id,
                employee.department_id.name or employee.version_id.department_id.name,
                employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else '',
                employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else '',
                employee.job_title or employee.job_id.name,
                line.nature_code,
                line.taxable_amount,
                line.withholding_amount,
            )
            for col, value in enumerate(rr_row):
                style = style_currency if col in (7, 8) else style_normal
                replacement_revenue_worksheet.write(row, col, value, style)

        # 274.64 (Worker training) employees are manually selected and are not
        # tied to a certificate / scientific-research percentage, so they use a
        # dedicated set of columns.
        training_headers = [
            self.env._("Full Name"),
            self.env._("National Number"),
            self.env._("Department"),
            self.env._("Entry Date"),
            self.env._("Departure Date"),
            self.env._("Position"),
            self.env._("Nature"),
            self.env._("Taxable Amount"),
            self.env._("Training Withholding Exemption"),
        ]
        for col, header in enumerate(training_headers):
            training_worksheet.write(0, col, header, style_header)
            training_worksheet.set_column(col, col, 30)
        for row, line in enumerate(self.line_274_64_ids, start=1):
            employee = line.employee_id.sudo()
            training_row = (
                employee.legal_name,
                employee.version_id.identification_id,
                employee.department_id.name or employee.version_id.department_id.name,
                employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else '',
                employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else '',
                employee.job_title or employee.job_id.name,
                line.nature_code,
                line.taxable_amount,
                line.amount,
            )
            for col, value in enumerate(training_row):
                style = style_currency if col in (7, 8) else style_normal
                training_worksheet.write(row, col, value, style)

        # 274.74 (Team Shifts)
        team_shifts_headers = [
            self.env._("Full Name"),
            self.env._("National Number"),
            self.env._("Department"),
            self.env._("Entry Date"),
            self.env._("Departure Date"),
            self.env._("Position"),
            self.env._("Nature"),
            self.env._("Taxable Amount"),
            self.env._("Team Shifts Withholding Exemption"),
        ]
        for col, header in enumerate(team_shifts_headers):
            team_shift_worksheet.write(0, col, header, style_header)
            team_shift_worksheet.set_column(col, col, 30)
        for row, line in enumerate(self.line_274_74_ids, start=1):
            employee = line.employee_id.sudo()
            team_shift_row = (
                employee.legal_name,
                employee.version_id.identification_id,
                employee.department_id.name or employee.version_id.department_id.name,
                employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else '',
                employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else '',
                employee.job_title or employee.job_id.name,
                line.nature_code,
                line.taxable_amount,
                line.amount,
            )
            for col, value in enumerate(team_shift_row):
                style = style_currency if col in (7, 8) else style_normal
                team_shift_worksheet.write(row, col, value, style)

        # 274.74 (Night Shifts)
        night_shifts_headers = [
            self.env._("Full Name"),
            self.env._("National Number"),
            self.env._("Department"),
            self.env._("Entry Date"),
            self.env._("Departure Date"),
            self.env._("Position"),
            self.env._("Nature"),
            self.env._("Taxable Amount"),
            self.env._("Night Shifts Withholding Exemption"),
        ]
        for col, header in enumerate(night_shifts_headers):
            night_shift_worksheet.write(0, col, header, style_header)
            night_shift_worksheet.set_column(col, col, 30)
        for row, line in enumerate(self.line_274_75_ids, start=1):
            employee = line.employee_id.sudo()
            night_shift_row = (
                employee.legal_name,
                employee.version_id.identification_id,
                employee.department_id.name or employee.version_id.department_id.name,
                employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else '',
                employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else '',
                employee.job_title or employee.job_id.name,
                line.nature_code,
                line.taxable_amount,
                line.amount,
            )
            for col, value in enumerate(night_shift_row):
                style = style_currency if col in (7, 8) else style_normal
                night_shift_worksheet.write(row, col, value, style)

        # 274.81 (Aid Zone) employees are not tied to a certificate or R&D %
        # so they use a dedicated set of headers.
        aid_zone_headers = [
            self.env._("Full Name"),
            self.env._("National Number"),
            self.env._("Department"),
            self.env._("Entry Date"),
            self.env._("Departure Date"),
            self.env._("Position"),
            self.env._("Nature"),
            self.env._("Taxable Amount"),
            self.env._("Professional Withholding Tax"),
            self.env._("Aid Zone withholding exemption"),
        ]
        for col, header in enumerate(aid_zone_headers):
            aid_zone_worksheet.write(0, col, header, style_header)
            aid_zone_worksheet.set_column(col, col, 30)

        for row, line in enumerate(self.line_274_81_ids, start=1):
            employee = line.employee_id.sudo()
            aid_zone_row = (
                employee.legal_name,
                employee.version_id.identification_id,
                employee.department_id.name or employee.version_id.department_id.name,
                employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else '',
                employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else '',
                employee.job_title or employee.job_id.name,
                line.nature_code,
                line.taxable_amount,
                line.withholding_amount,
                line.amount,
            )
            for col, value in enumerate(aid_zone_row):
                style = style_currency if col in (7, 8, 9) else style_normal
                aid_zone_worksheet.write(row, col, value, style)

        # unemployment sheet 274.13
        if self.line_274_13_ids:
            unemployment_headers = [
                self.env._("Full Name"),
                self.env._("Working Start Date"),
                self.env._("Working End Date"),
                self.env._("Taxable Amount"),
                self.env._("Withholding Amount"),
                self.env._("Amount"),
                self.env._("Nature Code"),
            ]

            for col, header in enumerate(unemployment_headers):
                unemployment_worksheet.write(0, col, header, style_header)
                unemployment_worksheet.set_column(col, col, 30)

            for row, line in enumerate(self.line_274_13_ids, start=1):
                employee = line.employee_id.sudo()

                start_date = employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else ''
                end_date = employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else ''

                unemployment_worksheet.write(row, 0, employee.legal_name, style_normal)
                unemployment_worksheet.write(row, 1, start_date, style_normal)
                unemployment_worksheet.write(row, 2, end_date, style_normal)
                unemployment_worksheet.write(row, 3, line.taxable_amount, style_currency)
                unemployment_worksheet.write(row, 4, line.withholding_amount, style_currency)
                unemployment_worksheet.write(row, 5, line.amount, style_currency)
                unemployment_worksheet.write(row, 6, line.nature_code, style_normal)

        if self.line_274_30_ids:
            presence_tokens_headers = [
                self.env._("Full Name"),
                self.env._("Working Start Date"),
                self.env._("Working End Date"),
                self.env._("Taxable Amount"),
                self.env._("Withholding Amount"),
            ]

            for col, header in enumerate(presence_tokens_headers):
                presence_tokens_worksheet.write(0, col, header, style_header)
                presence_tokens_worksheet.set_column(col, col, 30)

            for row, line in enumerate(self.line_274_30_ids, start=1):
                employee = line.employee_id.sudo()

                start_date = employee.contract_date_start.strftime("%d-%m-%Y") if employee.contract_date_start else ''
                end_date = employee.departure_date.strftime("%d-%m-%Y") if employee.departure_date else ''

                presence_tokens_worksheet.write(row, 0, employee.legal_name, style_normal)
                presence_tokens_worksheet.write(row, 1, start_date, style_normal)
                presence_tokens_worksheet.write(row, 2, end_date, style_normal)
                presence_tokens_worksheet.write(row, 3, line.taxable_amount, style_currency)
                presence_tokens_worksheet.write(row, 4, line.withholding_amount, style_currency)

        workbook.close()
        xlsx_data = output.getvalue()
        self.xls_file = BinaryBytes(xlsx_data)
        self.xls_filename = "withholding_tax_exemption_details.xlsx"
        self.state = 'ready'
        message = _("XLSX generation started. It will be available shortly.")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': message,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload'
                }
            }
        }

    def action_generate_xml_and_download_data(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_generate_xml()
        return {
            'model': self._name,
            'id': self.id,
            'field': 'xml_file',
            'filename': self.xml_filename,
            'filename_field': 'xml_filename',
            'download': True,
        }

    def action_force_done(self):
        # Used by the dashboard warning, which files the declaration without its Belcotax reference.
        self.ensure_one()
        self.state = 'done'

    def action_mark_done(self):
        self.ensure_one()
        if not self.belcotax_reference:
            raise UserError(_("Please provide the Belcotax reference to validate this declaration."))
        if self.parent_id:
            self.parent_id.is_correction_needed = False
        self.state = 'done'

    def action_correct_274(self):
        self.ensure_one()
        if not self.belcotax_reference:
            raise UserError(_("The declaration can't be corrected without the reference from Belcotax."))
        return {
            'name': _("274.XX Modification"),
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_declaration_type': 'modification',
                'default_year': self.year,
                'default_month': self.month,
                'default_quarter': self.quarter,
                'default_parent_id': self.id,
            },
        }

    def action_cancel_274(self):
        self.search([('id', 'child_of', self.ids)]).state = 'canceled'

    @api.ondelete(at_uninstall=False)
    def _unlink_except_filed(self):
        if any(sheet.state != 'draft' for sheet in self):
            raise UserError(_("Only draft declarations can be deleted."))


class L10n_Be274_XxLine(models.Model):
    _name = 'l10n_be.274_xx.line'
    _description = '274.XX Sheets Line'
    _rec_name = 'employee_id'

    sheet_id = fields.Many2one('l10n_be.274_xx', index=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', index='btree_not_null')
    certificate = fields.Selection(related='employee_id.certificate', string="Certificate Level")
    nature_code = fields.Char(string="Nature Code")
    rd_percentage = fields.Float(related='employee_id.rd_percentage', string="Time in R&D (%)")
    taxable_amount = fields.Monetary()
    amount = fields.Monetary(string="Exempted Amount")
    raw_amount = fields.Monetary(
        string="Raw Exempted Amount",
        help="Only set for 274.34 (bachelor) lines: the exempted amount before the cap is applied.")
    withholding_amount = fields.Monetary()
    company_id = fields.Many2one('res.company', related='sheet_id.company_id')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    start_date = fields.Date(related='employee_id.contract_date_start')
    end_date = fields.Date(related='employee_id.contract_date_end')
    extra_exempted_rate = fields.Float(related='sheet_id.extra_exempted_rate', string="Extra Hours Exemption Rate")
    paid_withholding_tax = fields.Monetary(compute='_compute_paid_withholding_tax', string="Paid Withholding Tax")

    @api.depends('withholding_amount', 'amount')
    def _compute_paid_withholding_tax(self):
        for line in self:
            line.paid_withholding_tax = line.withholding_amount - line.amount
