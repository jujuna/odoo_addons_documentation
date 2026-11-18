from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class HrPayrollComponentSettlement(models.Model):
    _name = 'hr.payroll.component.settlement'
    _description = 'Work Log or Timesheet in a Payslip'
    _order = 'id desc'
    _allow_sudo_commands = False
    _check_company_auto = True

    work_log_id = fields.Many2one('hr.employee.work.log', index=True, ondelete='set null', check_company=True)
    timesheet_line_id = fields.Many2one('account.analytic.line', index=True, ondelete='set null', check_company=True)
    payslip_id = fields.Many2one('hr.payslip', index=True, ondelete='set null', check_company=True)
    payslip_ref = fields.Char(string='Payslip Reference')
    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict')
    currency_id = fields.Many2one('res.currency', required=True, ondelete='restrict')
    component_code = fields.Selection([
        ('worklog_ot', 'Overtime'),
        ('worklog_daily', 'Daily Work'),
        ('daily_basic', 'Daily Work (Base Pay)'),
        ('timesheet_basic', 'Timesheet (Base Pay)'),
        ('timesheet_extra', 'Timesheet (Extra Pay)'),
        ('unit_basic', 'Unit Work (Base Pay)'),
        ('unit_extra', 'Unit Work (Extra Pay)'),
    ], string='Pay Type', required=True, index=True)
    source_version_id = fields.Many2one('hr.version', string='Contract', index=True, ondelete='set null',
        help="The contract whose wage or rate priced this row: the contract on the work date, not the contract of the payslip.")
    date = fields.Date(string='Work Date', required=True)
    quantity = fields.Float(help="Hours for overtime and timesheets, days for daily work, quantity for unit work.")
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', ondelete='restrict',
        help="Only for unit work: the unit the work log was approved with.")
    rate = fields.Monetary(aggregator=None)
    amount = fields.Monetary(required=True)
    active_claim = fields.Boolean(string='In Payslip', default=True, index=True)
    release_reason = fields.Char(string='Removal Reason')
    released_at = fields.Datetime(string='Removed On')
    project_id = fields.Many2one('project.project', compute='_compute_source_project', compute_sudo=True)
    task_id = fields.Many2one('project.task', compute='_compute_source_project', compute_sudo=True)

    _one_live_claim_per_log = models.UniqueIndex("(work_log_id) WHERE active_claim AND work_log_id IS NOT NULL")
    _one_live_claim_per_timesheet = models.UniqueIndex("(timesheet_line_id) WHERE active_claim AND timesheet_line_id IS NOT NULL")

    @api.depends('work_log_id.project_id', 'work_log_id.task_id', 'timesheet_line_id.project_id', 'timesheet_line_id.task_id')
    def _compute_source_project(self):
        for settlement in self:
            source = settlement.timesheet_line_id or settlement.work_log_id
            settlement.project_id = source.project_id
            settlement.task_id = source.task_id

    @api.constrains('work_log_id', 'timesheet_line_id', 'active_claim')
    def _check_one_source(self):
        for settlement in self:
            if settlement.work_log_id and settlement.timesheet_line_id:
                raise ValidationError(self.env._("A row must come from a work log or from a timesheet line, not from both."))
            if settlement.active_claim and not settlement.work_log_id and not settlement.timesheet_line_id:
                raise ValidationError(self.env._("A row that is in a payslip must come from a work log or a timesheet line."))

    def write(self, vals):
        raise UserError(self.env._("These rows are written by payroll and cannot be edited: compute the payslip again to refresh them."))

    def _write_release(self, vals):
        """Write release metadata outside the RPC path."""
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_forbidden(self):
        raise UserError(self.env._("These rows are the record of what each payslip paid and cannot be deleted."))

    def _release(self, reason):
        self._write_release({'active_claim': False, 'release_reason': reason, 'released_at': fields.Datetime.now()})
