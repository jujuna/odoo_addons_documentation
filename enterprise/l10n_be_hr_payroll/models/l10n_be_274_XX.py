# Part of Odoo. See LICENSE file for full copyright and licensing details.

import io
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import BinaryBytes, float_is_zero, format_amount, format_date
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
    line_274_30_ids = fields.One2many('l10n_be.274_xx.line', 'sheet_id', compute='_compute_nature_line_ids', compute_sudo=True, string="Presence Tokens")
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
    l10n_be_complementary_indemnity_warning = fields.Char(compute='_compute_complementary_indemnity_warning')
    l10n_be_negative_amounts_warning = fields.Text(compute='_compute_negative_amounts_warning')

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
    startup_taxable_amount = fields.Monetary(compute="_compute_amounts", compute_sudo=True)
    startup_withholding_amount = fields.Monetary(compute="_compute_amounts", compute_sudo=True)
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

    def _get_negative_amounts_anomalies(self):
        """The amounts of the declaration that Finprof refuses or may refuse.

        :return: (the blocking anomalies, the other ones): Finprof refuses a negative income nature
            (274.10 to 274.30) and exemptions exceeding the withholding tax; a negative exemption
            (a regularisation) is only reported.
        :rtype: tuple(list[str], list[str])
        """
        self.ensure_one()

        def is_negative(amount):
            return self.currency_id.compare_amounts(amount, 0.0) < 0

        def fmt(amount):
            return format_amount(self.env, amount, self.currency_id)

        blocking, others = [], []
        for nature in ['10', '13', '18', '20', '30']:
            taxable = self[f'taxable_amount_{nature}']
            pp_amount = self[f'pp_amount_{nature}']
            if is_negative(taxable) or is_negative(pp_amount):
                blocking.append(self.env._(
                    "- Nature 274.%(nature)s: Taxable Amount = %(taxable)s, Withholding Tax = %(pp)s",
                    nature=nature, taxable=fmt(taxable), pp=fmt(pp_amount),
                ))

        if is_negative(self.total_taxable_amount) or is_negative(self.total_pp_amount):
            blocking.append(self.env._(
                "- Totals: Taxable Amount = %(taxable)s, Withholding Tax = %(pp)s",
                taxable=fmt(self.total_taxable_amount), pp=fmt(self.total_pp_amount),
            ))

        # A negative withholding tax is already reported above
        if (
            not is_negative(self.total_pp_amount)
            and self.currency_id.compare_amounts(self.deducted_amount, self.total_pp_amount) > 0
        ):
            blocking.append(self.env._(
                "- Exemptions (%(deductions)s) exceed the withholding tax (%(pp)s)",
                deductions=fmt(self.deducted_amount), pp=fmt(self.total_pp_amount),
            ))

        # The taxable base and the exempted amount each exemption nature declares in the XML
        exemption_natures = [
            (nature, self[f'taxable_amount_{nature}'], self[f'deducted_amount_{nature}'])
            for nature in ['32', '33', '44', '55', '62', '64', '74', '75', '81']
        ] + [
            ('34', self.taxable_amount_34, self.capped_amount_34),
            ('56', self.sme_taxable_amount, self.sme_exempted_amount),
            ('60/61', self.startup_taxable_amount, self.startup_exempted_amount),
        ]
        for nature, taxable, deducted in exemption_natures:
            if is_negative(taxable) or is_negative(deducted):
                others.append(self.env._(
                    "- Exemption 274.%(nature)s: Taxable Base = %(taxable)s, Exempted Amount = %(deducted)s",
                    nature=nature, taxable=fmt(taxable), deducted=fmt(deducted),
                ))
        return blocking, others

    @api.depends('line_ids', 'date_start', 'date_end', 'company_id')
    def _compute_negative_amounts_warning(self):
        for sheet in self:
            blocking, others = sheet._get_negative_amounts_anomalies()
            if not blocking and not others:
                sheet.l10n_be_negative_amounts_warning = False
                continue
            message = self.env._("This declaration has negative amounts:") + '\n' + '\n'.join(blocking + others)
            if blocking:
                message += '\n\n' + self.env._(
                    "Finprof refuses the negative income natures and the exemptions exceeding the withholding tax: "
                    "the XML file cannot be generated.")
            sheet.l10n_be_negative_amounts_warning = message + '\n' + self.env._(
                "Correct the original period through a modification declaration.")

    def _check_negative_amounts(self):
        """Raise if Finprof refuses the declaration: a negative income nature, or exemptions exceeding the
        withholding tax. A negative exemption is only shown in the warning of the declaration."""
        self.ensure_one()
        blocking, _others = self._get_negative_amounts_anomalies()
        if blocking:
            raise UserError(self.env._(
                "Finprof refuses a declaration with negative amounts. Please fix the following issues:\n\n%(issues)s\n\n"
                "Correct the original period through a modification declaration.",
                issues='\n'.join(blocking),
            ))

    @api.constrains('company_id')
    def _check_l10n_be_company_number(self):
        for sheet in self:
            config = sheet.company_id._get_payroll_config(sheet.date_start)
            if not config.l10n_be_company_number or not config.l10n_be_revenue_code:
                raise ValidationError(_("Please configure the 'Company Number' and the 'Revenue Code' in Payroll > Configuration > Company data."))

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
        # The base is read from the payslips of the declaration, for the amounts attached to its period: the
        # remunerations (IPA_REDUCTION_BASE), the taxable salary without social security contributions
        # (TAXABLE_NO_ONSS), the benefits in kind taxable but not subject to the social security contributions (the
        # company car, the miscellaneous ones such as the meal vouchers taken over by the employer), the guaranteed
        # salary of a work accident (WORK_ACCIDENT), the taxable fuel card of the commute and the taxable part of the
        # private car commuting allowance (above its withholding tax exemption), and the termination indemnities (their gross amounts on the termination fees
        # payslips, without the ONSS), and the
        # taxable amounts of the natures 13 and 18 (the complements of unemployment and of sickness paid by the
        # employer). The holiday pays (double holiday pay, holiday pays on departure), the bonuses and the warrants
        # are part of it with their gross amounts: their withholding tax bases without the ONSS, and without the lines
        # already in the social security base (SALARY) of the monthly payslip. The base of a Horeca occasional worker
        # is its flat wage (SALARY), with the premiums taxed at the scale it covers (HORECA_OCC_SCALE_PREMIUM_FLAT, as
        # a taxable salary without social security contributions). The pay of the flexi-jobs is exempted from the tax:
        # they are in the base for the taxable part of their private car allowance and their taxable amounts without
        # social security contributions only.
        # The amounts paid net, without ONSS nor withholding tax, are out of the base: the commuting allowances
        # exempted from the tax (public transport, train, third party payer, bicycle) and the exempted part of the
        # private car allowance, as the balance of the mobility budget paid in cash (MOBILITY_TO_PAY, pillar 3),
        # without withholding tax (only its special social security contribution).
        category_codes = (
            *self.env['hr.payslip']._get_child_category_ids('IPA_REDUCTION_BASE'),
            'TERMINATION_HOLIDAY_WITHHOLDING_BASE', 'TAXABLE_13', 'TAXABLE_18',
        )
        # the ONSS of the employee and the employment bonus (a reduction of it)
        onss_rules = self.env['hr.salary.rule'].with_context(active_test=False).search(
            Domain('category_ids.code', 'in', ('ONSS', 'ONSS_BASE')) | Domain('code', '=', 'EmpBonus.1.FALLBACK'))
        exempted_commuting_rules = self.env['hr.salary.rule'].with_context(active_test=False).search(
            [('category_ids.code', '=', 'EXEMPTED_COMMUTING')])
        flexi_payslips = payslips.filtered(lambda p: p.version_id.is_flexi())
        termination_payslips = payslips.filtered(lambda p: p.struct_id.code == 'BETERM')
        # the bonuses of the CCT 90 are exempted from the withholding tax: out of the base, as their ONSS
        cct90_payslips = payslips.filtered(lambda p: p.struct_id.code == 'BECCT90')
        fiscal_line_domain = self.env['hr.payslip']._l10n_be_get_fiscal_line_domain(self.date_start, self.date_end)
        taxable_amount_by_employee = dict(self.env['hr.payslip.line']._read_group(
            Domain('slip_id', 'in', (payslips - cct90_payslips).ids)
            & (
                (Domain('salary_rule_id.category_ids.code', 'in', category_codes)
                 & Domain('salary_rule_id', 'not in', onss_rules.ids)
                 & Domain('salary_rule_id', 'not in', exempted_commuting_rules.ids)
                 & Domain('salary_rule_id.code', '!=', 'CAR.PRIV')
                 & Domain('slip_id', 'not in', flexi_payslips.ids))
                | Domain('salary_rule_id.code', 'in', (
                    'TAXABLE_NO_ONSS', 'ATN.CAR', 'ATNCARREGUL', 'ATN_MISC_NO_ONSS', 'WORK_ACCIDENT',
                    'FUEL_CARD_COMMUTE', 'HORECA_OCC_SCALE_PREMIUM_FLAT'))
                | (Domain('slip_id', 'in', termination_payslips.ids)
                   & Domain('salary_rule_id.category_ids.code', '=', 'TERMINATION_WITHHOLDING_BASE')
                   & Domain('salary_rule_id.code', '!=', 'ONSS_TERM'))
            )
            & fiscal_line_domain,
            ['employee_id'], ['total:sum'],
        ))
        # The private car commuting allowance is exempted from the withholding tax up to a monthly amount: only its
        # taxable part is in the base
        private_car_lines = self.env['hr.payslip.line'].search(
            Domain('slip_id', 'in', (payslips - cct90_payslips).ids) & Domain('code', '=', 'CAR.PRIV') & fiscal_line_domain)
        for line in private_car_lines:
            exemption = self.env['hr.rule.parameter']._get_parameter_from_code(
                'private_car_withholding_monthly_exemption', line.slip_id.date_to, raise_if_not_found=False) or 0.0
            taxable_amount_by_employee[line.employee_id] = (
                taxable_amount_by_employee.get(line.employee_id, 0.0) + max(0.0, line.total - exemption))
        result_per_employee = {}
        for employee in payslips.employee_id:
            taxable_amount = taxable_amount_by_employee.get(employee, 0.0)
            result_per_employee[employee] = (
                taxable_amount,
                taxable_amount * sme_exemption_rate * exemption_cap_multiplier,
            )
        return result_per_employee

    @api.model
    def _get_exemption_withholding_tax(self, payslips, line_values, voluntary=False):
        # The withholding tax that the exemptions can reduce, as in the salary rule of the 274.81: the one of the
        # remuneration, without the ones of the replacement incomes (the flat-rate taxes of the economic unemployment
        # supplements, 274.13, and of the other replacement incomes), of the double holiday pay and of the presence
        # tokens, as the payslips cap them (_get_team_night_274_74_75_exemptions). PPTOTAL is the total of all the
        # withholding taxes, the others are negative lines.
        # PPTOTAL is computed before the voluntary withholding tax (fiscal voluntarism, FISC_VOL, a negative line):
        # it is the withholding tax legally due, the base of the research, training, starter jobs and aid zones
        # exemptions. The voluntary one is part of the cap of the overtime and shifts exemptions (`voluntary=True`).
        codes = (
            'PPTOTAL', 'ECONOMIC_UNEMPLOYMENT.P.P', 'REPLACEMENT_REVENUE.P.P', 'DH_PP',
            'PRESENCE_TOKEN_WITHHOLDING_TAX',
        )
        withholding_tax = sum(line_values[code][payslip.id]['total'] for payslip in payslips for code in codes)
        if voluntary:
            withholding_tax -= sum(line_values['FISC_VOL'][payslip.id]['total'] for payslip in payslips)
        return withholding_tax

    @api.model
    def _get_overtime_withholding_tax(self, payslips, line_values):
        """ The withholding tax the overtime exemptions (274.44 / 274.55) can reduce: the one of the salary of the
        payslips, the voluntary one (FISC_VOL, a negative line) included, without the ones of the double holiday pay
        (DH_PP) and of the bonuses (exceptional withholding tax, BONUS_PP) paid with it, as the social secretariats do
        (only the withholding tax of the salary, not the one of the holiday pay, of the bonuses, of the termination
        indemnities: these have their own payslips, without overtime). The flat-rate taxes of the economic
        unemployment supplements and of the replacement incomes of the month stay in it, as at the social
        secretariats (unlike the other exemptions, see _get_exemption_withholding_tax).

        :param line_values: code -> payslip id -> {'total': ...}, PPTOTAL at least (the other codes may be missing)
        """
        def total(code, payslip):
            values = line_values.get(code) or {}
            return values[payslip.id]['total'] if payslip.id in values else 0.0

        return sum(
            total('PPTOTAL', p) - total('FISC_VOL', p) + total('DH_PP', p) + total('BONUS_PP', p)
            for p in payslips
        )

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

        # The withholding tax of a bonus paid with the salary (exceptional withholding tax, BONUS_PP, a negative line)
        # is the one of a bonus: at the average research share of the year, as the ones of the bonus payslips
        monthly_bonus_withholding = -sum_line_totals(monthly_payslips, "BONUS_PP")
        monthly_withholding = self._get_exemption_withholding_tax(monthly_payslips, line_values) - monthly_bonus_withholding

        double_pay_withholding = (-sum_line_totals(monthly_payslips, "DH_PP") + sum_line_totals(double_pay_payslips, "PPTOTAL"))

        withholding_by_structure = {
            "BEMONTHLY": monthly_withholding,
            "BEDOUBLE": double_pay_withholding,
        }
        if monthly_bonus_withholding:
            withholding_by_structure["BETHIRTEEN"] = monthly_bonus_withholding + sum_line_totals(
                payslips_by_structure.get("BETHIRTEEN", self.env["hr.payslip"]), "PPTOTAL")

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
        # Art. 275/3 CIR 92: 80 % of the withholding tax on the researchers' remuneration, warrants included
        concerned_payslips_structs = ['BEMONTHLY', 'BEDOUBLE', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1', 'BEWARRANT']
        date_from = min(payslips.mapped('date_from'), default=False)
        return payslips.filtered(
            lambda p: p.struct_id.code in concerned_payslips_structs
            and p.version_id.l10n_be_joint_committee_id.egov3_code != '999'
            and p.employee_id.certificate in ['doctor', 'civil_engineer']
            and p.employee_id._get_average_rd_percentage(p.struct_id.code, date_from) > 0
        )

    def _get_valid_274_33_payslips(self, payslips):
        concerned_payslips_structs = ['BEMONTHLY', 'BEDOUBLE', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1', 'BEWARRANT']
        date_from = min(payslips.mapped('date_from'), default=False)
        return payslips.filtered(
            lambda p: p.struct_id.code in concerned_payslips_structs
            and p.version_id.l10n_be_joint_committee_id.egov3_code != '999'
            and p.employee_id.certificate in ['master']
            and p.employee_id._get_average_rd_percentage(p.struct_id.code, date_from) > 0
        )

    def _get_valid_274_34_payslips(self, payslips):
        concerned_payslips_structs = ['BEMONTHLY', 'BEDOUBLE', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1', 'BEWARRANT']
        date_from = min(payslips.mapped('date_from'), default=False)
        return payslips.filtered(
            lambda p: p.struct_id.code in concerned_payslips_structs
            and p.version_id.l10n_be_joint_committee_id.egov3_code != '999'
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
        night_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_NIGHT')
        if not night_hours:
            return False
        # The night premium paid for an hour must be at least 12% of the contractual gross hourly wage: the amount per
        # hour of cp_200_premium_pay_night_hourly_rate when the payslip pays it (PREMNIGHT, archived by an employer
        # paying its own premium otherwise), plus the custom premiums. A premium Odoo doesn't know (paid by an input
        # of the employer's own) can't be checked: the exemption is granted on the night hours, as before.
        pays_cp200_premium = 'PREMNIGHT' in payslip.struct_id.rule_ids.mapped('code')
        night_premium = (payslip._rule_parameter('cp_200_premium_pay_night_hourly_rate', raise_if_not_found=False) or 0
                         if pays_cp200_premium else 0) \
            + payslip._get_premium_pay_additional_amount('PREMIUM_PAY_NIGHT') / night_hours
        hourly_wage = payslip.worked_days_line_ids[:1]._l10n_be_get_normal_hourly_wage() if payslip.worked_days_line_ids else 0
        if night_premium and (not hourly_wage or night_premium < hourly_wage * 12 / 100):
            return False

        full_pay_hours = payslip._get_l10n_be_full_pay_worked_hours()
        return full_pay_hours and night_hours >= full_pay_hours / 3

    @api.model
    def _get_team_shift_exemption_vals(self, payslip, taxable=None):
        """
        274.74 (Team / Continuous Team) individual theoretical withholding tax exemption.

        To be eligible, the Team (resp. Continuous Team) hourly bonus must be at least the
        legal rate, and the hours tagged with those premiums (summed together) must reach
        at least a third of the hours of the period (see
        hr.payslip._l10n_be_is_shift_exemption_work_entry_type). The exemption
        rate then applies to the taxable remuneration of the payslip (`taxable`, its GROSS
        line by default): the Continuous Team rate on the share of the Continuous Team hours
        in all the hours of the period, the Team rate on the rest. Since 2025 that share is
        not computed on the hours of the third-time rule but on the hours of the taxable
        remuneration (see hr.payslip._get_l10n_be_contteam_share).

        :return: (is_eligible, exemption_amount)
        """
        if payslip.is_refund_payslip and payslip.origin_payslip_id:
            eligible, exemption = self._get_team_shift_exemption_vals(payslip.origin_payslip_id)
            return eligible, -exemption
        if not self._is_team_exemption_eligible(payslip):
            return False, 0.0

        team_exemption_rate = payslip._rule_parameter('l10n_be_274_74_team_exemption_rate')
        contteam_exemption_rate = payslip._rule_parameter('l10n_be_274_74_contteam_exemption_rate')
        # CIR 92, art. 275/5: 25 % in continuous teams, in the ratio of their hours to all the hours of the period
        # (the normal ones included), 22.8 % on the rest
        contteam_ratio = payslip._get_l10n_be_contteam_share()
        exemption_rate = contteam_ratio * contteam_exemption_rate + (1 - contteam_ratio) * team_exemption_rate
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

    def _get_274_32_33_34_values(self, payslips, line_values, taxable_values, consumed_per_employee=None):
        """
        274.32, 274.33, 274.34 report is about withholding tax exemption for PhDs/Engineers, Masters and Bachelors.
        The exemption is capped to the withholding tax the exemptions imputed before it leave to the employee
        (``consumed_per_employee``: employee id -> amount already exempted, see _compute_line_ids).
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
        consumed_per_employee = consumed_per_employee or {}
        result_per_employee = defaultdict(lambda: (0.0, 0.0, 0.0))
        total_exemption = 0
        for employee, employee_slips in payslips.grouped('employee_id').items():
            taxable_amount, withholding_tax_amount, exemption_amount = self._get_rd_basic_exemption_vals(
                employee_slips, line_values, taxable_values
            )
            remaining_withholding = withholding_tax_amount - consumed_per_employee.get(employee.id, 0.0)
            exemption_amount = min(exemption_amount, max(0.0, remaining_withholding))
            current_taxable, current_withholding, current_exemption = result_per_employee[employee]
            result_per_employee[employee] = (
                current_taxable + taxable_amount,
                current_withholding + withholding_tax_amount,
                current_exemption + exemption_amount,
            )
            total_exemption += exemption_amount
        return result_per_employee

    def _get_274_64_values(self, payslips, line_values, taxable_values, consumed_per_employee=None):
        """
        274.64 report is about the withholding tax exemption for worker training.The exemption equals a fixed percentage
        (11.75%) of the taxable salary (monthly remuneration + premium + benefit in kind, i.e. the GROSS line) of the
        month during which the training took place (ends), capped to 3 500 EUR a month (see _get_274_64_taxable_cap).
        The company directors, the termination indemnities, the double holiday pay, the year-end premium and the
        arrears are not part of it (only the monthly payslips of the employees, their GROSS line).

        The cumulative dispensation for one employee cannot exceed the withholding tax actually due for that employee,
        so the training exemption is floored to the withholding left after the exemptions imputed before it (overtime,
        see _compute_line_ids) and never goes below 0. ``consumed_per_employee`` maps each employee id to that
        already-granted exemption (0 when absent).
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
        consumed_per_employee = consumed_per_employee or {}
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
            # the taxable remuneration of each month, capped
            exemption_base = sum(
                min(sum(taxable_values[p.id] for p in month_slips), self._get_274_64_taxable_cap(month_slips))
                for month_slips in emp_slips.grouped(lambda p: p.date_to.replace(day=1)).values()
            )
            withholding_tax_amount = self._get_exemption_withholding_tax(emp_slips, line_values)
            remaining_withholding = withholding_tax_amount - consumed_per_employee.get(employee.id, 0.0)
            result_per_employee[employee] = (
                taxable_amount,
                withholding_tax_amount,
                max(0.0, min(rate * exemption_base, remaining_withholding)),
            )
        return result_per_employee

    def _get_274_64_taxable_cap(self, payslips):
        """The cap of the taxable remuneration of a month of a worker (his payslips of that month) the training
        exemption (274.64) applies to: 3 500 EUR, for a part-time worker too."""
        return self.env["hr.rule.parameter"]._get_parameter_from_code(
            "l10n_be_274_64_training_taxable_cap", self.date_start, raise_if_not_found=False,
        ) or 3500.0

    def _get_274_74_values(self, payslips, line_values, taxable_values, consumed_per_employee=None):
        """
        274.74 report is about withholding tax exemption for team shifts, pooled between the employees (see
        _get_shift_exemption_pooled_values).
        Returns:
        {
            employee: (
                taxable_amount,
                withholding_tax_amount,
                exemption_amount,
            )
        }
        """
        return self._get_shift_exemption_pooled_values(
            payslips, line_values, taxable_values, consumed_per_employee, self._get_team_shift_exemption_vals)

    def _get_274_75_values(self, payslips, line_values, taxable_values, consumed_per_employee=None):
        """
        274.75 report is about withholding tax exemption for night shifts, pooled as the 274.74.
        Returns:
        {
            employee: (
                taxable_amount,
                withholding_tax_amount,
                exemption_amount,
            )
        }
        """
        return self._get_shift_exemption_pooled_values(
            payslips, line_values, taxable_values, consumed_per_employee, self._get_night_shift_exemption_vals)

    def _get_shift_exemption_pooled_values(self, payslips, line_values, taxable_values, consumed_per_employee,
                                           get_exemption_vals):
        """
        The team and night shifts exemptions (274.74 / 274.75) are exemptions of the employer, pooled between all the
        eligible workers of the declaration: the exemption is the rate of the taxable remuneration of each eligible
        worker, capped to the withholding tax of all of them, not to the one of each worker (Partena, 05/11 and
        10/11). The workers whose theoretical exemption exceeds their withholding tax (e.g. a flexi-job, whose taxable
        remuneration is in the base with no withholding tax) bring their surplus to the pool, which goes to the
        workers left with withholding tax, whatever their order: the total is min(sum of the theoretical
        exemptions, sum of the withholding taxes). As on the payslips (_get_team_night_274_74_75_exemptions), no
        worker is granted more than his own withholding tax, which the exemptions imputed before leave him
        (``consumed_per_employee``, see _compute_line_ids).
        """
        self.ensure_one()
        consumed_per_employee = consumed_per_employee or {}
        values = {}
        for employee, employee_slips in payslips.grouped('employee_id').items():
            theoretical_exemption = sum(get_exemption_vals(p)[1] for p in employee_slips)
            withholding_tax_amount = self._get_exemption_withholding_tax(employee_slips, line_values, voluntary=True)
            # the exemptions imputed before take at most the withholding tax (a reversal's is negative)
            remaining_withholding = withholding_tax_amount - min(
                consumed_per_employee.get(employee.id, 0.0), max(0.0, withholding_tax_amount))
            exemption = min(remaining_withholding, theoretical_exemption)
            values[employee] = {
                'taxable': sum(taxable_values[p.id] for p in employee_slips),
                'withholding': withholding_tax_amount,
                'room': max(0.0, remaining_withholding - exemption),
                'surplus': max(0.0, theoretical_exemption - exemption),
                'exemption': exemption,
            }
        # the surplus of the ones capped to their withholding tax goes to the others, up to theirs
        pool = sum(vals['surplus'] for vals in values.values())
        for vals in values.values():
            extra_amount = min(vals['room'], pool)
            vals['exemption'] += extra_amount
            pool -= extra_amount
        return {
            employee: (vals['taxable'], vals['withholding'], vals['exemption'])
            for employee, vals in values.items()
        }

    def _get_274_81_values(self, payslips, line_values, taxable_values=None, consumed_per_employee=None):
        # 25 % of the withholding tax, capped to what the exemptions imputed before it leave (see _compute_line_ids)
        self.ensure_one()
        consumed_per_employee = consumed_per_employee or {}
        result_per_employee = defaultdict(lambda: (0.0, 0.0, 0.0))
        if taxable_values is None:
            gross_codes = self.env['hr.payslip']._get_gross_wage_line_codes()
            taxable_values = {p.id: sum(line_values[code][p.id]['total'] for code in gross_codes) for p in payslips}
        for employee, emp_slips in payslips.grouped('employee_id').items():
            # the taxable salary of the declaration period, as for the 274.10
            taxable_amount = sum(taxable_values[p.id] for p in emp_slips)
            withholding_tax_amount = self._get_exemption_withholding_tax(emp_slips, line_values)
            remaining_withholding = withholding_tax_amount - consumed_per_employee.get(employee.id, 0.0)
            exemption_amount = min(0.25 * withholding_tax_amount, max(0.0, remaining_withholding))
            current_taxable, current_withholding, current_exemption = result_per_employee[employee]
            result_per_employee[employee] = (
                current_taxable + taxable_amount,
                current_withholding + withholding_tax_amount,
                current_exemption + exemption_amount,
            )
        return result_per_employee

    def _get_274_60_61_vals(self, payslips, line_ids_vals, line_values, consumed_per_employee):
        """
        274.60 / 274.61: the exemption of the starting small (10 %) and micro (20 %) companies, during their 48 first
        months (see _compute_cbe_expiration). It is an exemption of each worker: 10 % / 20 % of the withholding tax
        of all his remunerations of the period (the 274.10 and 274.18 natures: monthly payslip, 13th month, double
        holiday pay, departure, ...), without the voluntary one, capped to what the exemptions imputed before it
        leave him (``consumed_per_employee``, see _compute_line_ids). Each worker's exemption is rounded to the cent:
        the declaration declares their sum (see _compute_amounts).

        :param line_ids_vals: the lines of the declaration computed so far, the 274.10 and 274.18 ones included
        :return: the values of the lines of the exemption, one per worker
        """
        self.ensure_one()
        status = self.company_id._get_payroll_config(self.date_start).exemption_sme_status
        if not status or self.is_cbe_expired:
            return []
        rate = 0.10 if status == 'startup' else 0.20
        taxable_per_employee = defaultdict(float)
        withholding_per_employee = defaultdict(float)
        for vals in line_ids_vals:
            if vals['nature_code'] in ('274.10', '274.18'):
                taxable_per_employee[vals['employee_id']] += vals['taxable_amount']
                withholding_per_employee[vals['employee_id']] += vals['withholding_amount']
        # The voluntary withholding tax of the natures (negative lines)
        for payslip in payslips:
            withholding_per_employee[payslip.employee_id.id] += sum(
                line_values[code][payslip.id]['total'] for code in ('FISC_VOL_10', 'FISC_VOL_18'))
        currency = self.company_id.currency_id
        return [{
            'sheet_id': self.id,
            'employee_id': employee_id,
            'amount': max(0.0, min(
                currency.round(withholding * rate),
                currency.round(withholding - consumed_per_employee.get(employee_id, 0.0)),
            )),
            'withholding_amount': withholding,
            'taxable_amount': taxable_per_employee[employee_id],
            'nature_code': '274.60' if status == 'startup' else '274.61',
        } for employee_id, withholding in withholding_per_employee.items() if employee_id in taxable_per_employee]

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
        # The overtime giving right to the legal overtime premium, voluntary overtime included, in all the joint
        # committees (the hotel industry's included: SPF Finances, dispense secteur Horeca)
        # with a premium of at least 20%: the overtime paid at 100% has no exemption (see _is_extra_hours_qualifying)
        is_overtime = self.env['hr.payslip']._is_extra_hours_qualifying

        payslips = payslips.filtered(lambda p: any(map(is_overtime, p.worked_days_line_ids.work_entry_type_id)))

        if not payslips:
            return [], False

        exemption_rate = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_be_extra_hours_exemption_rate', date_start, raise_if_not_found=False) or 0.4125
        # from a payslip's salary rule there is no declaration: the company is the payslips' own
        company = self.company_id or payslips.company_id[:1]

        Payslip = self.env['hr.payslip']
        consumed_by_employee_jc = payslips._l10n_be_get_overtime_hours_consumed(company, date_start)
        payslips_by_employee_jc = payslips.grouped(lambda p: (p.employee_id, Payslip._l10n_be_get_overtime_joint_committee(p.version_id)))

        line_ids_vals = []
        capped_employees = set()

        for (employee, joint_committee), emp_slips in payslips_by_employee_jc.items():
            if not joint_committee:
                continue

            overtime_cap = Payslip._l10n_be_get_overtime_cap(joint_committee, company, date_start)
            # In the hotel industry, from 2026 the first hours up to the general cap (180) are declared under 274.44 as
            # in the other sectors, the next ones up to the cap of the sector (360) under 274.55 (Royal Decree of
            # 22 July 2026, from 1 January 2026); before, all of them under 274.55
            if joint_committee == '200':
                general_cap = overtime_cap
            elif date_start >= date(2026, 1, 1):
                general_cap = min(overtime_cap, Payslip._l10n_be_get_overtime_cap('200', company, date_start))
            else:
                general_cap = 0.0

            consumed = consumed_by_employee_jc[employee, joint_committee]

            # Sort so which lines get (partially) capped is deterministic/auditable.
            worked_days_lines = emp_slips.mapped('worked_days_line_ids').sorted(
                lambda wd: wd.payslip_id.date_from
            )

            taxable_by_nature = defaultdict(float)
            for wd in worked_days_lines:
                if not is_overtime(wd.work_entry_type_id):
                    continue

                if consumed >= overtime_cap:
                    capped_employees.add(employee.name)
                    continue

                hours = wd.number_of_hours
                if consumed + hours > overtime_cap:
                    capped_employees.add(employee.name)

                added_hours = min(hours, overtime_cap - consumed)
                general_hours = max(0.0, min(added_hours, general_cap - consumed))
                # Taxable amount is the amount of extra hours flagged as extra hours, but only 100% of it.
                hourly_base = wd._l10n_be_get_overtime_base() / hours if hours else 0.0
                taxable_by_nature[44] += hourly_base * general_hours
                taxable_by_nature[55] += hourly_base * (added_hours - general_hours)
                consumed += added_hours

            # The exemption is the rate of the declared taxable amount: both rounded as declared
            taxable_by_nature = {
                nature: company.currency_id.round(taxable) for nature, taxable in taxable_by_nature.items()
                if company.currency_id.round(taxable)
            }
            if taxable_by_nature:
                withholding_tax_amount = self._get_overtime_withholding_tax(emp_slips, line_values)
                total_taxable = sum(taxable_by_nature.values())
                # an exemption from the payment of the withholding tax withheld: at most the one of the employee, as
                # the payslips grant it (WITHHOLDING_TAX_EX_274_44 / _55), the 274.44 hours first
                withholding_left = max(0.0, company.currency_id.round(withholding_tax_amount))
                for nature, taxable_amount in sorted(taxable_by_nature.items()):
                    amount = min(company.currency_id.round(taxable_amount * exemption_rate), withholding_left)
                    withholding_left -= amount
                    line_ids_vals.append({
                        'sheet_id': self.id,
                        'employee_id': employee.id,
                        'amount': amount,
                        # the withholding tax of the employee, shared between the natures as their taxable amounts
                        'withholding_amount': company.currency_id.round(
                            withholding_tax_amount * taxable_amount / total_taxable),
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
            payslips = all_payslips._l10n_be_filter_declared_withholding_taxes()
            # The taxable salary is added up from the amounts it is made of, so that each one is
            # declared in the period it is attached to instead of following the aggregate line.
            base_values = payslips._l10n_be_get_gross_wage_base_values(sheet.date_start, sheet.date_end)
            taxable_values = defaultdict(float)
            for code_values in base_values.values():
                for payslip_id, amount in code_values.items():
                    taxable_values[payslip_id] += amount
            gross_values = base_values.get('GROSS', defaultdict(float))
            # The other amounts of the natures are read from their categories, for the same reason
            nature_values = {
                category_code: payslips._l10n_be_get_declaration_base(category_code, sheet.date_start, sheet.date_end)
                for category_code in [
                    'TAXABLE_13', 'TAXABLE_18', 'TAXABLE_30', 'WITHHOLDING_TAX_274_10_20', 'WITHHOLDING_TAX_274_13',
                    'WITHHOLDING_TAX_274_18', 'WITHHOLDING_TAX_274_30', 'OCCASIONAL_WITHHOLDING_BASE',
                ]
            }

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
                        nature_values=nature_values,
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

            # The exemption is computed on the remunerations of the employees, not on the ones of the company directors
            # (274.20). The flexi-jobs are in for their commuting allowance only (see _get_274_56_values).
            valid_payslips_56 = payslips.filtered(lambda p: not p.version_id._l10n_be_is_company_director())
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

            # The exemptions of the employees (research, starter jobs, training, shifts, aid zones, overtime) are
            # exemptions from the payment of their withholding tax: none for the students without withholding taxes,
            # declared on the 274.10 and in the base of the 0.12 % exemption only, nor for the flexi-jobs, whose pay is
            # exempted from the tax (their taxable part is only in the pool of the shifts exemptions)
            withheld_payslips = payslips.filtered(
                lambda p: not p.version_id.no_withholding_taxes and not p.version_id.is_flexi())
            base_count = len(line_ids_vals)
            line_ids_vals, warning_msg = sheet._get_employee_exemptions_vals(
                payslips, withheld_payslips, line_ids_vals, line_values, taxable_values, gross_values)
            # The aid zone exemption (274.81) can't be cumulated, for a worker and a period, with the overtime (274.44
            # / 274.55) and research (274.32 / 33 / 34) ones: the worker keeps the most advantageous, the overtime and
            # research ones on a tie. The dropped exemptions consume nothing in the cascade.
            amounts = defaultdict(lambda: defaultdict(float))
            for vals in line_ids_vals:
                amounts[vals['employee_id']][vals['nature_code']] += vals['amount']
            overtime_research_codes = ('274.44', '274.55', '274.32', '274.33', '274.34')
            conflicting = {
                employee_id for employee_id, nature_amounts in amounts.items()
                if nature_amounts['274.81'] > 0 and any(nature_amounts[code] > 0 for code in overtime_research_codes)
            }
            if conflicting:
                aid_zone_vals, _warning = sheet._get_employee_exemptions_vals(
                    payslips, withheld_payslips, line_ids_vals[:base_count], line_values, taxable_values,
                    gross_values, without_overtime_research=conflicting)
                aid_zone_amounts = defaultdict(float)
                for vals in aid_zone_vals[base_count:]:
                    if vals['nature_code'] == '274.81':
                        aid_zone_amounts[vals['employee_id']] += vals['amount']
                aid_zone_employee_ids = {
                    employee_id for employee_id in conflicting
                    if aid_zone_amounts[employee_id] > sum(amounts[employee_id][code] for code in overtime_research_codes)
                }
                line_ids_vals, warning_msg = sheet._get_employee_exemptions_vals(
                    payslips, withheld_payslips, line_ids_vals[:base_count], line_values, taxable_values,
                    gross_values, without_overtime_research=aid_zone_employee_ids,
                    without_aid_zone=conflicting - aid_zone_employee_ids)
            sheet.extra_hours_cap_warning = warning_msg

            sheet.line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in line_ids_vals]

    def _get_employee_exemptions_vals(
        self, payslips, withheld_payslips, line_ids_vals, line_values, taxable_values, gross_values,
        without_overtime_research=frozenset(), without_aid_zone=frozenset(),
    ):
        """
        The lines of the exemptions of the employees, imputed in cascade (see _compute_line_ids).

        :param line_ids_vals: the lines of the declaration computed so far (natures 274.10, 274.18, ...)
        :param without_overtime_research: ids of the employees without overtime and research exemptions
        :param without_aid_zone: ids of the employees without aid zone exemption
        :return: (the lines of the declaration, the exemptions ones added, the overtime cap warning)
        """
        line_ids_vals = list(line_ids_vals)
        # The exemptions of an employee are imputed one after the other, each capped to the withholding tax the
        # previous ones leave to the employee, in the order of the social secretariats: overtime, training,
        # research, starting company, team and night shifts, starter jobs, aid zones. Before 2026, the starting
        # company exemption came after the team and night shifts ones. The 0.12 % exemption is computed on the
        # totals of the declaration (_compute_amounts), after all the others.
        consumed_per_employee = defaultdict(float)

        def consume(nature_vals):
            for vals in nature_vals:
                consumed_per_employee[vals['employee_id']] += max(0.0, vals['amount'])

        # the aid zone exemption can't be cumulated with the overtime and research ones (see _compute_line_ids)
        cumulable_payslips = withheld_payslips.filtered(lambda p: p.employee_id.id not in without_overtime_research)
        warning_msg = False
        if cumulable_payslips:
            extra_hours_vals, warning_msg = self._get_extra_hours_lines_ids(
                cumulable_payslips, self.date_start, line_values)
            line_ids_vals += extra_hours_vals
            consume(extra_hours_vals)

        valid_payslips_64 = withheld_payslips.filtered(
            lambda p: p.struct_id.code == "BEMONTHLY" and p.employee_id in self.training_employee_ids._origin
            and not p.version_id._l10n_be_is_company_director(),
        )
        result_274_64_per_employee = self._get_274_64_values(
            valid_payslips_64,
            line_values,
            gross_values,
            consumed_per_employee,
        )
        training_vals = []
        for employee, res in result_274_64_per_employee.items():
            taxable, withholding, exemption = res
            training_vals.append({
                "sheet_id": self.id,
                "employee_id": employee.id,
                "amount": exemption,
                "withholding_amount": withholding,
                "taxable_amount": taxable,
                "nature_code": "274.64",
            })
        line_ids_vals += training_vals
        consume(training_vals)

        rd_vals = []
        for nature_code, valid_payslips in (
            ('274.32', self._get_valid_274_32_payslips(cumulable_payslips)),
            ('274.33', self._get_valid_274_33_payslips(cumulable_payslips)),
            ('274.34', self._get_valid_274_34_payslips(cumulable_payslips)),
        ):
            result_per_employee = self._get_274_32_33_34_values(
                valid_payslips, line_values, taxable_values, consumed_per_employee)
            for employee, res in result_per_employee.items():
                taxable, withholding, exemption = res
                rd_vals.append({
                    'sheet_id': self.id,
                    'employee_id': employee.id,
                    'amount': exemption,
                    'withholding_amount': withholding,
                    'taxable_amount': taxable,
                    'nature_code': nature_code,
                })

        # The total of the bachelors' exemptions is capped to a rate of the doctors' and masters' ones (see
        # _compute_amounts): scale every bachelor's exempted amount down by that same ratio.
        # The raw_amount variable keeps the pre-cap value.
        bachelor_vals = [vals for vals in rd_vals if vals['nature_code'] == '274.34']
        raw_dm_total = sum(v['amount'] for v in rd_vals if v['nature_code'] != '274.34')
        raw_bachelor_total = sum(v['amount'] for v in bachelor_vals)
        bachelor_rate = self._get_bachelor_exemption_rate(self.date_start)
        capped_bachelor_total = min(raw_bachelor_total, raw_dm_total * bachelor_rate)
        for vals in bachelor_vals:
            vals['raw_amount'] = vals['amount']
        if raw_bachelor_total:
            ratio = capped_bachelor_total / raw_bachelor_total
            for vals in bachelor_vals:
                vals['amount'] *= ratio

        line_ids_vals += rd_vals
        consume(rd_vals)

        starting_company_before_shifts = bool(self.date_start) and self.date_start >= date(2026, 1, 1)
        if starting_company_before_shifts:
            starting_company_vals = self._get_274_60_61_vals(
                payslips, line_ids_vals, line_values, consumed_per_employee)
            line_ids_vals += starting_company_vals
            consume(starting_company_vals)

        # The team and night shifts exemptions are pooled between the eligible employees (see
        # _get_shift_exemption_pooled_values). The taxable remuneration of the flexi-jobs is in the pool: without
        # withholding tax of their own, their exemption goes to the other eligible employees.
        shift_payslips = withheld_payslips | payslips.filtered(
            lambda p: p.version_id.is_flexi() and not p.version_id.no_withholding_taxes)
        for nature_code, is_eligible, get_values in (
            ('274.74', self._is_team_exemption_eligible, self._get_274_74_values),
            ('274.75', self._is_night_exemption_eligible, self._get_274_75_values),
        ):
            result_per_employee = get_values(
                shift_payslips.filtered(is_eligible),
                line_values,
                gross_values,
                consumed_per_employee,
            )
            shift_vals = []
            for employee, res in result_per_employee.items():
                taxable, withholding, exemption = res
                shift_vals.append({
                    "sheet_id": self.id,
                    "employee_id": employee.id,
                    "amount": exemption,
                    "withholding_amount": withholding,
                    "taxable_amount": taxable,
                    "nature_code": nature_code,
                })
            line_ids_vals += shift_vals
            consume(shift_vals)

        if not starting_company_before_shifts:
            starting_company_vals = self._get_274_60_61_vals(
                payslips, line_ids_vals, line_values, consumed_per_employee)
            line_ids_vals += starting_company_vals
            consume(starting_company_vals)

        valid_payslips_62 = withheld_payslips.filtered(
            lambda p: p.version_id.l10n_be_is_starterjob
            and p.version_id.l10n_be_joint_committee_id.egov3_code != '999'
        )
        starter_job_vals = []
        for employee, emp_slips in valid_payslips_62.grouped('employee_id').items():
            withholding = self._get_exemption_withholding_tax(emp_slips, line_values)
            remaining_withholding = withholding - consumed_per_employee[employee.id]
            starter_job_vals.append({
                'sheet_id': self.id,
                'employee_id': employee.id,
                'amount': min(
                    sum(line_values['COMPSUPP'][p.id]['total'] for p in emp_slips),
                    max(0.0, remaining_withholding),
                ),
                'withholding_amount': withholding,
                'taxable_amount': sum(gross_values[p.id] for p in emp_slips),
                'nature_code': '274.62'
            })
        line_ids_vals += starter_job_vals
        consume(starter_job_vals)

        valid_payslips_81 = withheld_payslips.filtered(
            lambda p: p.struct_id.code == 'BEMONTHLY' and p.version_id.l10n_be_is_aid_zone
            and p.version_id.l10n_be_joint_committee_id.egov3_code != '999'
            and p.employee_id.id not in without_aid_zone
        )
        result_274_81_per_employee = self._get_274_81_values(
            valid_payslips_81, line_values, taxable_values, consumed_per_employee)
        for employee, res in result_274_81_per_employee.items():
            taxable, withholding, exemption = res
            line_ids_vals.append({
                'sheet_id': self.id,
                'employee_id': employee.id,
                'amount': exemption,
                'withholding_amount': withholding,
                'taxable_amount': taxable,
                'nature_code': '274.81'
            })
        return line_ids_vals, warning_msg

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

    @api.depends('payslip_ids')
    def _compute_complementary_indemnity_warning(self):
        for sheet in self:
            sheet.l10n_be_complementary_indemnity_warning = sheet.payslip_ids._l10n_be_get_complementary_indemnity_warning()

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

            # Startup/M-E Exemption: the sums of the exemptions of the workers (see _get_274_60_61_vals), on the
            # remunerations of the workers, their arrears included (274.18), not the ones of the company directors
            # (274.20) nor the replacement incomes (274.13). The withholding tax is the one legally due, without the
            # voluntary one.
            startup_lines = sheet.line_ids.filtered(lambda l: l.nature_code in ('274.60', '274.61'))
            sheet.startup_taxable_amount = sum(startup_lines.mapped('taxable_amount'))
            sheet.startup_withholding_amount = sum(startup_lines.mapped('withholding_amount'))
            sheet.startup_exempted_amount = sum(startup_lines.mapped('amount'))
            sheet.startup_amount_to_pay = sheet.startup_withholding_amount - sheet.startup_exempted_amount

            sheet.total_pp_amount = sheet.pp_amount_10 + sheet.pp_amount_13 + sheet.pp_amount_20 + sheet.pp_amount_18 + sheet.pp_amount_30
            sheet.total_taxable_amount = sheet.taxable_amount_10 + sheet.taxable_amount_13 + sheet.taxable_amount_20 + sheet.taxable_amount_18 + sheet.taxable_amount_30

            other_deducted_amount = sheet.deducted_amount_32 + sheet.deducted_amount_33 + sheet.capped_amount_34 + sheet.deducted_amount_62 + sheet.deducted_amount_64 + sheet.deducted_amount_74 + sheet.deducted_amount_75 + sheet.startup_exempted_amount + sheet.deducted_amount_81 + sheet.extra_hours_exempted_amount
            # The 0.12 % exemption is an exemption from the payment of the withholding tax withheld, computed on the
            # whole declaration: it comes after the exemptions of the employees (research, overtime, shifts, ...),
            # on what they leave to pay, never above it (e.g. none on a period without withholding tax, as with
            # students only)
            sheet.sme_exempted_amount = min(
                sheet.sme_exempted_amount, max(0.0, round(sheet.total_pp_amount - other_deducted_amount, 2)))
            sheet.deducted_amount = other_deducted_amount + sheet.sme_exempted_amount
            sheet.amount_to_pay = max(0, sheet.total_pp_amount - sheet.deducted_amount)

    @api.depends('date_start', 'company_id.l10n_be_cbe_inscription')
    def _compute_cbe_expiration(self):
        for record in self:
            cbe_date = record.company_id.l10n_be_cbe_inscription

            if not cbe_date:
                record.is_cbe_expired = True
                continue

            # The first month of the declared period (a quarterly declaration has no month)
            reference_date = record.date_start or fields.Date.context_today(self).replace(day=1)
            # The 48 first months of activity: from the month of the inscription when it is on its 1st day, else from
            # the next month (the month of the inscription is not a complete one)
            start_period = cbe_date if cbe_date.day == 1 else cbe_date + relativedelta(months=+1, day=1)
            expiration_date = start_period + relativedelta(months=+48)
            record.is_cbe_expired = reference_date >= expiration_date

    def _get_pdf_sections(self):
        """Return the 274.XX sections to print in the PDF, in page order: the ones with a non-zero taxable,
        withheld or exempted amount. When there is nothing to declare, the (empty) 274.10 sheet is kept."""
        self.ensure_one()
        sections = {
            '274.10': self.taxable_amount_10 or self.pp_amount_10,
            '274.13': self.taxable_amount_13 or self.pp_amount_13,
            '274.18': self.taxable_amount_18 or self.pp_amount_18,
            '274.20': self.taxable_amount_20 or self.pp_amount_20,
            '274.30': self.taxable_amount_30 or self.pp_amount_30,
            '274.32': self.taxable_amount_32 or self.pp_amount_32 or self.deducted_amount_32,
            '274.33': self.taxable_amount_33 or self.pp_amount_33 or self.deducted_amount_33,
            '274.34': self.taxable_amount_34 or self.pp_amount_34 or self.deducted_amount_34,
            '274.44': self.taxable_amount_44 or self.pp_amount_44 or self.deducted_amount_44,
            '274.55': self.taxable_amount_55 or self.pp_amount_55 or self.deducted_amount_55,
            '274.56': self.is_ipa_reduction and (self.sme_taxable_amount or self.sme_exempted_amount),
            '274.6x': self.exemption_sme_status and not self.is_cbe_expired and (self.startup_taxable_amount or self.startup_exempted_amount),
            '274.62': self.deducted_amount_62,
            '274.81': self.deducted_amount_81,
        }
        return [section for section, has_data in sections.items() if has_data] or ['274.10']

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
                'taxable_revenue': self.startup_taxable_amount,
                'prepayment': -self.startup_exempted_amount,
                'payment_reference': payment_reference,
                'district': district,
                'office': office,
            }
            declarations.append(declaration_6x)

        # Only declare the natures with data; an exemption is declared even if its taxable revenue is 0.
        # When there is nothing to declare, the (empty) 274.10 declaration is kept.
        declarations = [
            declaration for declaration in declarations
            if declaration['taxable_revenue'] or declaration['prepayment']
        ] or [declaration_10]

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
        self._check_negative_amounts()
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
        # Only add the worksheets of the sections with data
        has_ipa = self.is_ipa_reduction and (self.sme_taxable_amount or self.sme_exempted_amount)
        has_startup = self.exemption_sme_status and not self.is_cbe_expired and (self.startup_taxable_amount or self.startup_exempted_amount)
        has_starterjob = self.line_274_62_ids or self.taxable_amount_62 or self.deducted_amount_62
        summary_worksheet = workbook.add_worksheet(self.env._('Exemption Summary'))
        if self.line_274_13_ids:
            unemployment_worksheet = workbook.add_worksheet(self.env._('Temporary Unemployment (274.13)'))
        if self.line_274_18_ids:
            replacement_revenue_worksheet = workbook.add_worksheet(self.env._('Replacement Revenues (274.18)'))
        if self.line_274_30_ids:
            presence_tokens_worksheet = workbook.add_worksheet(self.env._('Presence Tokens (274.30)'))
        if self.line_274_32_ids:
            doctors_worksheet = workbook.add_worksheet(self.env._('Doctors / Civil Engineers (274.32)'))
        if self.line_274_33_ids:
            masters_worksheet = workbook.add_worksheet(self.env._('Masters (274.33)'))
        if self.line_274_34_ids:
            bachelors_worksheet = workbook.add_worksheet(self.env._('Bachelors (274.34)'))
        if self.line_274_81_ids:
            aid_zone_worksheet = workbook.add_worksheet(self.env._('Aid Zone (274.81)'))
        if self.line_274_extra_hours_ids:
            extra_hours_worksheet = workbook.add_worksheet(self.env._('Extra Hours'))
        if has_ipa:
            ipa_worksheet = workbook.add_worksheet(self.env._('SME Exemption (274.56)'))
        if has_startup:
            startup_worksheet = workbook.add_worksheet(self.env._('Start-up (274.60) - M-E (275.61)'))
        if has_starterjob:
            starterjob_worksheet = workbook.add_worksheet(self.env._('Starterjob (274.62)'))
        if self.line_274_64_ids:
            training_worksheet = workbook.add_worksheet(self.env._('Training (274.64)'))
        if self.line_274_74_ids:
            team_shift_worksheet = workbook.add_worksheet(self.env._('(Continuous) Team Shifts (274.74)'))
        if self.line_274_75_ids:
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

        if has_ipa:
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
        if has_startup:
            startup_worksheet.set_column(0, 4, 30)
        if has_starterjob:
            starterjob_worksheet.set_column(0, 4, 30)
        startup_headers = [
            self.env._("Exemption Category"),
            self.env._("Taxable Amount"),
            self.env._("Withholding Taxes"),
            self.env._("Exempted Amount"),
            self.env._("Amount to Pay")
        ]
        for col, header in enumerate(startup_headers):
            if has_startup:
                startup_worksheet.write(0, col, header, style_header)
            if has_starterjob:
                starterjob_worksheet.write(0, col, header, style_header)
        startup_row = {
            'header': self.env._("Start-up / Micro-enterprise Exemption"),
            'taxable_amount': self.startup_taxable_amount,
            'withholding_taxes': self.startup_withholding_amount,
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
                if has_startup:
                    startup_worksheet.write(1, col, startup_row[key], style_normal)
                if has_starterjob:
                    starterjob_worksheet.write(1, col, starterjob_row[key], style_normal)
            else:
                if has_startup:
                    startup_worksheet.write(1, col, startup_row[key], style_currency)
                if has_starterjob:
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

        if self.line_274_32_ids:
            _write_employee_data(self.line_274_32_ids, doctors_worksheet)
        if self.line_274_33_ids:
            _write_employee_data(self.line_274_33_ids, masters_worksheet)
        if self.line_274_34_ids:
            _write_employee_data(self.line_274_34_ids, bachelors_worksheet)
        if self.line_274_extra_hours_ids:
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
        if self.line_274_18_ids:
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
        if self.line_274_64_ids:
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
        if self.line_274_74_ids:
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
        if self.line_274_75_ids:
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
        if self.line_274_81_ids:
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
