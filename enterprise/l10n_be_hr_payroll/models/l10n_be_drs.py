# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from dateutil.rrule import DAILY, rrule
from lxml import etree

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import date_utils, email_normalize, float_round, format_date

from odoo.addons.l10n_be_hr_payroll.models.utils import format_amount, xml_str_to_dict

LANG_CODE = {
    'nl_NL': '1',
    'fr_FR': '2',
    'de_DE': '3',
    'nl_BE': '1',
    'fr_BE': '2',
    'de_BE': '3',
}

# Natures of the days of the adapted work as a maternity protection measure
ZIMA002_NATURES = ('3.1', '3.2', '3.3', '3.4', '3.6', '5.1', '5.2', '5.3', '5.4', '5.5', '5.6', '5.7', '5.8', '5.9', '5.10', '5.11', '6.1', '6.21')

# Natures of the days of the reference period of ZIMA001, by risk
ZIMA001_INCAPACITY_NATURES = {
    '1', '1.1', '1.3', '1.6', '2.1', '2.4', '2.5', '2.6', '2.7', '2.8', '2.9', '3.1', '3.2', '3.3', '3.4', '3.5', '3.6', '4',
    '5.1', '5.2', '5.3', '5.4', '5.5', '5.6', '5.7', '5.8', '5.9', '5.10', '5.11', '6.5', '6.6', '6.7', '6.8', '6.9', '7', '9',
}
ZIMA001_RISK_NATURES = {
    '001': ZIMA001_INCAPACITY_NATURES,
    '006': {'1', '1.6', '6.10'},
    '007': {'1', '1.6', '4'},
    '008': {'1', '1.6', '4'},
}
# The incapacity is declared once the guaranteed salary is over
GUARANTEED_SALARY_NATURES = ('1.3', '2.4', '2.5', '2.6')
# The natures of the days worked or paid by the employer before a risk
WORKED_NATURES = ('1', '1.2', '1.4', '1.5', '1.6', '3.1', '3.2', '3.3', '3.5', '3.6', '4')
# Worker codes that can't be declared, by scenario ('6' stands for the codes of the civil servants, starting with 6):
# the workers not subject to the social security, the early retirees, the members of a parliament or a
# government and the trainees, then the codes specific to the scenario
DRS_FORBIDDEN_WORKER_CODES = ('000', '690', '879', '406', '407', '848', '849')
FORBIDDEN_WORKER_CODES_BY_IDENTIFICATION = {
    'WECH001': ('676', '497', '876', '883'),
    'WECH002': ('6', '876', '877', '497', '883'),
    'WECH005': ('6', '876', '877', '497', '883'),
    'ZIMA001': ('840', '841', '6', '883', '885'),
    'ZIMA002': ('840', '841', '676', '877', '883', '885'),
    'ZIMA003': ('840', '841', '6', '883', '885', '497'),
}
# The other scenarios of the unemployment sector
UNEMPLOYMENT_FORBIDDEN_WORKER_CODES = ('840', '841', '676', '497', '883')
# Third-party payers, Fedris and shipowners
DRS_FORBIDDEN_EMPLOYER_CATEGORIES = ('027', '028', '099', '105', '199', '205', '299', '305', '405', '699', '755', '756', '757', '758', '898')

# Risks of WECH008 with a work allowance, and with an uninterrupted occupation
WECH008_WORK_ALLOWANCE_RISKS = ('003', '007', '010', '011', '012', '020', '021')
WECH008_UNINTERRUPTED_OCCUPATION_RISKS = ('003', '004', '007', '010', '011', '012', '020', '021')
WORK_ACCIDENT_WORK_ENTRY_TYPES = (
    'l10n_be_work_entry_type_work_accident_first_week',
    'l10n_be_work_entry_type_work_accident_second_week',
    'l10n_be_work_entry_type_work_accident_second_week_short_term_employee',
    'l10n_be_work_entry_type_work_accident_guaranteed_monthly',
    'l10n_be_work_entry_type_work_accident_unpaid',
    'l10n_be_work_entry_type_work_accident_unassimilated',
    'l10n_be_work_entry_occupational_disease_unpaid',
)

# Natures of the days of a sheltered workshop: the paid recoveries and rests are worked days, the overtime and
# the usual days of inactivity aren't declared
WECH007_NATURES = {'1.2': '1', '1.3': '1', '1.5': '1', '1.4': False, '8': False}

# Kinds of work interrupting the occupation (DmfA codes): incapacity without salary, birth, temporary unemployment,
# youth and senior holidays, career breaks, foster care...
WECH001_INTERRUPTION_DMFA_CODES = ('50', '51', '52', '53', '60', '61', '70', '71', '72', '73', '75', '76', '77')
# Departures decided by the employer, who then pays the public holidays following the end of the contract
EMPLOYER_DEPARTURE_REASON_CODES = (342, 353, 358, 359)

# Risks of temporary unemployment declared for each time off
WECH002_EXCEPTIONAL_RISKS = ('005', '010')

# Scenarios declaring all their risks in the same declaration of the month
GROUPED_RISKS_IDENTIFICATIONS = ('WECH005',)
TEMPORARY_UNEMPLOYMENT_NATURES = tuple(f'5.{index}' for index in range(1, 12))

# Natures of the days of incapacity declared on all the calendar days in WECH006
WECH006_INCAPACITY_NATURES = ('2.7', '2.9', '6.1', '6.2', '6.3', '6.4', '6.5', '6.6', '6.7', '6.8', '6.9', '6.10', '6.11')

# Scenarios declaring a month of work: the occupation is limited to the month
MONTHLY_IDENTIFICATIONS = {'WECH005', 'WECH006', 'WECH007', 'WECH008', 'WECH010', 'WECH011', 'ZIMA002', 'ZIMA003'}

# Folder of the XSD schemas per social security sector
# https://www.socialsecurity.be/site_fr/employer/general/techlib.htm
SCHEMA_FOLDER_PER_SECTOR = {
    'unemployment': 'onem',
    'compensation': 'inami',
    'work_accident': 'fat',
}


