# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    category_options_ids = fields.Many2many(
        'hr.salary.rule.category',
        string='Payroll Options',
        groups='hr_payroll.group_hr_payroll_user',
        domain="[('optional_on_work_entry_type_ids', 'in', work_entry_type_id)]",
    )

    payslip_id = fields.Many2one(
        'hr.payslip',
        string="Payslip",
        compute="_compute_payslip_id",
        groups="hr_payroll.group_hr_payroll_user",
    )

    @api.depends('employee_id', 'check_in', 'check_out')
    def _compute_payslip_id(self):
        valid_attendances = self.filtered(lambda a: a.employee_id and a.check_in and a.check_out)
        (self - valid_attendances).payslip_id = False
        if not valid_attendances:
            return

        # Search the payslips of all the attendances at once
        check_in_dates = {attendance: attendance._get_localized_times()[0].date() for attendance in valid_attendances}
        payslips_per_employee = self.env['hr.payslip'].search_fetch(
            [
                ('employee_id', 'in', valid_attendances.employee_id.ids),
                ('date_from', '<=', max(check_in_dates.values())),
                ('date_to', '>=', min(check_in_dates.values())),
                ('state', 'not in', ['draft', 'cancel']),
            ],
            ['employee_id', 'date_from', 'date_to'],
            order='date_from desc, id desc',
        ).grouped('employee_id')
        for attendance in valid_attendances:
            check_in_date = check_in_dates[attendance]
            attendance.payslip_id = next((
                payslip for payslip in payslips_per_employee.get(attendance.employee_id, [])
                if payslip.date_from <= check_in_date <= payslip.date_to
            ), False)

    def _get_payslip_domain(self):
        self.ensure_one()
        localized_check_in, _localized_check_out = self._get_localized_times()
        return [
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '<=', localized_check_in.date()),
            ('date_to', '>=', localized_check_in.date()),
            ('state', 'not in', ['draft', 'cancel']),
        ]

    def action_open_payslip(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.payslip_id.display_name,
            'res_model': 'hr.payslip',
            'res_id': self.payslip_id.id,
            'view_mode': 'form',
        }
