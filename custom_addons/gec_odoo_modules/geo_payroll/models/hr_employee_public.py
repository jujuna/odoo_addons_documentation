from odoo import fields, models


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    work_log_ids = fields.One2many('hr.employee.work.log', 'employee_id', string='Work Logs')