class L10nBeDrs(models.Model):
    _name = 'l10n.be.drs'
    _description = 'DRS'
    _inherit = 'l10n.be.onss.batch.declaration'

    def _get_year_selection(self):
        current_year = fields.Date.context_today(self).year
        next_year = current_year + 1
        return [
            (str(current_year), current_year),
            (str(next_year), next_year),
        ]

    name = fields.Char(compute='_compute_name', store=True, readonly=True)
    sector = fields.Selection([
        ('work_accident', 'Work Accidents (Fedris)'),
        ('unemployment', 'Unemployment (ONEM/RVA)'),
        ('compensation', 'Benefits & Compensation (INAMI/RIZIV)'),
    ], string="Sector", required=True)
    risk_id = fields.Many2one(comodel_name='l10n.be.drs.risk', compute="_compute_risk", inverse="_inverse_risk",
        store=True, readonly=False, required=True, domain="[('id', 'in', allowed_risk_ids)]")
    identification = fields.Char(related="risk_id.identification")
    code = fields.Char(related="risk_id.code")
    allowed_risk_ids = fields.Many2many(comodel_name='l10n.be.drs.risk', compute="_compute_allowed_risks",
        export_string_translation=False)

    # Employee
    employee_id = fields.Many2one(comodel_name="hr.employee", string="Employee", required=True, index='btree',
        domain="[('company_id', 'in', allowed_company_ids), ('company_id.partner_id.country_id.code', '=', 'BE')]")

    # Employer
    company_id = fields.Many2one(related="employee_id.company_id", default=None)
    payroll_config_id = fields.Many2one(comodel_name='payroll.config.settings', compute='_compute_payroll_config')
    company_onss_number = fields.Char(compute='_compute_payroll_config')

    # Technical
    is_automatically_created = fields.Boolean()

    # WECH003 Specifics
    version_id = fields.Many2one('hr.version', string="Part-time Version", compute='_compute_version_id',
        help="Employee version of the part-time occupation")

    # WECH001 Specifics
    departure_id = fields.Many2one('hr.employee.departure', compute='_compute_departure_id',
        help="Departure of the employee during the month of the declaration")

    # WECH002 / WECH005 Specifics
    unemployment_start_date = fields.Date(compute='_compute_unemployment_data',
        help="Day of the month from which the temporary unemployment must be declared")
    major_force_reason = fields.Char(compute='_compute_unemployment_data',
        help="Description of the time off of force majeure")

    # WECH006 & WECH008 Specifics
    payslip_id = fields.Many2one('hr.payslip', compute='_compute_payslip_id',
        help="Validated payslip of the month of the declaration")

    # WECH008 Specifics
    paid_hours = fields.Float(compute='_compute_payslip_data', help="Hours with a salary due during the month")
    net_salary = fields.Float(compute='_compute_payslip_data',
        help="Net salary for the month, including the activation allowance.")
    work_allowance = fields.Float(compute='_compute_payslip_data', digits=(16, 4),
        help="Work allowance of the unemployment sector, prorated on the hours with a salary due")
    work_accident_indicator = fields.Boolean(compute='_compute_work_accident_indicator',
        help="The employee had a work accident during the month")

    # WECH009 Specifics
    leave_allocation_id = fields.Many2one('hr.leave.allocation', index='btree_not_null')
    holiday_hours = fields.Float(compute='_compute_holiday_hours', readonly=False, store=True,
        help="Hours of legal holidays (art. 17bis included) taken during the year before the month of the first youth or senior holidays")

    # ZIMA001 Specifics
    leave_ids = fields.Many2many('hr.leave', string="Time Off", compute='_compute_risk_period',
        help="Approved time off of the risk starting during the month of the declaration")
    risk_start_date = fields.Date(compute='_compute_risk_period')
    risk_end_date = fields.Date(compute='_compute_risk_period')

    # Declaration Period
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
        ('12', 'December')
    ], default=lambda self: str(fields.Date.context_today(self).month))
    year = fields.Integer(default=lambda self: fields.Date.context_today(self).year)

    # ZIMA006 Specifics
    origin_drs_id = fields.Many2one('l10n.be.drs', string="Origin DRS", compute='_compute_work_recovery',
        help="The declaration of the risk ended by the return to work")
    work_recovery_date = fields.Date(string="Work Recovery Date", compute='_compute_work_recovery',
        help="First day of work after the risk")

    @api.depends('risk_id', 'employee_id')
    def _compute_name(self):
        for drs in self:
            ref_date = drs.create_date or fields.Datetime.now()
            drs.name = f'{ref_date.strftime('%Y%m%d%H%M%S%f')}'

    @api.depends('sector')
    def _compute_risk(self):
        for drs in self:
            if drs.sector != drs.risk_id.sector:
                drs.risk_id = False

    def _inverse_risk(self):
        for drs in self:
            if drs.risk_id.sector and not drs.sector:
                drs.sector = drs.risk_id.sector

    @api.onchange('risk_id')
    def _onchange_risk(self):
        for drs in self:
            if drs.risk_id.sector and not drs.sector:
                drs.sector = drs.risk_id.sector

    @api.depends('sector', 'month', 'year')
    def _compute_allowed_risks(self):
        all_risks = self.env["l10n.be.drs.risk"].search([])
        risks_per_sector = all_risks.grouped('sector')
        today = fields.Date.context_today(self)
        for drs in self:
            risks = risks_per_sector.get(drs.sector, all_risks.browse()) if drs.sector else all_risks
            # The expired risks can't be declared anymore
            date_from, date_to = drs._get_first_last_day_of_month()
            risks = risks.filtered(lambda risk: risk.date_start <= (date_to or today) and (not risk.date_end or risk.date_end >= (date_from or today)))
            drs.allowed_risk_ids = risks

    @api.depends('company_id', 'month', 'year', 'identification', 'risk_start_date')
    def _compute_payroll_config(self):
        for drs in self:
            if not drs.company_id:
                drs.payroll_config_id = False
            elif drs.identification == 'ZIMA001' and drs.risk_start_date:
                drs.payroll_config_id = drs.company_id._get_payroll_config(drs.risk_start_date)
            elif drs.year and drs.month:
                drs.payroll_config_id = drs.company_id._get_payroll_config(date(int(drs.year), int(drs.month), 1))
            else:
                drs.payroll_config_id = drs.company_id.current_payroll_config_id
            drs.company_onss_number = drs.payroll_config_id.onss_registration_number

    @api.depends('employee_id', 'risk_id', 'month', 'year')
    def _compute_holiday_hours(self):
        for drs in self:
            if drs.identification != 'WECH009' or not drs.employee_id or not drs.year or not drs.month:
                drs.holiday_hours = 0
                continue
            date_from = date(drs.year, 1, 1)
            date_to = date(drs.year, int(drs.month), 1) - relativedelta(days=1)
            if date_to < date_from:
                drs.holiday_hours = 0
                continue
            day_list = drs._get_nature_of_days(('3.1', '3.5'), date_from, date_to)[0]
            drs.holiday_hours = sum(day['hours_amount'] for day in day_list) / 100

    @api.depends('employee_id', 'month', 'year')
    def _compute_departure_id(self):
        for drs in self:
            date_from, date_to = drs._get_first_last_day_of_month()
            drs.departure_id = drs.employee_id and date_from and self.env['hr.employee.departure'].search([
                ('employee_id', '=', drs.employee_id.id),
                ('departure_date', '>=', date_from),
                ('departure_date', '<=', date_to),
            ], order='departure_date desc', limit=1)

    @api.depends('employee_id', 'month', 'year')
    def _compute_version_id(self):
        for drs in self:
            drs.version_id = drs.employee_id and drs.year and drs.month and drs._get_period_version()

    @api.depends('employee_id', 'risk_id', 'month', 'year')
    def _compute_unemployment_data(self):
        for drs in self:
            drs.unemployment_start_date = drs.major_force_reason = False
            if drs.identification != 'WECH002' or not drs.employee_id or not drs.year or not drs.month:
                continue
            date_from, date_to = drs._get_first_last_day_of_month()
            start_dates = [
                (start_date, leave) for start_date, risk, leave in self._get_wech002_start_dates(drs.employee_id)
                if risk == drs.risk_id and date_from <= start_date <= date_to
            ]
            if start_dates:
                drs.unemployment_start_date, leave = start_dates[0]
                # sudo: hr.leave - the description of the time off is restricted to the time off officers
                drs.major_force_reason = (leave.sudo().private_name or '').strip()[:60]

    @api.depends('employee_id', 'month', 'year')
    def _compute_payslip_id(self):
        for drs in self:
            date_from, date_to = drs._get_first_last_day_of_month()
            drs.payslip_id = date_from and drs.employee_id and self.env['hr.payslip'].search([
                ('employee_id', '=', drs.employee_id.id),
                ('state', 'in', ('validated', 'paid')),
                ('date_from', '>=', date_from),
                ('date_to', '<=', date_to),
                ('credit_note', '=', False),
            ], order='date_from desc, id desc', limit=1)

    @api.depends('payslip_id', 'risk_id')
    def _compute_payslip_data(self):
        for drs in self:
            payslip = drs.payslip_id
            if not payslip or drs.identification != 'WECH008':
                drs.paid_hours = drs.net_salary = drs.work_allowance = 0
                continue
            drs.net_salary = payslip._get_category_data('WECH008_NET')['total']
            # The hours and allowance are 0 when no salary is due
            if not drs.net_salary:
                drs.paid_hours = drs.work_allowance = 0
                continue
            drs.paid_hours = float_round(sum(payslip.worked_days_line_ids.filtered('is_paid').mapped('number_of_hours')), precision_digits=2)
            # The monthly amount of the allowance is prorated on the hours of a full time worker in 4 weeks,
            # without being limited: the unemployment sector limits it
            monthly_amount = payslip._get_impulsion_plan_amount()[0]
            full_time_hours = payslip.version_id._get_reference_calendar().hours_per_week * 4
            drs.work_allowance = float_round(monthly_amount * drs.paid_hours / full_time_hours, precision_digits=4) if full_time_hours else 0

    @api.depends('employee_id', 'month', 'year')
    def _compute_work_accident_indicator(self):
        work_accident_types = self.env['hr.work.entry.type'].browse([
            work_entry_type.id for xmlid in WORK_ACCIDENT_WORK_ENTRY_TYPES
            if (work_entry_type := self.env.ref(f'hr_work_entry.{xmlid}', raise_if_not_found=False))
        ])
        for drs in self:
            if drs.identification != 'WECH008' or not drs.employee_id or not drs.year or not drs.month:
                drs.work_accident_indicator = False
                continue
            date_from, date_to = drs._get_first_last_day_of_month()
            drs.work_accident_indicator = any(
                work_entry['work_entry_type_id'] in work_accident_types
                for work_entry in drs.employee_id.generate_work_entries(date_from, date_to))

    # =======================================
    # MIXIN OVERRIDES
    # =======================================
    @api.model
    def _issues_dependencies(self):
        return super()._issues_dependencies() + ['employee_id', 'identification', 'month', 'year', 'company_id.l10n_be_cbe_inscription']

    def _get_declaration_type(self):
        # Type of the batch file, the scenario is identified in the form
        self.ensure_one()
        return self.identification[:4]

    def _get_base_schema_url(self):
        self.ensure_one()
        sector = self.sector or self.risk_id.sector
        folder = SCHEMA_FOLDER_PER_SECTOR.get(sector, 'onem')
        return f"https://www.socialsecurity.be/docu_xml/drs/{folder}/"

    def _get_base_schema_filename(self):
        self.ensure_one()
        return f'scen{int(self.identification[4:])}/{self.identification}_'

    def _get_declaration_template_xmlid(self):
        self.ensure_one()
        # The common templates are only loaded by an update of the module
        if not self.env.ref('l10n_be_hr_payroll.drs_xml_form', raise_if_not_found=False):
            raise UserError(self.env._("Update the Belgium - Payroll module to generate the DRS declarations."))
        xmlid = f'l10n_be_hr_payroll.{self.identification.lower()}_xml_export'
        if not self.env.ref(xmlid, raise_if_not_found=False):
            raise UserError(self.env._("XML report generation is not yet supported for %(identification)s declarations.", identification=self.identification))
        return xmlid

    def _get_rendering_data(self):
        self.ensure_one()
        version = self._get_declaration_version()
        if self._get_attestation_status() == '3':
            # A cancellation only identifies the cancelled declaration, its data may not exist anymore
            if errors := self._get_identification_errors():
                raise ValidationError("\n\n".join(errors))
            return self._get_cancellation_data(version)
        if errors := self._get_errors(version):
            raise ValidationError("\n\n".join(errors))
        return self._get_declaration_data(version)

    def _get_cancellation_data(self, version):
        """ The cancellation repeats the data of the cancelled declaration outside of the worker record """
        self.ensure_one()
        data = self._get_common_declaration_data(version)
        cancelled_declaration = self._get_modified_declaration()
        root = etree.fromstring(cancelled_declaration.xml_file.content) if cancelled_declaration.xml_file else None
        if self.identification == 'WECH001':
            # The simplified cancellation is made on the current quarter
            quarter_start = date_utils.get_quarter(fields.Date.context_today(self))[0]
            data['quarters'] = [{'quarter': f'{quarter_start.year}{date_utils.get_quarter_number(quarter_start)}'}]
        elif self.identification == 'ZIMA001':
            data['quarter'] = root is not None and root.findtext('Form/EmployerDeclaration/Quarter')
        elif self.identification == 'ZIMA006':
            data['work_recovery_date'] = root is not None and root.findtext('.//WorkRecoveryDate')
        return data

    # =======================================
    # ACTIONS
    # =======================================

    def action_modify_declaration(self):
        """ Replace the declaration accepted by the ONSS by a new one, generated with the current data """
        self.ensure_one()
        if not self._get_ticket_number():
            raise UserError(self.env._("Only a declaration accepted by the ONSS can be modified."))
        return self._copy_for_resubmission()._get_records_action()

    def action_cancel_declaration(self):
        """ Cancel the declaration accepted by the ONSS """
        self.ensure_one()
        if not self._get_ticket_number():
            raise UserError(self.env._("Only a declaration accepted by the ONSS can be cancelled."))
        cancellation = self._copy_for_resubmission()
        cancellation.with_context(l10n_be_drs_cancellation=True).generate_declaration_xml_report()
        return cancellation._get_records_action()

    def _copy_for_resubmission(self):
        self.ensure_one()
        return self.copy({
            'is_automatically_created': False,
            'xml_file': False,
            'xml_raw_content': False,
            'xml_filename': False,
            'signature_file': False,
            'signature_filename': False,
            'go_file': False,
            'go_filename': False,
        })

    # =======================================
    # AUTOMATIC CREATION
    # =======================================

    @api.model
    def _get_creation_key(self, vals):
        risk = self.env['l10n.be.drs.risk'].browse(vals['risk_id'])
        # A declaration of the month groups all the risks of the scenario
        risk_key = risk.identification if risk.identification in GROUPED_RISKS_IDENTIFICATIONS else risk.id
        return (risk_key, vals['employee_id'], int(vals['year']), str(vals['month']))

    @api.model
    def _create_missing_declarations(self, vals_list):
        """ Create the declarations that don't exist yet for the same risk, employee and month """
        if not vals_list:
            return self
        identifications = self.env['l10n.be.drs.risk'].browse({vals['risk_id'] for vals in vals_list}).mapped('identification')
        existing_declarations = self.search([
            ('risk_id.identification', 'in', identifications),
            ('employee_id', 'in', list({vals['employee_id'] for vals in vals_list})),
            ('year', 'in', list({int(vals['year']) for vals in vals_list})),
        ])
        existing_keys = {self._get_creation_key({
            'risk_id': drs.risk_id.id,
            'employee_id': drs.employee_id.id,
            'year': drs.year,
            'month': drs.month,
        }) for drs in existing_declarations}
        vals_to_create = []
        for vals in vals_list:
            key = self._get_creation_key(vals)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            vals_to_create.append(dict(vals, month=str(vals['month']), is_automatically_created=True))
        return self.create(vals_to_create)

    def _is_necessary(self):
        """ Whether the data of the employee still require the declaration, e.g. after the cancellation of a time off """
        self.ensure_one()
        if self.identification == 'WECH001':
            return self.code == '004' or bool(self._get_wech001_end_date())
        if self.identification == 'WECH002':
            return bool(self.unemployment_start_date)
        if self.identification in ('WECH009', 'WECH010'):
            return bool(self._get_nature_of_days(('3.4',))[0])
        if self.identification == 'WECH005':
            return bool(self._get_wech005_days()[0])
        if self.identification == 'ZIMA006':
            return bool(self.work_recovery_date)
        if self.identification == 'ZIMA003':
            return bool(self._get_zima003_pauses(self._get_period_version())[0])
        if self.identification == 'ZIMA001':
            return bool(self.risk_start_date) and self._is_zima001_needed({'risk': self.risk_id, 'leaves': self.leave_ids})
        return True

    # =======================================
    # COMMON
    # =======================================

    def _get_declaration_version(self):
        self.ensure_one()
        if self.identification == 'WECH001' and (end_date := self._get_wech001_end_date()):
            return self.employee_id._get_version(end_date)
        if self.identification == 'WECH002' and self.unemployment_start_date:
            return self.employee_id._get_version(self.unemployment_start_date)
        if self.identification == 'WECH006' and self.payslip_id:
            return self.payslip_id.version_id
        if self.identification == 'ZIMA001' and self.risk_start_date:
            return self.employee_id._get_version(self.risk_start_date)
        return self._get_period_version()

    def _get_errors(self, version):
        self.ensure_one()
        errors = self._get_common_errors(version)
        get_declaration_errors = {
            'ZIMA003': self._get_zima003_errors,
            'WECH007': self._get_wech007_errors,
            'WECH001': self._get_wech001_errors,
            'WECH006': self._get_wech006_errors,
            'WECH002': self._get_wech002_errors,
            'WECH003': self._get_wech003_errors,
            'WECH005': self._get_wech005_errors,
            'WECH008': self._get_wech008_errors,
            'WECH009': self._get_wech009_errors,
            'WECH010': self._get_wech010_errors,
            'ZIMA001': self._get_zima001_errors,
            'ZIMA002': self._get_zima002_errors,
            'ZIMA006': self._get_zima006_errors,
        }.get(self.identification)
        if get_declaration_errors:
            errors += get_declaration_errors(version)
        return errors

    def _get_identification_errors(self):
        """ Errors on the identification of the employer, the worker and the contact person """
        self.ensure_one()
        errors = []
        if not self.company_onss_number:
            errors.append(self.env._("No ONSS registration number was found for company %s. Please provide at least one.", self.company_id.name))
        if not self.employee_id._is_niss_valid() or self.employee_id.niss == '/':
            errors.append(self.env._('Invalid NISS number for %s', self.employee_id.name))
        if not self.payroll_config_id.l10n_be_employer_category_id:
            errors.append(self.env._('Missing Employer Category for %s', self.company_id.name))
        if self.employee_id.lang not in LANG_CODE:
            errors.append(self.env._("Employee's language must be either Dutch, French or German"))
        if self.sector == 'compensation':
            email = self._get_contact_values()['email']
            if not email:
                errors.append(self.env._(
                    "The HR responsible of %(employee)s must have an email address: they are the contact person of the declaration.",
                    employee=self.employee_id.name))
            elif len(email) > 60 or not email_normalize(email):
                errors.append(self.env._(
                    "The email address of the HR responsible of %(employee)s must be valid and have at most 60 characters.",
                    employee=self.employee_id.name))
        employer_category = self.payroll_config_id.l10n_be_employer_category_id.dmfa_code
        if employer_category in DRS_FORBIDDEN_EMPLOYER_CATEGORIES:
            errors.append(self.env._(
                "The employers of the category %(category)s (third-party payers, Fedris, shipowners) can't send DRS declarations.",
                category=employer_category))
        return errors

    def _get_common_errors(self, version):
        self.ensure_one()
        errors = self._get_identification_errors()
        if self.identification != 'ZIMA006' and not version.l10n_be_joint_committee_id:
            errors.append(self.env._(
                "%(employee)s is missing a joint committee.", employee=self.employee_id.name))
        if self.risk_id and self.year and self.month and self.risk_id not in self.allowed_risk_ids:
            errors.append(self.env._("The risk %(risk)s can't be declared for that month anymore.", risk=self.risk_id.display_name))
        if self.year and self.year < 2016:
            errors.append(self.env._("The declarations of the months before 2016 must be made from the portal of the social security."))
        if self.identification != 'ZIMA006':
            errors += self._get_worker_code_errors(version) + self._get_working_schedule_errors(version)
        if self._is_monthly_declaration():
            date_from, date_to = self._get_first_last_day_of_month()
            __, occupation_start, occupation_end = version._get_occupation_dates()[-1]
            if occupation_start > date_to or occupation_end and occupation_end < date_from:
                errors.append(self.env._("%(employee)s has no occupation during %(month)s/%(year)s.", employee=self.employee_id.name, month=self.month, year=self.year))
        return errors

    def _get_worker_code_errors(self, version):
        self.ensure_one()
        worker_code = version.l10n_be_worker_code_id.dmfa_code
        if not worker_code:
            return [self.env._("%(employee)s is missing a worker code.", employee=self.employee_id.name)]
        default_codes = UNEMPLOYMENT_FORBIDDEN_WORKER_CODES if self.sector == 'unemployment' else ()
        forbidden_codes = DRS_FORBIDDEN_WORKER_CODES + FORBIDDEN_WORKER_CODES_BY_IDENTIFICATION.get(self.identification, default_codes)
        if worker_code in forbidden_codes or ('6' in forbidden_codes and worker_code.startswith('6')):
            if self.sector == 'compensation':
                return [self.env._("The worker code %(code)s can't be declared to the health insurance.", code=worker_code)]
            return [self.env._("The worker code %(code)s can't be declared to the unemployment sector.", code=worker_code)]
        return []

    def _get_working_schedule_errors(self, version):
        """ The mean weekly hours of the worker (Q) and of the full-time reference worker (S) """
        self.ensure_one()
        calendar = version.resource_calendar_id
        reference_calendar = version._get_reference_calendar()
        if round(calendar.hours_per_week, 2) <= 0 or round(calendar.days_per_week, 2) <= 0:
            return [self.env._("The working schedule of %(employee)s must define its working hours and days per week.", employee=self.employee_id.name)]
        errors = []
        if round(calendar.hours_per_week, 2) > round(reference_calendar.hours_per_week, 2):
            errors.append(self.env._(
                "%(employee)s works more hours per week than the full-time reference schedule (%(schedule)s) of their working schedule.",
                employee=self.employee_id.name, schedule=reference_calendar.name))
        if reference_calendar.hours_per_week > 48:
            errors.append(self.env._("The full-time reference schedule %(schedule)s can't exceed 48 hours per week.", schedule=reference_calendar.name))
        return errors

    def _check_days_in_occupation(self, version, day_list):
        """ The days are declared in the occupation of the declaration, the last one of the month """
        self.ensure_one()
        __, occupation_start, occupation_end = version._get_occupation_dates()[-1]
        if any(day['day'] < occupation_start or occupation_end and day['day'] > occupation_end for day in day_list):
            return [self.env._(
                "%(employee)s has days to declare outside of their last occupation of the month (from %(date)s): the occupations of the month must be declared from the portal of the social security.",
                employee=self.employee_id.name, date=format_date(self.env, occupation_start))]
        return []

    def _check_hours_per_day(self, day_list, max_hours):
        """ The hours of all the natures of a day can't exceed `max_hours` """
        self.ensure_one()
        hours_per_day = defaultdict(int)
        for day in day_list:
            hours_per_day[day['day']] += day['hours_amount']
        return [
            self.env._("More than %(hours)s hours are declared on %(date)s.", hours=max_hours, date=format_date(self.env, day))
            for day, hours in sorted(hours_per_day.items()) if hours > max_hours * 100
        ]

    def _check_month_not_future(self):
        self.ensure_one()
        if date(self.year, int(self.month), 1) > fields.Date.context_today(self):
            return [self.env._("The declaration month cannot be in the future.")]
        return []

    def _get_declaration_data(self, version):
        self.ensure_one()
        data = self._get_common_declaration_data(version)
        get_declaration_data = {
            'ZIMA003': self._get_zima003_declaration_data,
            'WECH007': self._get_wech007_declaration_data,
            'WECH001': self._get_wech001_declaration_data,
            'WECH003': self._get_wech003_declaration_data,
            'WECH006': self._get_wech006_declaration_data,
            'WECH002': self._get_wech002_declaration_data,
            'WECH005': self._get_wech005_declaration_data,
            'WECH008': self._get_wech008_declaration_data,
            'WECH009': self._get_wech009_declaration_data,
            'WECH010': self._get_wech010_declaration_data,
            'ZIMA001': self._get_zima001_declaration_data,
            'ZIMA002': self._get_zima002_declaration_data,
            'ZIMA006': self._get_zima006_declaration_data,
        }.get(self.identification)
        if get_declaration_data:
            data.update(get_declaration_data(version))
        return data

    def _get_common_declaration_data(self, version):
        self.ensure_one()
        date_from, date_to = self._get_first_last_day_of_month()
        now = datetime.now(ZoneInfo('Europe/Brussels'))
        attestation_status = self._get_attestation_status()
        remuneration_time_unit = '1' if version.wage_type == 'hourly' else '4'
        return {
            'data': self,
            'identification': self.identification,
            'schema_location': f'{self.identification}_{self._get_schema_year_quarter()}.xsd',
            'form_creation_date': now.strftime('%Y-%m-%d'),
            'form_creation_hour': now.strftime('%H:%M:%S.%f')[:12],
            'attestation_status': attestation_status,
            'references': self._get_references(attestation_status),
            'contact': self._get_contact_values() if self.sector == 'compensation' else False,
            'declaration_lang': LANG_CODE.get(self.employee_id.lang, '2'),
            'risk_code': self.risk_id.code,
            'risk_codes': [self.risk_id.code],
            'onss_registration_number': format_amount(self.company_onss_number or 0, width=9, hundredth=False),
            'l10n_be_company_number': format_amount(self.payroll_config_id.l10n_be_company_number or 0, width=10, hundredth=False),
            'inss': self.employee_id.niss,
            'employer_class': self.payroll_config_id.l10n_be_employer_category_id.dmfa_code,
            'worker_code': version.l10n_be_worker_code_id.dmfa_code,
            'occupation': self._get_occupation_values(version),
            'occupation_features': False,
            # A cancellation of a declaration to the health insurance is commented
            'form_comment': 'ANNULATIE / ANNULATION' if self.sector == 'compensation' and attestation_status == '3' else False,
            'declaration_comment': False,
            'date_from': date_from and date_from.strftime('%Y-%m-%d'),
            'date_to': date_to and date_to.strftime('%Y-%m-%d'),
            'remuneration_time_unit': remuneration_time_unit,
            'remuneration_basis_amount': round(self._get_remuneration_basis_amount(version) * (10000 if remuneration_time_unit == '1' else 100)),
        }

    def _get_contact_values(self):
        """ The HR responsible of the employee answers the questions about the declaration """
        self.ensure_one()
        contact = self.employee_id.hr_responsible_id or self.env.user
        return {
            'name': (contact.name or '')[:48],
            'phone': (contact.phone or '').strip()[:20],
            'email': (contact.email or '').strip(),
        }

    def _get_attestation_status(self):
        """ 0: original declaration, 1: modification and 3: cancellation of the last declaration of the
        same risk accepted by the ONSS """
        self.ensure_one()
        if self.env.context.get('l10n_be_drs_cancellation') or self._is_cancellation():
            return '3'
        return '1' if self._get_modified_declaration() else '0'

    def _is_cancellation(self):
        self.ensure_one()
        if not self.xml_file:
            return False
        try:
            root = etree.fromstring(self.xml_file.content)
        except etree.XMLSyntaxError:
            return False
        return root.findtext('Form/AttestationStatus') == '3'

    def _get_modification_key(self):
        # The declarations of the same key replace each other
        self.ensure_one()
        risk_key = self.identification if self.identification in GROUPED_RISKS_IDENTIFICATIONS else self.risk_id
        return (self.employee_id, risk_key, self.year, self.month)

    def _get_modified_declaration(self):
        """ Return the last declaration of the same key accepted by the ONSS, that this one replaces """
        self.ensure_one()
        if not self.id:
            return self.browse()
        previous_declarations = self.search([
            ('id', '<', self.id),
            ('employee_id', '=', self.employee_id.id),
            ('risk_id.identification', '=', self.identification),
        ], order='id desc').filtered(lambda drs: drs._get_modification_key() == self._get_modification_key())
        for declaration in previous_declarations:
            if declaration._get_ticket_number():
                # A cancelled declaration can't be modified anymore, a new declaration is an original one
                return self.browse() if declaration._is_cancellation() else declaration
        return self.browse()

    def _get_ticket_number(self):
        """ Return the ticket number given by the ONSS to the declaration in the notification of its acceptance """
        self.ensure_one()
        accepted_declarations = self.onss_declaration_ids.filtered(lambda declaration: declaration.state == 'notified')
        notifications = accepted_declarations.onss_file_ids.filtered(lambda onss_file: onss_file.declaration_type == 'NOTI' and onss_file.file)
        for notification in notifications.sorted('id', reverse=True):
            try:
                form = xml_str_to_dict(notification.file.content)['NOTIFICATION']['Form']
            except (etree.XMLSyntaxError, KeyError, TypeError):
                continue
            references = form.get('HandledReference', [])
            for reference in references if isinstance(references, list) else [references]:
                if reference.get('ReferenceOrigin') == '2' and reference.get('ReferenceNbr'):
                    return reference['ReferenceNbr']
        return False

    def _get_references(self, attestation_status):
        self.ensure_one()
        references = [{'type': '1', 'origin': '1', 'number': self.name}]
        if attestation_status in ('1', '3'):
            original = self._get_modified_declaration()
            if not original:
                raise UserError(self.env._("No declaration accepted by the ONSS was found for this modification or cancellation."))
            references.append({'type': '3', 'origin': '2', 'number': original._get_ticket_number()})
        return references

    def _is_monthly_declaration(self):
        self.ensure_one()
        return self.identification in MONTHLY_IDENTIFICATIONS

    def _get_occupation_values(self, version):
        self.ensure_one()
        calendar = version.resource_calendar_id
        reference_calendar = version._get_reference_calendar()
        __, occupation_start, occupation_end = version._get_occupation_dates()[-1]
        date_from, date_to = self._get_first_last_day_of_month()
        is_parttime = calendar.hours_per_week < reference_calendar.hours_per_week
        start, end = occupation_start, False
        if self._is_monthly_declaration():
            # The occupation is limited to the month of the declaration for a part-time worker,
            # its end is only declared when it's in the month
            if is_parttime:
                start = max(occupation_start, date_from)
                end = min(occupation_end or date_to, date_to)
            elif occupation_end and occupation_end <= date_to:
                end = occupation_end
        is_apprentice = version.l10n_be_worker_code_id.dmfa_code in ('035', '439')
        return {
            'start': start.strftime('%Y-%m-%d'),
            'end': end and end.strftime('%Y-%m-%d'),
            'committee': version.l10n_be_joint_committee_id.egov3_code,
            'working_days_system': format_amount(calendar.days_per_week, width=3),
            'mean_working_hours': format_amount(calendar.hours_per_week, width=4),
            'ref_mean_working_hours': format_amount(reference_calendar.hours_per_week, width=4),
            'worker_status': version.l10n_be_worker_status,
            'retired': version.l10n_be_is_retired,
            'apprenticeship': 1 if version.l10n_be_apprenticeship_contract_number or is_apprentice else False,
            'contract_type': 1 if is_parttime else 0,
            'remun_method': 2 if version.commission_on_target else False,
        }

    def _get_occupation_features(self, version, with_work_schedule=True):
        """ Changes of occupation in the month, and the kind of work schedule of the occupation """
        self.ensure_one()
        date_from, date_to = self._get_first_last_day_of_month()
        versions = self.employee_id._get_versions_with_contract_overlap_with_period(date_from, date_to) or version
        calendar = version.resource_calendar_id
        is_parttime = calendar.hours_per_week < version._get_reference_calendar().hours_per_week
        if is_parttime and len(set(versions.resource_calendar_id.mapped('hours_per_week'))) > 1:
            interruption = '3'
        elif len(set(versions.resource_calendar_id.mapped('days_per_week'))) > 1 or len(set(versions.resource_calendar_id.mapped('calendar_type'))) > 1:
            interruption = '5'
        else:
            interruption = '2'
        work_schedule_code = False
        if with_work_schedule:
            if interruption in ('3', '5'):
                work_schedule_code = '99'
            elif is_parttime:
                work_schedule_code = {'fixed': '10', 'variable': '11'}.get(calendar.calendar_type, '12')
            else:
                work_schedule_code = {'fixed': '01', 'variable': '02'}.get(calendar.calendar_type, '99')
        return {
            'interruption': interruption,
            'work_schedule_code': work_schedule_code,
        }

    # =======================================
    # WECH002
    # =======================================

    def _get_wech001_end_date(self):
        """ Last day of the employment contract ending during the month of the declaration """
        self.ensure_one()
        if self.departure_id:
            return self.departure_id.departure_date
        return self._get_wech001_contract_end_date()

    def _get_wech001_contract_end_date(self):
        """ Last day of the employment contract ending during the month of the declaration, from the contract dates """
        self.ensure_one()
        date_from, date_to = self._get_first_last_day_of_month()
        if not date_from:
            return False
        # The contract ends without being followed by another one
        return next((
            contract_end for contract_end in sorted(set(self.employee_id.version_ids.mapped('contract_date_end')) - {False}, reverse=True)
            if date_from <= contract_end <= date_to and not self.employee_id._get_versions_with_contract_overlap_with_period(
                contract_end + relativedelta(days=1), contract_end + relativedelta(days=1))
        ), False)

    def _get_wech001_errors(self, version):
        self.ensure_one()
        errors = []
        if self.code == '002':
            errors.append(self.env._("The unemployment with company supplement (RCC) must be declared from the portal of the social security."))
        elif self.code == '003':
            errors.append(self.env._("The end of the employment contracts in education can't be declared from Odoo."))
        elif self.code == '001' and not self._get_wech001_end_date():
            errors.append(self.env._("The employment contract of %(employee)s doesn't end during that month.", employee=self.employee_id.name))
        if self.code == '001' and self._get_remuneration_basis_amount(version) <= 0:
            errors.append(self.env._("The contractual salary of %(employee)s must be positive.", employee=self.employee_id.name))
        if version.l10n_be_worker_code_id.dmfa_code in ('840', '841'):
            errors.append(self.env._("The end of the occupation of a student can't be declared from Odoo."))
        end_date = self._get_wech001_end_date()
        if self.code == '001' and end_date and any(
                day > end_date + relativedelta(days=60) for day in self._get_wech001_paid_public_holidays(version, end_date)):
            errors.append(self.env._(
                "The public holidays paid after the end of the contract of %(employee)s are more than 60 days after it: the end of the employment contract must be declared from the portal of the social security.",
                employee=self.employee_id.name))
        quarters = self._get_wech001_quarters()
        if quarters[-1][0] > date_utils.get_quarter(fields.Date.context_today(self))[0]:
            errors.append(self.env._(
                "The end of the employment contract of %(employee)s can only be declared from the quarter in which it ends.",
                employee=self.employee_id.name))
        versions = self.employee_id.version_ids.filtered(lambda v: v.date_start <= quarters[-1][1] and (not v.date_end or v.date_end >= quarters[0][0]))
        if any(versions.mapped('l10n_be_time_credit')):
            errors.append(self.env._("The occupations with time credit must be declared from the portal of the social security."))
        for quarter_start, quarter_end in quarters:
            quarter_versions = versions.filtered(lambda v, start=quarter_start, end=quarter_end: v.date_start <= end and (not v.date_end or v.date_end >= start))
            if len(set(quarter_versions.l10n_be_worker_code_id.mapped('dmfa_code'))) > 1:
                errors.append(self.env._(
                    "The worker code of %(employee)s changes during the quarter: the end of the employment contract must be declared from the portal of the social security.",
                    employee=self.employee_id.name))
                break
        for previous_version in versions - version:
            errors += [error for error in self._get_worker_code_errors(previous_version) if error not in errors]
        return errors

    def _get_wech001_quarters(self):
        """ Quarters to declare: the one of the end of the contract, and the previous one if it isn't declared yet
        in the DmfA """
        self.ensure_one()
        reference_date = self._get_wech001_end_date() or self._get_first_last_day_of_month()[1]
        quarter_start, quarter_end = date_utils.get_quarter(reference_date)
        quarters = [(quarter_start, quarter_end)]
        previous_start = quarter_start - relativedelta(months=3)
        # The data of a DmfA accepted since 5 days are available to the unemployment sector
        previous_dmfa = self.env['l10n_be.dmfa'].sudo().search_count([
            ('company_id', '=', self.company_id.id),
            ('year', '=', str(previous_start.year)),
            ('quarter', '=', str(date_utils.get_quarter_number(previous_start))),
            ('declaration_type', '=', 'original'),
            ('state', 'in', ('done', 'in_progress', 'pending', 'paid')),
            ('write_date', '<=', fields.Datetime.now() - relativedelta(days=5)),
        ], limit=1)
        if not previous_dmfa and self.employee_id._get_versions_with_contract_overlap_with_period(previous_start, quarter_start - relativedelta(days=1)):
            quarters.insert(0, (previous_start, quarter_start - relativedelta(days=1)))
        return quarters

    def _get_wech001_declaration_data(self, version):
        self.ensure_one()
        end_date = self._get_wech001_end_date() if self.code == '001' else False
        occupation_dates = [
            (occupation_versions, start, end)
            for occupation_versions, start, end in self.employee_id.version_ids.sorted('date_start')._get_occupation_dates()
            if not end_date or start <= end_date
        ]
        quarters = []
        for quarter_start, quarter_end in self._get_wech001_quarters():
            occupations = []
            for occupation_versions, start, end in occupation_dates:
                if start > quarter_end or (end and end < quarter_start):
                    continue
                occupation_end = end_date if end_date and end_date <= quarter_end and (not end or end >= end_date) else end
                period_end = min(occupation_end or quarter_end, quarter_end)
                occupation_version = occupation_versions.filtered(lambda v: v.date_start <= period_end).sorted('date_start')[-1:] or occupation_versions[:1]
                occupations.append(self._get_wech001_occupation_values(
                    occupation_version, start, occupation_end if occupation_end and occupation_end <= quarter_end else False,
                    max(start, quarter_start), period_end, len(occupations) + 1))
            if end_date and quarter_start <= end_date <= quarter_end and occupations:
                occupations[-1]['severance'] = self._get_wech001_severance(end_date)
                occupations[-1]['end_block'] = self._get_wech001_end_block(version, end_date)
            quarters.append({
                'quarter': f'{quarter_start.year}{date_utils.get_quarter_number(quarter_start)}',
                'start': quarter_start.strftime('%Y-%m-%d'),
                'end': quarter_end.strftime('%Y-%m-%d'),
                'worker_code': (occupations and occupations[-1]['worker_code']) or version.l10n_be_worker_code_id.dmfa_code,
                'occupations': occupations,
            })
        return {'quarters': quarters}

    def _get_wech001_occupation_values(self, version, start, end, period_start, period_end, sequence):
        self.ensure_one()
        calendar = version.resource_calendar_id
        reference_hours = version._get_reference_calendar().hours_per_week
        is_parttime = calendar.hours_per_week < reference_hours
        employment_promotion = False
        if version.l10n_be_is_starterjob:
            employment_promotion = 13 if version.disabled else (16 if not self.employee_id.niss else 10)
        services = self._get_wech001_services(version, period_start, period_end)
        interruption = any(service['code'].lstrip('0') in WECH001_INTERRUPTION_DMFA_CODES for service in services)
        return {
            'sequence': sequence,
            'start': start.strftime('%Y-%m-%d'),
            'end': end and end.strftime('%Y-%m-%d'),
            'committee': version.l10n_be_joint_committee_id.egov3_code,
            'working_days_system': format_amount(calendar.days_per_week, width=3),
            'contract_type': 1 if is_parttime else 0,
            'ref_mean_working_hours': format_amount(reference_hours, width=4),
            'worker_status': version.l10n_be_worker_status,
            'mean_working_hours': format_amount(calendar.hours_per_week, width=4),
            'employment_promotion': employment_promotion,
            'retired': version.l10n_be_is_retired,
            'apprenticeship': 1 if version.l10n_be_apprenticeship_contract_number or version.l10n_be_worker_code_id.dmfa_code in ('035', '439') else False,
            'remun_method': 2 if version.commission_on_target else False,
            'worker_code': version.l10n_be_worker_code_id.dmfa_code,
            'interruption': 1 if interruption else 0,
            # The services are only declared for an occupation interrupted during the quarter
            'services': services if interruption else [],
            'severance': False,
            'end_block': False,
        }

    def _get_wech001_services(self, version, date_from, date_to):
        """ Days and hours of the occupation by kind of work (DmfA code) """
        self.ensure_one()
        hours_per_day = version.resource_calendar_id.hours_per_day or 1
        is_parttime = version.resource_calendar_id.hours_per_week < version._get_reference_calendar().hours_per_week
        hours_by_code = defaultdict(float)
        for work_entry in self.employee_id.generate_work_entries(date_from, date_to):
            work_entry_type = work_entry['work_entry_type_id']
            if work_entry_type.dmfa_code == '-1' or work_entry_type.code == '000.00':
                continue
            if not work_entry_type.dmfa_code:
                raise UserError(self.env._("The following work entry type does not have a DMFA code set: %s", work_entry_type.name))
            hours_by_code[work_entry_type.dmfa_code.zfill(3)] += work_entry['duration']
        # A service is declared with at least half a day
        return [{
            'code': code,
            'days': format_amount(round(hours / hours_per_day * 2) / 2, width=5),
            'hours': format_amount(hours, width=5) if is_parttime else False,
        } for code, hours in sorted(hours_by_code.items()) if round(hours / hours_per_day * 2)]

    def _get_wech001_severance(self, end_date):
        """ Period covered by an indemnity for the notice period not worked """
        self.ensure_one()
        departure = self.departure_id
        if not departure or departure.l10n_be_reason_code not in EMPLOYER_DEPARTURE_REASON_CODES \
                or departure.l10n_be_notice_respect == 'with' \
                or not departure.l10n_be_notice_period_theoretical_end or departure.l10n_be_notice_period_theoretical_end <= end_date:
            return False
        return {
            'start': (end_date + relativedelta(days=1)).strftime('%Y-%m-%d'),
            'end': departure.l10n_be_notice_period_theoretical_end.strftime('%Y-%m-%d'),
        }

    def _get_wech001_end_block(self, version, end_date):
        self.ensure_one()
        is_public_sector = self.payroll_config_id.l10n_be_employer_category_id.sector != 'private' or version.l10n_be_worker_code_id.dmfa_code in ('675', '678')
        holiday_sector = '2' if is_public_sector else '1'
        holidays = []
        if holiday_sector == '1':
            calendar = version.resource_calendar_id
            is_fulltime = calendar.hours_per_week >= version._get_reference_calendar().hours_per_week
            year_start = max(date(end_date.year, 1, 1), version._get_occupation_dates()[-1][1])
            # Legal holidays (code 1) and the additional holidays of the art. 17bis (code 11) taken during the year
            for code, nature in (('1', '3.1'), ('11', '3.5')):
                hours = sum(day['hours_amount'] for day in self._get_nature_of_days((nature,), year_start, end_date)[0]) / 100
                if code == '11' and not hours:
                    continue
                # The days are declared in a regime of 6 days, rounded to the half day
                days = hours / (calendar.hours_per_day or 1) * 6 / (calendar.days_per_week or 5)
                holidays.append({
                    'code': code,
                    'days': str(round(days * 2) * 5) if is_fulltime else False,
                    'hours': False if is_fulltime else round(hours * 100),
                })
        return {
            'compensatory_rest_days': 0,
            'public_holidays': [day.strftime('%Y-%m-%d') for day in self._get_wech001_paid_public_holidays(version, end_date)],
            'holiday_sector': holiday_sector,
            'holidays': holidays,
        }

    def _get_wech001_paid_public_holidays(self, version, end_date):
        """ The employer ending the contract pays the public holidays of the 30 days following the end of the
        contract (or of the period covered by the indemnity), 14 days for a seniority of less than a month """
        self.ensure_one()
        departure = self.departure_id
        if not departure or departure.l10n_be_reason_code not in EMPLOYER_DEPARTURE_REASON_CODES:
            return []
        severance = self._get_wech001_severance(end_date)
        reference_date = fields.Date.to_date(severance['end']) if severance else end_date
        first_contract_date = version._get_occupation_dates()[-1][1]
        if (end_date - first_contract_date).days < 15:
            return []
        period = 30 if first_contract_date + relativedelta(months=1) <= end_date else 14
        last_day = reference_date + relativedelta(days=period)
        # The public holidays are stored in UTC, they start the day before in UTC
        public_holidays = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('company_id', 'in', (self.company_id.id, False)),
            ('work_entry_type_id.code', '=', '006.00'),
            ('date_from', '>', datetime.combine(reference_date - relativedelta(days=1), time.max)),
            ('date_from', '<=', datetime.combine(last_day + relativedelta(days=1), time.max)),
        ], order='date_from')
        tz = ZoneInfo(self.employee_id._get_tz())
        public_holiday_dates = {public_holiday.date_from.replace(tzinfo=UTC).astimezone(tz).date() for public_holiday in public_holidays}
        return sorted(day for day in public_holiday_dates if reference_date < day <= last_day)[:4]

    @api.model
    def _get_wech002_start_dates(self, employee):
        """ Return the days on which the temporary unemployment of the employee must be declared, sorted, with
        their risk and time off: the first day of temporary unemployment, the first one of each period starting
        on the 1st of October, and the first one after a change of the working hours. Each time off of medical
        force majeure or for the dismissal of a protected worker is declared on its own, the other risks are
        declared together. """
        # sudo: hr.leave - the declarations are created when time off officers approve the time off
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('work_entry_type_id.l10n_be_drs_risk_ids.identification', '=', 'WECH002'),
        ], order='request_date_from, id')
        version_dates = set(employee.version_ids.mapped('date_version'))
        declared_hours = defaultdict(list)
        start_dates = []
        for leave in leaves:
            risk = leave.work_entry_type_id.l10n_be_drs_risk_ids.filtered(lambda risk: risk.identification == 'WECH002')[:1]
            is_exceptional_risk = risk.code in WECH002_EXCEPTIONAL_RISKS
            date_from, date_to = leave.request_date_from, leave.request_date_to
            october_firsts = {date(year, 10, 1) for year in range(date_from.year, date_to.year + 1)}
            check_dates = [date_from] + sorted(day for day in october_firsts | version_dates if date_from < day <= date_to)
            for check_date in check_dates:
                period_start = date(check_date.year if check_date.month >= 10 else check_date.year - 1, 10, 1)
                if is_exceptional_risk:
                    period_start = max(period_start, date_from)
                version = employee._get_version(check_date)
                hours = (version.resource_calendar_id.hours_per_week, version._get_reference_calendar().hours_per_week)
                key = risk.code if is_exceptional_risk else False
                last_hours = next((
                    declared for day, declared in reversed(declared_hours[key])
                    if period_start <= day <= check_date
                ), None)
                if last_hours == hours:
                    continue
                declared_hours[key].append((check_date, hours))
                start_dates.append((check_date, risk, leave))
        return sorted(start_dates, key=lambda start_date: start_date[0])

    def _get_wech002_errors(self, version):
        self.ensure_one()
        errors = []
        if not self.unemployment_start_date:
            errors.append(self.env._(
                "%(employee)s has no temporary unemployment to declare for the risk %(risk)s during that month.",
                employee=self.employee_id.name, risk=self.code))
            return errors
        errors += self._get_temporary_unemployment_errors(version, self.risk_id.mapped('code'))
        if self.code == '004' and not self.major_force_reason:
            errors.append(self.env._("The description of the time off is mandatory for force majeure (risk 004): it's the reason of the force majeure."))
        __, occupation_start, occupation_end = version._get_occupation_dates()[-1]
        if self.unemployment_start_date < occupation_start:
            errors.append(self.env._("The temporary unemployment can't start before the occupation of %(employee)s.", employee=self.employee_id.name))
        if occupation_end and self.unemployment_start_date > occupation_end:
            errors.append(self.env._("The temporary unemployment can't start after the end of the occupation of %(employee)s.", employee=self.employee_id.name))
        today = fields.Date.context_today(self)
        if self.unemployment_start_date > today + relativedelta(months=1, day=31):
            errors.append(self.env._(
                "The temporary unemployment of %(employee)s starts on %(date)s: it can only be declared from the month before.",
                employee=self.employee_id.name, date=format_date(self.env, self.unemployment_start_date)))
        if occupation_start > date_utils.get_quarter(today)[1]:
            errors.append(self.env._(
                "The occupation of %(employee)s starts after the current quarter: its temporary unemployment can only be declared from that quarter.",
                employee=self.employee_id.name))
        return errors

    def _get_temporary_unemployment_errors(self, version, risk_codes):
        self.ensure_one()
        errors = []
        is_worker = version.is_worker()
        if not is_worker and set(risk_codes) & {'001', '002', '003'}:
            errors.append(self.env._(
                "The temporary unemployment for economic reasons, bad weather or technical accident is reserved to the blue-collar workers: use the suspension for lack of work for %(employee)s.",
                employee=self.employee_id.name))
        if is_worker and '011' in risk_codes:
            errors.append(self.env._("The suspension for lack of work is reserved to the white-collar workers."))
        committee = version.l10n_be_joint_committee_id.egov3_code or ''
        if '007' in risk_codes and committee.split('.')[0] not in ('120', '324'):
            errors.append(self.env._("The collective closure for holidays of a collective agreement (risk 007) is reserved to the joint committees 120 and 324."))
        if committee.split('.')[0] == '322':
            errors.append(self.env._("The temporary unemployment of the temporary workers (joint committee 322) can't be declared from Odoo."))
        return errors

    def _get_wech002_declaration_data(self, version):
        self.ensure_one()
        return {
            'major_force_reason': self.major_force_reason if self.code == '004' else False,
            'temp_unemployment_starting_date': self.unemployment_start_date.strftime('%Y-%m-%d'),
        }

    # =======================================
    # WECH005
    # =======================================

    def _get_wech005_days(self):
        """ Return the hours of temporary unemployment of the month by day and nature, and the risks of these
        natures (the nature 5.n is the risk 0nn) """
        self.ensure_one()
        day_list = self._get_nature_of_days(TEMPORARY_UNEMPLOYMENT_NATURES)[0]
        risk_codes = sorted({'%03d' % int(day['nature_code'].split('.')[1]) for day in day_list})
        return day_list, risk_codes

    def _get_wech005_errors(self, version):
        self.ensure_one()
        day_list, risk_codes = self._get_wech005_days()
        if not day_list:
            return [self.env._(
                "%(employee)s has no temporary unemployment during that month, thus a declaration for that month is unnecessary.",
                employee=self.employee_id.name)]
        errors = self._get_temporary_unemployment_errors(version, risk_codes)
        date_from, date_to = self._get_first_last_day_of_month()
        if date_to >= fields.Date.context_today(self):
            errors.append(self.env._("The hours of temporary unemployment can only be declared once the month is over."))
        if len(risk_codes) > 5:
            errors.append(self.env._("At most 5 risks of temporary unemployment can be declared in the same month."))
        if '011' in risk_codes and set(risk_codes) & {'001', '002', '003'}:
            errors.append(self.env._("The suspension for lack of work (risk 011) can't be declared with the temporary unemployment of the blue-collar workers."))
        if '004' in risk_codes and not self._get_wech005_major_force_reason():
            errors.append(self.env._("The description of the time off is mandatory for force majeure (risk 004): it's the reason of the force majeure."))
        errors += self._check_nature_of_days(day_list) + self._check_hours_per_day(day_list, 14) + self._check_days_in_occupation(version, day_list)
        if self._get_occupation_features(version)['interruption'] != '2':
            errors.append(self.env._(
                "The working schedule of %(employee)s changed during the month: the temporary unemployment must be declared from the portal of the social security.",
                employee=self.employee_id.name))
        if set(risk_codes) & {'006', '007'} and self._has_previous_collective_closure(date_from):
            errors.append(self.env._(
                "The previous collective closures of the year must be declared with the collective closure: the temporary unemployment must be declared from the portal of the social security."))
        if version.is_fulltime and self._get_weekend_public_holidays_before_unemployment(day_list):
            errors.append(self.env._(
                "A public holiday falls on a weekend before a day of temporary unemployment: its replacement day must be declared from the portal of the social security."))
        return errors

    def _get_wech005_major_force_reason(self):
        self.ensure_one()
        date_from, date_to = self._get_first_last_day_of_month()
        # sudo: hr.leave - the description of the time off is restricted to the time off officers
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('work_entry_type_id.l10n_be_drs_nature', '=', '5.4'),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ], order='request_date_from')
        return next((leave.private_name.strip()[:60] for leave in leaves if leave.private_name and leave.private_name.strip()), False)

    def _has_previous_collective_closure(self, date_from):
        """ Whether the employee had a collective closure earlier in the year, to declare as closing period """
        self.ensure_one()
        return bool(self.env['hr.leave'].sudo().search_count([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('work_entry_type_id.l10n_be_drs_nature', 'in', ('5.6', '5.7')),
            ('request_date_from', '>=', date_from.replace(month=1, day=1)),
            ('request_date_from', '<', date_from),
        ], limit=1))

    def _get_weekend_public_holidays_before_unemployment(self, day_list):
        """ Public holidays on a weekend followed by a monday of temporary unemployment: the day replacing them
        isn't compensated """
        self.ensure_one()
        public_holidays = self._get_public_holiday_dates()
        unemployment_mondays = {day['day'] for day in day_list if day['day'].weekday() == 0}
        return [
            day for day in public_holidays
            if day.weekday() in (5, 6) and day + timedelta(days=7 - day.weekday()) in unemployment_mondays
        ]

    def _get_wech005_declaration_data(self, version):
        self.ensure_one()
        day_list, risk_codes = self._get_wech005_days()
        return {
            'risk_codes': risk_codes,
            'occupation_features': self._get_occupation_features(version),
            'nature_of_day_list': day_list,
            'major_force_reason': self._get_wech005_major_force_reason() if '004' in risk_codes else False,
        }

    def _get_payslip_errors(self):
        self.ensure_one()
        errors = []
        if not self.payslip_id or self.payslip_id.state not in ('validated', 'paid'):
            errors.append(self.env._(
                "A validated payslip for %(month)s/%(year)s is required for %(employee)s.",
                month=self.month, year=self.year, employee=self.employee_id.name))
        return errors + self._check_month_not_future()

    def _get_theoretical_salary_values(self, version):
        # Monthly salary in eurocents, hourly salary in hundredths of eurocents
        is_hourly_wage = version.wage_type == 'hourly'
        wage = version._get_contract_wage()
        return {
            'is_hourly_wage': is_hourly_wage,
            'theoretical_salary': round(wage * 10000) if is_hourly_wage else round(wage * 100),
        }

    def _get_part_time_errors(self, version):
        self.ensure_one()
        errors = []
        if version.resource_calendar_id.hours_per_week >= version._get_reference_calendar().hours_per_week:
            errors.append(self.env._("%(employee)s doesn't work part-time.", employee=self.employee_id.name))
        if self._get_theoretical_salary_values(version)['theoretical_salary'] <= 0:
            errors.append(self.env._("The contractual salary of %(employee)s must be positive.", employee=self.employee_id.name))
        return errors

    # =======================================
    # WECH003
    # =======================================

    def _get_wech003_errors(self, version):
        self.ensure_one()
        errors = self._get_part_time_errors(version)
        occupation_start = version._get_occupation_dates()[-1][1]
        if occupation_start < date(2016, 1, 1):
            errors.append(self.env._(
                "The part-time occupation of %(employee)s started before 2016: its work schedule must be declared from the portal of the social security.",
                employee=self.employee_id.name))
        if occupation_start > date_utils.get_quarter(fields.Date.context_today(self))[1] + relativedelta(months=1):
            errors.append(self.env._(
                "The part-time occupation of %(employee)s starts more than one month after the current quarter: it can't be declared yet.",
                employee=self.employee_id.name))
        return errors

    def _get_wech003_declaration_data(self, version):
        self.ensure_one()
        return {
            # The occupation isn't part of a company plan for the redistribution of the work
            'dbr_indicator': 0,
            # The workers asking an income guarantee allowance asked a full-time occupation, without joint committee
            # the question is not applicable
            'full_time_occupation_request': 9 if version.l10n_be_joint_committee_id.egov3_code == '999' else 1,
            **self._get_theoretical_salary_values(version),
        }

    # =======================================
    # WECH006
    # =======================================

    def _get_wech006_days(self):
        """ Return the days of the month with their nature, and their worked or paid hours. The days of
        incapacity after the guaranteed salary are declared with 0 hours on the days without work. """
        self.ensure_one()
        day_list = [dict(day, hours_amount=min(day['hours_amount'], 2400)) for day in self._get_nature_of_days()[0]]
        declared_days = {day['day'] for day in day_list}
        for nature in WECH006_INCAPACITY_NATURES:
            nature_days = [day['day'] for day in day_list if day['nature_code'] == nature]
            if not nature_days:
                continue
            gap = min(nature_days)
            while gap < max(nature_days):
                if gap not in declared_days:
                    day_list.append({'day': gap, 'date': gap.strftime('--%m-%d'), 'nature_code': nature, 'hours_amount': 0})
                    declared_days.add(gap)
                gap += timedelta(days=1)
        return sorted(day_list, key=lambda day: (day['day'], day['nature_code']))

    def _get_wech006_errors(self, version):
        self.ensure_one()
        errors = self._get_payslip_errors() + self._get_part_time_errors(version)
        date_to = self._get_first_last_day_of_month()[1]
        if date_to >= fields.Date.context_today(self):
            errors.append(self.env._("The part-time work can only be declared once the month is over."))
        day_list = self._get_wech006_days()
        if not day_list:
            errors.append(self.env._(
                "%(employee)s has no worked or absence hours to declare during that month.",
                employee=self.employee_id.name))
        errors += self._check_nature_of_days(day_list) + self._check_hours_per_day(day_list, 24) + self._check_days_in_occupation(version, day_list)
        natures = {day['nature_code'] for day in day_list}
        if '1.1' in natures:
            errors.append(self.env._("The nature of day 1.1 can't be declared for the part-time work."))
        if '8' in natures and len(natures) > 1:
            errors.append(self.env._(
                "The days of normal inactivity (nature 8) of %(employee)s can only be declared for an occupation without any work or absence during the month.",
                employee=self.employee_id.name))
        if self._get_occupation_features(version)['interruption'] != '2':
            errors.append(self.env._(
                "The working schedule of %(employee)s changed during the month: the part-time work must be declared from the portal of the social security.",
                employee=self.employee_id.name))
        return errors

    def _get_wech006_declaration_data(self, version):
        self.ensure_one()
        day_list = self._get_wech006_days()
        gross_salary = self.payslip_id._get_line_values(['SALARY'])['SALARY'][self.payslip_id.id]['total']
        has_holidays = any(day['nature_code'] in ('3.1', '3.2', '3.3', '3.4') for day in day_list)
        is_public_sector = self.payroll_config_id.l10n_be_employer_category_id.sector != 'private' or version.l10n_be_worker_code_id.dmfa_code in ('675', '678')
        return {
            'occupation_features': self._get_occupation_features(version),
            # The employer didn't offer a full time occupation refused by the worker during the month
            'occupation_refused': 0,
            'holiday_sector': ('2' if is_public_sector else '1') if has_holidays else False,
            'nature_of_day_list': day_list,
            'gross_salary': max(round(gross_salary * 100), 0),
            **self._get_theoretical_salary_values(version),
        }

    # =======================================
    # WECH007
    # =======================================

    def _get_wech007_days(self):
        self.ensure_one()
        hours_by_day = defaultdict(int)
        for day in self._get_nature_of_days()[0]:
            nature_code = WECH007_NATURES.get(day['nature_code'], day['nature_code'])
            if nature_code:
                hours_by_day[day['day'], nature_code] += day['hours_amount']
        return [{
            'day': day,
            'date': day.strftime('--%m-%d'),
            'nature_code': nature_code,
            'hours_amount': hours_amount,
        } for (day, nature_code), hours_amount in sorted(hours_by_day.items())]

    def _get_wech007_errors(self, version):
        self.ensure_one()
        errors = []
        if (version.l10n_be_joint_committee_id.egov3_code or '').split('.')[0] != '327':
            errors.append(self.env._("The work in a sheltered workshop is declared for the joint committee 327 only."))
        date_to = self._get_first_last_day_of_month()[1]
        if date_to >= fields.Date.context_today(self):
            errors.append(self.env._("The work in a sheltered workshop can only be declared once the month is over."))
        day_list = self._get_wech007_days()
        if not day_list:
            errors.append(self.env._("%(employee)s has no worked or absence hours to declare during that month.", employee=self.employee_id.name))
        errors += self._check_nature_of_days(day_list) + self._check_hours_per_day(day_list, 14) + self._check_days_in_occupation(version, day_list)
        if any(day['nature_code'] == '1.1' for day in day_list):
            errors.append(self.env._("The nature of day 1.1 can't be declared for the work in a sheltered workshop."))
        return errors

    def _get_wech007_declaration_data(self, version):
        self.ensure_one()
        day_list = self._get_wech007_days()
        return {
            # The hours of holidays covered by the holiday pay, only declared with statutory or supplementary holidays
            'paid_holiday_hours': sum(day['hours_amount'] for day in day_list if day['nature_code'] in ('3.1', '3.2', '3.3'))
                if any(day['nature_code'] in ('3.1', '3.2') for day in day_list) else 0,
            # Odoo doesn't know the changes of family or personal situation of the worker
            'worker_situation_changed': 0,
            'nature_of_day_list': day_list,
        }

    # =======================================
    # WECH008
    # =======================================

    def _get_wech008_errors(self, version):
        self.ensure_one()
        errors = self._get_payslip_errors()
        if self.code in WECH008_WORK_ALLOWANCE_RISKS and self.code not in ('010', '011'):
            errors.append(self.env._("Only the work allowance of the Impulsion plans (risks 010 and 011) can be declared."))
        occupation_start = version._get_occupation_dates()[-1][1]
        if self.code in ('010', '011', '012') and occupation_start < date(2017, 7, 1):
            errors.append(self.env._("The uninterrupted occupation of %(employee)s must start from the 1st of July 2017 for the risk %(risk)s.",
                employee=self.employee_id.name, risk=self.code))
        if self.net_salary < 0:
            errors.append(self.env._("The net salary of %(employee)s for the month can't be negative.", employee=self.employee_id.name))
        elif self.code in WECH008_WORK_ALLOWANCE_RISKS and self.net_salary and not self.work_allowance:
            errors.append(self.env._(
                "%(employee)s has no right to a work allowance of the Impulsion plan for %(month)s/%(year)s: the declaration is not needed.",
                employee=self.employee_id.name, month=self.month, year=self.year))
        if self._get_occupation_features(version, with_work_schedule=False)['interruption'] not in ('2', '3', '4'):
            errors.append(self.env._(
                "The working schedule of %(employee)s changed during the month: the work in an activation program must be declared from the portal of the social security.",
                employee=self.employee_id.name))
        return errors

    def _get_wech008_declaration_data(self, version):
        self.ensure_one()
        __, occupation_start, occupation_end = version._get_occupation_dates()[-1]
        # The allowance of a contract of less than 2 months is rounded to the cent
        is_short_contract = occupation_end and occupation_end < occupation_start + relativedelta(months=2)
        return {
            'occupation_features': self._get_occupation_features(version, with_work_schedule=False),
            'uninterrupted_occupation_date': occupation_start.strftime('%Y-%m-%d') if self.code in WECH008_UNINTERRUPTED_OCCUPATION_RISKS else False,
            'work_accident_indicator': 1 if self.work_accident_indicator else 0,
            'has_work_allowance': self.code in WECH008_WORK_ALLOWANCE_RISKS,
            'paid_hours': round(self.paid_hours * 100),
            'work_allowance': round(self.work_allowance * 100) if is_short_contract else round(self.work_allowance * 10000),
            'net_salary': round(self.net_salary * 100),
            'bonus_payment_frequency': False,
        }

    # =======================================
    # WECH009
    # =======================================

    def _get_wech009_errors(self, version):
        self.ensure_one()
        errors = []
        if not self._get_nature_of_days(('3.4',))[0]:
            errors.append(self.env._(
                "%(employee)s didn't take youth or senior holidays during that month: the declaration is made for the month of the first youth or senior holidays of the year.",
                employee=self.employee_id.name))
        errors += self._check_month_not_future()
        # The right to youth or senior holidays depends on the age at the end of the previous year (holiday year)
        if self.employee_id.birthday:
            age = self.employee_id._get_age(date(self.year - 1, 12, 31))
            if self.code == '001' and age >= 25:
                errors.append(self.env._("%(employee)s is not entitled to youth holidays: they were 25 years old or more at the end of the previous year.", employee=self.employee_id.name))
            elif self.code == '002' and age < 50:
                errors.append(self.env._("%(employee)s is not entitled to senior holidays: they were less than 50 years old at the end of the previous year.", employee=self.employee_id.name))
        return errors

    def _get_wech009_declaration_data(self, version):
        self.ensure_one()
        is_public_sector = self.payroll_config_id.l10n_be_employer_category_id.sector != 'private' or version.l10n_be_worker_code_id.dmfa_code in ('675', '678')
        return {
            'holiday_start_month': f'{self.year}-{int(self.month):02d}',
            'holiday_hours': round(self.holiday_hours * 100),
            'sector': '2' if is_public_sector else '1',
        }

    # =======================================
    # WECH010
    # =======================================

    def _get_wech010_nature_of_day(self):
        self.ensure_one()
        if self.identification != 'WECH010':
            return False
        day_list, __ = self._get_nature_of_days(('3.1', '3.4'))  # Legal Time Off or Youth/Senior Time Off
        return day_list

    def _get_wech010_errors(self, version):
        self.ensure_one()
        day_list = self._get_wech010_nature_of_day()
        youth_days = [day['day'] for day in day_list if day['nature_code'] == '3.4']
        if not youth_days:
            return [self.env._(
                "%(employee)s didn't take any youth or senior holidays during that month, "
                "thus a declaration for that month is unnecessary.",
                employee=self.employee_id.name)]
        errors = self._check_nature_of_days(day_list) + self._check_hours_per_day(day_list, 14) + self._check_days_in_occupation(version, day_list)
        errors += self._check_month_not_future()
        # The legal holidays must be taken before the youth or senior holidays
        if any(day['nature_code'] == '3.1' and day['day'] > youth_days[0] for day in day_list):
            errors.append(self.env._(
                "%(employee)s took legal holidays after youth or senior holidays during that month: the legal holidays must be taken first.",
                employee=self.employee_id.name))
        return errors

    def _get_wech010_declaration_data(self, version):
        self.ensure_one()
        return {
            'occupation_features': self._get_occupation_features(version),
            'nature_of_day_list': self._get_wech010_nature_of_day(),
        }

    # =======================================
    # ZIMA002
    # =======================================

    def _get_zima002_period(self, version):
        """ The reference period is the month, limited to the contract """
        self.ensure_one()
        date_from, date_to = self._get_first_last_day_of_month()
        return (
            max(date_from, version.contract_date_start or date_from),
            min(date_to, version.contract_date_end or date_to),
        )

    def _get_zima002_services(self, date_from, date_to):
        """ Hours of the adapted work by kind of work (DmfA code): the work, the guaranteed salary and the absences
        due to the incapacity """
        self.ensure_one()
        hours_by_code = defaultdict(float)
        for work_entry in self.employee_id.generate_work_entries(date_from, date_to):
            work_entry_type = work_entry['work_entry_type_id']
            if not work_entry_type.dmfa_code or work_entry_type.dmfa_code == '-1' or work_entry_type.code == '000.00':
                continue
            hours_by_code[work_entry_type.dmfa_code.zfill(3)] += work_entry['duration']
        return [{'code': code, 'hours': format_amount(hours, width=7)} for code, hours in sorted(hours_by_code.items()) if round(hours, 2)]

    def _get_zima002_errors(self, version):
        self.ensure_one()
        errors = []
        date_from, date_to = self._get_zima002_period(version)
        if date_to - timedelta(days=5) > fields.Date.context_today(self):
            errors.append(self.env._("The adapted work can only be declared from 5 days before the end of the month."))
        if date_from > fields.Date.context_today(self):
            errors.append(self.env._("The adapted work can only be declared once the employment contract of %(employee)s started.", employee=self.employee_id.name))
        if self.code == '002':
            if self.employee_id.sex != 'female':
                errors.append(self.env._("The adapted work as a maternity protection measure is reserved to women."))
            errors += self._get_payslip_errors()
            day_list = self._get_nature_of_days(ZIMA002_NATURES, date_from, date_to)[0]
            errors += self._check_nature_of_days(day_list) + self._check_hours_per_day(day_list, 14)
        elif not (services := self._get_zima002_services(date_from, date_to)):
            errors.append(self.env._("%(employee)s has no adapted work to declare during that month.", employee=self.employee_id.name))
        else:
            if any(service['code'] == '998' for service in services):
                errors.append(self.env._(
                    "%(employee)s has time off without a DmfA service code (parental leave, palliative care) during that month: the adapted work must be declared from the portal of the social security.",
                    employee=self.employee_id.name))
            if date(2024, 7, 1) <= date_from < date(2026, 2, 1) and any(service['code'] == '011' for service in services):
                errors.append(self.env._(
                    "The guaranteed salary (service code 011) of the adapted work before February 2026 requires a theoretical salary: the adapted work must be declared from the portal of the social security."))
        if self._get_occupation_features(version)['interruption'] != '2':
            errors.append(self.env._(
                "The working schedule of %(employee)s changed during the month: the adapted work must be declared from the portal of the social security.",
                employee=self.employee_id.name))
        return errors

    def _get_zima002_declaration_data(self, version):
        self.ensure_one()
        date_from, date_to = self._get_zima002_period(version)
        calendar = version.resource_calendar_id
        reference_calendar = version._get_reference_calendar()
        # The occupation includes the hours of the medical part-time, the adapted work excludes them
        occupation_hours = calendar._l10n_be_get_work_time_rate_med_included(date_from, date_to, reference_calendar) * reference_calendar.hours_per_week
        occupation_days = len(set(calendar.attendance_ids.filtered(
            lambda attendance: not attendance.date and (attendance._is_work_period() or attendance.work_entry_type_id.code in ('122.04', '123.04'))
        ).mapped('dayofweek')))
        occupation = dict(
            self._get_occupation_values(version),
            start=version._get_occupation_dates()[-1][1].strftime('%Y-%m-%d'),
            end=version.contract_date_end and version.contract_date_end <= date_to and version.contract_date_end.strftime('%Y-%m-%d'),
            working_days_system=format_amount(occupation_days or calendar.days_per_week, width=3),
            mean_working_hours=format_amount(occupation_hours, width=4),
            contract_type=1 if round(occupation_hours, 2) < reference_calendar.hours_per_week else 0,
        )
        values = {
            'occupation': occupation,
            'adapted_working_hours': format_amount(calendar.hours_per_week, width=4),
            'adapted_working_days': format_amount(calendar.days_per_week, width=3),
            'date_from': date_from.strftime('%Y-%m-%d'),
            'date_to': date_to.strftime('%Y-%m-%d'),
            'services': [],
            'nature_of_day_list': [],
            'gross_salary': False,
        }
        if self.code == '001':
            values['services'] = self._get_zima002_services(date_from, date_to)
        else:
            # The holidays, temporary unemployment and work accidents of the period
            values['nature_of_day_list'] = self._get_nature_of_days(ZIMA002_NATURES, date_from, date_to)[0]
            gross_salary = self.payslip_id._get_line_values(['SALARY'])['SALARY'][self.payslip_id.id]['total']
            values['gross_salary'] = max(round(gross_salary * 100), 0)
        return values

    def _get_first_last_day_of_month(self):
        self.ensure_one()
        if not self.year or not self.month:
            return (False, False)
        date_from = date(self.year, int(self.month), 1)
        date_to = date_from + relativedelta(day=31)
        return (date_from, date_to)

    def _get_remuneration_basis_amount(self, version):
        self.ensure_one()
        return version.hourly_wage if version.wage_type == 'hourly' else version.wage

    def _get_period_version(self):
        self.ensure_one()
        date_from, date_to = self._get_first_last_day_of_month()
        versions = self.employee_id._get_versions_with_contract_overlap_with_period(date_from, date_to)
        return versions[-1] if versions else self.employee_id._get_version(date_to)

    def _get_nature_of_day_list(self):
        self.ensure_one()
        return self._get_nature_of_days()[0]

    def _get_nature_of_days(self, nature_codes=None, date_from=None, date_to=None):
        """ Return the hours of the days of the period (the month by default) by nature of day, sorted by date,
        and the work entries of the period """
        self.ensure_one()
        if not date_from or not date_to:
            date_from, date_to = self._get_first_last_day_of_month()
        work_entries = self.employee_id.generate_work_entries(date_from, date_to)
        hours_by_day = defaultdict(int)
        for work_entry in work_entries:
            nature_code = work_entry['work_entry_type_id'].l10n_be_drs_nature
            if nature_code and (nature_codes is None or nature_code in nature_codes):
                hours_by_day[work_entry['date'], nature_code] += round(work_entry['duration'] * 100)
        day_list = [{
            'day': day,
            'date': day.strftime('--%m-%d'),
            'nature_code': nature_code,
            'hours_amount': hours_amount,
        } for (day, nature_code), hours_amount in sorted(hours_by_day.items()) if hours_amount]
        return day_list, work_entries

    def _check_nature_of_days(self, day_list):
        """ A day is declared with at most 2 natures """
        self.ensure_one()
        natures_per_day = defaultdict(list)
        for day in day_list:
            natures_per_day[day['day']].append(day['nature_code'])
        return [
            self.env._("%(employee)s has more than 2 natures of day on %(date)s (%(natures)s): a day can only be declared with 2 natures.",
                employee=self.employee_id.name, date=format_date(self.env, day), natures=', '.join(natures))
            for day, natures in natures_per_day.items() if len(natures) > 2
        ]

    def _get_public_holiday_dates(self):
        """Public holidays of the period, in the employee timezone."""
        self.ensure_one()
        employee = self.employee_id
        tz = ZoneInfo(employee._get_tz())
        date_from, date_to = self._get_first_last_day_of_month()
        holiday_dates = set()
        for public_holiday in employee._get_public_holidays(date_from, date_to + relativedelta(days=1)):
            first_day = max(public_holiday.date_from.replace(tzinfo=UTC).astimezone(tz).date(), date_from)
            last_day = min(public_holiday.date_to.replace(tzinfo=UTC).astimezone(tz).date(), date_to)
            holiday_dates.update(day.date() for day in rrule(DAILY, first_day, until=last_day))

        return holiday_dates

    # =======================================
    # ZIMA001
    # =======================================

    @api.model
    def _get_zima001_periods(self, employee):
        """ Return the periods of the risks of the health insurance of the employee, with their risk and time off.
        Successive incapacities separated by less than 14 days of work are the same risk. """
        # sudo: hr.leave - the declarations are created when time off officers approve the time off
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('work_entry_type_id.l10n_be_drs_risk_ids.identification', '=', 'ZIMA001'),
        ], order='request_date_from, id')
        periods = []
        for leave in leaves:
            risk = leave.work_entry_type_id.l10n_be_drs_risk_ids.filtered(lambda risk: risk.identification == 'ZIMA001').sorted('code')[:1]
            period = next((period for period in reversed(periods) if period['risk'] == risk), None)
            if period:
                gap_start, gap_end = period['end'] + timedelta(days=1), leave.request_date_from - timedelta(days=1)
                if risk.code == '001':
                    is_same_risk = (leave.request_date_from - period['end']).days <= 14
                else:
                    is_same_risk = gap_end < gap_start or not self._has_worked_days(employee, gap_start, gap_end)
                if is_same_risk:
                    period['leaves'] |= leave
                    period['end'] = max(period['end'], leave.request_date_to)
                    continue
            periods.append({'risk': risk, 'leaves': leave, 'start': leave.request_date_from, 'end': leave.request_date_to})
        return periods

    @api.model
    def _has_worked_days(self, employee, date_from, date_to):
        return any(
            work_entry['work_entry_type_id'].l10n_be_drs_nature in WORKED_NATURES and work_entry['work_entry_type_id'].count_as == 'working_time'
            for work_entry in employee.generate_work_entries(date_from, date_to))

    @api.model
    def _is_zima001_needed(self, period):
        """ An incapacity is declared once the guaranteed salary is over, the birth and adoption leaves once the
        health insurance pays them, the other risks as soon as they start """
        natures = set(period['leaves'].work_entry_type_id.mapped('l10n_be_drs_nature'))
        if period['risk'].code == '001':
            return bool(natures - set(GUARANTEED_SALARY_NATURES))
        if period['risk'].code == '006':
            return '6.10' in natures
        if period['risk'].code == '007':
            return '6.11' in natures
        return True

    @api.depends('employee_id', 'risk_id', 'month', 'year')
    def _compute_work_recovery(self):
        for drs in self:
            drs.origin_drs_id = self.browse()
            drs.work_recovery_date = False
            if drs.identification != 'ZIMA006' or not drs.employee_id or not drs.year or not drs.month:
                continue
            date_from, date_to = drs._get_first_last_day_of_month()
            recovery = next((
                (recovery_date, declaration) for recovery_date, declaration in self._get_zima006_recoveries(drs.employee_id)
                if date_from <= recovery_date <= date_to
            ), None)
            if recovery:
                drs.work_recovery_date, drs.origin_drs_id = recovery

    @api.depends('employee_id', 'risk_id', 'month', 'year')
    def _compute_risk_period(self):
        for drs in self:
            drs.leave_ids = self.env['hr.leave']
            drs.risk_start_date = drs.risk_end_date = False
            if drs.identification != 'ZIMA001' or not drs.employee_id or not drs.year or not drs.month:
                continue
            date_from, date_to = drs._get_first_last_day_of_month()
            period = next((
                period for period in self._get_zima001_periods(drs.employee_id)
                if period['risk'] == drs.risk_id and date_from <= period['start'] <= date_to
            ), None)
            if period:
                drs.leave_ids = period['leaves']
                drs.risk_start_date, drs.risk_end_date = period['start'], period['end']

    def _get_zima001_errors(self, version):
        self.ensure_one()
        errors = []
        if self.code in ('002', '003', '004') and self.employee_id.sex != 'female' or self.code == '005' and self.employee_id.sex != 'male':
            errors.append(self.env._("The risk %(risk)s doesn't match the sex of %(employee)s.", risk=self.code, employee=self.employee_id.name))
        if not self.risk_start_date:
            return errors + [self.env._("%(employee)s has no time off of the risk %(risk)s starting during that month.", employee=self.employee_id.name, risk=self.code)]
        if self.code == '004':
            errors.append(self.env._("The partial removal from work must be declared from the portal of the social security."))
        if self.risk_start_date > fields.Date.context_today(self):
            errors.append(self.env._("The risk can only be declared once it started."))
        if not version.contract_date_start or version.contract_date_start > self.risk_start_date:
            errors.append(self.env._("No employment contract was found at the start of the risk."))
        if version.l10n_be_worker_code_id.dmfa_code == '497':
            errors.append(self.env._("The risks of the childminders must be declared from the portal of the social security."))
        if version.l10n_be_worker_status == 'B':
            errors.append(self.env._("The risks of the volunteer firefighters must be declared from the portal of the social security."))
        if version.commission_on_target:
            errors.append(self.env._("The remuneration paid by commission must be declared from the portal of the social security."))
        if version.l10n_be_time_credit:
            errors.append(self.env._("The occupations with time credit must be declared from the portal of the social security."))
        location_unit = self._get_local_unit(version)
        if not location_unit.bce_code:
            errors.append(self.env._("The work address of %(employee)s isn't linked to a location unit with a BCE number.", employee=self.employee_id.name))
        elif int(location_unit.bce_code[8:]) != 97 - int(location_unit.bce_code[:8]) % 97:
            errors.append(self.env._(
                "The BCE number %(code)s of the location unit of %(employee)s has an invalid check digit.",
                code=location_unit.bce_code, employee=self.employee_id.name))
        elif location_unit.date_start and location_unit.date_start > self.risk_start_date or location_unit.date_end and location_unit.date_end < self.risk_start_date:
            errors.append(self.env._("The location unit of %(employee)s isn't valid at the start of the risk.", employee=self.employee_id.name))
        if self._get_remuneration_basis_amount(self._get_zima001_salary_version(version)) <= 0:
            errors.append(self.env._("A positive gross remuneration is required to declare the risk."))
        # No day was worked before a risk starting with the occupation
        if not self._get_zima001_last_working_day() and self.risk_start_date > version._get_occupation_dates()[-1][1]:
            errors.append(self.env._("No working or assimilated day was found before the start of the risk."))
        day_list = self._get_zima001_days()
        if len(day_list) > (20 if self.code == '006' else 182):
            errors.append(self.env._("The reference period contains too many days."))
        allowed_natures = ZIMA001_RISK_NATURES.get(self.code, ZIMA001_INCAPACITY_NATURES - {'1.1', '1.3'})
        if invalid_natures := {day['nature_code'] for day in day_list} - allowed_natures:
            errors.append(self.env._("The natures of day %(natures)s can't be declared for the risk %(risk)s.", natures=', '.join(sorted(invalid_natures)), risk=self.code))
        if len({day['date'] for day in day_list}) < len(day_list):
            errors.append(self.env._("The reference period of the risk can't exceed a year: it must be declared from the portal of the social security."))
        if self.code in ('007', '008') and day_list and day_list[-1]['day'] >= self._get_zima001_reference_end_date():
            errors.append(self.env._("The days paid by the employer must precede the last day of the leave for the risk %(risk)s.", risk=self.code))
        if self.code == '006' and self.risk_end_date > self.risk_start_date + relativedelta(months=4):
            errors.append(self.env._("The birth leave must be taken within 4 months of the birth."))
        return errors

    def _get_local_unit(self, version):
        return self.env['hr.work.location'].search([
            ('address_id', '=', version.address_id.id),
            ('location_type', '=', 'dmfa_unit'),
            ('company_id', 'in', (self.company_id.id, False)),
        ], limit=1)

    def _get_local_unit_code(self, version):
        code = self._get_local_unit(version).bce_code
        return code and format_amount(code, width=10, hundredth=False)

    def _get_zima001_salary_version(self, version):
        """ The remuneration of a stable occupation is the one at the end of the second quarter before the risk """
        reference_date = date_utils.start_of(self.risk_start_date, 'quarter') - relativedelta(months=3, days=1)
        if version._get_occupation_dates()[-1][1] <= reference_date:
            return self.employee_id._get_version(reference_date)
        return version

    def _get_zima001_last_working_day(self):
        self.ensure_one()
        date_to = self.risk_start_date - timedelta(days=1)
        work_entries = self.employee_id.generate_work_entries(max(date_to - relativedelta(months=3), date(1900, 1, 1)), date_to)
        return max((
            work_entry['date'] for work_entry in work_entries
            if work_entry['work_entry_type_id'].l10n_be_drs_nature in WORKED_NATURES
        ), default=False)

    def _get_zima001_reference_end_date(self):
        """ The reference period of a birth leave ends at the latest on the day of the declaration: its following
        days are declared by a modification """
        self.ensure_one()
        if self.code == '006':
            return min(self.risk_end_date, fields.Date.context_today(self))
        return self.risk_end_date

    def _get_zima001_days(self):
        """ Return the nature of the days of the risk paid by the employer, or assimilated. The days paid by the
        health insurance aren't declared, and the first day of work between two incapacities of the same risk is
        coded 1.1. """
        self.ensure_one()
        if not self.risk_start_date or self.code == '004':
            return []
        nature_by_day = {}
        for work_entry in self.employee_id.generate_work_entries(self.risk_start_date, self._get_zima001_reference_end_date()):
            work_entry_type = work_entry['work_entry_type_id']
            nature = work_entry_type.l10n_be_drs_nature
            if not nature or nature in ('6.2', '6.3', '6.4', '6.11') or (nature == '6.10' and self.code != '006'):
                continue
            if nature == '1' and work_entry_type.count_as == 'absence':
                nature = '1.6'  # Absence with salary maintained
            # The nature of the absence prevails over the worked days
            if work_entry['date'] not in nature_by_day or nature_by_day[work_entry['date']] in ('1', '1.6'):
                nature_by_day[work_entry['date']] = nature
        if self.code == '001':
            covered_days = set()
            for leave in self.leave_ids:
                covered_days.update(leave.request_date_from + timedelta(days=offset) for offset in range((leave.request_date_to - leave.request_date_from).days + 1))
            resumption_days = sorted(day for day in nature_by_day if day not in covered_days)
            previous_day = None
            for day in resumption_days:
                del nature_by_day[day]
                # The first day of work of each resumption
                if previous_day is None or any(previous_day < covered_day < day for covered_day in covered_days):
                    nature_by_day[day] = '1.1'
                previous_day = day
        return [{'day': day, 'date': day.strftime('--%m-%d'), 'nature_code': nature} for day, nature in sorted(nature_by_day.items())]

    def _get_zima001_declaration_data(self, version):
        self.ensure_one()
        quarter_start, quarter_end = date_utils.get_quarter(self.risk_start_date)
        __, occupation_start, occupation_end = version._get_occupation_dates()[-1]
        occupation = self._get_wech001_occupation_values(
            version, occupation_start, occupation_end if occupation_end and occupation_end <= quarter_end else False,
            quarter_start, quarter_end, 1)
        salary_version = self._get_zima001_salary_version(version)
        remuneration_time_unit = '1' if salary_version.wage_type == 'hourly' else '4'
        day_list = self._get_zima001_days()
        if self.code in ('006', '007', '008'):
            reference_period = (self.risk_start_date, self._get_zima001_reference_end_date())
        else:
            reference_period = day_list and (day_list[0]['day'], day_list[-1]['day'])
        car_atn = version.car_atn if version.transport_mode_car else 0
        return {
            'quarter': f'{quarter_start.year}{date_utils.get_quarter_number(quarter_start)}',
            'quarter_start': quarter_start.strftime('%Y-%m-%d'),
            'quarter_end': quarter_end.strftime('%Y-%m-%d'),
            'risk_start_date': self.risk_start_date.strftime('%Y-%m-%d'),
            'occupation': occupation,
            'local_unit_code': self._get_local_unit_code(version),
            'last_working_day': (last_working_day := self._get_zima001_last_working_day()) and last_working_day.strftime('%Y-%m-%d'),
            'remuneration_time_unit': remuneration_time_unit,
            'remuneration_basis_amount': round(self._get_remuneration_basis_amount(salary_version) * (10000 if remuneration_time_unit == '1' else 100)),
            'stable_occupation': 1 if salary_version != version or version._get_occupation_dates()[-1][1] <= quarter_start - relativedelta(months=3, days=1) else 0,
            # The benefits in kind kept during the risk, by working day (6 days a week)
            'nature_advantages': [{
                'amount': round(car_atn * 12 / 312 * 100),
                'start': self.risk_start_date.strftime('%Y-%m-%d'),
            }] if car_atn and self.code != '004' else [],
            'reference_period': reference_period and tuple(day.strftime('%Y-%m-%d') for day in reference_period),
            'nature_of_day_list': day_list,
            'service_ending_date': version.contract_date_end.strftime('%Y-%m-%d')
                if self.code in ('001', '003', '007', '008') and version.contract_date_end and version.contract_date_end >= self.risk_start_date else False,
        }

    # =======================================
    # ZIMA003
    # =======================================

    def _get_zima003_pauses(self, version):
        """ Return the breastfeeding pauses of half an hour of the month, and the date of the last one """
        self.ensure_one()
        date_from, date_to = self._get_zima002_period(version)
        pause_dates = [
            (work_entry['date'], work_entry['duration']) for work_entry in self.employee_id.generate_work_entries(date_from, date_to)
            if self.risk_id in work_entry['work_entry_type_id'].l10n_be_drs_risk_ids
        ]
        return round(sum(duration for __, duration in pause_dates) * 2), max((day for day, __ in pause_dates), default=False)

    def _get_zima003_hourly_wage(self, version):
        """ Average gross hourly salary """
        self.ensure_one()
        if version.wage_type == 'hourly':
            return version.hourly_wage
        # The contractual hours include the breastfeeding pauses planned in the working schedule
        calendar = version.resource_calendar_id
        pause_hours = sum(calendar.attendance_ids.filtered(
            lambda attendance: not attendance.date and self.risk_id in attendance.work_entry_type_id.l10n_be_drs_risk_ids
        ).mapped('duration_hours')) if calendar.calendar_type == 'fixed' else 0
        hours_per_week = calendar.hours_per_week + pause_hours
        return version.wage * 12 / (52 * hours_per_week) if hours_per_week else 0

    def _get_zima003_errors(self, version):
        self.ensure_one()
        errors = []
        if self.employee_id.sex != 'female':
            errors.append(self.env._("The breastfeeding pauses are reserved to women."))
        if version.l10n_be_worker_status == 'B':
            errors.append(self.env._("The breastfeeding pauses of the volunteer firefighters can't be declared."))
        pause_count = self._get_zima003_pauses(version)[0]
        date_to = self._get_first_last_day_of_month()[1]
        if not pause_count:
            errors.append(self.env._("%(employee)s has no breastfeeding pause to declare during that month.", employee=self.employee_id.name))
        elif pause_count > min(62, 2 * date_to.day):
            errors.append(self.env._("At most 2 breastfeeding pauses of half an hour can be declared by day."))
        if date_to >= fields.Date.context_today(self):
            errors.append(self.env._("The breastfeeding pauses can only be declared once the month is over."))
        if self._get_zima003_hourly_wage(version) <= 0:
            errors.append(self.env._("A positive gross remuneration is required to declare the breastfeeding pauses."))
        return errors

    def _get_zima003_declaration_data(self, version):
        self.ensure_one()
        date_from, date_to = self._get_zima002_period(version)
        pause_count, last_pause = self._get_zima003_pauses(version)
        return {
            'date_from': date_from.strftime('%Y-%m-%d'),
            # The period ends with the last pause
            'date_to': min(date_to, last_pause).strftime('%Y-%m-%d'),
            'breastfeeding_pause_count': pause_count,
            'breastfeeding_hourly_wage': round(self._get_zima003_hourly_wage(version) * 10000),
        }

    # =======================================
    # ZIMA006
    # =======================================

    @api.model
    def _get_zima006_recoveries(self, employee):
        """ Return the days the employee resumes the work after the risks declared to the health insurance (except
        the birth leave), with the declaration of the risk """
        declarations = self.search([
            ('employee_id', '=', employee.id),
            ('risk_id.identification', '=', 'ZIMA001'),
            ('risk_id.code', '!=', '006'),
        ])
        recoveries = []
        for period in self._get_zima001_periods(employee):
            declaration = declarations.filtered(lambda drs: drs.risk_id == period['risk'] and drs.risk_start_date == period['start'])[:1]
            if not declaration:
                continue
            # The first day of work after the risk
            work_entries = employee.generate_work_entries(period['end'] + timedelta(days=1), period['end'] + relativedelta(months=1))
            recovery_date = min((
                work_entry['date'] for work_entry in work_entries
                if work_entry['work_entry_type_id'].count_as == 'working_time' and work_entry['date'] > period['end']
            ), default=False)
            if recovery_date:
                recoveries.append((recovery_date, declaration))
        return recoveries

    def _get_zima006_errors(self, version):
        self.ensure_one()
        if not self.work_recovery_date:
            return [self.env._("%(employee)s doesn't resume the work after a declared risk during that month.", employee=self.employee_id.name)]
        errors = []
        if self.work_recovery_date > fields.Date.context_today(self):
            errors.append(self.env._("The return to work can only be declared once the work resumed."))
        origin = self.origin_drs_id
        if origin and not origin._get_ticket_number():
            errors.append(self.env._(
                "The declaration of the risk ended by the return to work of %(employee)s must be accepted by the social security first.",
                employee=self.employee_id.name))
        if origin.risk_end_date and self.work_recovery_date <= origin.risk_end_date:
            errors.append(self.env._("The return to work must be after the end of the risk (%(date)s).", date=format_date(self.env, origin.risk_end_date)))
        return errors

    def _get_zima006_declaration_data(self, version):
        self.ensure_one()
        return {
            'work_recovery_date': self.work_recovery_date.strftime('%Y-%m-%d'),
        }
