from datetime import date

from odoo import api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_compare

from .tools import gec_lock_for_update


class HrVersion(models.Model):
    _inherit = 'hr.version'

    _PAY_SCHEME_WAGE_TYPE = {
        'fixed': 'monthly',
        'hourly': 'hourly',
        'daily': 'daily',
        'fixed_daily': 'monthly',
        'fixed_hourly': 'monthly',
        'daily_hourly': 'daily',
        'unit': 'unit',
        'daily_unit': 'daily',
    }

    _GEC_ROUTING_FIELDS = frozenset({'pay_scheme', 'hourly_source', 'overtime_pay_mode'})
    _GEC_TIMESHEET_CONFIG_FIELDS = frozenset({'timesheet_pay_project_ids', 'timesheet_pay_start_date'})

    pay_scheme = fields.Selection([
        ('fixed', 'Fixed'),
        ('hourly', 'Hourly'),
        ('daily', 'Daily'),
        ('unit', 'Per Unit'),
        ('fixed_daily', 'Fixed + Daily'),
        ('fixed_hourly', 'Fixed + Hourly'),
        ('daily_hourly', 'Daily + Hourly'),
        ('daily_unit', 'Daily + Per Unit'),
    ], tracking=True, groups='hr_payroll.group_hr_payroll_user',
        help="How the employee is paid: a fixed monthly salary, by the hour, by the day, per unit of work, or a mix; overtime goes with any scheme.")
    wage_type = fields.Selection(selection_add=[('daily', 'Daily Wage'), ('unit', 'Unit Wage')],
        ondelete={'daily': 'set monthly', 'unit': 'set monthly'})
    daily_wage = fields.Monetary(string='Daily Wage', tracking=True, help="Gross wage for one fully scheduled working day.",
        groups='hr_payroll.group_hr_payroll_user')
    worklog_ot_enabled = fields.Boolean(string='Pay Overtime Work Logs', tracking=True,
        help="Approved overtime work logs are paid on this employee's payslips at the Hourly Wage; not available when the employee is paid by the "
        "hour from timesheets.", groups='hr_payroll.group_hr_payroll_user')
    worklog_daily_enabled = fields.Boolean(string='Pay Daily Work Logs', tracking=True, compute='_compute_scheme_components', store=True,
        readonly=True, help="On with the Fixed + Daily pay scheme: approved daily work logs are paid at the Daily Wage.",
        groups='hr_payroll.group_hr_payroll_user')
    overtime_pay_mode = fields.Selection([('with_salary', 'With Salary'), ('separate', 'Separate Payslip')], string='Overtime Payment',
        default='with_salary', required=True, tracking=True, groups='hr_payroll.group_hr_payroll_user',
        help="Whether approved overtime is paid on the salary payslip or on a payslip of its own; a separate overtime payslip has no benefits, "
        "deductions or advance repayments.")
    timesheet_extra_enabled = fields.Boolean(string='Pay Timesheet Hours', tracking=True, compute='_compute_scheme_components', store=True,
        readonly=True, help="On with the Fixed + Hourly and Daily + Hourly pay schemes: timesheet hours are paid on top of the base wage.",
        groups='hr_payroll.group_hr_payroll_user')
    hourly_source = fields.Selection([('work_entry', 'Work Entries'), ('timesheet', 'Timesheets')], string='Hours Come From', default='work_entry',
        tracking=True, groups='hr_payroll.group_hr_payroll_user',
        help="Where the paid hours of an hourly employee come from; with Timesheets only timesheet hours are paid: work entries, paid time off, "
        "public holidays and work logs are not.")
    timesheet_pay_project_ids = fields.Many2many('project.project', string='Payroll Timesheet Projects',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="Only timesheets on these projects are paid. Leave empty to pay every project of the employee's own company; timesheets of another "
        "company are never paid. Projects without a company are listed too: their timesheets take the employee's company.",
        groups='hr_payroll.group_hr_payroll_user')
    timesheet_pay_start_date = fields.Date(string='Timesheet Pay From',
        groups='hr_payroll.group_hr_payroll_user', help="Timesheets before this date are never paid, so turning this on does not pay old timesheets.")

    @api.model
    def _gec_hourly_source_allowed(self, pay_scheme, hourly_source):
        return hourly_source != 'timesheet' or pay_scheme == 'hourly'

    @api.model
    def _normalize_payroll_values(self, vals):
        """A value passed to create or write wins over a recompute, so the wage type of the pay scheme goes into the values here and in write;
        `_compute_wage_type` covers a pay scheme that comes from a contract template or a change of structure type."""
        vals = dict(vals)
        if vals.get('pay_scheme'):
            vals['wage_type'] = self._PAY_SCHEME_WAGE_TYPE[vals['pay_scheme']]
        if not self._gec_hourly_source_allowed(vals.get('pay_scheme'), vals.get('hourly_source')):
            vals['hourly_source'] = 'work_entry'
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_payroll_values(vals) for vals in vals_list])

    def write(self, vals):
        if not self:
            return super().write(vals)
        if (self._GEC_ROUTING_FIELDS | self._GEC_TIMESHEET_CONFIG_FIELDS) & vals.keys():
            self._gec_check_routing_change(vals)
        normalized = dict(vals)
        if vals.get('pay_scheme'):
            normalized['wage_type'] = self._PAY_SCHEME_WAGE_TYPE[vals['pay_scheme']]
        can_manage_payroll = (self.env.su or self.env.user.has_group('hr_payroll.group_hr_payroll_user'))
        groups = {}
        for version in self:
            fix_hourly = False
            if can_manage_payroll:
                version_sudo = version.sudo()
                fix_hourly = not self._gec_hourly_source_allowed(normalized.get('pay_scheme', version_sudo.pay_scheme),
                    normalized.get('hourly_source', version_sudo.hourly_source))
            groups.setdefault(fix_hourly, self.browse())
            groups[fix_hourly] |= version
        res = True
        for fix_hourly, records in groups.items():
            record_vals = dict(normalized)
            if fix_hourly:
                record_vals['hourly_source'] = 'work_entry'
            res = super(HrVersion, records).write(record_vals) and res
        return res

    @api.model
    def _gec_m2m_ids_after_commands(self, current_ids, commands):
        """Ids an x2many write would leave behind; a recordset, tuple or id list sets, False clears."""
        if isinstance(commands, models.BaseModel):
            return set(commands.ids)
        if isinstance(commands, tuple) or (isinstance(commands, list) and commands and not isinstance(commands[0], (tuple, list))):
            return set(commands)
        if commands is False or commands is None:
            return set()
        ids = set(current_ids)
        for command in commands:
            if command[0] == Command.SET:
                ids = set(command[2] or [])
            elif command[0] == Command.LINK:
                ids.add(command[1])
            elif command[0] in (Command.UNLINK, Command.DELETE):
                ids.discard(command[1])
            elif command[0] == Command.CLEAR:
                ids = set()
        return ids

    def _gec_raise_strandable(self, version, stranded):
        raise UserError(self.env._("%(name)s has %(count)s timesheet line(s) that payroll could no longer pay after this change (dates: %(dates)s): "
            "use New Contract to make the change from a date, or ask a payroll manager to waive those lines first (cancel or delete a draft payslip "
            "that already contains them).",
            name=version.employee_id.name or version.display_name, count=len(stranded),
            dates=', '.join(str(d) for d in sorted(set(stranded.mapped('date')))[:5])))

    def _gec_check_routing_change(self, vals):
        """Block edits to pay routing that would double-pay or strand hours."""
        payslip_model = self.env['hr.payslip'].sudo()
        settlement_model = self.env['hr.payroll.component.settlement'].sudo()
        for version in self.sudo():
            routing_changes = {field for field in self._GEC_ROUTING_FIELDS & vals.keys() if (vals[field] or False) != (version[field] or False)}
            config_touched = self._GEC_TIMESHEET_CONFIG_FIELDS & vals.keys()
            if not routing_changes and not config_touched:
                continue
            if version.employee_id:
                gec_lock_for_update(version.employee_id, allow_referencing=True)
            if routing_changes:
                # A version may be paid on another version's payslip of the same contract.
                finalized = payslip_model.search_count([
                    '|',
                    ('version_id', '=', version.id),
                    ('worked_days_line_ids.version_id', '=', version.id),
                    ('state', 'in', ('validated', 'paid')),
                ], limit=1) or settlement_model.search_count([
                    ('source_version_id', '=', version.id),
                    ('active_claim', '=', True),
                    ('payslip_id.state', 'in', ('validated', 'paid')),
                ], limit=1)
                if finalized:
                    raise UserError(self.env._("The pay settings of %(name)s cannot change on this contract because payslips are already validated "
                        "or paid with it: use New Contract to change them from a date.", name=version.employee_id.name or version.display_name))
            if not version._gec_uses_timesheet_hourly_base():
                continue
            still_timesheet = (vals.get('pay_scheme',
                version.pay_scheme) == 'hourly' and vals.get('hourly_source', version.hourly_source) == 'timesheet')
            if routing_changes and not still_timesheet:
                stranded = version._gec_strandable_timesheet_lines(include_draft_claims=True)
                if stranded:
                    self._gec_raise_strandable(version, stranded)
            elif still_timesheet and config_touched:
                if 'timesheet_pay_project_ids' in vals:
                    new_project_ids = self._gec_m2m_ids_after_commands(version.timesheet_pay_project_ids.ids, vals['timesheet_pay_project_ids'])
                else:
                    new_project_ids = set(version.timesheet_pay_project_ids.ids)
                new_cutoff = fields.Date.to_date(vals.get('timesheet_pay_start_date', version.timesheet_pay_start_date))
                stranded = version._gec_strandable_timesheet_lines(
                    include_draft_claims=True,
                ).filtered(
                    lambda line: (new_project_ids and line.project_id.id not in new_project_ids)
                    or (new_cutoff and line.date < new_cutoff))
                if stranded:
                    self._gec_raise_strandable(version, stranded)

    def _gec_uses_timesheet_hourly_base(self):
        self.ensure_one()
        return self.pay_scheme == 'hourly' and self.hourly_source == 'timesheet'

    def _gec_timesheet_component_code(self):
        self.ensure_one()
        if self._gec_uses_timesheet_hourly_base():
            return 'timesheet_basic'
        if self.timesheet_extra_enabled:
            return 'timesheet_extra'
        return False

    def _gec_timesheet_line_eligible(self, line):
        """Work-date eligibility shared by claiming and the routing guard; leave, mirror and waived lines never pay."""
        self.ensure_one()
        version = self.sudo()
        if line.company_id != version.company_id:
            return False
        if not version._is_in_contract(line.date):
            return False
        if not version._gec_timesheet_component_code():
            return False
        if float_compare(line.unit_amount, 0.0, precision_digits=2) <= 0:
            return False
        if float_compare(line.unit_amount, 24.0, precision_digits=2) > 0:
            return False
        if version.currency_id.compare_amounts(version.hourly_wage, 0.0) <= 0:
            return False
        if version.timesheet_pay_start_date and line.date < version.timesheet_pay_start_date:
            return False
        projects = version.timesheet_pay_project_ids
        if projects and line.project_id not in projects:
            return False
        line_fields = line._fields
        if 'holiday_id' in line_fields and line.holiday_id:
            return False
        if 'global_leave_id' in line_fields and line.global_leave_id:
            return False
        if line.work_log_id:
            return False
        if line.sudo().gec_payroll_waived_at:
            return False
        return True

    def _gec_strandable_timesheet_lines(self, include_draft_claims=False):
        """Unwaived timesheets only this timesheet-mode version can pay.
        Unclaimed lines; with include_draft_claims also those claimed by a draft slip, released by a routing change."""
        self.ensure_one()
        version = self.sudo()
        line_model = self.env['account.analytic.line'].sudo()
        if not (version.employee_id and version._gec_uses_timesheet_hourly_base()):
            return line_model.browse()
        domain = [
            ('employee_id', '=', version.employee_id.id),
            ('company_id', '=', version.company_id.id),
            ('project_id', '!=', False),
            ('work_log_id', '=', False),
            ('gec_payroll_waived_at', '=', False),
        ]
        if version.date_start:
            domain.append(('date', '>=', version.date_start))
        if version.date_end:
            domain.append(('date', '<=', version.date_end))
        lines = line_model.search(domain).filtered(lambda line: version._gec_timesheet_line_eligible(line))

        def strandable(line):
            claims = line.gec_settlement_ids.filtered('active_claim')
            if not claims:
                return True
            return include_draft_claims and all(claim.payslip_id.state == 'draft' for claim in claims)

        return lines.filtered(strandable)

    @api.model
    def _gec_timesheet_mode_warning(self, employee, company, projects, cutoff):
        """Warning for a switch to Hourly-from-Timesheets: unclaimed lines since the cutoff will be paid."""
        if not employee:
            return None
        domain = [('employee_id', '=', employee.id), ('company_id', '=', company.id),
            ('project_id', 'in', projects.ids) if projects else ('project_id', '!=', False), ('work_log_id', '=', False), ('unit_amount', '>', 0),
            ('gec_payroll_waived_at', '=', False), ('gec_settlement_ids', 'not any', [('active_claim', '=', True)])]
        if cutoff:
            domain.append(('date', '>=', cutoff))
        count = self.env['account.analytic.line'].sudo().search_count(domain)
        if not count:
            return None
        if cutoff:
            message = self.env._("%(count)s timesheet line(s) on the allowed projects since %(date)s are not paid yet and will be paid by the next "
                "payslips.", count=count, date=cutoff)
        else:
            message = self.env._("%(count)s timesheet line(s) on the allowed projects are not paid yet and will be paid by the next payslips.",
                count=count)
        return {'warning': {'title': self.env._('Historical timesheets become payable'), 'message': message}}

    @api.onchange('pay_scheme', 'hourly_source', 'timesheet_pay_project_ids', 'timesheet_pay_start_date')
    def _onchange_gec_timesheet_mode_preview(self):
        if not (self.pay_scheme == 'hourly' and self.hourly_source == 'timesheet'):
            return
        return self._gec_timesheet_mode_warning(self.employee_id._origin, self.company_id, self.timesheet_pay_project_ids._origin,
            self.timesheet_pay_start_date)

    @api.depends('pay_scheme')
    def _compute_scheme_components(self):
        for version in self:
            version.worklog_daily_enabled = version.pay_scheme == 'fixed_daily'
            version.timesheet_extra_enabled = version.pay_scheme in ('fixed_hourly', 'daily_hourly')

    @api.depends('pay_scheme', 'structure_type_id')
    def _compute_wage_type(self):
        super()._compute_wage_type()
        for version in self:
            if version.pay_scheme:
                version.wage_type = self._PAY_SCHEME_WAGE_TYPE[version.pay_scheme]

    @api.constrains('hourly_source', 'hourly_wage', 'worklog_ot_enabled')
    def _check_pay_scheme_wage_type(self):
        for version in self.filtered(lambda version: version.hourly_source == 'timesheet'):
            if version.currency_id.compare_amounts(version.hourly_wage, 0.0) <= 0:
                raise ValidationError(self.env._("Set an Hourly Wage above zero before paying this employee by timesheets."))
            if version.worklog_ot_enabled:
                raise ValidationError(self.env._("Pay Overtime Work Logs cannot be on when the employee is paid by the hour from timesheets: enter "
                    "the overtime as timesheets instead."))

    def _get_fields_that_recompute_payslip(self):
        return super()._get_fields_that_recompute_payslip() + ['pay_scheme', 'structure_type_id', 'wage_type', 'wage', 'hourly_wage', 'daily_wage',
            'worklog_ot_enabled', 'overtime_pay_mode', 'hourly_source', 'timesheet_pay_project_ids', 'timesheet_pay_start_date']

    def _recompute_payslips(self, date_from=None, date_to=None):
        """Core refreshes the regular drafts; overtime drafts priced by this version are not regular, so add them."""
        super()._recompute_payslips(date_from=date_from, date_to=date_to)
        if not self:
            return
        domain = Domain.OR(
            Domain('date_from', '<=', date_to or version.date_end or date.max)
            & Domain('date_to', '>=', date_from or version.date_start)
            & (Domain('version_id', '=', version.id) | Domain('worked_days_line_ids.version_id', '=', version.id))
            for version in self
        )
        draft_slips = self.env['hr.payslip'].sudo().search(domain & Domain([('state', '=', 'draft'), ('company_id', 'in', self.company_id.ids)]))
        draft_slips.filtered(lambda slip: slip._gec_is_overtime_base() and not slip.edited).action_refresh_from_work_entries()

    def _get_contract_wage_field(self):
        self.ensure_one()
        if self.wage_type == 'daily':
            return 'daily_wage'
        return super()._get_contract_wage_field()

    def _get_contract_wage(self):
        """Unit pay has no contract wage; a kept old `wage` would misreport a piecework employee."""
        if self.wage_type == 'unit':
            return 0.0
        return super()._get_contract_wage()

    def _get_normalized_wage(self):
        if self.wage_type == 'unit':
            return 0.0
        if self.wage_type == 'daily':
            hours_per_day = self.resource_calendar_id.hours_per_day
            return self.daily_wage / hours_per_day if hours_per_day else 0
        return super()._get_normalized_wage()

    def _get_whitelist_fields_from_template(self):
        return super()._get_whitelist_fields_from_template() + ['pay_scheme', 'hourly_wage', 'daily_wage', 'worklog_ot_enabled', 'overtime_pay_mode',
            'worklog_daily_enabled', 'timesheet_extra_enabled', 'hourly_source', 'timesheet_pay_project_ids',
            'timesheet_pay_start_date']
