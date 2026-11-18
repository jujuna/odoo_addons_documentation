from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class HrEmployeeWorkLog(models.Model):
    _name = 'hr.employee.work.log'
    _description = 'Employee Work Log'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _allow_sudo_commands = False
    _check_company_auto = True

    name = fields.Char(string='Reason', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True, ondelete='restrict',
        default=lambda self: self.env.user.employee_id, tracking=True)
    user_id = fields.Many2one('res.users', string='User', index='btree_not_null', copy=False)
    project_id = fields.Many2one('project.project', string='Project', index='btree_not_null', check_company=True)
    task_id = fields.Many2one('project.task', string='Task', index='btree_not_null', check_company=True, domain="[('project_id', '=?', project_id)]")
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    type = fields.Selection([('overtime', 'Overtime'), ('daily', 'Daily Work'), ('unit', 'Unit Work')], required=True, default='overtime',
        tracking=True)
    hours = fields.Float(tracking=True)
    units = fields.Float(string='Days', tracking=True)
    work_unit_id = fields.Many2one('hr.payroll.unit.rate', string='Unit Rate', index='btree_not_null', ondelete='restrict', tracking=True,
        check_company=True)
    unit_qty = fields.Float(string='Quantity', tracking=True)
    percentage = fields.Selection([('100', '100%'), ('125', '125%'), ('150', '150%'), ('200', '200%')], string='Rate %', required=True, default='100',
        tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], required=True, default='draft', copy=False, index=True, tracking=True)
    rejection_reason = fields.Char(copy=False, tracking=True)
    version_id = fields.Many2one('hr.version', string='Contract', copy=False, readonly=True, groups='hr_payroll.group_hr_payroll_user')
    rate_snapshot = fields.Monetary(string='Rate at Approval', copy=False, readonly=True, groups='hr_payroll.group_hr_payroll_user')
    amount_snapshot = fields.Monetary(string='Amount at Approval', copy=False, readonly=True, groups='hr_payroll.group_hr_payroll_user')
    component_code_snapshot = fields.Char(copy=False, readonly=True, groups='hr_payroll.group_hr_payroll_user',
        help="Pay component frozen at approval, so a later flag/scheme change cannot re-route or drop the pay.")
    currency_id_snapshot = fields.Many2one('res.currency', copy=False, readonly=True, ondelete='restrict', groups='hr_payroll.group_hr_payroll_user',
        help="Currency in force at approval, frozen so a later company transfer cannot reinterpret the amount.")
    unit_uom_snapshot_id = fields.Many2one('uom.uom', string='Unit at Approval', copy=False, readonly=True, ondelete='restrict',
        groups='hr_payroll.group_hr_payroll_user', help="The unit of the rate at approval; a later change of the rate does not change it.")
    approved_by_id = fields.Many2one('res.users', string='Approved By', copy=False, readonly=True)
    approved_at = fields.Datetime(copy=False, readonly=True)
    settlement_ids = fields.One2many('hr.payroll.component.settlement', 'work_log_id', groups='hr_payroll.group_hr_payroll_user')
    timesheet_ids = fields.One2many('account.analytic.line', 'work_log_id', string='Timesheets',
        help="Timesheet lines created when this overtime log was approved.")
    settlement_state = fields.Selection([('unclaimed', 'Not in Payslip'), ('claimed', 'In Draft Payslip'), ('paid', 'Paid')],
        string='Payslip Status', compute='_compute_settlement_state', compute_sudo=True, groups='hr_payroll.group_hr_payroll_user')
    unit_uom_id = fields.Many2one('uom.uom', string='Unit', compute='_compute_unit_display', compute_sudo=True)
    unit_price_display = fields.Monetary(string='Price per Unit', compute='_compute_unit_display', compute_sudo=True)
    unit_amount_display = fields.Monetary(string='Unit Amount', compute='_compute_unit_display', compute_sudo=True)
    can_approve = fields.Boolean(compute='_compute_can_approve')

    _employee_state_date_idx = models.Index('(employee_id, state, date)')
    _one_daily_per_date = models.UniqueIndex("(employee_id, date) WHERE type = 'daily' AND state NOT IN ('rejected', 'cancelled')",
        "An employee can have only one active daily work log per date. Cancel or reject the other one first.")

    @api.depends('settlement_ids.active_claim', 'settlement_ids.payslip_id.state')
    def _compute_settlement_state(self):
        for log in self:
            live = log.settlement_ids.filtered('active_claim')
            if live and live.payslip_id.state in ('validated', 'paid'):
                log.settlement_state = 'paid'
            elif live:
                log.settlement_state = 'claimed'
            else:
                log.settlement_state = 'unclaimed'

    @api.depends('type', 'unit_qty', 'work_unit_id.uom_id', 'work_unit_id.price_per_unit', 'unit_uom_snapshot_id', 'rate_snapshot', 'amount_snapshot')
    def _compute_unit_display(self):
        """Live catalog price until approval, frozen snapshot after; sudo as snapshots are payroll-only."""
        for log in self:
            if log.type != 'unit':
                log.unit_uom_id = False
                log.unit_price_display = 0.0
                log.unit_amount_display = 0.0
            elif log.unit_uom_snapshot_id:
                log.unit_uom_id = log.unit_uom_snapshot_id
                log.unit_price_display = log.rate_snapshot
                log.unit_amount_display = log.amount_snapshot
            else:
                log.unit_uom_id = log.work_unit_id.uom_id
                log.unit_price_display = log.work_unit_id.price_per_unit
                amount = log.unit_qty * log.work_unit_id.price_per_unit
                log.unit_amount_display = log.currency_id.round(amount) if log.currency_id else amount

    @api.depends('employee_id.parent_id.user_id')
    @api.depends_context('uid')
    def _compute_can_approve(self):
        is_officer = self.env.user.has_group('hr_payroll.group_hr_payroll_officer')
        for log in self:
            # sudo: a plain employee cannot read the employee record of a report
            log.can_approve = is_officer or log.sudo().employee_id.parent_id.user_id == self.env.user

    @api.constrains('type', 'hours', 'units', 'unit_qty', 'work_unit_id')
    def _check_quantities(self):
        for log in self:
            if log.type == 'overtime':
                if float_compare(log.hours, 0.0, precision_digits=2) <= 0 or log.hours > 24:
                    raise ValidationError(self.env._("Overtime requires a number of hours between 0 and 24."))
            elif log.type == 'daily':
                if float_compare(log.units, 0.0, precision_digits=2) <= 0:
                    raise ValidationError(self.env._("Daily work requires a positive number of days."))
                if float_compare(log.units, 1.0, precision_digits=2) > 0:
                    raise ValidationError(self.env._("A daily work log covers a single date, so days cannot exceed 1."))
            else:
                if not log.work_unit_id:
                    raise ValidationError(self.env._("Select a unit rate item on a unit work log."))
                if float_compare(log.unit_qty, 0.0, precision_digits=2) <= 0:
                    raise ValidationError(self.env._("Unit work requires a positive quantity."))

    @api.constrains('type', 'hours', 'date', 'employee_id', 'state')
    def _check_overtime_daily_cap(self):
        """Cap active overtime at 24 h per employee and day, counting logs saved in the same call."""
        for log in self:
            if log.type != 'overtime' or log.state in ('rejected', 'cancelled'):
                continue
            siblings = self.sudo().search([
                ('id', '!=', log.id),
                ('employee_id', '=', log.employee_id.id),
                ('date', '=', log.date),
                ('type', '=', 'overtime'),
                ('state', 'not in', ('rejected', 'cancelled')),
            ])
            total = log.hours + sum(siblings.mapped('hours'))
            if float_compare(total, 24.0, precision_digits=2) > 0:
                raise ValidationError(self.env._("Total active overtime for %(employee)s on %(date)s would be %(total).2f hours, over the 24h/day "
                    "limit.", employee=log.employee_id.name, date=log.date, total=total))

    _GEC_TYPE_FIELDS = {'overtime': ('hours',), 'daily': ('units',), 'unit': ('work_unit_id', 'unit_qty')}
    _GEC_ALL_TYPE_FIELDS = sum(_GEC_TYPE_FIELDS.values(), ())
    _GEC_APPROVAL_FIELDS = ('version_id', 'rate_snapshot', 'amount_snapshot', 'component_code_snapshot', 'currency_id_snapshot',
        'unit_uom_snapshot_id', 'approved_by_id', 'approved_at')

    @api.model
    def _gec_clear_other_type_fields(self, vals, log_type):
        """The form clears them on type change; the inline lists on the user and employee pages do not."""
        own = self._GEC_TYPE_FIELDS[log_type]
        for field in self._GEC_ALL_TYPE_FIELDS:
            if field not in own:
                vals[field] = False if field == 'work_unit_id' else 0.0
        return vals

    @api.onchange('type')
    def _onchange_type(self):
        self.update(self._gec_clear_other_type_fields({}, self.type))
        if self.type == 'daily' and float_is_zero(self.units, precision_digits=2):
            self.units = 1.0
        elif self.type == 'unit' and float_is_zero(self.unit_qty, precision_digits=2):
            self.unit_qty = 1.0

    @api.model_create_multi
    def create(self, vals_list):
        """Set the owner and discard forged workflow snapshots."""
        employee_model = self.env['hr.employee'].sudo()
        user_model = self.env['res.users'].sudo()
        for vals in vals_list:
            if not vals.get('employee_id') and vals.get('user_id'):
                vals['employee_id'] = user_model.browse(vals['user_id']).employee_id.id
            if vals.get('employee_id'):
                vals['user_id'] = employee_model.browse(vals['employee_id']).user_id.id
            vals['state'] = 'draft'
            self._gec_clear_other_type_fields(vals, vals.get('type', 'overtime'))
            for field_name in self._GEC_APPROVAL_FIELDS:
                vals.pop(field_name, None)
        return super().create(vals_list)

    def _write_workflow(self, vals):
        """Write workflow fields outside the RPC path."""
        return super().write(vals)

    def write(self, vals):
        forbidden = {'state', 'user_id', *self._GEC_APPROVAL_FIELDS} & vals.keys()
        if forbidden:
            raise UserError(self.env._("The status, owner and approval values of a work log cannot be edited: use the Submit, Approve, Reject, "
                "Reset to Draft and Cancel buttons."))
        if 'employee_id' in vals and not self.env.user.has_group('hr_payroll.group_hr_payroll_officer'):
            if self.env['hr.employee'].sudo().browse(vals['employee_id']).user_id != self.env.user:
                raise UserError(self.env._("You can only file work logs for yourself. A payroll officer can reassign them."))
        if (vals.keys() - {'rejection_reason', 'message_main_attachment_id'} and any(log.state == 'approved' for log in self)):
            raise UserError(self.env._("An approved work log cannot be changed: ask a payroll officer to reset it to draft first."))
        if vals.keys() & {'type', *self._GEC_ALL_TYPE_FIELDS}:
            res = True
            for log_type, logs in self.grouped(lambda log: vals.get('type') or log.type).items():
                res = super(HrEmployeeWorkLog, logs).write(self._gec_clear_other_type_fields(dict(vals), log_type)) and res
        else:
            res = super().write(vals)
        if 'employee_id' in vals:
            for log in self:
                expected = log.sudo().employee_id.user_id.id or False
                if (log.user_id.id or False) != expected:
                    log._write_workflow({'user_id': expected})
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_processed(self):
        if any(log.state not in ('draft', 'rejected', 'cancelled') for log in self):
            raise UserError(self.env._("Only draft, rejected or cancelled work logs can be deleted."))
        if any(log.sudo().settlement_ids for log in self):
            raise UserError(self.env._("A work log that was in a payslip cannot be deleted: cancel it instead."))

    def _ensure_owner(self):
        if self.env.user.has_group('hr_payroll.group_hr_payroll_officer'):
            return
        for log in self:
            if log.sudo().employee_id.user_id != self.env.user:
                raise UserError(self.env._("Only the employee or a payroll officer can do this."))

    def _ensure_approver(self):
        if not all(self.mapped('can_approve')):
            raise UserError(self.env._("Only the direct manager or a payroll officer can approve or reject work logs."))

    def _resolve_component_code(self, version):
        self.ensure_one()
        if not version:
            return False
        if self.type == 'overtime':
            return 'worklog_ot' if version.worklog_ot_enabled else False
        if self.type == 'unit':
            if version.pay_scheme == 'unit':
                return 'unit_basic'
            if version.pay_scheme == 'daily_unit':
                return 'unit_extra'
            return False
        if version.wage_type == 'daily':
            return 'daily_basic'
        if version.worklog_daily_enabled:
            return 'worklog_daily'
        return False

    def action_submit(self):
        self._ensure_owner()
        if any(log.state not in ('draft', 'rejected') for log in self):
            raise UserError(self.env._("Only draft or rejected work logs can be submitted."))
        self._write_workflow({'state': 'submitted', 'rejection_reason': False})

    def _gec_approval_component(self, employee_sudo, version):
        """Pay component under the work-date contract version."""
        self.ensure_one()
        log = self
        if not version or not version._is_in_contract(log.date):
            raise UserError(self.env._("%(employee)s is not under contract on %(date)s.", employee=employee_sudo.name, date=log.date))
        if version.wage_type == 'hourly' and 'attendance_based' in version._fields and version.attendance_based:
            raise UserError(self.env._("%(employee)s is paid by the hour from attendance, so these hours are already in the payslip: correct the "
                "attendance instead of adding a work log.", employee=employee_sudo.name))
        if log.type == 'overtime' and version._gec_uses_timesheet_hourly_base():
            raise UserError(self.env._("%(employee)s is paid by the hour from timesheets: enter the overtime as a timesheet, not as a work log.",
                employee=employee_sudo.name))
        component_code = log._resolve_component_code(version)
        if not component_code:
            work_kind = {'overtime': self.env._("overtime"), 'daily': self.env._("daily"), 'unit': self.env._("unit work")}[log.type]
            raise UserError(self.env._("%(employee)s's contract does not pay %(kind)s work logs: set a Pay Scheme or pay option on the contract "
                "that pays them, then approve again.", employee=employee_sudo.name, kind=work_kind))
        return component_code

    def _gec_approval_rate(self, employee_sudo, version):
        """Rate frozen at approval: the unit rate price, or the version's hourly or daily wage."""
        self.ensure_one()
        log = self
        if log.type == 'unit':
            rate_item = log.work_unit_id
            if not rate_item.active:
                raise UserError(self.env._("Unit rate '%(rate)s' is archived. Pick a current rate item before approving.", rate=rate_item.name))
            if rate_item.company_id and rate_item.company_id != log.company_id:
                raise UserError(self.env._("Unit rate '%(rate)s' belongs to %(company)s. Pick a rate of %(employee)s's company or a shared one.",
                    rate=rate_item.name, company=rate_item.company_id.name, employee=employee_sudo.name))
            if rate_item.currency_id != log.currency_id:
                raise UserError(self.env._("Unit rate '%(rate)s' is priced in %(rate_currency)s but %(employee)s is paid in %(currency)s. Use a rate "
                    "in the employee company's currency.", rate=rate_item.name, rate_currency=rate_item.currency_id.name, employee=employee_sudo.name,
                    currency=log.currency_id.name))
            rate = rate_item.price_per_unit
            if log.currency_id.compare_amounts(rate, 0.0) <= 0:
                raise UserError(self.env._("Unit rate '%(rate)s' has no positive price.", rate=rate_item.name))
        else:
            rate = version.hourly_wage if log.type == 'overtime' else version.daily_wage
            if log.currency_id.compare_amounts(rate, 0.0) <= 0:
                field_label = self.env._("Hourly Wage") if log.type == 'overtime' else self.env._("Daily Wage")
                raise UserError(self.env._("Set the %(field)s on %(employee)s's contract before approving.", field=field_label,
                    employee=employee_sudo.name))
        return rate

    def _gec_timesheet_vals(self):
        self.ensure_one()
        project = self.project_id or self.task_id.project_id or self.company_id.internal_project_id
        return {
            'name': self.env._("Overtime: %(reason)s", reason=self.name),
            'project_id': project.id,
            'task_id': self.task_id.id,
            'employee_id': self.employee_id.id,
            'company_id': self.company_id.id,
            'date': self.date,
            'unit_amount': self.hours,
            'work_log_id': self.id,
        }

    def _gec_create_timesheets(self):
        """Mirror approved overtime into timesheets; sudo as approvers may lack timesheet rights."""
        overtime = self.sudo().filtered(lambda log: log.type == 'overtime')
        for company, logs in overtime.grouped('company_id').items():
            self.env['account.analytic.line'].sudo().with_company(company).create([log._gec_timesheet_vals() for log in logs])

    def _gec_unlink_timesheets(self):
        """Remove the mirrors of logs leaving approval; the link is cleared first as mirrors refuse deletion."""
        lines = self.sudo().timesheet_ids
        lines.write({'work_log_id': False})
        lines.unlink()

    def action_approve(self):
        self._ensure_approver()
        for log in self:
            if log.state not in ('draft', 'submitted'):
                raise UserError(self.env._("Only draft or submitted work logs can be approved."))
            employee_sudo = log.sudo().employee_id
            version = employee_sudo._get_version(log.date)
            component_code = log._gec_approval_component(employee_sudo, version)
            rate = log._gec_approval_rate(employee_sudo, version)
            if log.type == 'overtime' and not (log.project_id or log.sudo().task_id.project_id or log.company_id.internal_project_id):
                raise UserError(self.env._("The overtime work log of %(employee)s on %(date)s needs a project, because its hours are recorded as a "
                    "timesheet: set the project on a draft work log, or reject a submitted one so it can be set.", employee=employee_sudo.name,
                    date=log.date))
            if log.type == 'overtime':
                amount = log.hours * rate * int(log.percentage) / 100.0
            elif log.type == 'daily':
                amount = log.units * rate
            else:
                amount = log.unit_qty * rate
            log.sudo()._write_workflow({
                'state': 'approved',
                'version_id': version.id,
                'rate_snapshot': rate,
                'amount_snapshot': log.currency_id.round(amount),
                'component_code_snapshot': component_code,
                'currency_id_snapshot': log.currency_id.id,
                'unit_uom_snapshot_id': log.work_unit_id.uom_id.id if log.type == 'unit' else False,
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
            })
        self._gec_create_timesheets()

    def action_reject(self):
        self._ensure_approver()
        for log in self:
            if log.state != 'submitted':
                raise UserError(self.env._("Only submitted work logs can be rejected."))
            if not log.rejection_reason:
                raise UserError(self.env._("Set a rejection reason first."))
        self._write_workflow({'state': 'rejected'})

    def action_reset_to_draft(self):
        is_payroll = self.env.user.has_group('hr_payroll.group_hr_payroll_officer')
        if not is_payroll:
            self._ensure_owner()
        for log in self:
            if log.state in ('approved', 'cancelled') and not is_payroll:
                raise UserError(self.env._("Only payroll officers can reset approved or cancelled work logs."))
            if log.state == 'approved' and log.sudo().settlement_ids.filtered('active_claim'):
                raise UserError(self.env._("This work log is already in a payslip: cancel that payslip or compute it again first."))
        self._gec_unlink_timesheets()
        self.sudo()._write_workflow({'state': 'draft', **dict.fromkeys(self._GEC_APPROVAL_FIELDS, False)})

    def action_cancel(self):
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_officer'):
            raise UserError(self.env._("Only payroll officers can cancel work logs."))
        for log in self:
            if log.state == 'cancelled':
                continue
            if log.sudo().settlement_ids.filtered('active_claim'):
                raise UserError(self.env._("This work log is already in a payslip: cancel that payslip or compute it again first."))
        self._gec_unlink_timesheets()
        self._write_workflow({'state': 'cancelled'})
