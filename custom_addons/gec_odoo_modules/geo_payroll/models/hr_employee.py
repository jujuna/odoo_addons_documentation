from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.onchange('pay_scheme', 'hourly_source', 'timesheet_pay_project_ids', 'timesheet_pay_start_date')
    def _onchange_gec_timesheet_mode_preview(self):
        if not (self.pay_scheme == 'hourly' and self.hourly_source == 'timesheet'):
            return
        return self.env['hr.version']._gec_timesheet_mode_warning(self._origin, self.company_id, self.timesheet_pay_project_ids._origin,
            self.timesheet_pay_start_date)

    work_log_ids = fields.One2many('hr.employee.work.log', 'employee_id', string='Work Logs')
    pension_fund_member = fields.Boolean(string='Pension Fund Member', groups='hr.group_hr_user', tracking=True, copy=False)
    pay_scheme = fields.Selection(readonly=False, related='version_id.pay_scheme', inherited=True, groups='hr_payroll.group_hr_payroll_user')
    daily_wage = fields.Monetary(readonly=False, related='version_id.daily_wage', inherited=True, groups='hr_payroll.group_hr_payroll_user')
    worklog_ot_enabled = fields.Boolean(readonly=False, related='version_id.worklog_ot_enabled', inherited=True,
        groups='hr_payroll.group_hr_payroll_user')
    worklog_daily_enabled = fields.Boolean(related='version_id.worklog_daily_enabled', inherited=True, groups='hr_payroll.group_hr_payroll_user')
    overtime_pay_mode = fields.Selection(readonly=False, related='version_id.overtime_pay_mode', inherited=True,
        groups='hr_payroll.group_hr_payroll_user')
    timesheet_extra_enabled = fields.Boolean(related='version_id.timesheet_extra_enabled', inherited=True, groups='hr_payroll.group_hr_payroll_user')
    hourly_source = fields.Selection(readonly=False, related='version_id.hourly_source', inherited=True, groups='hr_payroll.group_hr_payroll_user')
    timesheet_pay_start_date = fields.Date(readonly=False, related='version_id.timesheet_pay_start_date', inherited=True,
        groups='hr_payroll.group_hr_payroll_user')
    timesheet_pay_project_ids = fields.Many2many('project.project', related='version_id.timesheet_pay_project_ids', readonly=False, inherited=True,
        groups='hr_payroll.group_hr_payroll_user')

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if not self.env.context.get('gec_pension_sync'):
            for employee, vals in zip(employees, vals_list):
                employee._gec_sync_pension(push='pension_fund_member' in vals)
        return employees

    def write(self, vals):
        """Sync the pension flag with the work contact; core adds work_contact_id when user_id is written."""
        had_contact = {}
        if {'work_contact_id', 'user_id'} & vals.keys():
            had_contact = {employee.id: bool(employee.work_contact_id) for employee in self}
        result = super().write(vals)
        if self.env.context.get('gec_pension_sync'):
            return result
        if 'pension_fund_member' in vals:
            self._gec_sync_pension(push=True)
        elif 'work_contact_id' in vals:
            # a first contact takes the employee's value; a relink takes the new person's value
            for employee in self:
                employee._gec_sync_pension(push=not had_contact[employee.id])
        return result

    def _gec_sync_pension(self, push):
        # sudo: HR users lack partner rights and accountants lack HR rights
        for employee in self.sudo():
            partner = employee.work_contact_id
            if not partner or partner.pension_fund_member == employee.pension_fund_member:
                continue
            if push:
                # unflagged on purpose: the partner write spreads the value to all employees of the contact
                partner.write({'pension_fund_member': employee.pension_fund_member})
            else:
                employee.with_context(gec_pension_sync=True).write({'pension_fund_member': partner.pension_fund_member})
