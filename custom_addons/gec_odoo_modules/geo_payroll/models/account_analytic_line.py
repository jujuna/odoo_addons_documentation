from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    gec_settlement_ids = fields.One2many('hr.payroll.component.settlement', 'timesheet_line_id', groups='hr_payroll.group_hr_payroll_user')
    gec_payroll_waived_at = fields.Datetime(string='Payroll Pay Waived On', copy=False, readonly=True, groups='hr_payroll.group_hr_payroll_user',
        help="When a payroll manager excluded this timesheet from payroll for good, e.g. before changing the employee's pay scheme.")
    gec_payroll_waived_by_id = fields.Many2one('res.users', string='Payroll Pay Waived By', copy=False, readonly=True, ondelete='set null',
        groups='hr_payroll.group_hr_payroll_user')
    gec_payroll_waive_reason = fields.Char(string='Payroll Waive Reason', copy=False, readonly=True, groups='hr_payroll.group_hr_payroll_user')
    work_log_id = fields.Many2one('hr.employee.work.log', string='Work Log', copy=False, readonly=True, index='btree_not_null', ondelete='cascade',
        help="The approved overtime work log that created this timesheet; its hours are paid through the work log, not as timesheet hours.")

    _GEC_LOCKED_FIELDS = {'unit_amount', 'employee_id', 'date', 'project_id', 'task_id', 'company_id'}
    _GEC_WAIVER_FIELDS = {'gec_payroll_waived_at', 'gec_payroll_waived_by_id', 'gec_payroll_waive_reason'}

    def _gec_has_active_claim(self):
        return bool(self.sudo().gec_settlement_ids.filtered('active_claim'))

    def _gec_waivable_payroll_lines(self):
        waivable = self.browse()
        for line in self.sudo():
            if line.gec_payroll_waived_at or line._gec_has_active_claim():
                continue
            version = line.employee_id._get_version(line.date) if line.employee_id else False
            if version and version._gec_timesheet_line_eligible(line):
                waivable |= line
        return waivable

    def _is_readonly(self):
        """Overtime mirrors are read-only here; the work log is the record."""
        return super()._is_readonly() or bool(self.work_log_id)

    def _check_can_write(self, values):
        """Refuse user edits of overtime mirrors; the work log writes them under sudo."""
        if not self.env.su and (self.work_log_id or 'work_log_id' in values):
            raise UserError(self.env._("Timesheets created from an overtime work log follow that work log. Change, reset or cancel the work log "
                "instead."))
        return super()._check_can_write(values)

    def write(self, vals):
        if self._GEC_WAIVER_FIELDS & vals.keys():
            raise UserError(self.env._("Use the Waive Payroll Pay and Restore Payroll Pay actions to change this."))
        if self._GEC_LOCKED_FIELDS & vals.keys():
            for line in self:
                if line._gec_has_active_claim():
                    raise UserError(self.env._("This timesheet is already in a payslip: cancel or delete that payslip before changing it."))
                if line.sudo().gec_payroll_waived_at:
                    raise UserError(self.env._("Payroll pay was waived on this timesheet, so its hours, date, employee, project and task cannot "
                        "change: ask a payroll manager to restore its payroll pay first."))
        return super().write(vals)

    def _gec_write_waiver(self, vals):
        """Write waiver stamps outside the RPC path."""
        return super().write(vals)

    def _gec_waive_payroll_pay(self, reason):
        self._gec_write_waiver({
            'gec_payroll_waived_at': fields.Datetime.now(),
            'gec_payroll_waived_by_id': self.env.user.id,
            'gec_payroll_waive_reason': reason,
        })

    def action_gec_restore_payroll_pay(self):
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_manager'):
            raise UserError(self.env._("Only payroll managers can restore payroll pay on a waived timesheet."))
        self.sudo().filtered('gec_payroll_waived_at')._gec_write_waiver({
            'gec_payroll_waived_at': False,
            'gec_payroll_waived_by_id': False,
            'gec_payroll_waive_reason': False,
        })

    @api.ondelete(at_uninstall=False)
    def _gec_unlink_claimed(self):
        for line in self:
            if line._gec_has_active_claim():
                raise UserError(self.env._("This timesheet is already in a payslip and cannot be deleted: cancel or delete that payslip first."))
            if line.sudo().gec_payroll_waived_at:
                raise UserError(self.env._("Payroll pay was waived on this timesheet, so it cannot be deleted: ask a payroll manager to restore its "
                    "payroll pay first."))

    @api.ondelete(at_uninstall=False)
    def _gec_unlink_work_log_lines(self):
        """An overtime mirror goes only with its work log's reset or cancel."""
        if any(line.work_log_id for line in self):
            raise UserError(self.env._("Timesheets created from an overtime work log cannot be deleted. Reset or cancel the work log instead."))
