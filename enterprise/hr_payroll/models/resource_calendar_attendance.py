# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResourceCalendarAttendance(models.Model):
    _inherit = "resource.calendar.attendance"

    category_options_ids = fields.Many2many('hr.salary.rule.category', string="Payroll Options", groups="hr_payroll.group_hr_payroll_user",
        domain="[('optional_on_work_entry_type_ids', 'in', work_entry_type_id)]")
    has_category_options = fields.Boolean(compute='_compute_has_category_options', groups="hr_payroll.group_hr_payroll_user")

    @api.depends('work_entry_type_id.optional_category_ids')
    def _compute_has_category_options(self):
        for attendance in self:
            attendance.has_category_options = bool(attendance.work_entry_type_id.optional_category_ids)
