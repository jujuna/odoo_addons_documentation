# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import math

from collections import defaultdict
from datetime import date
from functools import reduce
from itertools import zip_longest

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, Command, fields, models, modules, _
from odoo.fields import Domain
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL, float_round, config, convert_file, format_amount
from odoo.tools.float_utils import float_compare
from odoo.tools.misc import format_date
from odoo.tools.safe_eval import safe_eval, datetime as safe_eval_datetime, dateutil as safe_eval_dateutil

_logger = logging.getLogger(__name__)


class DefaultDictPayroll(defaultdict):
    def get(self, key, default=None):
        if key not in self and default is not None:
            self[key] = default
        return self[key]


class HrPayslip(models.Model):
    _name = 'hr.payslip'
    _description = 'Pay Slip'
    _explanation = "Represents an employee's payslip for a specific period. It calculates the final net salary using salary rules, inputs, and worked days based on the employee's contract."
    _inherit = ['mail.thread.main.attachment', 'mail.activity.mixin']
    _order = 'date_to desc'

    struct_id = fields.Many2one(
        'hr.payroll.structure', string='Pay Structure', precompute=True,
        compute='_compute_struct_id', store=True, index=True, readonly=False, tracking=True,
        help='Defines the rules that have to be applied to this payslip, according '
             'to the contract chosen. If the contract is empty, this field isn\'t '
             'mandatory anymore and all the valid rules of the structures '
             'of the employee\'s contracts will be applied.',
        domain="[('country_id', 'in', [country_id, False])]")
    structure_code = fields.Char(related="struct_id.code")
    struct_type_id = fields.Many2one('hr.payroll.structure.type', related='struct_id.type_id')
    wage_type = fields.Selection(related='version_id.wage_type')
    wage = fields.Monetary(related='version_id.wage')
    hourly_wage = fields.Float(related='version_id.hourly_wage')
    schedule_pay = fields.Selection(related='version_id.schedule_pay', store=True, index=True)
    name = fields.Char(string='Payslip Name', compute='_compute_name', store=False, recursive=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, index=True,
        domain="['|', ('company_id', '=', False), ('company_id', 'child_of', company_id), '|', ('active', '=', True), ('active', '=', False)]")
    image_128 = fields.Image(related='employee_id.image_128')
    image_1920 = fields.Image(related='employee_id.image_1920')
    avatar_128 = fields.Image(related='employee_id.avatar_128')
    avatar_1920 = fields.Image(related='employee_id.avatar_1920')
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', readonly=True, store=True)
    job_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_id', readonly=True, store=True)
    date_from = fields.Date(
        string='From', readonly=False, required=True, tracking=True,
        default=lambda self: date.today().replace(day=1),
        help='For accurate monthly salary calculation, please select the full calendar '
        'month period (e.g., 01/06/2024 - 30/06/2024), regardless of the employee\'s '
        'joining date. The system will automatically pro-rate based on the joining date.')
    date_to = fields.Date(
        string='To', readonly=False, required=True, tracking=True,
        compute="_compute_date_to", store=True, precompute=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('paid', 'Paid'),
        ('cancel', 'Canceled')],
        string='State', index=True, readonly=True, copy=False,
        default='draft', tracking=True,
        help="""* When the payslip is created the status is \'Draft\'
                \n* If the payslip is confirmed then status is set to \'Done\'.
                \n* When the user cancels a payslip, the status is \'Canceled\'.""")
    state_display = fields.Selection([
            ('01_error', 'Blocked'),
            ('02_warning', 'Warning'),
            ('03_draft', 'Draft'),
            ('04_validated', 'Done'),
            ('05_paid', 'Paid'),
            ('06_cancel', 'Canceled'),
        ],
        string='Status',
        compute='_compute_state_display',
        store=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        'hr.payslip.line', 'slip_id', string='Payslip Lines',
        compute='_compute_line_ids', store=True, readonly=False, copy=True)
    company_id = fields.Many2one(
        'res.company', string='Company', copy=False, required=True,
        compute='_compute_company_id', store=True, index=True, readonly=True,
        default=lambda self: self.env.company)
    payroll_config_id = fields.Many2one(
        'payroll.config.settings',
        string='payroll config',
        tracking=True,
        compute='_compute_payroll_config_id',
        store=True,
        readonly=False,
        index=True,
        domain="""[
            ('date_start', '<=', date_end),
            '|', ('date_end', '=', False), ('date_end', '>=', date_from)
        ]""",
    )
    country_id = fields.Many2one(
        'res.country', string='Country',
        related='company_id.country_id', readonly=True, search='_search_country_id'
    )
    country_code = fields.Char(related='country_id.code', depends=['country_id'], readonly=True)
    worked_days_line_ids = fields.One2many(
        'hr.payslip.worked_days', 'payslip_id', string='Payslip Worked Days', copy=True,
        compute='_compute_worked_days_line_ids', store=True, readonly=False)
    input_line_ids = fields.One2many(
        'hr.payslip.input', 'payslip_id', string='Payslip Inputs', copy=True,
        compute='_compute_input_line_ids', store=True,
        readonly=False)
    paid = fields.Boolean(
        string='Made Payment Order? ', copy=False)
    done_date = fields.Datetime(string="payslip confirmation Date")
    paid_date = fields.Date(string="Payment Date")
    title = fields.Char(string='Title')
    note = fields.Html(string='Note')
    allowed_version_ids = fields.Many2many('hr.version', string='Allowed Versions', compute='_compute_allowed_version_ids')
    version_id = fields.Many2one(
        'hr.version',
        string='Contract',
        precompute=True,
        tracking=True,
        compute='_compute_version_id',
        store=True,
        readonly=False,
        index=True,
        domain="[('id', 'in', allowed_version_ids)]"
    )
    employee_version_ids_count = fields.Integer(compute='_compute_employee_version_ids_count')
    credit_note = fields.Boolean(
        string='Credit Note',
        help="Indicates this payslip has a refund of another")
    payslip_run_id = fields.Many2one(
        'hr.payslip.run', string='Pay Run',
        copy=False, ondelete='cascade', tracking=True, index='btree_not_null',
        domain="[('company_id', '=', company_id)]")
    sum_worked_days = fields.Float(string='Worked Days', compute='_compute_worked_days_hours', store=True, help='Total days of attendance and time off (paid or not)')
    sum_worked_hours = fields.Float(string='Worked Hours', compute='_compute_worked_days_hours', store=True, help='Total hours of attendance and time off (paid or not)')
    sum_worked_paid_days = fields.Float(string='Worked Paid Days', compute='_compute_worked_paid_days_hours', help='Total days of attendance and time off (paid only)')
    sum_worked_paid_hours = fields.Float(string='Worked Paid Hours', compute='_compute_worked_paid_days_hours', help='Total days of attendance and time off (paid only)')
    compute_date = fields.Date('Computed On')
    basic_wage = fields.Monetary(compute='_compute_basic_net', store=True)
    gross_wage = fields.Monetary(compute='_compute_basic_net', store=True)
    net_wage = fields.Monetary(compute='_compute_basic_net', store=True)
    currency_id = fields.Many2one(related='version_id.currency_id')
    employee_type_id = fields.Many2one(related='version_id.employee_type_id', store=True)
    is_regular = fields.Boolean(compute='_compute_is_regular')
    is_wrong_version = fields.Boolean(compute='_compute_is_wrong_version')
    has_wrong_data = fields.Boolean(compute='_compute_has_wrong_data')
    has_wrong_leaves = fields.Boolean(compute='_compute_has_wrong_leaves')
    keep_wrong_version = fields.Boolean(compute='_compute_keep_wrong_version', store=True, default=False)
    is_wrong_company_version = fields.Boolean(compute='_compute_is_wrong_company_version')
    has_wrong_company_data = fields.Boolean(compute='_compute_has_wrong_company_data')
    has_negative_net_to_report = fields.Boolean()
    negative_net_to_report = fields.Monetary()
    is_superuser = fields.Boolean(compute="_compute_is_superuser")
    edited = fields.Boolean()
    queued_for_pdf = fields.Boolean(default=False)

    issues = fields.Json(compute='_compute_issues', store=True, readonly=True)
    warning_count = fields.Integer(compute='_compute_issues', store=True, readonly=True)
    error_count = fields.Integer(compute='_compute_issues', store=True, readonly=True)
    is_wrong_duration = fields.Boolean(compute='_compute_is_wrong_duration', compute_sudo=True)

    salary_attachment_ids = fields.Many2many(
        'hr.salary.attachment',
        relation='hr_payslip_hr_salary_attachment_rel',
        string='Payslip Adjustments',
        compute='_compute_salary_attachment_ids',
        store=True,
        readonly=False,
    )
    salary_attachment_count = fields.Integer('Payslip Adjustment count', compute='_compute_salary_attachment_count')
    ignore_worked_day_lines = fields.Boolean(string="No Worked Days", help="Remove worked days and their corresponding remuneration from the payslips computation")
    struct_use_worked_day_lines = fields.Boolean(related='struct_id.use_worked_day_lines')
    payment_report = fields.Binary(
        string='Payment Report',
        help="Export .csv file related to this payslip",
        readonly=True)
    payment_report_filename = fields.Char(readonly=True)
    payment_report_date = fields.Date(readonly=True)
    ytd_computation = fields.Boolean(related='struct_id.ytd_computation')
    employer_cost = fields.Monetary(compute='_compute_basic_net', store=True, string='Employer Cost')
    is_refund_payslip = fields.Boolean(string="Is Refund payslip", default=False)
    is_refunded = fields.Boolean(string="Is Refunded", default=False)
    is_corrected = fields.Boolean(string="Is Corrected", default=False)
    is_correction_payslip = fields.Boolean(string="Is Correction Payslip", compute='_compute_is_correction_payslip')
    correction_net_delta = fields.Monetary(string="Correction Net Delta", compute='_compute_correction_net_delta')
    origin_payslip_id = fields.Many2one('hr.payslip', string='Origin Payslip', index='btree_not_null')
    related_payslip_ids = fields.One2many('hr.payslip', 'origin_payslip_id', string="Related Payslips")
    related_payslip_count = fields.Integer("Related payslip count", compute="_compute_related_payslip_count_count")
    is_company_executive = fields.Boolean(compute='_compute_is_company_executive')

    def _get_salary_advance_balances(self):
        """Return the salary advance balances of the employees of ``self``.

        Hook for the localizations handling salary advances (``l10n_be_hr_payroll``,
        ``l10n_sa_hr_payroll``, ``l10n_tr_hr_payroll``). The base implementation returns an empty
        ``defaultdict(lambda: defaultdict(float))``, i.e. ``{employee: {balance_key: amount}}``.
        """
        return defaultdict(lambda: defaultdict(float))

    def _show_notification(self, message, notification_type):
        """Return a client action displaying a notification.

        :param str message: title of the notification.
        :param str notification_type: ``'success'``, ``'warning'``, ``'danger'`` or ``'info'``.
        :rtype: dict
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': message,
                'type': notification_type,
            }
        }

    @api.model
    def _schedule_period_start(self, schedule, today, country_code=False):
        """Return the first day of the pay period of the given schedule that contains ``today``.

        Used to default the start date of payslips and pay runs. Unknown schedules fall back on the
        monthly behaviour. The ``bi-weekly`` periods depend on the week start of the user language.

        :param str schedule: a ``schedule_pay`` value (``'monthly'``, ``'weekly'``, ``'bi-weekly'``,
            ``'semi-monthly'``, ``'bi-monthly'``, ``'quarterly'``, ``'semi-annually'``,
            ``'annually'``, ``'daily'``).
        :param date today: reference date.
        :param str country_code: unused in the base implementation, available for overrides.
        :rtype: date
        """
        week_start = self.env["res.lang"]._get_data(code=self.env.user.lang).week_start
        if schedule == 'quarterly':
            current_year_quarter = math.ceil(today.month / 3)
            date_from = today.replace(day=1, month=(current_year_quarter - 1) * 3 + 1)
        elif schedule == 'semi-annually':
            is_second_half = math.floor((today.month - 1) / 6)
            date_from = today.replace(day=1, month=7) if is_second_half else today.replace(day=1, month=1)
        elif schedule == 'annually':
            date_from = today.replace(day=1, month=1)
        elif schedule == 'weekly':
            week_day = today.weekday()
            date_from = today + relativedelta(days=-week_day)
        elif schedule == 'bi-weekly':
            week = int(today.strftime("%U") if week_start == '7' else today.strftime("%W"))
            week_day = today.weekday()
            is_second_week = week % 2 == 0
            date_from = today + relativedelta(days=-week_day - 7 * int(is_second_week))
        elif schedule == 'semi-monthly':
            date_from = today.replace(day=1 if today.day < 16 else 16)
        elif schedule == 'bi-monthly':
            current_year_slice = math.ceil(today.month / 2)
            date_from = today.replace(day=1, month=(current_year_slice - 1) * 2 + 1)
        elif schedule == 'daily':
            date_from = today
        else:  # if not handled, put the monthly behaviour
            date_from = today.replace(day=1)
        return date_from

    @api.model_create_multi
    def create(self, vals_list):
        structures = self.env['hr.payroll.structure'].browse([vals['struct_id'] for vals in vals_list if vals.get('struct_id')])
        use_wdl_by_structure = {e['id']: e['use_worked_day_lines'] for e in structures.read(['use_worked_day_lines'])}
        for vals in vals_list:
            if struct_id := vals.get('struct_id'):
                vals['ignore_worked_day_lines'] = not use_wdl_by_structure[struct_id]
        return super().create(vals_list)

    def _creation_message(self):
        """Return the chatter message logged at creation, mentioning the pay run if any."""
        # A payslip is most often created by a pay run rather than by hand.
        # The creation log names the run and the user so the reader knows where the payslip came from.
        self.ensure_one()
        if self.payslip_run_id:
            return self.env._(
                "Payslip created from the pay run %(payrun)s by %(user)s",
                payrun=self.payslip_run_id.name,
                user=self.create_uid.name,
            )
        return self.env._("Payslip created by %(user)s", user=self.create_uid.name)

    @api.depends('employee_id.version_ids.contract_date_start', 'employee_id.version_ids.contract_date_end', 'date_from', 'date_to')
    def _compute_employee_version_ids_count(self):
        for payslip in self:
            if not payslip.date_from or not payslip.date_to:
                payslip.employee_version_ids_count = 0
                continue
            overlapping_contract_dates = set()
            overlapping_versions = payslip.employee_id._get_versions_with_contract_overlap_with_period(payslip.date_from, payslip.date_to)
            if overlapping_versions:
                overlapping_contract_dates.update(overlapping_versions.mapped(lambda v: v._get_version_lookup_key()))
            payslip.employee_version_ids_count = len(overlapping_contract_dates)

    @api.depends('error_count', 'warning_count', 'state')
    def _compute_state_display(self):
        state_mapping = {
            'draft': '03_draft',
            'validated': '04_validated',
            'paid': '05_paid',
            'cancel': '06_cancel',
        }
        for payslip in self:
            if payslip.error_count:
                payslip.state_display = '01_error'
            elif payslip.warning_count and payslip.state == 'draft':
                payslip.state_display = '02_warning'
            else:
                payslip.state_display = state_mapping[payslip.state]

    @api.model
    def _schedule_timedelta(self, schedule, date_from, country_code=False):
        """Return the ``relativedelta`` to add to the period start to get the period end (inclusive).

        ``date_to = date_from + _schedule_timedelta(...)``. For instance ``months=1, days=-1`` for a
        monthly schedule. Overridden by ``l10n_mx_hr_payroll`` for its own periods.

        :param str schedule: a ``schedule_pay`` value, see :meth:`_schedule_period_start`.
        :param date date_from: start of the period (only used by ``semi-monthly``).
        :param str country_code: unused in the base implementation, available for overrides.
        :rtype: dateutil.relativedelta.relativedelta
        """
        if schedule == 'quarterly':
            timedelta = relativedelta(months=3, days=-1)
        elif schedule == 'semi-annually':
            timedelta = relativedelta(months=6, days=-1)
        elif schedule == 'annually':
            timedelta = relativedelta(years=1, days=-1)
        elif schedule == 'weekly':
            timedelta = relativedelta(days=6)
        elif schedule == 'bi-weekly':
            timedelta = relativedelta(days=13)
        elif schedule == 'semi-monthly':
            timedelta = relativedelta(day=15 if date_from.day < 16 else 31)
        elif schedule == 'bi-monthly':
            timedelta = relativedelta(months=2, days=-1)
        elif schedule == 'daily':
            timedelta = relativedelta(days=0)
        else:  # if not handled, put the monthly behaviour
            timedelta = relativedelta(months=1, days=-1)
        return timedelta

    def _get_schedule_timedelta(self):
        """Return the period ``relativedelta`` of this payslip, see :meth:`_schedule_timedelta`.

        The schedule is the version ``schedule_pay``, or the default schedule of its structure type.
        """
        self.ensure_one()
        schedule = self.version_id.schedule_pay or self.version_id.structure_type_id.default_schedule_pay
        return self._schedule_timedelta(schedule, self.date_from, self.country_code)

    @api.depends('date_from', 'version_id', 'struct_id')
    def _compute_date_to(self):
        for payslip in self:
            if self.env.context.get('default_date_to'):
                payslip.date_to = self.env.context.get('default_date_to')
            else:
                payslip.date_to = payslip.date_from and payslip.date_from + payslip._get_schedule_timedelta()

    @api.depends('employee_id', 'version_id', 'struct_id', 'date_from', 'date_to',
                 'version_id.payroll_properties', 'employee_id.salary_attachment_ids')
    def _compute_input_line_ids(self):
        """Synchronize the input lines from the salary attachments and the version properties.

        Only draft and validated payslips with a structure are processed:

        * input lines whose rule is linked to one of the employee's salary attachments are
          rebuilt from the attachments that are open during the period (one line per attachment,
          named after its payslip description, amount ``_get_active_amount()``, negated on
          credit notes);
        * rules of the structure reading a property input (``condition_select`` or
          ``amount_select`` equal to ``'property_input'``, ``input_usage_employee`` or
          ``input_selected_by_default``) get a line seeded from ``version.payroll_properties``
          (only if the version structure is the payslip structure) or from the rule default value.
          Codes that already have a line are never touched, so manual edits are kept.

        Overridden by many localizations to inject their own input lines.
        """
        property_rules_by_struct = {}
        for struct in self.struct_id:
            property_rules_by_struct[struct.id] = [
                (rule, rule._get_property_default_value())
                for rule in struct.rule_ids.filtered(
                    lambda r: r.condition_select == 'property_input'
                    or r.amount_select == 'property_input'
                    or r.input_usage_employee
                    or r.input_selected_by_default
                )
            ]

        for slip in self:
            if not slip.struct_id or slip.state not in ('draft', 'validated'):
                continue
            # Input lines backed by one of the employee's salary attachments are fully
            # managed from the attachments: they are rebuilt on every pass (dropping the
            # ones whose attachment is gone), while manually entered input lines on other
            # rules are left untouched.
            attach_rules_by_code = {
                r.code: r for r in slip.struct_id.rule_ids.filtered('input_usage_payslip')
            }
            attachment_codes = {
                code
                for code in slip.employee_id.salary_attachment_ids.salary_rule_id.mapped('code')
                if code in attach_rules_by_code
            }
            lines_to_remove = slip.input_line_ids.filtered(
                lambda x: x.code in attachment_codes
            )
            input_line_vals = [Command.unlink(line.id) for line in lines_to_remove]

            if slip.employee_id and slip.employee_id.salary_attachment_ids and slip.date_to:
                valid_attachments = slip.employee_id.salary_attachment_ids.filtered(
                    lambda a: a.state == '1_open'
                        and a.date_start <= slip.date_to
                        and (not a.date_estimated_end or a.date_estimated_end >= slip.date_from)
                        and (not a.date_end or a.date_end >= slip.date_from)
                        and a.salary_rule_id.code in attach_rules_by_code
                )
                for attachment in valid_attachments:
                    rule = attach_rules_by_code[attachment.salary_rule_id.code]
                    input_line_vals.append(Command.create({
                        'name': attachment.description,
                        'amount': attachment._get_active_amount() * (-1 if slip.credit_note else 1),
                        'salary_rule_id': rule.id,
                    }))

            # Property-input rules and employee-editable rules are injected as input
            # lines from the version's property value. Rules flagged "Selected by
            # Default" are seeded with their default value even without a version
            # property.
            version_props = dict(slip.version_id.payroll_properties or {})
            version_matches_struct = slip.version_id.structure_id == slip.struct_id
            # Seed only codes without an existing line: recomputes must not
            # duplicate previously seeded lines nor override manual edits, and
            # attachment-managed codes are fully owned by the block above.
            existing_codes = set((slip.input_line_ids - lines_to_remove).mapped('code'))
            for rule, default_value in property_rules_by_struct.get(slip.struct_id.id, ()):
                if rule.code in existing_codes or rule.code in attachment_codes:
                    continue
                raw_value = default_value if rule.input_selected_by_default else 0.0
                if version_matches_struct and rule.code in version_props:
                    raw_value = version_props[rule.code]
                try:
                    amount = float(raw_value or 0.0)
                except (TypeError, ValueError):
                    amount = 0.0
                if not amount and not rule.input_selected_by_default:
                    # Selected-by-default rules always get their line, even at 0.
                    continue
                input_line_vals.append(Command.create({
                    'name': rule.input_name,
                    'amount': amount,
                    'salary_rule_id': rule.id,
                }))

            if input_line_vals:
                slip.update({'input_line_ids': input_line_vals})

    @api.depends('input_line_ids.salary_rule_id', 'input_line_ids')
    def _compute_salary_attachment_ids(self):
        for slip in self:
            if not slip.input_line_ids and not slip.salary_attachment_ids:
                continue
            attachments = self.env['hr.salary.attachment']
            if slip.employee_id and slip.input_line_ids and slip.date_to:
                deduction_rule_codes = slip.input_line_ids.salary_rule_id.filtered("input_usage_payslip").mapped('code')
                attachments = slip.employee_id.salary_attachment_ids.filtered(
                    lambda a: (
                        a.state == '1_open'
                        and a.salary_rule_id.code in deduction_rule_codes
                        and a.date_start <= slip.date_to
                    )
                )
            slip.salary_attachment_ids = attachments

    @api.depends('employee_id', 'date_from', 'date_to', 'employee_id.version_ids')
    def _compute_allowed_version_ids(self):
        valid_payslips = self.filtered(lambda p: p.date_from and p.date_to and p.employee_id)
        # Search on stored fields only, searching on date_start/date_end is costly
        all_candidate_versions = self.env['hr.version'].search([
            ('active', '=', True),
            ('employee_id', 'in', valid_payslips.employee_id.ids),
            ('date_version', '<=', max(valid_payslips.mapped('date_to'))),
        ]).sorted('date_start') if valid_payslips else self.env['hr.version']
        versions_by_employee = defaultdict(lambda: self.env['hr.version'])
        for version in all_candidate_versions:
            versions_by_employee[version.employee_id.id] |= version

        for payslip in self:
            if not payslip.date_from or not payslip.date_to or not payslip.employee_id:
                payslip.allowed_version_ids = False
                continue

            versions_seen = defaultdict(lambda: self.env['hr.version'])
            valid_versions = self.env['hr.version']

            for version in versions_by_employee[payslip.employee_id.id]:
                if version.date_start > payslip.date_to or (version.date_end and version.date_end < payslip.date_from):
                    continue
                key = version._get_version_lookup_key()
                if not versions_seen[key]:
                    valid_versions |= version
                versions_seen[key] |= version
            payslip.allowed_version_ids = valid_versions

    @api.depends('salary_attachment_ids')
    def _compute_salary_attachment_count(self):
        for slip in self:
            slip.salary_attachment_count = len(slip.salary_attachment_ids)

    def _get_payslip_family(self):
        """Return the payslips related to this one through ``origin_payslip_id``, excluding itself.

        For an original payslip: its refunds and corrections. For a refund or a correction: the
        origin and all its other related payslips.

        :rtype: hr.payslip
        """
        self.ensure_one()
        if (origin := self.origin_payslip_id):
            return (origin | origin.related_payslip_ids | self.related_payslip_ids) - self
        else:
            return self.related_payslip_ids

    @api.depends('related_payslip_ids', 'origin_payslip_id', 'origin_payslip_id.related_payslip_ids')
    def _compute_related_payslip_count_count(self):
        for slip in self:
            slip.related_payslip_count = len(slip._get_payslip_family())

    @api.depends('origin_payslip_id', 'is_refund_payslip')
    def _compute_is_correction_payslip(self):
        for slip in self:
            slip.is_correction_payslip = bool(slip.origin_payslip_id and not slip.is_refund_payslip)

    @api.depends('net_wage', 'origin_payslip_id.net_wage', 'is_correction_payslip')
    def _compute_correction_net_delta(self):
        for slip in self:
            if slip.is_correction_payslip:
                slip.correction_net_delta = slip.net_wage - slip.origin_payslip_id.net_wage
            else:
                slip.correction_net_delta = 0.0

    def _get_negative_net_rule(self):
        """Return the salary rule with code ``DEDUCTION`` of the payslip structure, if any.

        It is the rule used to carry over a negative net to the next payslip. Overridden by
        ``l10n_be_hr_payroll``.

        :rtype: hr.salary.rule
        """
        self.ensure_one()
        return self.env['hr.salary.rule'].search([
            ('code', '=', 'DEDUCTION'),
            ('struct_ids', 'in', [self.struct_id.id]),
        ], limit=1)

    def _set_input_value(self, code, value):
        """Set the input value of the rule ``code`` of the payslip structure.

        Creates or updates the matching input line; a falsy value deletes it (0 means absent).
        The input line takes precedence over the version property value. Does nothing if the
        structure has no rule with this code. The lines are updated with ``update()``, so on a
        saved payslip ``write`` recomputes the lines of computed drafts.

        :param str code: salary rule code.
        :param value: new amount (anything convertible to ``float``, invalid values count as 0).
        """
        self._set_input_values({code: value})

    def _set_input_values(self, values):
        """Batch version of :meth:`_set_input_value`.

        :param dict values: ``{rule_code: value}``.
        """
        self.ensure_one()
        commands = []
        for code, value in values.items():
            rule = self.struct_id.rule_ids.filtered(lambda r: r.code == code)[:1]
            if not rule:
                continue
            line = self.input_line_ids.filtered(lambda l: l.salary_rule_id == rule)[:1]
            try:
                amount = float(value or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            if not amount:
                if line:
                    commands.append(Command.delete(line.id))
            elif line:
                line.amount = amount
            else:
                commands.append(Command.create({'name': rule.input_name, 'salary_rule_id': rule.id, 'amount': amount}))
        if commands:
            self.update({'input_line_ids': commands})

    def _compute_is_regular(self):
        for payslip in self:
            payslip.is_regular = payslip.struct_id.type_id.default_struct_id == payslip.struct_id

    @api.depends('employee_id.current_version_id', 'date_from')
    def _compute_is_wrong_version(self):
        """Flag validated/paid payslips whose version is not (anymore) the expected one for the period.

        The expected version is the one of the same contract overlapping the period, or the version
        valid at ``date_from``. Used by the payroll warnings proposing a correction.
        """
        non_validated = self.filtered(lambda slip: slip.state not in ("validated", "paid"))
        non_validated.is_wrong_version = False
        for payslip in (self - non_validated):
            # Several contracts can overlap the period, compare with the version of the payslip contract
            versions = payslip.employee_id._get_versions_with_contract_overlap_with_period(payslip.date_from, payslip.date_to)
            expected_version = versions.filtered(lambda v: v.contract_date_start == payslip.version_id.contract_date_start)[:1] \
                or payslip.employee_id._get_version(date=payslip.date_from)
            payslip.is_wrong_version = payslip.employee_id and payslip.version_id \
                                        and payslip.version_id != expected_version

    @api.depends('has_wrong_data', 'is_wrong_version')
    def _compute_keep_wrong_version(self):
        non_validated = self.filtered(lambda slip: slip.state not in ("validated", "paid"))
        for payslip in (self - non_validated):
            payslip.keep_wrong_version = False if payslip.has_wrong_data or payslip.is_wrong_version else payslip.keep_wrong_version

    @api.depends('company_id.current_payroll_config_id', 'date_from')
    def _compute_is_wrong_company_version(self):
        non_validated = self.filtered(lambda slip: slip.state not in ("validated", "paid"))
        non_validated.is_wrong_company_version = False
        for payslip in (self - non_validated):
            payslip.is_wrong_company_version = payslip.company_id and payslip.payroll_config_id \
                                        and payslip.payroll_config_id != payslip.company_id._get_payroll_config(date=payslip.date_from)

    @api.depends('version_id.last_modified_date', 'done_date')
    def _compute_has_wrong_data(self):
        non_validated = self.filtered(lambda slip: slip.state not in ("validated", "paid"))
        non_validated.has_wrong_data = False
        for payslip in (self - non_validated):
            payslip.has_wrong_data = bool(payslip.done_date) and payslip.version_id.last_modified_date > payslip.done_date

    @api.depends('payroll_config_id.write_date', 'done_date')
    def _compute_has_wrong_company_data(self):
        non_validated = self.filtered(lambda slip: slip.state not in ("validated", "paid"))
        non_validated.has_wrong_company_data = False
        for payslip in (self - non_validated):
            payslip.has_wrong_company_data = bool(payslip.payroll_config_id.write_date) and bool(payslip.done_date) and payslip.payroll_config_id.write_date > payslip.done_date

    @api.depends('employee_id.leave_ids', 'date_from', 'date_to', 'done_date')
    def _compute_has_wrong_leaves(self):
        non_validated = self.filtered(lambda slip: slip.state not in ("validated", "paid"))
        non_validated.has_wrong_leaves = False
        for payslip in (self - non_validated):
            overlapping_leaves = payslip.employee_id.leave_ids.filtered(
                lambda leave: leave.date_from.date() <= payslip.date_to
                and leave.date_to.date() >= payslip.date_from
                and leave.write_date > payslip.done_date
            )
            payslip.has_wrong_leaves = bool(overlapping_leaves)

    def _is_invalid(self):
        """Return a message if the payslip is not a legal document yet (not validated nor paid).

        Used by the reports to display a watermark. Overridden by ``l10n_be_hr_payroll`` and
        ``l10n_mx_hr_payroll_account``.

        :return: the message, or ``False`` if the payslip is valid.
        """
        self.ensure_one()
        if self.state not in ['validated', 'paid']:
            return _("This payslip is not validated. This is not a legal document.")
        return False

    @api.depends(lambda self: self._get_recomputing_fields())
    def _compute_line_ids(self):
        """Recompute the lines of computed draft payslips when one of :meth:`_get_recomputing_fields` changes.

        Opt-in only: nothing happens unless the context key ``payslip_no_recompute`` is truthy
        (despite its name). The normal way to compute the lines is :meth:`compute_sheet`.
        """
        if not self.env.context.get("payslip_no_recompute"):
            return

        payslips = self.filtered(lambda p: p.line_ids and p.state == 'draft')
        for payslip in payslips:
            lines_vals = []
            if payslip.employee_id and payslip.version_id and payslip.date_from and payslip.date_to and payslip.struct_id:
                lines_vals = [(0, 0, line_vals) for line_vals in payslip._get_payslip_lines()]
            payslip.line_ids = [(5, 0, 0)] + lines_vals

    def _get_recomputing_fields(self):
        """Return the field names triggering :meth:`_compute_line_ids` (its ``depends``).

        :rtype: list[str]
        """
        return [
            'employee_id', 'version_id', 'struct_id',
            'date_from', 'date_to', 'worked_days_line_ids',
            'input_line_ids'
        ]

    def _get_basic_wage_line_codes(self):
        """Return the rule codes summed into the ``basic_wage`` field (default ``{'BASIC'}``).

        Overridden by ``l10n_be_hr_payroll``.

        :rtype: set[str]
        """
        return {'BASIC'}

    def _get_gross_wage_line_codes(self):
        """Return the rule codes summed into the ``gross_wage`` field (default ``{'GROSS'}``).

        :rtype: set[str]
        """
        return {'GROSS'}

    def _get_net_wage_line_codes(self):
        """Return the rule codes summed into the ``net_wage`` field (default ``{'NET'}``).

        :rtype: set[str]
        """
        return {'NET'}

    @api.depends('line_ids.total')
    def _compute_basic_net(self):
        """Compute ``basic_wage``, ``gross_wage``, ``net_wage`` and ``employer_cost`` from the lines.

        Only draft payslips are recomputed: the values of validated payslips are frozen. The codes
        come from :meth:`_get_basic_wage_line_codes`, :meth:`_get_gross_wage_line_codes`,
        :meth:`_get_net_wage_line_codes` and the rules flagged ``appears_on_employee_cost_dashboard``.
        """
        to_compute_payslips = self.filtered(lambda p: p.state == 'draft').with_prefetch()
        if not to_compute_payslips:
            return

        basic_codes = self._get_basic_wage_line_codes()
        gross_codes = self._get_gross_wage_line_codes()
        net_codes = self._get_net_wage_line_codes()
        line_values = to_compute_payslips._origin._get_line_values([*basic_codes, *gross_codes, *net_codes])
        employer_codes_by_structure = {
            structure: structure.rule_ids.filtered('appears_on_employee_cost_dashboard').mapped('code')
            for structure in to_compute_payslips.struct_id
        }
        employer_cost_codes = list(set(
            code for codes in employer_codes_by_structure.values() for code in codes
        ))
        employer_cost_values = {}
        if employer_cost_codes:
            employer_cost_values = to_compute_payslips._origin._get_line_values(employer_cost_codes)
        for payslip in to_compute_payslips:
            payslip_id = payslip._origin.id
            if not payslip_id:
                payslip.update({
                    'basic_wage': 0.0,
                    'gross_wage': 0.0,
                    'net_wage': 0.0,
                    'employer_cost': 0.0,
                })
                continue
            payslip_employer_codes = employer_codes_by_structure.get(payslip.struct_id, [])
            employer_cost_total = sum(
                employer_cost_values[code][payslip_id]['total']
                for code in payslip_employer_codes
            )
            payslip.update({
                'basic_wage': sum(line_values[code][payslip_id]['total'] for code in basic_codes),
                'gross_wage': sum(line_values[code][payslip_id]['total'] for code in gross_codes),
                'net_wage': sum(line_values[code][payslip_id]['total'] for code in net_codes),
                'employer_cost': employer_cost_total,
            })

    @api.depends('worked_days_line_ids.number_of_days', 'worked_days_line_ids.number_of_hours', 'worked_days_line_ids.is_paid')
    def _compute_worked_days_hours(self):
        for payslip in self:
            payslip.sum_worked_days = sum(payslip.worked_days_line_ids.mapped('number_of_days'))
            payslip.sum_worked_hours = sum(payslip.worked_days_line_ids.mapped('number_of_hours'))

    @api.depends('worked_days_line_ids.number_of_days', 'worked_days_line_ids.number_of_hours', 'worked_days_line_ids.is_paid')
    def _compute_worked_paid_days_hours(self):
        for payslip in self:
            is_paid_worked_days = payslip.worked_days_line_ids.filtered(lambda line: line.is_paid)
            payslip.sum_worked_paid_days = sum(is_paid_worked_days.mapped('number_of_days'))
            payslip.sum_worked_paid_hours = sum(is_paid_worked_days.mapped('number_of_hours'))

    @api.depends('employee_type_id')
    def _compute_is_company_executive(self):
        executive_type = self.env.ref('hr.contract_type_company_executive', raise_if_not_found=False)
        for payslip in self:
            payslip.is_company_executive = executive_type and payslip.employee_type_id == executive_type

    def _get_regular_worked_hours(self):
        """Return the reference number of worked hours of the payslip (default ``sum_worked_hours``).

        Hook for localizations, overridden by ``l10n_au_hr_payroll``.

        :rtype: float
        """
        # To be overridden by localization modules. Used for the amount computation for each worked days type.
        self.ensure_one()
        return self.sum_worked_hours

    def _compute_is_superuser(self):
        self.is_superuser = self.env.user._is_superuser() and self.env.user.has_group('base.group_no_one')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        if any(payslip.date_from > payslip.date_to for payslip in self):
            raise ValidationError(_("Payslip 'Date From' must be earlier than 'Date To'."))

    def _record_attachment_payment(self, attachments, slip_lines):
        """Register the payment of salary attachments with the total of the given payslip lines.

        Called when the payslip is marked as paid (see :meth:`write`). The amount is negative for
        credit notes.

        :param hr.salary.attachment attachments: attachments sharing the same rule code.
        :param hr.payslip.line slip_lines: lines of that rule code.
        """
        self.ensure_one()
        sign = -1 if self.credit_note else 1
        amount = sum(sl.total for sl in slip_lines)
        attachments.record_payment(self, sign * abs(amount))

    def write(self, vals):
        """Write the payslips, with the following side effects:

        * editing ``name``, ``amount``, ``quantity`` or ``rate`` of lines (``line_ids`` update
          commands): the lines are recomputed with the edited values forced (see
          :meth:`_recompute_with_forced_lines`), the edited lines are flagged
          ``manually_modified`` and the changes are logged in the chatter. Writing ``total``
          alone writes it as ``amount``;
        * changing ``input_line_ids``: computed, non-refund draft payslips are recomputed with
          :meth:`compute_sheet`;
        * ``state`` set to ``'paid'``: the payments of the linked salary attachments are recorded;
        * ``state`` set to ``'draft'`` on non-draft payslips: :meth:`action_refresh_from_work_entries`;
        * changing ``struct_id`` updates ``ignore_worked_day_lines`` from the structure, and
          changing ``ignore_worked_day_lines`` recomputes the payslips;
        * moving a payslip out of a draft pay run removes its version from that pay run.
        """
        payslips_to_update = self.env['hr.payslip']
        if vals.get('state') == 'draft':
            payslips_to_update = self.filtered(lambda p: p.state != 'draft')
        if struct_id := vals.get('struct_id'):
            vals['ignore_worked_day_lines'] = not self.env['hr.payroll.structure'].browse(struct_id).use_worked_day_lines

        # if line_ids total are updated it should be the amount of the line that have the new value as it is only possible if both are equal
        for line in vals.get('line_ids', []):
            if line[0] == 1 and 'total' in line[2] and 'amount' not in line[2]:
                line[2]['amount'] = line[2].pop("total")

        update_cmds = {
            cmd[1]: cmd[2] for cmd in vals.get('line_ids', [])
            if cmd[0] == 1 and any(k in cmd[2] for k in ('name', 'amount', 'quantity', 'rate'))
        }
        old_line_vals = {}

        payrun_is_changed = False
        if 'payslip_run_id' in vals:
            payrun_is_changed = True
            new_payrun_id = vals['payslip_run_id']

        for payslip in self:
            old_line_vals[payslip.id] = {}
            if update_cmds and any(line_id in payslip.line_ids.ids for line_id in update_cmds):
                for line, key in payslip._get_line_override_keys().items():
                    old_line_vals[payslip.id][key] = {
                        'name': line.name,
                        'code': line.code,
                        'amount': line.amount,
                        'quantity': line.quantity,
                        'rate': line.rate,
                        'total': line.total,
                    }

            if payrun_is_changed:
                old_payrun = payslip.payslip_run_id
                if old_payrun and old_payrun.state == '00_draft' and old_payrun.id != new_payrun_id and payslip.version_id:
                    old_payrun.write({'version_ids': [Command.unlink(payslip.version_id.id)]})

        res = super().write(vals)

        if update_cmds:
            for payslip in self:
                overrides = {}
                audit_changes = defaultdict(list)
                line_keys = payslip._get_line_override_keys()
                for line_id, changed_vals in update_cmds.items():
                    line = self.env['hr.payslip.line'].browse(line_id)
                    if line.slip_id.id != payslip.id:
                        continue
                    explanation = line.explanation
                    # A line edited a second time already starts with this label.
                    if explanation and not line.manually_modified:
                        explanation = self.env._("Manually modified. Explanation before the change:\n%(explanation)s", explanation=explanation)
                    overrides[line_keys[line]] = {
                        'name': line.name,
                        'amount': line.amount,
                        'quantity': line.quantity,
                        'rate': line.rate,
                        'manually_modified': True,
                        'explanation': explanation,
                    }
                if overrides:
                    payslip._recompute_with_forced_lines(overrides)
                if old_line_vals[payslip.id]:
                    for line, key in payslip._get_line_override_keys().items():
                        old = old_line_vals[payslip.id].get(key, {})
                        for field in ('name', 'amount', 'quantity', 'rate', 'total'):
                            if old.get(field) != line[field]:
                                audit_changes[line.name].append({
                                    'field': field,
                                    'old': old.get(field),
                                    'new': line[field],
                                })
                if audit_changes:
                    payslip._log_line_manual_changes(audit_changes)

        if vals.get('input_line_ids'):
            self.filtered(lambda p: p.state == 'draft' and p.line_ids and not p.is_refund_payslip).compute_sheet()
        if 'state' in vals and vals['state'] == 'paid':
            # Register payment in Salary Attachments
            # NOTE: Since we combine multiple attachments on one input line, it's not possible to compute
            #  how much per attachment needs to be taken record_payment will consume monthly payments (child_support) before other attachments
            for slip in self.filtered(lambda r: r.salary_attachment_ids):
                for deduction_code, attachments in slip.salary_attachment_ids.grouped(lambda x: x.salary_rule_id.code).items():
                    # Use the amount from the computed value in the payslip lines not the input
                    salary_lines = slip.line_ids.filtered(lambda r: r.code == deduction_code)
                    if not attachments or not salary_lines:
                        continue
                    slip._record_attachment_payment(attachments, salary_lines)
        if payslips_to_update:
            payslips_to_update.action_refresh_from_work_entries()
        if 'ignore_worked_day_lines' in vals:
            self.compute_sheet()

        return res

    @api.model
    def _get_line_override_key(self, code, rank=0):
        """Return the key of a payslip line in ``force_payslip_line_overrides``.

        A rule computed once per input line (several inputs of its code) gives several lines of
        the same code, told apart by their rank in the order of computation.

        :param str code: code of the line.
        :param int rank: rank of the line among the lines of its code.
        :return: ``code`` for the first line, else ``(code, rank)``.
        """
        return (code, rank) if rank else code

    def _get_line_override_keys(self):
        """Return ``{hr.payslip.line: key}`` of the lines of the payslip, see :meth:`_get_line_override_key`."""
        self.ensure_one()
        keys = {}
        rank_by_code = defaultdict(int)
        # The lines of a code are created in the order of their computation
        for line in self.line_ids.sorted('id'):
            keys[line] = self._get_line_override_key(line.code, rank_by_code[line.code])
            rank_by_code[line.code] += 1
        return keys

    def _recompute_with_forced_lines(self, forced_line_vals):
        """Recompute the lines of a draft payslip, forcing the values of some lines.

        The lines before the first modified line (by sequence) keep their current values, the
        following ones are recomputed by :meth:`_get_payslip_lines` (with the context key
        ``force_payslip_line_overrides``), so that the rules depending on the edited lines take
        the new values into account. Custom line names are always kept. Sets ``edited``.

        :param dict forced_line_vals: ``{line key: {'name', 'amount', 'quantity', 'rate',
            'manually_modified', 'explanation'}}``, see :meth:`_get_line_override_keys`.
        """
        self.ensure_one()
        if self.state != 'draft':
            return
        line_keys = self._get_line_override_keys()
        modified_lines = self.line_ids.filtered(lambda l: line_keys[l] in forced_line_vals)
        min_sequence = min(modified_lines.mapped('sequence'), default=0)
        all_overrides = {}
        for line, key in line_keys.items():
            if line.sequence < min_sequence:
                all_overrides[key] = {'name': line.name, 'amount': line.amount, 'quantity': line.quantity, 'rate': line.rate, 'explanation': line.explanation, 'manually_modified': line.manually_modified}
            else:
                all_overrides[key] = {'name': line.name}
        all_overrides.update(forced_line_vals)
        new_lines = self.with_context(
            force_payslip_line_overrides=all_overrides
        )._get_payslip_lines()
        self.line_ids.unlink()
        self.env['hr.payslip.line'].create(new_lines)
        super().write({'edited': True})

    def _log_line_manual_changes(self, changes):
        """Post a chatter message listing manual line changes.

        :param dict changes: ``{line_name: [{'field': str, 'old': value, 'new': value}]}``.
        """
        self.ensure_one()
        field_labels = {
            'name': self.env._('Name'),
            'amount': self.env._('Amount'),
            'quantity': self.env._('Quantity'),
            'rate': self.env._('Rate (%)'),
            'total': self.env._('Total'),
        }
        items = []
        for name, change_lines in changes.items():
            items.append(Markup('<li>%s</li><ul>') % name)
            for change in change_lines:
                if change['field'] in ('amount', 'total'):
                    old_fmt = format_amount(self.env, change['old'] or 0, self.currency_id)
                    new_fmt = format_amount(self.env, change['new'], self.currency_id)
                elif change['field'] == 'name':
                    old_fmt = change['old']
                    new_fmt = change['new']
                else:
                    old_fmt = '%.2f' % (change['old'] or 0)
                    new_fmt = '%.2f' % change['new']
                items.append(Markup('<li><strong>%s: %s → <span class="text-info">%s</span></strong></li>') % (
                    field_labels.get(change['field'], change['field']),
                    old_fmt,
                    new_fmt,
                ))
            items.append(Markup('</ul>'))
        body = Markup("%s<ul>%s</ul>") % (
            self.env._("This payslip has been manually edited by %(user)s:",
                    user=self.env.user.name),
            Markup("").join(items),
        )
        self.message_post(body=body)

    def action_payslip_draft(self):
        """Reset the payslips to draft, removing the payment report and the confirmation date.

        Through :meth:`write`, the worked days and lines of the payslips are regenerated (see
        :meth:`action_refresh_from_work_entries`).
        """
        self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'hr.payslip'),
            ('res_id', 'in', self.ids),
            ('res_field', '=', 'payment_report'),
        ]).unlink()
        self.write({
            'payment_report': False,
            'payment_report_filename': False,
            'payment_report_date': False,
            'state': 'draft',
            'done_date': False,
        })
        return True

    def _get_pdf_reports(self):
        """Group the payslips by PDF report: the structure ``report_id``, or ``hr_payroll.action_report_payslip``.

        :return: ``{ir.actions.report: hr.payslip}``.
        :rtype: dict
        """
        default_report = self.env.ref('hr_payroll.action_report_payslip')
        result = defaultdict(lambda: self.env['hr.payslip'])
        for payslip in self:
            if not payslip.struct_id or not payslip.struct_id.report_id:
                result[default_report] |= payslip
            else:
                result[payslip.struct_id.report_id] |= payslip
        return result

    def _get_email_template(self):
        """Return the mail template sent with the generated payslip PDF (``hr_payroll.mail_template_new_payslip``).

        :rtype: mail.template
        """
        return self.env.ref(
            'hr_payroll.mail_template_new_payslip', raise_if_not_found=False
        )

    def _check_send_payslip_mail(self):
        """Return whether the payslip must be sent by email after its PDF generation.

        Refunds and corrections without net difference are not sent. Overridden by
        ``l10n_mx_hr_payroll_account``.

        :rtype: bool
        """
        self.ensure_one()
        if self.is_correction_payslip and self.currency_id.is_zero(self.correction_net_delta):
            return False
        return not self.is_refund_payslip

    def _check_generate_payslip_pdf(self):
        """Return whether a PDF must be generated for the payslip.

        Refunds and corrections without net difference get no PDF.

        :rtype: bool
        """
        self.ensure_one()
        if self.is_correction_payslip and self.currency_id.is_zero(self.correction_net_delta):
            return False
        return not self.is_refund_payslip

    def _generate_pdf(self):
        """Generate the PDF of the payslips, attach it to them and send it by email.

        The PDFs are rendered by :meth:`_prepare_payslip_pdf_content` in the language given by
        :meth:`_get_payslips_pdf_lang`, registered as main attachment, then :meth:`_pdf_post_create`
        is called and the template of :meth:`_get_email_template` is sent for the payslips accepted
        by :meth:`_check_send_payslip_mail`. With the context key ``is_test_print``, the PDFs are
        only generated.

        :return: a notification client action, or ``None`` with ``is_test_print``.
        """
        mapped_reports = self._get_pdf_reports()
        employees = []
        attachments_vals_list = []
        generic_name = _("Payslip")
        for report, payslips in mapped_reports.items():
            payslips_languages = payslips._get_payslips_pdf_lang()
            for payslip in payslips.filtered(lambda p: p._check_generate_payslip_pdf()):
                pdf_content = payslip._prepare_payslip_pdf_content(report, payslips_languages.get(payslip, (None, None)))
                if report.print_report_name:
                    pdf_name = safe_eval(report.print_report_name, {'object': payslip})
                else:
                    pdf_name = generic_name
                employees.append(payslip.employee_id)
                attachments_vals_list.append({
                    'name': pdf_name,
                    'type': 'binary',
                    'raw': pdf_content,
                    'res_model': payslip._name,
                    'res_id': payslip.id,
                })

        new_pdfs = self.env['ir.attachment'].sudo().create(attachments_vals_list)
        employee_attachments = defaultdict(lambda: self.env['ir.attachment'])
        for employee, attachment in zip(employees, new_pdfs, strict=True):
            employee_attachments[employee] |= attachment
        registered_payslip_ids = set()
        for pdf in new_pdfs:
            if pdf.res_id in registered_payslip_ids:
                continue
            registered_payslip_ids.add(pdf.res_id)
            pdf.register_as_main_attachment(force=True)
        if self.env.context.get('is_test_print'):
            return

        self._pdf_post_create(employee_attachments)
        # Send email to employees (after attachment is created to include it in the mail by other bridge module)
        for payslip in self.filtered(lambda p: p._check_send_payslip_mail()):
            if template := payslip._get_email_template():
                template.send_mail(payslip.id, email_layout_xmlid='mail.mail_notification_light')

        notification_message = self.env.context.get('pdf_generation_message', self.env._("PDFs are generated"))
        return self._show_notification(notification_message, 'success')

    def _pdf_post_create(self, employee_attachments):
        """ Hook called right after the payslip PDF attachments have been created.

        :param dict[hr.employee, ir.attachment] employee_attachments: attachments generated per employee
        """

    def _is_out_of_contract(self):
        """Return whether the (non refund) payslip period does not overlap its version contract dates at all.

        Used by the "No running contract" payroll warning.

        :rtype: bool
        """
        return (not self.is_refund_payslip and self.version_id and self.date_from and self.date_to and
            (
                not self.version_id.contract_date_start or self.version_id.contract_date_start > self.date_to or
                (self.version_id.contract_date_end and self.version_id.contract_date_end < self.date_from)
            ))

    def _is_period_mismatch_payslip(self):
        """Return whether the period of a draft or validated payslip does not match its pay schedule.

        Payslips ignoring worked days are never considered mismatching.

        :rtype: bool
        """
        self.ensure_one()
        if self.state not in ['draft', 'validated'] or not (self.date_from and self.date_to) or self.ignore_worked_day_lines:
            return False
        schedule = self.version_id.schedule_pay or self.version_id.structure_type_id.default_schedule_pay
        return bool(schedule and self.date_from + self._get_schedule_timedelta() != self.date_to)

    def _get_payslips_pdf_lang(self):
        """Return the languages in which each payslip PDF is printed.

        The primary language is the employee language (or its user, the current user, the
        environment language). Overridden by ``l10n_be_hr_payroll`` (bilingual payslips).

        :return: ``{payslip: (primary_lang, secondary_lang_or_None)}``.
        :rtype: dict
        """
        # Returns primary/secondary language for each payslip
        lang_map = {}
        for payslip in self:
            payslip_lang = payslip.employee_id.lang or payslip.employee_id.user_id.lang or self.env.user.lang or self.env.lang
            lang_map[payslip] = (payslip_lang, None)
        return lang_map

    def _prepare_payslip_pdf_content(self, report, languages):
        """Render the payslip PDF with the given report, in the company of the payslip.

        :param ir.actions.report report: report to render.
        :param tuple languages: ``(primary_lang, secondary_lang)`` as returned by
            :meth:`_get_payslips_pdf_lang`.
        :return: the PDF content.
        :rtype: bytes
        """
        self.ensure_one()
        # in the document layout of the company of the payslip, not the one of the current company
        pdf_content, _ = self.env['ir.actions.report'].sudo().with_company(self.company_id).with_context(lang=languages[0])._render_qweb_pdf(report, self.id)
        return pdf_content

    def _queue_for_send(self):
        """Flag the payslips for PDF generation and trigger the cron doing it (:meth:`_cron_generate_pdf`)."""
        self.write({'queued_for_pdf': True})
        self.env.flush_all()  # This is necessary for the cron to have the changes
        payslip_cron = self.env.ref(
            'hr_payroll.ir_cron_generate_payslip_pdfs', raise_if_not_found=False
        )
        if payslip_cron:
            payslip_cron._trigger()

    def _get_employees_from_records(self, records):
        """Return the employees related to records of any model (employee, ``employee_id`` or ``employee_ids``).

        Used to match payroll warnings with the payslips to validate.

        :rtype: hr.employee
        """
        Employee = self.env['hr.employee']
        if not records:
            return Employee
        if records._name == 'hr.employee':
            return records
        if 'employee_id' in records:
            return records.mapped('employee_id')
        if 'employee_ids' in records:
            return records.mapped('employee_ids')
        return Employee

    def _get_leaves_domain(self, extra_domain=None):
        """Return a ``hr.leave`` domain matching the time off of each payslip employee overlapping its period.

        :param extra_domain: domain added (AND) to the domain of each payslip, or a callable taking
            the payslip and returning such a domain.
        :rtype: odoo.fields.Domain
        """
        domain_list = []
        for p in self:
            domain = [
                ('employee_id', '=', p.employee_id.id),
                ('date_from', '<=', p.date_to),
                ('date_to', '>=', p.date_from),
            ]
            if extra_domain:
                extra = extra_domain(p) if callable(extra_domain) else extra_domain
                if extra:
                    domain = Domain.AND([domain, extra])
            domain_list.append(domain)
        return Domain.OR(domain_list) if domain_list else Domain.FALSE

    def action_payslip_done(self):
        """Validate the payslips: ``state`` becomes ``'validated'`` and ``done_date`` is set.

        Raises a ``ValidationError`` if the user is not payroll officer, if a blocking payroll
        warning (``block_payslips``) concerns the payslips or their employees, if a payslip is
        cancelled, has errors (``error_count``) or is linked to an archived version. The payslips
        are expected to be computed (use :meth:`action_validate` to compute them first).

        Then the time off of regular payslips is flagged ``payslip_state = 'done'``, a negative net
        is stored in ``negative_net_to_report`` and, with the context key ``payslip_generate_pdf``,
        the PDFs are generated or queued. Overridden by most localizations (accounting entries,
        declarations, ...).
        """
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_officer'):
            raise ValidationError(self.env._("You do not have sufficient permissions to validate payslips."))

        warning_messages = []
        # The blocking warnings are the ones of the country of the payslips, not of the current company
        for company, payslips in self.grouped('company_id').items():
            warnings = self.env['hr.payroll.warning'].with_company(company).get_payroll_dashboard_warning_cards(
                [], block_payslips=True, include_model_warnings=True)
            payslip_employees = payslips.employee_id
            for warning in warnings:
                records = warning['warning_records']
                if records._name == 'hr.payslip':
                    has_blocking_records = bool(payslips & records)
                elif records._name == 'hr.leave':
                    # A time off only blocks the payslips of its period
                    has_blocking_records = any(
                        leave.employee_id == payslip.employee_id
                        and leave.request_date_from <= payslip.date_to
                        and leave.request_date_to >= payslip.date_from
                        for leave in records
                        for payslip in payslips
                    )
                else:
                    has_blocking_records = bool(payslip_employees & self._get_employees_from_records(records))
                message = f"{warning['name']}: {warning['description']}" if warning.get('description', '') else f"{warning['name']}"
                if has_blocking_records and message not in warning_messages:
                    warning_messages.append(message)
        if warning_messages:
            if len(warning_messages) > 1:
                warning_messages = [f"{i + 1}) {message}" for i, message in enumerate(warning_messages)]
            raise ValidationError('\n'.join(warning_messages))

        if any(slip.state == 'cancel' for slip in self):
            raise ValidationError(_("You can't confirm cancelled payslips."))
        if self.filtered('error_count'):
            raise ValidationError(self._get_error_message())
        if self.filtered(lambda slip: slip.version_id and not slip.version_id.active):
            raise ValidationError(self.env._("You can't validate a payslip linked to an archived version."))
        # The wages are only computed on draft payslips: compute the pending ones before the state changes.
        self.flush_recordset(['basic_wage', 'gross_wage', 'net_wage', 'employer_cost'])
        self.write({
            'state': 'validated',
            'done_date': fields.Datetime.now(),
        })

        regular_payslips = self.filtered(lambda p: p.is_regular)
        if regular_payslips:
            domain = Domain.AND([
                [('state', '=', 'validate'), ('payslip_state', '=', 'normal')],
                regular_payslips._get_leaves_domain(
                    extra_domain=lambda p: [
                        ('work_entry_type_id', 'in', p.worked_days_line_ids.work_entry_type_id.ids),
                    ] if p.struct_id.use_worked_day_lines else []
                ),
            ])
            leaves = self.env['hr.leave'].search(domain)
            leaves.write({'payslip_state': 'done'})

        for payslip in self.filtered(lambda p: not p.credit_note):
            if (payslip.is_correction_payslip and payslip.origin_payslip_id.state == 'paid'):
                amount = payslip.correction_net_delta
            else:
                amount = payslip.net_wage
            if payslip.currency_id.compare_amounts(amount, 0) < 0:
                payslip.write({
                    'has_negative_net_to_report': True,
                    'negative_net_to_report': abs(amount),
                })

        if self.env.context.get('payslip_generate_pdf'):
            actions_report = self.env['ir.actions.report']
            engine_name = actions_report._get_pdf_engine()
            pdf_state = actions_report.get_pdf_engine_state(engine_name)
            if self.env.context.get('payslip_generate_pdf_direct') and pdf_state != 'install':  # If not installed, redirect PDF generation to the cron
                self._generate_pdf()
            else:
                on_confirmed_payslips = self.filtered(lambda p: p.company_id.payslip_generate_and_send_trigger == 'on_confirmed')
                if len(on_confirmed_payslips) <= 5 and pdf_state != 'install':
                    on_confirmed_payslips._generate_pdf()
                else:
                    on_confirmed_payslips._queue_for_send()

    def action_validate(self):
        """Compute the draft payslips without lines, then validate the draft payslips with :meth:`action_payslip_done`.

        :return: the action returned by :meth:`compute_sheet` (a localization may ask for missing
            data) or by :meth:`action_payslip_done`, if any.
        """
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_officer'):
            raise ValidationError(self.env._("You do not have sufficient permissions to validate payslips."))
        to_recompute_payslips = self.filtered(lambda slip: slip.state == 'draft' and not slip.line_ids)
        if to_recompute_payslips:
            # A localization may ask for missing data before the lines can be computed.
            result = to_recompute_payslips.compute_sheet()
            if isinstance(result, dict):
                return result
        if self.filtered(lambda slip: slip.version_id and not slip.version_id.active):
            raise ValidationError(self.env._("You can't validate a payslip linked to an archived version."))
        # Give back whatever action the validation asks for, otherwise the button silently does nothing.
        return self.filtered(lambda slip: slip.state == 'draft').action_payslip_done()

    def action_payslip_cancel(self):
        """Cancel the payslips and give their time off back the ``'normal'`` payslip state.

        Only payroll managers can cancel validated payslips.
        """
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_manager') \
            and self.filtered(lambda slip: slip.state == 'validated'):
            raise UserError(_("Cannot cancel a payslip that is validated."))
        self.return_time_off_to_normal()
        self.write({'state': 'cancel', 'done_date': False})

    def action_payslip_paid(self):
        """Mark validated payslips as paid and set their ``paid_date`` (if not already set).

        Paying a correction also pays its validated origin and related payslips. When the company
        generates the PDF ``on_paid``, the PDFs are queued. Through :meth:`write`, the payments of
        the salary attachments are recorded.
        """
        if any(slip.state not in ['validated', 'paid'] for slip in self):
            raise UserError(_('Cannot mark payslip as paid if not confirmed.'))
        if self.filtered('error_count'):
            raise ValidationError(self._get_error_message())
        to_pay = self.filtered(lambda p: p.state != 'paid')
        to_pay.write({'state': 'paid'})
        # Keep a payment date that was set upfront (e.g. US).
        to_pay.filtered(lambda p: not p.paid_date).paid_date = fields.Date.context_today(self)
        for payslip in self.filtered('is_correction_payslip'):
            origin = payslip.origin_payslip_id
            (origin | origin.related_payslip_ids).filtered(lambda p: p.state == 'validated').action_payslip_paid()
        for payslips in self.grouped('company_id').values():
            if payslips.company_id.payslip_generate_and_send_trigger == 'on_paid':
                payslips._queue_for_send()

    def action_payslip_payment_report(self, export_format='csv'):
        self.ensure_one()
        if len(self.payslip_run_id) > 1:
            raise UserError(_('The selected payslips should be linked to the same batch'))
        payslip_domain = Domain.AND([
            Domain('version_id', '=', self.version_id.id),
            Domain('state', '=', 'validated'),
        ])
        unpaid_payslips = self.env['hr.payslip'].search(payslip_domain).ids

        return {
            'name': self.env._('Pay'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.payment.report.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_payslip_ids': self.ids,
                'default_payslip_run_id': self.payslip_run_id.id,
                'default_export_format': export_format,
                'default_unpaid_payslips': unpaid_payslips,
                'default_allowed_unpaid_payslip_ids': unpaid_payslips,
            },
        }

    def action_payslip_unpaid(self):
        """Set paid payslips back to validated."""
        if any(slip.state != 'paid' for slip in self):
            raise UserError(_('You cannot cancel the payment if the payslip has not been paid.'))
        self.write({'state': 'validated'})
        self.payslip_run_id.write({'state': '02_close'})

    def action_open_salary_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payslip Adjustments'),
            'res_model': 'hr.salary.attachment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.salary_attachment_ids.ids)],
        }

    def action_adjust_payslip(self):
        if self.env.context.get('correct_paid_payslips'):
            # This method is used in the wrong company/employee data warning
            # as an action to correct incorrect payslips (which do not necessarily have to be paid).
            if any(payslip.credit_note or payslip.state != 'paid' for payslip in self):
                raise UserError(self.env._('You can only correct payslips that have been paid.'))
        # Cached lookup: the payroll warnings build this action for each payslip to correct
        view_id = self.env['ir.model.data']._xmlid_to_res_id('hr_payroll.hr_payslip_correction_wizard_form', raise_if_not_found=False)
        default_is_button_action = self.env.context.get('default_is_button_action')
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Payslip Correction') if len(self) == 1 else self.env._('Payslips Correction'),
            'res_model': 'hr.payslip.correction.wizard',
            'view_mode': 'form',
            'views': [(view_id or False, 'form')],
            'target': 'new',
            'context': {
                'default_employee_ids': self.employee_id.ids,
                'default_payslip_ids': self.ids,
                'default_is_button_action': default_is_button_action,
                'dialog_size': 'medium'
            },
        }

    def action_open_related_payslips(self):
        self.ensure_one()
        return {
                'name': self.env._("Related Payslip"),
                'res_model': 'hr.payslip',
                'type': 'ir.actions.act_window',
                'target': 'current',
                'view_mode': 'list, form',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('id', 'in', self._get_payslip_family().ids)],
        }

    def action_open_employee_calendar(self):
        self.ensure_one()
        return {
            'name': self.env._("Calendar"),
            'res_model': 'hr.leave',
            'type': 'ir.actions.act_window',
            'view_mode': 'calendar, gantt',
            'views': [(self.env.ref('hr_holidays.hr_leave_employee_view_dashboard_month').id, 'calendar'), (self.env.ref('hr_holidays_gantt.hr_leave_gantt_view_payroll').id, 'gantt')],
            'search_view_id': [self.env.ref("hr_holidays.hr_leave_view_search_manager").id, 'search'],
            'domain': [('employee_id', '=', self.employee_id.id)],
            'context': {
                'default_employee_id': self.employee_id.id,
                'initial_date': self.date_from,
                'initialDate': self.date_from,
                'employee_id': [self.employee_id.id]
            }
        }

    def _get_payslips_action(self):
        formview_ref = self.env.ref('hr_payroll.view_hr_payslip_form', False)
        listview_ref = self.env.ref('hr_payroll.view_hr_payslip_tree', False)
        return {
                'type': 'ir.actions.act_window',
                'name': self.env._("Refund Payslip"),
                'res_model': 'hr.payslip',
                'target': 'current',
                'view_mode': 'list,form',
                'views': [(listview_ref.id, 'list'), (formview_ref.id, 'form')],
                'domain': [('id', 'in', self.ids)],
            }

    def _action_refund_payslips(self):
        """Create and validate a refund (credit note) for each payslip.

        A refund is a copy with ``credit_note``, ``is_refund_payslip`` and ``edited`` set, and
        ``origin_payslip_id`` pointing to the original payslip, whose worked days, inputs and lines
        are negated. The original is flagged ``is_refunded`` and its time off get back the
        ``'normal'`` payslip state.

        :return: the refunds.
        :rtype: hr.payslip
        """
        reverted_payslips = self.env['hr.payslip']
        for payslip in self:
            reverted_payslip = payslip.copy({
                'credit_note': True,
                'edited': True,
                'origin_payslip_id': payslip.id,
                'is_refund_payslip': True,
            })
            for wd in reverted_payslip.worked_days_line_ids:
                wd.number_of_hours = -wd.number_of_hours
                wd.number_of_days = -wd.number_of_days
                wd.amount = -wd.amount
            for input_line in reverted_payslip.input_line_ids:
                input_line.amount = -input_line.amount
            for line in reverted_payslip.line_ids:
                line.amount = -line.amount
                line.total = -line.total
            reverted_payslips |= reverted_payslip
            payslip.message_post(
                body=self.env._('This is a refunded payslip.\nFind the refund under this name: %(payslip)s', payslip=reverted_payslip.name)
            )
            payslip.is_refunded = True
        reverted_payslips.action_payslip_done()
        if self:
            domain = Domain.AND([
                [('payslip_state', 'in', ['blocked', 'done'])],
                self._get_leaves_domain()
            ])
            related_leaves = self.env['hr.leave'].search(domain)
            related_leaves.write({'payslip_state': 'normal'})
        return reverted_payslips

    def _action_correct_payslips(self):
        """Create and compute a correction payslip for each payslip.

        A correction is a new draft payslip for the same employee, version, structure and period,
        with ``origin_payslip_id`` set and a copy of the original input lines. The original is
        flagged ``is_corrected``. Usually called after :meth:`_action_refund_payslips`.

        :return: the corrections.
        :rtype: hr.payslip
        """
        corrected_payslips_values = []
        for payslip in self:
            reference_date = max(payslip.date_from, payslip.version_id.contract_date_start or payslip.date_from, payslip.version_id.date_version)
            corrected_payslips_values.append({
                'origin_payslip_id': payslip.id,
                'employee_id': payslip.employee_id.id,
                'struct_id': payslip.struct_id.id,
                'version_id': payslip.employee_id._get_version(reference_date).id,
                'date_from': payslip.date_from,
                'date_to': payslip.date_to,
                'input_line_ids': [
                    Command.create({
                        'salary_rule_id': line.salary_rule_id.id,
                        'amount': line.amount,
                        'name': line.name,
                    })
                    for line in payslip.input_line_ids
                ],
            })
            payslip.message_post(
                body=self.env._('This is a corrected payslip.\nFind the correction under this name: %(payslip)s', payslip=self.env._('Correction: %(payslip)s', payslip=payslip.name)))
            payslip.is_corrected = True
        corrected_payslips = self.env['hr.payslip'].create(corrected_payslips_values)
        corrected_payslips.compute_sheet()
        return corrected_payslips

    def refund_sheet(self):
        """Refund the payslips (see :meth:`_action_refund_payslips`) and open the payslips and their refunds."""
        reverted_payslips = self._action_refund_payslips()
        return (self | reverted_payslips)._get_payslips_action()

    @api.ondelete(at_uninstall=False)
    def _unlink_if_draft_or_cancel(self):
        """Prevent the deletion of validated or paid payslips, then recompute the issues of their remaining duplicates."""
        if any(payslip.state not in ('draft', 'cancel') for payslip in self):
            raise UserError(_(
                "Oops! Only draft and cancelled payslips can be deleted without causing any chaos. We can't "
                "take back our dedicated employees' hard-earned cash!"
            ))

        # _get_similar_payslips() filters out duplicate payslips by checking state = 'cancel'
        self.write({'state': 'cancel'})
        to_recompute_payslips = self.env['hr.payslip']
        similar_payslips = self._get_similar_payslips()
        for slip in self:
            duplicate_payslips = similar_payslips.get(
                (slip.version_id, slip.struct_id, slip.date_from, slip.date_to, slip.ignore_worked_day_lines),
                self.env['hr.payslip'],
            )
            if len(duplicate_payslips) == 1:
                to_recompute_payslips |= duplicate_payslips
        to_recompute_payslips._compute_issues()

    @api.ondelete(at_uninstall=False)
    def _unlink_and_remove_version_from_draft_payrun(self):
        # a pay run losing all its payslips and employees is deleted with them
        emptied_payruns = self.payslip_run_id.filtered(
            lambda payrun: payrun.slip_ids <= self and payrun.version_ids <= self.version_id
        )
        for slip in self:
            payrun = slip.payslip_run_id
            if payrun:
                payrun.write({'version_ids': [Command.unlink(slip.version_id.id)]})
        emptied_payruns._unlink_emptied_payruns()

    def compute_sheet(self):
        """Compute the lines of the draft payslips; the other payslips are ignored.

        The existing lines are deleted and ``compute_date`` is set. Refund payslips get the negated
        lines of their origin. The other payslips are computed with :meth:`_get_payslip_lines`.
        The worked days are not regenerated (see :meth:`action_refresh_from_work_entries`).

        Payslips are computed by employee in chronological "layers" so that the cumulative/YTD
        rules of an employee's second payslip of the period (e.g. after a mid-period version
        change) see the first one:

        * layer 1 computes the first payslip of all employees at once;
        * layer 2 computes the second payslip of the employees having one, etc.

        Overridden by several localizations (``l10n_au``, ``l10n_ch``, ``l10n_hk``, ``l10n_ae``),
        for instance to ask for missing data first.

        :return: ``True``, or an action returned by an override.
        """
        payslips = self.filtered(lambda slip: slip.state == 'draft')
        # delete old payslip lines
        payslips.line_ids.unlink()
        # this guarantees consistent results
        self.env.flush_all()
        today = fields.Date.context_today(self)
        for payslip in payslips:
            payslip.write({
                'state': 'draft',
                'compute_date': today
            })

        refund_payslips = payslips.filtered('is_refund_payslip')
        for payslip in refund_payslips:
            payslip.line_ids = payslip.origin_payslip_id.line_ids.copy()
            for line in payslip.line_ids:
                line.amount = -line.amount
                line.total = -line.total

        payslips -= refund_payslips

        sorted_lists = [
            sorted(v, key=lambda p: (p.version_id.date_version, p.date_from))
            for v in payslips.grouped('employee_id').values()
        ]
        for batch_tuple in zip_longest(*sorted_lists):
            batch = self.env['hr.payslip'].union(p for p in batch_tuple if p)
            self.env['hr.payslip.line'].create(batch._get_payslip_lines())

        self._compute_worked_days_ytd()
        return True

    def action_refresh_from_work_entries(self):
        """Regenerate the worked days and recompute the lines of the draft payslips.

        To be used after a change of the time off, attendances or version of the period. Manually
        edited payslips (``edited``) are skipped.
        """
        # Refresh the whole payslip in case the HR has modified some work entries
        # after the payslip generation
        if any(p.state != 'draft' for p in self):
            raise UserError(_('The payslips should be in Draft or Waiting state.'))
        payslips = self.filtered(lambda p: not p.edited)
        payslips.mapped('worked_days_line_ids').unlink()
        payslips.mapped('line_ids').unlink()
        payslips._compute_worked_days_line_ids()
        payslips.compute_sheet()

    def action_move_to_off_cycle(self):
        """Detach the payslips from their pay run and remove their versions from it; the pay runs left empty are deleted.

        :return: the pay runs action if a pay run was deleted, else a ``soft_reload`` client action.
        """
        # once detached, an emptied pay run would be refilled with all the valid versions
        emptied_payruns = self.payslip_run_id.filtered(
            lambda payrun: payrun.slip_ids <= self and payrun.version_ids <= self.version_id
        )
        for slip in self:
            payrun = slip.payslip_run_id
            if payrun:
                payrun.off_cycle_version(slip.version_id.id)
        if emptied_payruns:
            emptied_payruns.unlink()
            # the deleted pay run cannot be reloaded
            return self.env['ir.actions.act_window']._for_xml_id('hr_payroll.action_hr_payslip_run') | {'target': 'main'}
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def _round_days(self, work_entry_type, days):
        """Round a number of days according to the work entry type.

        Types requested by ``day`` or ``half_day`` are rounded to 1 or 0.5 with the type
        ``round_days_type`` method (``'HALF-UP'``, ``'UP'``, ``'DOWN'``); ``hour`` types are not
        rounded.

        :param hr.work.entry.type work_entry_type: type of the worked days line.
        :param float days: number of days to round.
        :rtype: float
        """
        if work_entry_type.request_unit != 'hour':
            precision_rounding = 0.5 if work_entry_type.request_unit == "half_day" else 1
            day_rounded = float_round(days, precision_rounding=precision_rounding, rounding_method=work_entry_type.round_days_type)
            return day_rounded
        return days

    @api.model
    def _get_attachment_rules(self):
        """Return the rules that can be used as salary attachment (``input_usage_payslip``).

        :return: ``{rule_code: hr.salary.rule}``.
        :rtype: dict
        """
        rules = self.env['hr.salary.rule'].search([('input_usage_payslip', '=', True)])
        return {rule.code: rule for rule in rules}

    def _get_worked_day_lines_hours_per_day(self, version):
        """Return the hours per day used to convert hours into days in the worked days lines.

        Defaults to the version calendar ``hours_per_day``. Overridden by ``l10n_be_hr_payroll``.

        :param hr.version version: version of the worked days.
        :rtype: float
        """
        return version.resource_calendar_id.hours_per_day

    def _get_worked_day_lines_hours_per_week(self, version):
        """Return the weekly hours of the version calendar (or of the employee calendars if flexible).

        :param hr.version version: version of the worked days.
        :rtype: float
        """
        self.ensure_one()
        if version.sudo()._is_flexible():
            return version.employee_id._get_calendars()[version.employee_id.id].hours_per_week
        return version.resource_calendar_id.hours_per_week

    def _get_out_of_contract_calendar(self, version):
        """Return the calendar used to count the out-of-contract time of the period.

        The version calendar, or for flexible versions the employee calendar, or the company calendar.
        Overridden by ``l10n_be_hr_payroll``.

        :param hr.version version: version not covering the whole period.
        :rtype: resource.calendar
        """
        self.ensure_one()
        if not version.sudo()._is_flexible():
            return version.resource_calendar_id
        employee = version.employee_id
        if not employee.sudo()._is_flexible():
            return employee.resource_calendar_id
        return version.company_id.resource_calendar_id

    def _get_worked_day_lines_values(self, version, work_entries_vals):
        """Return the worked days values of one version, from its generated work entries.

        The work entry durations of the payslip period are summed by (work entry type, category
        options) with ``version.get_work_hours()``, then converted into days with
        :meth:`_get_worked_day_lines_hours_per_day` and rounded with :meth:`_round_days`. The
        rounding difference is carried over to the type with the most hours. The time-rule-trimmed
        part of the hours (``trimmed_duration``) is never rounded. Overridden by
        ``l10n_be_hr_payroll``, ``l10n_hk_hr_payroll`` and ``l10n_ph_hr_payroll``.

        :param hr.version version: the version.
        :param list[dict] work_entries_vals: work entry values generated by
            ``hr.version.generate_work_entries()`` (keys ``date``, ``duration``,
            ``work_entry_type_id``, ``version_id``, optionally ``category_options_ids`` and
            ``trimmed_duration``).
        :return: list of ``hr.payslip.worked_days`` values, sorted by work entry type
            sequence::

                {
                    'version_id': int,
                    'sequence': int,
                    'work_entry_type_id': int,
                    'number_of_days': float,
                    'number_of_hours': float,
                    'category_options_ids': hr.salary.rule.category,
                }

        :rtype: list[dict]
        """
        self.ensure_one()
        res = []
        hours_per_day = self._get_worked_day_lines_hours_per_day(version)
        work_hours = version.get_work_hours(self.date_from, self.date_to, work_entries_vals)
        work_hours_ordered = sorted(work_hours.items(), key=lambda x: x[1])
        biggest_work = work_hours_ordered[-1][0] if work_hours_ordered else 0
        add_days_rounding = 0
        # trimmed_duration is tagged pre-merge by _enrich_work_entry_val
        # and summed during merge, it isolates the time-rule-split portion.
        # _round_days is applied only to normal_hours; trimmed_hours keep their exact fraction.
        trimmed_hours_by_wet = defaultdict(float)
        empty_cat = self.env['hr.salary.rule.category']
        for vals in work_entries_vals:
            td = vals.get('trimmed_duration', 0.0)
            if td and self.date_from <= vals.get('date', self.date_from) <= self.date_to:
                # key must match _get_work_hours: (wet_record, sorted category recordset)
                cat = vals.get('category_options_ids', empty_cat).sorted()
                trimmed_hours_by_wet[vals['work_entry_type_id'], cat] += td
        for work_entry_type_with_options, hours in work_hours_ordered:
            work_entry_type, category_options = work_entry_type_with_options
            trimmed_hours = trimmed_hours_by_wet.get(work_entry_type_with_options, 0.0)
            normal_hours = hours - trimmed_hours
            normal_days = round(normal_hours / hours_per_day, 5) if hours_per_day else 0
            trimmed_days = round(trimmed_hours / hours_per_day, 5) if hours_per_day else 0
            if work_entry_type_with_options == biggest_work:
                normal_days += add_days_rounding
            normal_day_rounded = self._round_days(work_entry_type, normal_days)
            add_days_rounding += (normal_days - normal_day_rounded)
            day_rounded = normal_day_rounded + trimmed_days
            attendance_line = {
                'version_id': version.id,
                'sequence': work_entry_type.sequence,
                'work_entry_type_id': work_entry_type.id,
                'number_of_days': day_rounded,
                'number_of_hours': hours,
                'category_options_ids': category_options,
            }
            res.append(attendance_line)

        # Sort by Work Entry Type sequence
        work_entry_type = self.env['hr.work.entry.type']
        return sorted(res, key=lambda d: work_entry_type.browse(d['work_entry_type_id']).sequence)

    def _get_out_of_period_duration(self, start, stop, reference_calendar):
        """Return the working time of the calendar between two datetimes, used for the out-of-contract line.

        Only attendances counted as working time are taken into account, without time off.
        Overridden by ``l10n_be_hr_payroll`` and ``l10n_mx_hr_payroll``.

        :param datetime start: start of the out-of-contract period.
        :param datetime stop: end of the out-of-contract period.
        :param resource.calendar reference_calendar: see :meth:`_get_out_of_contract_calendar`.
        :return: ``{'days': float, 'hours': float}``.
        :rtype: dict
        """
        return reference_calendar.get_work_duration_data(start, stop, compute_leaves=False,
            domain=['|', ('work_entry_type_id', '=', False), ('work_entry_type_id.count_as', '=', 'working_time')])

    def _get_worked_day_lines(self, versions, work_entries_vals, check_out_of_version=True):
        """Return the worked days values of the payslip for all its versions.

        For each version (sorted by ``date_version``), the values of
        :meth:`_get_worked_day_lines_values` are added. With ``check_out_of_version``, the parts of
        the period before the contract start (first version) or after the contract end (last
        version), or the whole period if the version has no contract, are added as an
        out-of-contract line: work entry type with code ``000.00`` of the structure country, or
        ``hr_work_entry.generic_hr_work_entry_type_out_of_contract``. Its amount is 0, so the wage
        is prorated. Overridden by ``l10n_hk_hr_payroll``.

        :param hr.version versions: the versions of the payslip (same contract).
        :param list[dict] work_entries_vals: generated work entry values of these versions.
        :param bool check_out_of_version: whether to add the out-of-contract lines.
        :return: list of worked days values, see :meth:`_get_worked_day_lines_values` (the
            out-of-contract line has no ``category_options_ids``).
        :rtype: list[dict]
        """
        res = []
        self.ensure_one()
        sorted_versions = versions.sorted('date_version')
        for version in sorted_versions:
            res += self._get_worked_day_lines_values(version=version, work_entries_vals=work_entries_vals)

            if check_out_of_version:
                # We could have multiple versions per payslip if they have the same contract dates
                # We have to check if the contract starts after the date_from or if contract ends before date_to
                # If the version doesn't cover the whole month, create
                # worked_days lines to adapt the wage accordingly
                out_days, out_hours = 0, 0
                reference_calendar = self._get_out_of_contract_calendar(version=version)
                out_periods = []
                if not version.contract_date_start:
                    start = fields.Datetime.to_datetime(self.date_from)
                    stop = fields.Datetime.to_datetime(self.date_to) + relativedelta(hour=23, minute=59)
                    out_periods.append((start, stop))
                else:
                    if version.date_start and self.date_from < version.date_start and version == sorted_versions[0]:
                        start = fields.Datetime.to_datetime(self.date_from)
                        stop = min(fields.Datetime.to_datetime(version.date_start) + relativedelta(days=-1, hour=23, minute=59),
                            fields.Datetime.to_datetime(self.date_to) + relativedelta(hour=23, minute=59))
                        out_periods.append((start, stop))
                    if version.date_end and version.date_end < self.date_to and version == sorted_versions[-1]:
                        start = max(fields.Datetime.to_datetime(version.date_end) + relativedelta(days=1),
                            fields.Datetime.to_datetime(self.date_from))
                        stop = fields.Datetime.to_datetime(self.date_to) + relativedelta(hour=23, minute=59)
                        out_periods.append((start, stop))

                for out_period in out_periods:
                    start, stop = out_period
                    out_time = self._get_out_of_period_duration(start, stop, reference_calendar)
                    out_days += out_time['days']
                    out_hours += out_time['hours']

                out_work_entry_type = self.env['hr.work.entry.type'].search([
                    ('code', '=', '000.00'),
                    ('country_id', '=', self.struct_id.country_id.id)
                ]) or self.env.ref('hr_work_entry.generic_hr_work_entry_type_out_of_contract', raise_if_not_found=False)
                if out_work_entry_type and (out_days or out_hours):
                    res.append({
                        'version_id': version.id,
                        'sequence': out_work_entry_type.sequence,
                        'work_entry_type_id': out_work_entry_type.id,
                        'number_of_days': out_days,
                        'number_of_hours': out_hours,
                    })
        return res

    @property
    def is_outside_contract(self):
        """Whether the version contract does not cover the payslip period at all (always ``False`` in salary simulations)."""
        self.ensure_one()
        if self.env.context.get('salary_simulation'):
            return False
        return self._is_outside_contract_dates()

    def _rule_parameter(self, code, reference_date=False, raise_if_not_found=True):
        """Return the value of the rule parameter ``code`` valid at the reference date.

        Main way for salary rules to read legal values (rates, ceilings, scales), e.g.
        ``payslip._rule_parameter('cct90_employer_onss_threshold')``.

        :param str code: ``hr.rule.parameter`` code.
        :param date reference_date: defaults to :meth:`_get_ytd_reference_date` (``date_to``).
        :param bool raise_if_not_found: raise a ``UserError`` if no value exists, otherwise
            return ``None``.
        :return: the evaluated parameter value (any python literal: number, dict, list, ...), a
            deep copy of the cached value.
        """
        self.ensure_one()
        if not reference_date:
            reference_date = self._get_ytd_reference_date()
        return self.env['hr.rule.parameter']._get_parameter_from_code(code, reference_date, raise_if_not_found)

    def _sum(self, code, from_date, to_date=None):
        """Return the sum of the line totals with the given rule code of the employee's validated or paid payslips in a date range.

        Only payslips fully included in ``[from_date, to_date]`` are taken into account. The
        current payslip is not included unless validated.

        :param str code: rule code.
        :param date from_date: minimum ``date_from`` of the payslips.
        :param date to_date: maximum ``date_to`` of the payslips, defaults to today.
        :rtype: float
        """
        if to_date is None:
            to_date = fields.Date.context_today(self)
        self.env.cr.execute("""
            SELECT sum(pl.total)
            FROM hr_payslip as hp, hr_payslip_line as pl
            WHERE hp.employee_id = %s
            AND hp.state in ('validated', 'paid')
            AND hp.date_from >= %s
            AND hp.date_to <= %s
            AND hp.id = pl.slip_id
            AND pl.code = %s""", (self.employee_id.id, from_date, to_date, code))
        res = self.env.cr.fetchone()
        return res and res[0] or 0.0

    @api.ormcache('code')
    def _get_child_category_ids(self, code):
        """Return the codes of the salary rule category ``code`` and all its descendants (cached).

        :rtype: tuple[str]
        """
        root_category = self.env['hr.salary.rule.category'].search([('code', '=', code)], limit=1)
        if not root_category:
            return tuple()
        return tuple(self.env['hr.salary.rule.category'].search([('id', 'child_of', root_category.id)]).mapped('code'))

    def _sum_category(self, code, from_date, to_date=None, include_children=False):
        """Return the sum of the line totals of a category on the validated or paid payslips of the employees of ``self``.

        Only payslips fully included in ``[from_date, to_date]`` are taken into account.

        :param str code: salary rule category code.
        :param date from_date: minimum ``date_from`` of the payslips.
        :param date to_date: maximum ``date_to`` of the payslips, today by default.
        :param bool include_children: also sum the descendant categories. A line whose rule
            has several matching categories is counted once.
        :rtype: float
        """
        if to_date is None:
            to_date = fields.Date.context_today(self)
        if not self.ids:
            return 0.0

        self.env['hr.payslip'].flush_model(['employee_id', 'state', 'date_from', 'date_to'])
        self.env['hr.payslip.line'].flush_model(['total', 'slip_id', 'salary_rule_id'])
        self.env['hr.salary.rule.category'].flush_model(['code'])
        self.env['hr.salary.rule'].flush_model(['category_ids'])
        category_codes = self._get_child_category_ids(code) if include_children else (code,)
        employee_ids = tuple(self.mapped('employee_id').ids)
        if not category_codes or not employee_ids:
            return 0.0

        # A line is counted once, even if several categories of its rule match.
        self.env.cr.execute("""
            SELECT sum(pl.total)
            FROM hr_payslip as hp,
                 hr_payslip_line as pl
            WHERE hp.employee_id IN %s
              AND hp.state in ('validated', 'paid')
              AND hp.date_from >= %s
              AND hp.date_to <= %s
              AND hp.id = pl.slip_id
              AND EXISTS (
                  SELECT 1
                  FROM hr_salary_rule_hr_salary_rule_category_rel as rel,
                       hr_salary_rule_category as rc
                  WHERE rel.hr_salary_rule_id = pl.salary_rule_id
                    AND rc.id = rel.hr_salary_rule_category_id
                    AND rc.code IN %s
              )""", (tuple(employee_ids), from_date, to_date, tuple(category_codes)))

        res = self.env.cr.fetchone()
        return res and res[0] or 0.0

    def _sum_worked_days(self, code, from_date, to_date=None):
        """Return the sum of the worked days amounts of a work entry type on the employee's validated or paid payslips.

        :param str code: work entry type code.
        :param date from_date: minimum ``date_from`` of the payslips.
        :param date to_date: maximum ``date_to`` of the payslips, defaults to today.
        :rtype: float
        """
        self.ensure_one()
        if to_date is None:
            to_date = fields.Date.context_today(self)

        query = """
            SELECT sum(hwd.amount)
            FROM hr_payslip hp, hr_payslip_worked_days hwd, hr_work_entry_type hwet
            WHERE hp.state in ('validated', 'paid')
            AND hp.id = hwd.payslip_id
            AND hwet.id = hwd.work_entry_type_id
            AND hp.employee_id = %(employee)s
            AND hp.date_to <= %(stop)s
            AND hwet.code = %(code)s
            AND hp.date_from >= %(start)s"""

        self.env.cr.execute(query, {
            'employee': self.employee_id.id,
            'code': code,
            'start': from_date,
            'stop': to_date})
        res = self.env.cr.fetchone()
        return res[0] if res else 0.0

    def _get_base_local_dict(self):
        """Return the helpers available in the salary rules code, merged first in :meth:`_get_localdict`.

        Base keys: ``float_round``, ``float_compare``, ``relativedelta``, ``ceil``, ``floor``,
        ``UserError``, ``date``, ``datetime``, ``defaultdict`` and ``_get_payroll_translation``.
        Override to expose more helpers (e.g. ``l10n_in_hr_payroll`` adds ``_``,
        ``l10n_mx_hr_payroll``, ``l10n_au_hr_payroll``, ``l10n_ch_hr_payroll``,
        ``l10n_hk_hr_payroll`` add their own).

        :rtype: dict
        """
        return {
            'float_round': float_round,
            'float_compare': float_compare,
            'relativedelta': safe_eval_dateutil.relativedelta.relativedelta,
            'ceil': math.ceil,
            'floor': math.floor,
            'UserError': UserError,
            'date': safe_eval_datetime.date,
            'datetime': safe_eval_datetime.datetime,
            'defaultdict': defaultdict,
            '_get_payroll_translation': self._get_payroll_translation,
        }

    def _get_category_options_data(self, work_entries=None):
        """Return the hours of the worked days lines by category option code.

        A category option implies its ancestors: hours carrying a child option (e.g. a custom
        premium pay) are also credited to each parent category code, once per worked days line.
        Exposed as ``category_options`` in the rules, e.g. ``category_options['PREMIUM_PAY_NIGHT']``.
        Overridden by ``l10n_be_hr_payroll``.

        :param list work_entries: work entry values carrying category options (unused by the
            base implementation).
        :return: mapping category code to total hours, 0 for missing keys.
        :rtype: DefaultDictPayroll
        """
        self.ensure_one()
        category_options = DefaultDictPayroll(lambda: 0)
        if not self.ignore_worked_day_lines:
            for worked_day_line in self.worked_days_line_ids:
                for code in worked_day_line.category_options_ids._get_codes_with_ancestors():
                    category_options[code] += worked_day_line.number_of_hours
        return category_options

    def _get_premium_pay_additional_amount(self, category_code):
        """Compute the extra amount granted by the custom premium pays of the worked days, on top of the legal rate.

        Custom premium pays are descendant categories of ``category_code`` with a
        ``premium_amount_per_hour``, ``premium_amount_per_day`` or ``premium_percentage_hourly_rate``.
        The percentage is based on the hourly rate of each worked day line itself: percentage / 100
        x (amount / hours) x hours, which simplifies to percentage / 100 x amount.

        :param str category_code: code of the legal premium pay category (e.g. ``'PREMIUM_PAY_NIGHT'``).
        :rtype: float
        """
        self.ensure_one()
        if self.ignore_worked_day_lines:
            return 0
        total = 0
        for worked_day_line in self.worked_days_line_ids:
            for option in worked_day_line.category_options_ids:
                if not (option.premium_amount_per_hour or option.premium_amount_per_day or option.premium_percentage_hourly_rate):
                    continue
                parent = option.parent_id
                while parent and parent.code != category_code:
                    parent = parent.parent_id
                if not parent:
                    continue
                total += option.premium_amount_per_hour * worked_day_line.number_of_hours \
                    + option.premium_amount_per_day * worked_day_line.number_of_days \
                    + option.premium_percentage_hourly_rate / 100 * worked_day_line.amount
        return total

    def _get_localdict(self, work_entries=None):
        """Return the evaluation context of the salary rules of the payslip.

        Override to add keys (e.g. ``l10n_vn_hr_payroll`` adds ``l10n_vn_gross_up``,
        ``l10n_id_hr_payroll``, ``l10n_ph_hr_payroll``). Keys:

        * the helpers of :meth:`_get_base_local_dict`;
        * ``payslip`` (``hr.payslip``), ``employee`` (``hr.employee``), ``version``
          (``hr.version``), ``company`` (``res.company``), ``payroll_config``
          (``payroll.config.settings``);
        * ``categories``: ``DefaultDictPayroll`` ``{category_code: float}``, missing codes are 0.
          Initialized with the worked days amounts by category of their work entry type (with
          the ancestors, each code credited once per worked days line), then increased by each
          computed rule total (each code once per rule, see
          ``hr.salary.rule.category._sum_salary_rule_category``), e.g. ``categories['GROSS']``;
        * ``category_options``: see :meth:`_get_category_options_data`;
        * ``rules``: legacy ``DefaultDictPayroll``, never filled; use ``result_rules``;
        * ``result_rules``: ``DefaultDictPayroll`` ``{rule_code: {'total', 'amount', 'quantity',
          'rate', 'ytd'}}`` of the rules computed so far, e.g. ``result_rules['GROSS']['total']``;
        * ``worked_days``: plain ``dict`` ``{work_entry_type_code: hr.payslip.worked_days}``.
          A code may have several lines (several versions or category options): prefer
          ``sum(worked_days['WORK100'].mapped('number_of_days'))`` to
          ``worked_days['WORK100'].number_of_days``. Missing codes raise ``KeyError``;
        * ``inputs``: plain ``dict`` ``{rule_code: hr.payslip.input}``, e.g.
          ``inputs['DEDUCTION'].amount``. Several inputs with the same code are aggregated
          (summed ``amount``). Missing codes raise ``KeyError``, use ``inputs.get(code)``;
        * ``same_type_input_lines``: ``{rule_code: hr.payslip.input}`` of the codes having
          several input lines (the rule is then computed once per input line). Missing codes
          return an empty recordset;
        * ``work_entries``: work entry values of the period and of the worked days versions.

        :meth:`_get_payslip_lines` adds the keys of :meth:`_get_common_localdict` and
        :meth:`_get_round_common_localdict`, and the rule outputs.

        :param list[dict] work_entries: work entry values generated for the payslip versions.
        :rtype: dict
        """
        self.ensure_one()
        # Check for multiple inputs of the same type and keep a copy of
        # them because otherwise they are lost when building the dict
        same_type_input_lines = defaultdict(lambda: self.env['hr.payslip.input'])
        input_line_ids_by_code = self.input_line_ids.grouped('code')
        for code, input_lines in input_line_ids_by_code.items():
            if len(input_lines) > 1:
                same_type_input_lines[code] = input_lines

        if work_entries is None:
            work_entries = []
        worked_days_version_ids = set(self.worked_days_line_ids.version_id.ids)
        work_entries = [
            vals for vals in work_entries
            if vals['version_id'].id in worked_days_version_ids
            and self.date_from <= vals['date'] <= self.date_to
        ]

        categories = DefaultDictPayroll(lambda: 0)
        if not self.ignore_worked_day_lines:
            for worked_day_line in self.worked_days_line_ids:
                for code in worked_day_line.work_entry_type_id.category_ids._get_codes_with_ancestors():
                    categories[code] += worked_day_line.amount

        localdict = {
            **self._get_base_local_dict(),
            **{
                'categories': categories,
                'category_options': self._get_category_options_data([we for we in work_entries if 'category_options_ids' in we]),
                'rules': DefaultDictPayroll(lambda: dict(total=0, amount=0, quantity=0)),
                'payslip': self,
                'worked_days': dict(self.worked_days_line_ids.filtered('code').grouped('code')),
                'inputs': {line.code: line for line in self.input_line_ids if line.code},
                'employee': self.employee_id,
                'version': self.version_id,
                'company': self.company_id,
                'payroll_config': self.payroll_config_id,
                'result_rules': DefaultDictPayroll(lambda: dict(total=0, amount=0, quantity=0, rate=0, ytd=0)),
                'same_type_input_lines': same_type_input_lines,
                'work_entries': work_entries,
            }
        }
        for code, input_lines in same_type_input_lines.items():
            input_line_ids = input_lines.ids
            localdict['inputs'][code] = self.__get_aggregator_hr_payslip_input_model()(
                env=self.env, ids=input_line_ids, prefetch_ids=input_line_ids,
            )
        return localdict

    def _get_common_localdict(self):
        """Return the values shared by the localdicts of all the payslips computed together.

        Hook to fetch data once per batch instead of once per payslip (overridden by
        ``l10n_be_hr_payroll``). The base implementation returns ``global_line_values``:
        ``{rule_code: {payslip_id or 'sum': {'amount', 'quantity', 'total'}}}``, filled during the
        computation. :meth:`_get_payslip_lines` also adds ``localdicts`` (``{payslip_id: localdict}``)
        to the common dict, but does not copy it into the localdicts.

        :rtype: dict
        """
        vals_list = ['amount', 'quantity', 'total']
        return {
            'global_line_values': defaultdict(lambda: defaultdict(lambda: dict.fromkeys(vals_list, 0.0)))
        }

    def _get_round_common_localdict(self, round_nb, common_localdict):
        """Return values to add to the localdicts before computing a round of rules.

        Rules are computed by ``round_of_computation`` (all payslips of a structure for round 1,
        then round 2, ...). Override to compute values needing the results of the previous round
        for all the payslips, e.g. ``l10n_be_hr_payroll`` computes withholding tax exemptions
        shared between payslips in rounds 2 and 3.

        :param int round_nb: the ``round_of_computation`` about to be computed.
        :param dict common_localdict: see :meth:`_get_common_localdict`, with ``localdicts``.
        :rtype: dict
        """
        return {}

    def _get_payslip_line_total(self, amount, quantity, rate, rule):
        """Return the total of a payslip line: ``amount * quantity * rate / 100``.

        Override to round the totals (``l10n_be_hr_payroll`` rounds to the cent,
        ``l10n_ch_hr_payroll`` to 5 cents for some rules).

        :param float amount: rule amount (``result``).
        :param float quantity: rule quantity (``result_qty``).
        :param float rate: rule rate in percent (``result_rate``).
        :param hr.salary.rule rule: the computed rule.
        :rtype: float
        """
        self.ensure_one()
        return amount * quantity * rate / 100.0

    def _get_ytd_reference_date(self):
        """ Return the date used to calculate this payslip.
        Defaults to the closing date of the pay period.
        """
        self.ensure_one()
        return self.date_to

    def _get_ytd_date_field(self):
        """ Return the name of the field to pre-filter candidate payslips in SQL.
        It should stay consistent with the field `_get_ytd_reference_date` returns.
        """
        return 'date_to'

    def _get_last_ytd_payslips(self):
        """Return the last validated or paid payslip of the same employee and structure since the last YTD reset.

        The YTD reset date is given by the company (``get_last_ytd_reset_date``), the dates are
        compared with :meth:`_get_ytd_reference_date`.

        :return: ``defaultdict`` ``{payslip: hr.payslip}``, empty recordset if none.
        """
        last_ytd_payslips = defaultdict(lambda: self.env['hr.payslip'])
        if not self:
            return last_ytd_payslips

        ytd_reference_dates = {payslip: payslip._get_ytd_reference_date() for payslip in self}
        earliest_reference_date = min(ytd_reference_dates.values())
        earliest_ytd_reset_date = min(
            company.get_last_ytd_reset_date(earliest_reference_date) for company in self.company_id
        )
        date_field = self._get_ytd_date_field()
        ytd_payslips_grouped = self.env['hr.payslip']._read_group(
            domain=[
                ('employee_id', 'in', self.employee_id.ids),
                ('struct_id', 'in', self.struct_id.ids),
                (date_field, '>=', earliest_ytd_reset_date),
                (date_field, '<=', max(ytd_reference_dates.values())),
                ('state', 'in', ['validated', 'paid']),
            ],
            groupby=['employee_id', 'struct_id'],
            aggregates=['id:recordset']
        )

        ytd_payslips_sorted = defaultdict(lambda: self.env['hr.payslip'])
        for employee_id, struct_id, payslips in ytd_payslips_grouped:
            ytd_payslips_sorted[(employee_id, struct_id)] = payslips.sorted(
                key=lambda p: p._get_ytd_reference_date(), reverse=True
            )

        for payslip in self:
            reference_date = ytd_reference_dates[payslip]
            last_payslips = ytd_payslips_sorted[(payslip.employee_id, payslip.struct_id)].filtered(
                lambda p: p._get_ytd_reference_date() <= reference_date
            )
            if last_payslips and last_payslips[0]._get_ytd_reference_date() >=\
                    payslip.company_id.get_last_ytd_reset_date(reference_date):
                last_ytd_payslips[payslip] = last_payslips[0]

        return last_ytd_payslips

    def _get_last_line_ytd_values(self, code_list):
        """Return the YTD of the given codes on these payslips, as :meth:`_get_line_values`.

        A rule computed once per input line (several inputs of its code) gives several lines with
        a cumulative YTD: the YTD of the code is the one of its last line, not their sum.

        :param code_list: codes of the salary rules.
        :return: ``{code: {payslip_id: {'ytd': float}}}``, missing values are 0.
        :rtype: defaultdict
        """
        result = defaultdict(lambda: defaultdict(lambda: {'ytd': 0.0}))
        if not self or not code_list:
            return result
        last_line_ids = self.env['hr.payslip.line']._read_group(
            [('slip_id', 'in', self.ids), ('code', 'in', list(code_list))],
            ['slip_id', 'code'],
            ['id:max'],
        )
        for line in self.env['hr.payslip.line'].browse(line_id for _slip, _code, line_id in last_line_ids):
            result[line.code][line.slip_id.id]['ytd'] = line.ytd
        return result

    def _get_payslip_line_name(self, localdict, rule, input_line=None):
        """Return the name of the payslip line of ``rule``.

        The ``result_name`` of the rule, else the rule name. The description of the input line
        (e.g. the payslip description of a payslip adjustment) is appended to the rule name as
        "Rule - Description", unless it is the default name of the input (``input_name``, not
        translated) or the rule name, or the rule sets another ``result_name``.

        :param dict localdict: evaluation context of the rule, after its computation.
        :param hr.salary.rule rule: computed rule.
        :param hr.payslip.input input_line: input line read by the rule, if any.
        :rtype: str
        """
        result_name = localdict['result_name']
        # Most input rules only echo the input name in result_name, a different value is a deliberate label
        if (
            input_line and input_line.name
            and input_line.name not in (rule.name, rule.input_name)
            and result_name in (False, input_line.name)
        ):
            return f"{rule.name} - {input_line.name}"
        return result_name or rule.name

    def _get_payslip_lines(self, force_categories_by_code=None):
        """Evaluate the salary rules and return the values of the payslip lines to create.

        Does not write anything. For each structure, the rules are evaluated by
        ``round_of_computation`` then ``sequence``, for all the payslips of ``self``. Each
        payslip has one localdict (see :meth:`_get_localdict`) kept across the rounds. For each
        rule, ``result``, ``result_qty`` (1), ``result_rate`` (100), ``result_name`` and
        ``explanation_info`` are reset; if the condition is satisfied, the rule is computed, the
        total is given by :meth:`_get_payslip_line_total`, then:

        * ``localdict[rule.code]`` is set to the total (rule codes are variables in the next rules);
        * ``result_rules[rule.code]`` and ``global_line_values`` are updated;
        * the total is added to the rule categories (and their ancestors) in ``categories``;
        * the explanation is ``rule.explanation_template.format(**explanation_info)``.

        The YTD of each line is the YTD of the line of the same code in the last YTD payslip (see
        :meth:`_get_last_ytd_payslips`) plus its total. A rule whose code has several input lines
        (``same_type_input_lines``) produces one line per input line. Variables assigned in rule
        code stay in the localdict for the next rules.

        Context keys: ``force_payslip_localdict`` (use this localdict for all payslips),
        ``prevent_payslip_computation_line_ids`` (ids of rules to skip),
        ``force_payslip_line_overrides`` (``{line key: {'name', ...}}`` forced values, see
        :meth:`_recompute_with_forced_lines`). Overridden e.g. by ``l10n_vn_hr_payroll`` (net
        salary gross-up loop) and ``l10n_id_hr_payroll``.

        :param dict force_categories_by_code: ``{category_code: amount}`` forced in ``categories``
            before the computation, to simulate a payslip. Use with caution.
        :return: one dict per line, ready to be passed to ``hr.payslip.line.create()``
            (see ``compute_sheet``)::

                {
                    'sequence': int, 'code': str, 'name': str, 'salary_rule_id': int,
                    'version_id': int, 'employee_id': int, 'slip_id': int,
                    'explanation': str or False,
                    'amount': float, 'quantity': float, 'rate': float, 'total': float, 'ytd': float,
                    'manually_modified': bool,
                }

        :rtype: list[dict]
        """
        # The parameter force_categories_by_code should be used with caution. You should normally never use that parameter.
        # This parameter has been added in the purpose to simulate the result of the payslip by forcing one particular
        # salary rule category with a value. One usage example of that parameter is the withholding tax rule for the company
        # executive in BE in case of non-periodic revenue.

        if not self:
            return []

        if force_categories_by_code is None:
            force_categories_by_code = {}

        line_vals = []

        last_ytd_payslips = self._get_last_ytd_payslips()
        code_set = set(self.struct_id.rule_ids.mapped('code'))

        ytd_payslips = reduce(
            lambda ytd_payslips, payslip: ytd_payslips | payslip, last_ytd_payslips.values(),
            self.env['hr.payslip']
        )

        line_values = ytd_payslips._get_last_line_ytd_values(code_set)

        work_entries_vals = self.worked_days_line_ids.version_id.generate_work_entries(
            min(self.mapped('date_from')), max(self.mapped('date_to')))

        work_entries_vals_by_version_id = defaultdict(list)
        for vals in work_entries_vals:
            work_entries_vals_by_version_id[vals['version_id'].id].append(vals)

        localdicts = {}
        results = {}
        common_localdict = self._get_common_localdict()
        common_localdict['localdicts'] = localdicts
        for struct, payslips in self.grouped('struct_id').items():
            for round_of_computation, rules in sorted(struct.rule_ids.grouped('round_of_computation').items(), key=lambda x: x[0]):

                round_common_localdict = payslips._get_round_common_localdict(round_of_computation, common_localdict)

                for payslip in payslips:
                    if payslip.id not in localdicts:
                        if not (localdict := self.env.context.get('force_payslip_localdict')):
                            payslip_work_entries_vals = [
                                vals
                                for version in payslip.worked_days_line_ids.version_id
                                for vals in work_entries_vals_by_version_id[version.id]
                            ]
                            localdict = payslip._get_localdict(payslip_work_entries_vals)
                            # Including the batch registry creates localdict -> localdicts -> localdict,
                            # forcing safe_eval's runtime call validation to use its slower cycle-aware traversal.
                            localdict.update({key: value for key, value in common_localdict.items() if key != 'localdicts'})
                        for category_code, amount in force_categories_by_code.items():
                            localdict['categories'][category_code] = amount
                        localdicts[payslip.id] = localdict

                    localdict = localdicts[payslip.id]
                    localdict.update(**round_common_localdict)

                    result_rules_dict = localdict['result_rules']
                    global_line_values_dict = localdict['global_line_values']
                    blacklisted_rule_ids = self.env.context.get('prevent_payslip_computation_line_ids', [])
                    manual_overrides = self.env.context.get('force_payslip_line_overrides', {})

                    for rule in sorted(rules, key=lambda x: x.sequence):
                        if rule.id in blacklisted_rule_ids:
                            continue
                        result_rules_dict[rule.code]['ytd'] = line_values[rule.code][last_ytd_payslips[payslip].id]['ytd']

                    if payslip.id not in results:
                        results[payslip.id] = {}
                    result = results[payslip.id]

                    for rule in sorted(rules, key=lambda x: x.sequence):
                        if rule.id in blacklisted_rule_ids:
                            continue
                        localdict.update({
                            'result': None,
                            'result_qty': 1.0,
                            'result_rate': 100,
                            'result_name': False,
                            'explanation_info': {},
                        })
                        explanation = False
                        if rule._satisfy_condition(localdict):
                            if localdict['same_type_input_lines'].get(rule.code):
                                for rank, multi_line_rule in enumerate(localdict['same_type_input_lines'][rule.code]):
                                    localdict['inputs'][rule.code] = multi_line_rule
                                    localdict['result_name'] = False
                                    explanation = False
                                    forced = manual_overrides.get(payslip._get_line_override_key(rule.code, rank), {})
                                    amount_forced = 'amount' in forced
                                    if amount_forced:
                                        amount, qty, rate = forced['amount'], forced['quantity'], forced['rate']
                                        explanation = forced.get('explanation', False)
                                    else:
                                        amount, qty, rate, explanation_info = rule._compute_rule(localdict)
                                    tot_rule = payslip._get_payslip_line_total(amount, qty, rate, rule)
                                    ytd = result_rules_dict[rule.code]['ytd'] + tot_rule

                                    dicts_to_update = [
                                        result_rules_dict[rule.code],
                                        global_line_values_dict[rule.code][payslip.id],
                                        global_line_values_dict[rule.code]['sum'],
                                    ]

                                    for dict_to_update in dicts_to_update:
                                        dict_to_update['total'] += tot_rule
                                        dict_to_update['amount'] += tot_rule
                                        dict_to_update['quantity'] = 1
                                        dict_to_update['rate'] = 100
                                        dict_to_update['ytd'] = ytd

                                    localdict = rule.category_ids._sum_salary_rule_category(
                                        localdict, tot_rule)
                                    if rule.explanation_template and not amount_forced:
                                        try:
                                            explanation_info = explanation_info or {}
                                            explanation = rule.with_context(lang=self.env.user.lang).explanation_template.format(**explanation_info)
                                        except (KeyError, ValueError, IndexError):
                                            explanation = self.env._("Explanation couldn't be computed due to a syntax issue")
                                    line_vals.append({
                                        'sequence': rule.sequence,
                                        'code': rule.code,
                                        'name': forced.get('name') or payslip._get_payslip_line_name(localdict, rule, multi_line_rule),
                                        'salary_rule_id': rule.id,
                                        'version_id': localdict['version'].id,
                                        'employee_id': localdict['employee'].id,
                                        'explanation': explanation,
                                        'amount': amount,
                                        'quantity': qty,
                                        'rate': rate,
                                        'total': tot_rule,
                                        'slip_id': payslip.id,
                                        'ytd': ytd,
                                        'manually_modified': forced.get('manually_modified', False),
                                    })
                                input_line_ids = localdict['same_type_input_lines'][rule.code].ids
                                localdict['inputs'][rule.code] = self.__get_aggregator_hr_payslip_input_model()(
                                    env=self.env, ids=input_line_ids, prefetch_ids=input_line_ids,
                                )
                            else:
                                manually_modified = False
                                amount_forced = False
                                if manual_overrides and rule.code in manual_overrides:
                                    forced = manual_overrides[rule.code]
                                    override_name = forced['name']
                                    if 'amount' in forced:
                                        amount, qty, rate = forced['amount'], forced['quantity'], forced['rate']
                                        manually_modified = forced.get('manually_modified', False)
                                        explanation = forced.get('explanation', False)
                                        amount_forced = True
                                    else:
                                        amount, qty, rate, explanation_info = rule._compute_rule(localdict)
                                else:
                                    override_name = False
                                    amount, qty, rate, explanation_info = rule._compute_rule(localdict)
                                # check if there is already a rule computed with that code
                                previous_amount = localdict.get(rule.code, 0.0)
                                # set/overwrite the amount computed for this rule in the localdict
                                tot_rule = payslip._get_payslip_line_total(amount, qty, rate, rule)
                                ytd = result_rules_dict[rule.code]['ytd'] + tot_rule
                                localdict[rule.code] = tot_rule
                                result_rules_dict[rule.code] = {
                                    'total': tot_rule, 'amount': amount, 'quantity': qty, 'rate': rate, 'ytd': ytd
                                }

                                global_line_values_dict[rule.code][payslip.id] = {
                                    'total': tot_rule, 'amount': amount, 'quantity': qty, 'rate': rate, 'ytd': ytd
                                }

                                global_line_values_dict[rule.code]['sum']['total'] += tot_rule
                                global_line_values_dict[rule.code]['sum']['amount'] += amount
                                global_line_values_dict[rule.code]['sum']['quantity'] += qty

                                # sum the amount for its salary category
                                if rule.category_ids:
                                    localdict = rule.category_ids._sum_salary_rule_category(localdict, tot_rule - previous_amount)
                                # create/overwrite the rule in the temporary results
                                if rule.explanation_template and not amount_forced:
                                    try:
                                        explanation_info = explanation_info or {}
                                        explanation = rule.with_context(lang=self.env.user.lang).explanation_template.format(**explanation_info)
                                    except (KeyError, ValueError, IndexError):
                                        explanation = self.env._("Explanation couldn't be computed due to a syntax issue")
                                result[rule.code] = {
                                    'sequence': rule.sequence,
                                    'code': rule.code,
                                    'name': override_name or payslip._get_payslip_line_name(localdict, rule, localdict['inputs'].get(rule.code)),
                                    'salary_rule_id': rule.id,
                                    'version_id': localdict['version'].id,
                                    'employee_id': localdict['employee'].id,
                                    'explanation': explanation,
                                    'amount': amount,
                                    'quantity': qty,
                                    'rate': rate,
                                    'total': tot_rule,
                                    'slip_id': payslip.id,
                                    'ytd': ytd,
                                    'manually_modified': manually_modified,
                                }

        for result in results.values():
            line_vals += list(result.values())
        return line_vals

    def _compute_worked_days_ytd(self):
        """Set the ``ytd`` of the worked days lines: YTD of the same code in the last YTD payslip plus the line amount."""
        last_ytd_payslips = self._get_last_ytd_payslips()
        ytd_payslips = reduce(
            lambda ytd_payslips, payslip: ytd_payslips | payslip, last_ytd_payslips.values(),
            self.env['hr.payslip']
        )

        code_set = set(self.worked_days_line_ids.mapped('code'))
        worked_days_line_values = ytd_payslips._get_worked_days_line_values(code_set, ['ytd'])

        for payslip in self:
            for worked_days in payslip.worked_days_line_ids:
                worked_days.ytd = worked_days_line_values[worked_days.code][
                    last_ytd_payslips[payslip].id
                ]['ytd'] + worked_days.amount

    @api.depends('employee_id')
    def _compute_company_id(self):
        for slip in self.filtered(lambda p: p.employee_id.company_id):
            slip.company_id = slip.employee_id.company_id

    @api.depends('employee_id', 'date_from')
    def _compute_version_id(self):
        """Default the version: the first version of a contract overlapping the period, or the version valid at ``date_from``.

        The period end is estimated from the schedule of the version valid at ``date_from``.
        """
        for slip in self:
            if not slip.employee_id:
                slip.version_id = False
                continue
            version = slip.employee_id._get_version(slip.date_from)
            if slip.date_from:
                # Take the first version in contract during the period (e.g. rehired during the period).
                # date_to depends on the version, so the period is estimated from the version schedule.
                schedule = version.schedule_pay or version.structure_type_id.default_schedule_pay
                date_to = slip.date_from + self._schedule_timedelta(schedule, slip.date_from, slip.country_code)
                version = slip.employee_id._get_versions_with_contract_overlap_with_period(slip.date_from, date_to)[:1] or version
            slip.version_id = version

    @api.depends('company_id', 'date_from')
    def _compute_payroll_config_id(self):
        for slip in self:
            slip.payroll_config_id = slip.company_id._get_payroll_config(slip.date_from)

    @api.depends('version_id')
    def _compute_struct_id(self):
        """Default the structure to the default structure of the version structure type (only when not set)."""
        for slip in self.filtered(lambda p: not p.struct_id):
            slip.struct_id = slip.version_id.structure_type_id.default_struct_id\
                or slip.employee_id.version_id.structure_type_id.default_struct_id

    def _search_country_id(self, operator, value):
        return [('company_id.partner_id.country_id', operator, value)]

    def _get_period_name(self, cache):
        self.ensure_one()
        if self.date_from == self.date_to:
            return self._format_date_cached(cache, self.date_from)
        period_name = '%s - %s' % (
            self._format_date_cached(cache, self.date_from),
            self._format_date_cached(cache, self.date_to))
        if self.is_wrong_duration:
            return period_name

        start_date = self.date_from
        end_date = self.date_to
        lang = self.env.lang
        week_start = self.env["res.lang"]._get_data(code=lang).week_start
        schedule = self.version_id.schedule_pay or self.version_id.structure_type_id.default_schedule_pay
        if schedule == 'monthly':
            period_name = self._format_date_cached(cache, start_date, "MMMM y")
        elif schedule == 'quarterly':
            current_year_quarter = math.ceil(start_date.month / 3)
            period_name = _("Quarter %(quarter)s of %(year)s", quarter=current_year_quarter, year=start_date.year)
        elif schedule == 'semi-annually':
            year_half = start_date.replace(day=1, month=6)
            is_first_half = start_date < year_half
            period_name = _("1st semester of %s", start_date.year)\
                if is_first_half\
                else _("2nd semester of %s", start_date.year)
        elif schedule == 'annually':
            period_name = start_date.year
        elif schedule == 'weekly':
            wk_num = start_date.strftime('%U') if week_start == '7' else start_date.strftime('%W')
            period_name = _('Week %(week_number)s of %(year)s', week_number=wk_num, year=start_date.year)
        elif schedule == 'bi-weekly':
            week = int(start_date.strftime("%U") if week_start == '7' else start_date.strftime("%W"))
            first_week = week - 1 + week % 2
            period_name = _("Weeks %(week)s and %(week1)s of %(year)s",
                week=first_week, week1=first_week + 1, year=start_date.year)
        elif schedule == 'bi-monthly':
            start_date_string = self._format_date_cached(cache, start_date, "MMMM y")
            end_date_string = self._format_date_cached(cache, end_date, "MMMM y")
            period_name = _("%(start_date_string)s and %(end_date_string)s", start_date_string=start_date_string, end_date_string=end_date_string)
        return period_name

    def _format_date_cached(self, cache, date, date_format=False):
        key = (date, date_format, self.env.lang)
        if key not in cache:
            cache[key] = format_date(env=self.env, value=date, date_format=date_format)
        return cache[key]

    @api.depends('employee_id.legal_name', 'struct_id.payslip_name', 'date_from', 'date_to', 'title', 'is_refund_payslip', 'is_correction_payslip', 'origin_payslip_id.name')
    @api.depends_context('lang')
    def _compute_name(self):
        formated_date_cache = {}
        for slip in self:
            if not (slip.employee_id and slip.date_from and slip.date_to):
                slip.name = False
            else:
                payslip_name = slip.title or slip.struct_id.payslip_name or _("Payslip")
                full_name = '%(payslip_name)s - %(employee_name)s - %(dates)s' % {
                    'payslip_name': payslip_name,
                    'employee_name': slip.employee_id.legal_name,
                    'dates': slip._get_period_name(formated_date_cache),
                }
                if slip.is_refund_payslip:
                    origin_name = slip.origin_payslip_id.name if slip.origin_payslip_id else full_name
                    full_name = _("Refund: %(payslip)s", payslip=origin_name)
                elif slip.is_correction_payslip:
                    origin_name = slip.origin_payslip_id.name if slip.origin_payslip_id else full_name
                    full_name = _("Correction: %(payslip)s", payslip=origin_name)
                slip.name = full_name

    @api.model
    def _issues_dependencies(self):
        """Return the fields triggering the recomputation of the payslip issues (see :meth:`_compute_issues`).

        Extend it when a localization adds payroll warnings on payslips depending on other fields.

        :rtype: list[str]
        """
        return [
            'state', 'date_to', 'date_from', 'employee_id',
            'version_id', 'version_id.contract_date_start', 'version_id.contract_date_end', 'version_id.schedule_pay',
            'struct_id', 'version_id.structure_type_id.default_schedule_pay',
            'company_id', 'payslip_run_id.company_id',
            'employee_id.bank_account_ids', 'employee_id.bank_account_ids.allow_out_payment', 'keep_wrong_version',
            'has_wrong_data', 'is_wrong_version', 'is_refunded', 'is_corrected', 'is_refund_payslip',
            'salary_attachment_ids',
            'employee_id.leave_ids.payslip_state', 'employee_id.leave_ids.state',
            'employee_id.leave_ids.date_from', 'employee_id.leave_ids.date_to',
            'employee_id.review_state', 'employee_id.salary_attachment_ids',
            'net_wage', 'ignore_worked_day_lines',
        ]

    def _get_payslips_to_compute_issues(self):
        """Return the payslips whose issues must be computed.

        Draft and validated payslips, and paid payslips with outdated data (version, employee or
        time off changed since validation) that are not refunded, corrected or kept as is.

        :rtype: hr.payslip
        """
        to_compute_payslips = self.filtered(lambda p: p.state in ('draft', 'validated')).with_prefetch()
        paid_payslips_with_wrong_data = self.filtered_domain([
            ("state", "=", "paid"),
            "|", "|", ("has_wrong_data", "=", True), ("is_wrong_version", "=", True), ("has_wrong_leaves", "=", True),
            ("is_refunded", "=", False),
            ("is_corrected", "=", False),
            ("keep_wrong_version", "=", False),
            ("is_refund_payslip", "=", False)]).with_prefetch()
        return to_compute_payslips | paid_payslips_with_wrong_data

    @api.depends(lambda self: self._issues_dependencies())
    def _compute_issues(self):
        """Compute ``issues``, ``error_count`` and ``warning_count`` from the payroll warnings displayed on payslips.

        Each active ``hr.payroll.warning`` with ``display_on_model`` on ``hr.payslip`` is evaluated
        on the payslips of :meth:`_get_payslips_to_compute_issues`. ``issues`` is a JSON dict
        ``{index: {'message': str, 'level': 'danger' or 'warning', 'action_text': str,
        'action': dict}}`` (``action*`` keys only for python warnings giving
        ``warning_details``). ``'danger'`` issues are errors and block the validation.

        Not computed in tests or while the registry is loading, unless the context key
        ``hr_payroll_force_compute_issue`` is set.
        """
        self.error_count = 0
        self.warning_count = 0
        self.issues = {}
        if (
            (not self.env.registry.ready or config["test_enable"] or modules.module.current_test)
            # This context key acts as an escape hatch for upgrade scripts that need to
            # explicitly recompute payroll issues while the registry is still initializing,
            # and for the tests that check the issues.
            and not (self.env.context.get("hr_payroll_force_compute_issue"))
        ):
            return
        payslips_to_check = self._get_payslips_to_compute_issues()

        # Compute issues per slip
        payslip_warnings = self.env["hr.payroll.warning"].search([
            ("display_on_model", "=", True),
            ("model_name", "=", "hr.payslip"),
            ("country_id", "in", payslips_to_check.country_id.ids + [False]),
            ("active", "=", True),
        ])
        warning_result = {}
        for warning in payslip_warnings:
            if warning.warning_type == 'domain':
                warning_result[warning] = (warning._get_warning_domain_records(payslips_to_check.company_id, records_to_check=payslips_to_check), {})
            else:
                records, details, _, _ = warning._get_warning_python_records(localdict={'active_ids': payslips_to_check.ids})
                if records._name != self._name:
                    # Without saved payslips (new payslip form), a warning may answer for the dashboard instead
                    records = self.browse()
                warning_result[warning] = (records, details or {})

        for slip in payslips_to_check:
            payslip_issues = []
            e_count, w_count = 0, 0

            for warning, (related_payslips, details) in warning_result.items():
                if slip in related_payslips:
                    if warning.warning_type == 'domain':
                        issue = warning._get_warning_issue()
                        payslip_issues.append(issue)
                        if issue['level'] == 'danger':
                            e_count += 1
                        else:
                            w_count += 1
                    if warning.warning_type == 'python':
                        if slip in related_payslips:
                            if details:
                                issues = details.get(slip, [])
                            else:
                                issues = [warning._get_warning_issue()]
                            payslip_issues.extend(issues)
                            for issue in issues:
                                if issue['level'] == 'danger':
                                    e_count += 1
                                else:
                                    w_count += 1

            slip.error_count = e_count
            slip.warning_count = w_count
            slip.issues = dict(enumerate(payslip_issues)) if payslip_issues else {}

    def _get_error_message(self):
        """Return the blocking (``'danger'``) issues of the payslips as a bullet list text.

        :rtype: str
        """
        if len(self) == 1:
            return '\n'.join([
                f' • {issue["message"]}'
                for issue in self.issues.values() if issue['level'] == 'danger'
            ])
        return '\n'.join([
            f' • {slip.name}: {issue["message"]}'
            for slip in self
            for issue in (slip.issues or {}).values() if issue['level'] == 'danger'
        ])

    @api.depends('date_from', 'date_to', 'struct_id')
    def _compute_is_wrong_duration(self):
        for slip in self:
            slip.is_wrong_duration = slip.date_to and (
                slip.version_id.schedule_pay
                or slip.version_id.structure_type_id.default_schedule_pay
            ) and (
                slip.date_from + slip._get_schedule_timedelta() != slip.date_to
            )

    @api.depends('employee_id', 'version_id', 'struct_id', 'date_from', 'date_to', 'ignore_worked_day_lines')
    def _compute_worked_days_line_ids(self):
        """Generate the worked days lines of the payslips.

        Only payslips with an employee, dates, a version and a structure using worked days (and not
        ``ignore_worked_day_lines``) get lines. Refunds get the negated lines of their origin. For
        the others, the versions taken into account are the payslip version and the versions of the
        same contract (same ``_get_version_lookup_key()``) starting during the period. The work
        entries of these versions are generated on the fly (nothing is stored) and converted by
        :meth:`_get_new_worked_days_lines`. Skipped in salary simulations.
        """
        if not self or self.env.context.get('salary_simulation'):
            return
        self.update({'worked_days_line_ids': [(5, 0, 0)]})
        valid_slips = self.filtered(lambda p: p.employee_id and p.date_from and p.date_to and p.version_id and p.struct_id and p.struct_id.use_worked_day_lines and not p.ignore_worked_day_lines)

        refund_payslips = valid_slips.filtered('is_refund_payslip')
        for payslip in refund_payslips:
            payslip.worked_days_line_ids = payslip.origin_payslip_id.worked_days_line_ids.copy()
            for wd in payslip.worked_days_line_ids:
                wd.number_of_hours = -wd.number_of_hours  # noqa: OLS03019
                wd.number_of_days = -wd.number_of_days  # noqa: OLS03019
                wd.amount = -wd.amount  # noqa: OLS03019

        valid_slips -= refund_payslips
        if not valid_slips:
            return

        # multi-version payslip logic :
        # we compute the associated worked day lines of all versions that fall in the same contract dates

        domain = [
            ('employee_id', 'in', valid_slips.employee_id.ids),
            ('active', '=', True),
            # optimisation to only get version swaps mid-payslip
            ('date_version', '<=', max(valid_slips.mapped('date_to'))),
            ('date_version', '>=', min(valid_slips.mapped('date_from'))),
        ]
        all_candidate_versions = self.env['hr.version'].with_context(active_test=True).search(domain)
        versions_lookup = defaultdict(lambda: self.env['hr.version'])
        for version in all_candidate_versions:
            key = version._get_version_lookup_key()
            versions_lookup[key] |= version

        all_versions_to_generate = self.env['hr.version']
        versions_by_payslip = defaultdict(lambda: self.env['hr.version'])

        for slip in valid_slips:
            main_version = slip.version_id
            versions_by_payslip[slip] += main_version
            all_versions_to_generate += main_version

            lookup_key = main_version._get_version_lookup_key()
            concurrent_versions = versions_lookup.get(lookup_key, self.env['hr.version'])

            valid_concurrent_versions = concurrent_versions.filtered(
                lambda v: v.id != main_version.id and slip.date_from <= v.date_version <= slip.date_to
            )
            versions_by_payslip[slip] += valid_concurrent_versions
            all_versions_to_generate += valid_concurrent_versions

        # Ensure work entries are generated for all contracts
        generate_from = min(valid_slips.mapped('date_from')) + relativedelta(days=-1)
        generate_to = max(valid_slips.mapped('date_to')) + relativedelta(days=1)
        # YTI TODO: Work entries computation is probably unnecessary if all payslips are not using worked days lines
        work_entries_vals = all_versions_to_generate.generate_work_entries(generate_from, generate_to)

        work_entries_vals_by_version_id = defaultdict(list)
        for vals in work_entries_vals:
            work_entries_vals_by_version_id[vals['version_id'].id].append(vals)

        for slip in valid_slips:
            versions = versions_by_payslip[slip]
            slip_work_entries_vals = [
                vals
                for version in versions
                for vals in work_entries_vals_by_version_id[version.id]
            ]
            # YTI Note: We can't use a batched create here as the payslip may not exist
            slip.update({'worked_days_line_ids': slip._get_new_worked_days_lines(versions=versions, work_entries_vals=slip_work_entries_vals)})

    def _get_similar_payslips(self):
        """Return the non cancelled payslips with the same version, structure, period and ``ignore_worked_day_lines``.

        :return: ``{(version, structure, date_from, date_to, ignore_worked_day_lines): hr.payslip}``.
        :rtype: dict
        """
        done_payslips = self.filtered(lambda p: p.version_id and p.struct_id and p.date_from and p.date_to)
        search_domain = [
            ('struct_id', 'in', done_payslips.struct_id.ids),
            ('date_from', 'in', done_payslips.mapped('date_from')),
            ('date_to', 'in', done_payslips.mapped('date_to')),
            ('state', '!=', 'cancel'),
            ('version_id', 'in', done_payslips.version_id.ids),
        ]
        payslip_read_group = self.env['hr.payslip']._read_group(
            search_domain,
            ['version_id', 'struct_id', 'date_from:day', 'date_to:day', 'ignore_worked_day_lines'],
            ['id:recordset'],
        )
        return {
            (version, structure, date_from, date_to, ignore_worked_day_lines): slips
            for version, structure, date_from, date_to, ignore_worked_day_lines, slips in payslip_read_group
        }

    def _get_new_worked_days_lines(self, versions, work_entries_vals):
        """Return the ``worked_days_line_ids`` create commands, see :meth:`_get_worked_day_lines`.

        :rtype: list[tuple]
        """
        if self.ignore_worked_day_lines:
            return []
        return [(0, 0, vals) for vals in self._get_worked_day_lines(versions=versions, work_entries_vals=work_entries_vals)]

    def _get_salary_line_total(self, code):
        """Deprecated, use :meth:`_get_line_values`."""
        _logger.warning('The method _get_salary_line_total is deprecated in favor of _get_line_values')
        lines = self.line_ids.filtered(lambda line: line.code == code)
        return sum([line.total for line in lines])

    def _get_salary_line_quantity(self, code):
        """Deprecated, use :meth:`_get_line_values`."""
        _logger.warning('The method _get_salary_line_quantity is deprecated in favor of _get_line_values')
        lines = self.line_ids.filtered(lambda line: line.code == code)
        return sum([line.quantity for line in lines])

    def _get_line_values(self, code_list, vals_list=None, compute_sum=False, extra_domain=None):
        """Sum the payslip lines of ``self`` by code and payslip, in a single query.

        Main tool to read computed amounts in reports and declarations. For example
        ``payslips._get_line_values(['GROSS', 'NET'], compute_sum=True)['NET']['sum']['total']``.

        :param list[str] code_list: rule codes.
        :param list[str] vals_list: fields to sum among ``'total'`` (default), ``'amount'``,
            ``'quantity'`` and ``'ytd'``.
        :param bool compute_sum: also fill the ``'sum'`` key with the sum over all payslips.
        :param extra_domain: optional ``hr.payslip.line`` domain restricting the lines taken into
            account, e.g. to keep only the amounts a declaration must report for a given period.
        :return: nested ``defaultdict`` (missing codes or payslips give
            0.0)::

                {
                    'NET': {
                        'sum': {'total': 300.0},       # only with compute_sum
                        payslip_1.id: {'total': 100.0},
                        payslip_2.id: {'total': 200.0},
                    },
                }
        """
        if vals_list is None:
            vals_list = ['total']
        valid_values = {'quantity', 'amount', 'total', 'ytd'}
        if set(vals_list) - valid_values:
            raise UserError(_('The following values are not valid:\n%s', '\n'.join(list(set(vals_list) - valid_values))))
        result = defaultdict(lambda: defaultdict(lambda: dict.fromkeys(vals_list, 0.0)))
        if not self or not code_list:
            return result
        domain = Domain([
            ('slip_id', 'in', self.ids),
            ('code', 'in', code_list),
        ])
        if extra_domain is not None:
            domain &= Domain(extra_domain)
        payslip_line_read_group = self.env['hr.payslip.line']._read_group(
            domain,
            ['slip_id', 'code'],
            [f'{f_name}:sum' for f_name in vals_list],
        )
        # result = {
        #     'IP': {
        #         'sum': {'quantity': 2, 'total': 300},
        #         1: {'quantity': 1, 'total': 100},
        #         2: {'quantity': 1, 'total': 200},
        #     },
        #     'IP.DED': {
        #         'sum': {'quantity': 2, 'total': -5},
        #         1: {'quantity': 1, 'total': -2},
        #         2: {'quantity': 1, 'total': -3},
        #     },
        # }
        for payslip, code, *sum_vals_list in payslip_line_read_group:
            for vals, vals_value in zip(vals_list, sum_vals_list):
                if compute_sum:
                    result[code]['sum'][vals] += vals_value or 0.0
                result[code][payslip.id][vals] += vals_value or 0.0
        return result

    def _get_worked_days_line_values(self, code_list, vals_list=None, compute_sum=False, exclude_codes=False):
        """Sum the worked days lines of ``self`` by work entry type code and payslip, in a single query.

        :param list[str] code_list: work entry type codes.
        :param list[str] vals_list: fields to sum among ``'amount'`` (default),
            ``'number_of_days'``, ``'number_of_hours'`` and ``'ytd'``.
        :param bool compute_sum: also fill the ``'sum'`` key with the sum over all payslips.
        :param bool exclude_codes: take the codes not in ``code_list`` instead.
        :return: nested ``defaultdict`` ``{code: {payslip_id or 'sum': {field: float}}}``, same
            structure as :meth:`_get_line_values`.
        """
        if vals_list is None:
            vals_list = ['amount']
        valid_values = {'number_of_hours', 'number_of_days', 'amount', 'ytd'}
        if set(vals_list) - valid_values:
            raise UserError(_('The following values are not valid:\n%s', '\n'.join(list(set(vals_list) - valid_values))))
        result = defaultdict(lambda: defaultdict(lambda: dict.fromkeys(vals_list, 0.0)))
        if not self or (not code_list and not exclude_codes):
            return result

        self.env.flush_all()
        selected_fields = SQL(',').join(SQL('SUM(%(vals)s) AS %(vals)s', vals=SQL.identifier(vals)) for vals in vals_list)
        operation = SQL('IN') if not exclude_codes else SQL('NOT IN')
        self.env.cr.execute(SQL("""
            SELECT
                p.id,
                wet.code,
                %s
            FROM hr_payslip_worked_days wd
            JOIN hr_work_entry_type wet ON wet.id = wd.work_entry_type_id
            JOIN hr_payslip p ON p.id IN %s
            AND wd.payslip_id = p.id
            AND wet.code %s %s
            GROUP BY p.id, wet.code
        """, selected_fields, tuple(self.ids), operation, tuple(code_list)))
        # self = hr.payslip(1, 2)
        # request_rows = [
        #     {'id': 1, 'code': '002.00', 'amount': 100, 'number_of_days': 1},
        #     {'id': 1, 'code': 'LEAVE100', 'amount': 200, 'number_of_days': 1},
        #     {'id': 2, 'code': '002.00', 'amount': -2, 'number_of_days': 1},
        #     {'id': 2, 'code': 'LEAVE100', 'amount': -3, 'number_of_days': 1}
        # ]
        request_rows = self.env.cr.dictfetchall()
        # result = {
        #     'IP': {
        #         'sum': {'number_of_days': 2, 'amount': 300},
        #         1: {'number_of_days': 1, 'amount': 100},
        #         2: {'number_of_days': 1, 'amount': 200},
        #     },
        #     'LEAVE100': {
        #         'sum': {'number_of_days': 2, 'amount': -5},
        #         1: {'number_of_days': 1, 'amount': -2},
        #         2: {'number_of_days': 1, 'amount': -3},
        #     },
        # }
        for row in request_rows:
            code = row['code']
            payslip_id = row['id']
            for vals in vals_list:
                if compute_sum:
                    result[code]['sum'][vals] += row[vals] or 0.0
                result[code][payslip_id][vals] += row[vals] or 0.0
        return result

    # YTI TODO: Convert in a single SQL request + Handle children
    def _get_category_data(self, category_code):
        """Sum the quantity and total of the lines of the payslip whose rule belongs to the category (children excluded).

        :return: ``{'quantity': float, 'total': float}``.
        :rtype: dict
        """
        category_data = {'quantity': 0.0, 'total': 0.0}
        for line in self.line_ids:
            if any(cat.code == category_code for cat in line.salary_rule_id.category_ids):
                category_data['quantity'] += line.quantity
                category_data['total'] += line.total
        return category_data

    def _get_input_line_amount(self, code):
        """Return the sum of the amounts of the input lines with the given rule code.

        :rtype: float
        """
        lines = self.input_line_ids.filtered(lambda line: line.code == code)
        return sum([line.amount for line in lines])

    @api.model
    def get_views(self, views, options=None):
        res = super().get_views(views, options)
        if options and options.get('toolbar'):
            for view_type in res['views']:
                res['views'][view_type]['toolbar'].pop('print', None)
        return res

    def action_print_payslip(self):
        return {
            'name': 'Payslip',
            'type': 'ir.actions.act_url',
            'url': '/print/payslips?list_ids=%(list_ids)s' % {'list_ids': ','.join(str(x) for x in self.ids)},
        }

    def _get_contract_wage(self):
        """Return the wage of the payslip version (``version._get_contract_wage()``).

        :rtype: float
        """
        self.ensure_one()
        return self.version_id._get_contract_wage()

    def _is_outside_contract_dates(self):
        """Return whether the version contract does not overlap the payslip period at all (or the version has no contract).

        :rtype: bool
        """
        self.ensure_one()
        payslip = self
        contract = self.version_id
        return not contract.contract_date_start or contract.contract_date_start > payslip.date_to \
            or (contract.contract_date_end and contract.contract_date_end < payslip.date_from)

    def _get_data_files_to_update(self):
        """Return the data files reloaded by :meth:`_update_payroll_data`.

        Overridden by each localization to list its payroll data (rules, parameters, ...).

        :return: ``[(module_name, [file_path, ...]), ...]``, order matters.
        :rtype: list[tuple]
        """
        # Note: Use lists as modules/files order should be maintained
        return []

    def _update_payroll_data(self, country_code=False):
        """Reload the payroll data files of :meth:`_get_data_files_to_update`, then update the work entry types.

        :param str country_code: only reload the files of the ``l10n_<country_code>*`` modules.
        """
        data_to_update = self._get_data_files_to_update()
        _logger.info("Update payroll static data")
        idref = {}
        for module_name, files_to_update in data_to_update:
            if country_code and not module_name.startswith(f"l10n_{country_code.lower()}"):
                continue
            for file_to_update in files_to_update:
                _logger.info("Updating %s/%s", module_name, file_to_update)
                convert_file(self.env, module_name, file_to_update, idref)

        self.env['hr.work.entry.type']._update_payroll_related_fields(country_code)

    def action_generate_pdf(self):
        """Generate (and send) the PDFs of the computed payslips, see :meth:`_generate_pdf`."""
        computed_payslips = self.filtered('line_ids')
        if not computed_payslips:
            return self._show_notification(self.env._('No Computed Payslips'), 'danger')

        return computed_payslips._generate_pdf()

    @api.model
    def _cron_generate_pdf(self, batch_size=False):
        """Generate the queued payslip PDFs (``queued_for_pdf``), then the employee declaration PDFs, by batch.

        The cron is re-triggered while there are records left.

        :param int batch_size: number of records processed per run (default 30).
        :return: ``True`` if the cron was re-triggered.
        """
        payslips = self.search([
            ('state', 'in', ['validated', 'paid']),
            ('queued_for_pdf', '=', True),
        ])
        if payslips:
            BATCH_SIZE = batch_size or 30
            payslips_batch = payslips[:BATCH_SIZE]
            payslips_batch._generate_pdf()
            payslips_batch.write({'queued_for_pdf': False})
            # if necessary, retrigger the cron to generate more pdfs
            if len(payslips) > BATCH_SIZE:
                self.env.ref('hr_payroll.ir_cron_generate_payslip_pdfs')._trigger()
                return True

        lines = self.env['hr.payroll.employee.declaration'].search([('pdf_to_generate', '=', True)])
        if lines:
            BATCH_SIZE = batch_size or 30
            lines_batch = lines[:BATCH_SIZE]
            lines_batch._generate_pdf()
            lines_batch.write({'pdf_to_generate': False})
            # if necessary, retrigger the cron to generate more pdfs
            if len(lines) > BATCH_SIZE:
                self.env.ref('hr_payroll.ir_cron_generate_payslip_pdfs')._trigger()
                return True
        return False

    @api.model
    def __get_aggregator_hr_payslip_input_model(self):
        """Return an aggregator version of the ``hr.payslip.input`` model class.

        Used by :meth:`_get_localdict` for the codes having several input lines: a recordset
        of this class behaves like a single input in ``inputs[code]``, with ``amount`` summed,
        ``sequence`` the minimum and ``name`` the common name (or the names joined by commas).
        The other fields are read on the first record. It uses plain python inheritance
        (``_register = False``), not the Odoo one, and assumes all the inputs share the same
        code. Do not reproduce elsewhere.

        Override it when a module adds fields to ``hr.payslip.input`` that must be aggregated::

            def __get_aggregator_hr_payslip_input_model(self):
                class ProxyHrPayslipInput(super().__get_aggregator_hr_payslip_input_model()):
                    ...  # your modifications
                return ProxyHrPayslipInput

        The name is mangled by python (``_HrPayslip__get_aggregator_hr_payslip_input_model``):
        the override only works from a class also named ``HrPayslip``.

        :return: subclass of the ``hr.payslip.input`` model class.
        """

        class ProxyHrPayslipInput(self.env['hr.payslip.input'].__class__):
            _name = self.env['hr.payslip.input']._name
            _register = False  # invisible to the ORM

            # All the fields that are not overridden are considered as equal to
            # self[0]['field']

            def __getitem__(self, key_or_slice):
                if not self or len(self) == 1:
                    return super().__getitem__(key_or_slice)
                if key_or_slice == 'name':
                    return self.name
                if key_or_slice == 'sequence':
                    return self.sequence
                if key_or_slice == 'amount':
                    return self.amount
                return super().__getitem__(key_or_slice)

            @property
            def name(self):
                if not self or len(self) == 1:
                    return super().name
                if len(set(self.mapped('name'))) == 1:
                    return super(ProxyHrPayslipInput, self[0]).name
                return ', '.join(self.mapped('name'))

            @property
            def sequence(self):
                if not self or len(self) == 1:
                    return super().sequence
                return min(self.mapped('sequence'))

            @property
            def amount(self):
                if not self or len(self) == 1:
                    return super().amount
                return sum([payslip_input.amount for payslip_input in self])

        return ProxyHrPayslipInput

    def _compute_salary_allocations(self, total_amount=None):
        """Split the net amount of the payslip between the bank accounts of the employee.

        Salary attachments with a beneficiary bank account first receive their computed amount.
        Then, with a single account, it receives the whole amount; with several accounts, the
        fixed allocations are taken first, and the remaining amount is split by percentage, the
        last account receiving the rounding remainder.

        :param float total_amount: amount to split, defaults to the net wage (or the net
            difference for a correction).
        :return: ``defaultdict(float)`` ``{str(res.partner.bank id): amount}``.
        :raise ValidationError: if the allocations exceed or do not cover the amount.
        """
        self.ensure_one()
        if total_amount is None:
            if self.is_correction_payslip:
                remaining = self.currency_id.round(self.correction_net_delta)
            else:
                remaining = self.currency_id.round(self.net_wage)
        else:
            remaining = self.currency_id.round(total_amount)

        res = defaultdict(float)
        if remaining == 0:
            return res

        attachment_amount = {}
        if self.salary_attachment_ids:
            for deduction_code, attachments in self.salary_attachment_ids.grouped(lambda x: x.salary_rule_id.code).items():
                # Use the amount from the computed value in the payslip lines not the input
                salary_lines = self.line_ids.filtered(lambda r: r.code == deduction_code)
                if not attachments or not salary_lines:
                    continue
                sign = -1 if self.credit_note else 1
                sum_amount = sum(sl.total for sl in salary_lines)
                attachment_amount.update(attachments._get_payment_amount(sign * abs(sum_amount)))

        # Always allocate to attachments with beneficiary bank accounts, even if employee has no bank accounts
        for attachment in self.salary_attachment_ids.filtered(lambda x: x.beneficiary_bank_account_id):
            ba = attachment.beneficiary_bank_account_id
            amount = attachment_amount.get(attachment, 0)
            if amount > 0:
                res[str(ba.id)] += amount

        if not self.employee_id.bank_account_ids:
            return res

        if not self.employee_id.has_multiple_bank_accounts:
            res[str(self.employee_id.primary_bank_account_id.id)] = remaining
            return res

        fixed_bank_account_ids = self.employee_id.get_accounts_with_fixed_allocations()
        for ba in fixed_bank_account_ids:
            amount, _ = self.employee_id.get_bank_account_salary_allocation(str(ba.id))
            if amount > 0 and amount <= remaining:
                amount = self.currency_id.round(amount)
                res[str(ba.id)] += amount
                remaining -= amount
            else:
                raise ValidationError(self.env._("Allocated amounts surpass the net salary."))

        percentage_bank_account_ids = self.employee_id.bank_account_ids - fixed_bank_account_ids
        if not percentage_bank_account_ids and remaining > 0:
            raise ValidationError(self.env._("Allocated amounts are less than the net salary."))

        total_percentage_account_amounts = 0
        for i, ba in enumerate(percentage_bank_account_ids):
            percentage, _ = self.employee_id.get_bank_account_salary_allocation(str(ba.id))
            if percentage > 0:
                if i == len(percentage_bank_account_ids) - 1:
                    amount = self.currency_id.round(remaining - total_percentage_account_amounts)
                else:
                    amount = self.currency_id.round((percentage / 100.0) * remaining)
                    total_percentage_account_amounts += amount
                if amount > 0:
                    res[str(ba.id)] = amount
            else:
                res[str(ba.id)] = 0
        return res

    def safe_compute_salary_allocations(self, total_amount=None):
        """Same as :meth:`_compute_salary_allocations`, but return ``{'__error__': message}`` instead of raising."""
        try:
            return self._compute_salary_allocations(total_amount)
        except ValidationError as e:
            return {"__error__": str(e)}

    def generate_payments_dict(self):
        """Return the payments of the payslip, one per bank account, for the payment reports.

        :return: ``[{'partner': str, 'account_num': str, 'amount': float}]``; ``partner`` is the
            account holder between parentheses if it is not the employee.
        :rtype: list[dict]
        """
        payments = []
        allocations = self._compute_salary_allocations()

        for bank_id, amount in allocations.items():
            bank = self.env['res.partner.bank'].browse(int(bank_id))
            partner = f"({bank.partner_id.name})" if self.employee_id.legal_name != bank.partner_id.name else ''

            payments.append({
                'partner': partner,
                'account_num': bank.account_number,
                'amount': amount
            })
        return payments

    def _negative_net_context(self):
        """Return the negative net amounts still to report for the employees of the draft payslips.

        :return: ``{hr.employee: amount}`` summed over the validated or paid payslips with
            ``has_negative_net_to_report``.
        :rtype: dict
        """
        target_slips = self.filtered(
            lambda s: s.id and s.state == 'draft' and s.currency_id
        )
        if not target_slips:
            return {}

        return {
            employee: total
            for employee, total in self.env['hr.payslip']._read_group(
                domain=[
                    ('has_negative_net_to_report', '=', True),
                    ('employee_id', 'in', target_slips.employee_id.ids),
                    ('credit_note', '=', False),
                    ('state', 'in', ['validated', 'paid']),
                ],
                groupby=['employee_id'],
                aggregates=['negative_net_to_report:sum'],
            )
            if total
        }

    def _get_basic_salary(self):
        """Return the basic salary of the period: the sum of the worked days amounts.

        Falls back on the version wage (:meth:`_get_contract_wage`) in salary simulations, or if
        the payslip has no worked days.

        :rtype: float
        """
        self.ensure_one()
        salary_simulation = self.env.context.get('salary_simulation')
        if salary_simulation or self.ignore_worked_day_lines or not self.worked_days_line_ids:
            return self._get_contract_wage()
        return sum(line.amount for line in self.worked_days_line_ids)

    def _get_payroll_translation(self, text, **kwargs):
        """Return the translation of a source term used in data code (salary rules, warnings).

        Terms evaluated in data are not extracted for translation: each localization overrides this
        method with an explicit ``self.env._()`` call per term. Unknown terms are logged and
        returned as is, formatted with ``kwargs``.

        :param str text: source term.
        :rtype: str
        """
        # Please order alphabetically to easily spot duplicates
        _logger.warning('Translation source term not explicitely defined (It could remain untranslated) for:\n%s', text)
        if kwargs:
            return text.format(**kwargs)
        return text

    def return_time_off_to_normal(self):
        """Give the time off of the payslips (``payslip_state`` blocked or done) back the ``'normal'`` payslip state."""
        domain = Domain.AND([
            [('payslip_state', 'in', ['blocked', 'done'])],
            self._get_leaves_domain()
        ])
        leaves = self.env['hr.leave'].search(domain)
        leaves.write({
            'payslip_state': 'normal'
        })


HrPayslip._recompute_with_forced_lines.__override__ = False  # whitelist super()
