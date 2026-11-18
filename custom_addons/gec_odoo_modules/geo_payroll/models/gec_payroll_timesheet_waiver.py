from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from .tools import gec_lock_for_update


class GecPayrollTimesheetWaiver(models.TransientModel):
    _name = 'gec.payroll.timesheet.waiver'
    _description = 'Waive Payroll Pay on Timesheets'

    line_ids = fields.Many2many('account.analytic.line', string='Timesheets to Waive',
        help="The selected timesheets that payroll would pay and that are not in a payslip; once waived, payroll never pays them.")
    reason = fields.Char(required=True)

    @api.model
    def default_get(self, fields_list):
        """Preselect the waivable lines; set after super(), so it must be x2many commands."""
        defaults = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if active_ids and 'line_ids' in fields_list:
            lines = self.env['account.analytic.line'].browse(active_ids)
            defaults['line_ids'] = [Command.set(lines._gec_waivable_payroll_lines().ids)]
        return defaults

    def action_waive(self):
        self.ensure_one()
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_manager'):
            raise UserError(self.env._("Only payroll managers can waive payroll pay on timesheets."))
        lines = self.line_ids.sudo()
        if not lines:
            raise UserError(self.env._("None of the selected timesheets can be waived: select timesheets that payroll would pay, that are not in a "
                "payslip and are not waived yet."))
        gec_lock_for_update(lines)
        lines.invalidate_recordset()
        outside = lines - lines._gec_waivable_payroll_lines()
        if outside:
            raise UserError(self.env._("These timesheets can no longer be waived (already in a payslip, already waived, or no longer paid by "
                "payroll): %(names)s.", names=', '.join(outside.mapped('name'))))
        lines._gec_waive_payroll_pay(self.reason)
        return {'type': 'ir.actions.act_window_close'}
