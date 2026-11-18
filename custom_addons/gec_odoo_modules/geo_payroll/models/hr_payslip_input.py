from odoo import fields, models


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'

    benefit_line_id = fields.Many2one('hr.payroll.benefit.line', index='btree_not_null', ondelete='cascade')
