from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    work_log_ids = fields.One2many('hr.employee.work.log', 'user_id', string='Work Logs', user_writeable=True)
