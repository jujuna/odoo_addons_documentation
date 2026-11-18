from odoo import api, fields, models


class HrPayrollTaxExemption(models.Model):
    _name = 'hr.payroll.tax.exemption'
    _inherit = ['mail.thread']
    _description = 'Income Tax Exemption Category'
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    yearly_limit = fields.Float(required=True, tracking=True,
        help="Gross income per calendar year exempt from income tax for the assigned employees. Once the cumulative payslip gross of the year passes "
        "this limit, the excess is taxed normally.")
    employee_ids = fields.Many2many('hr.employee', string='Employees', tracking=True)
    employee_count = fields.Integer(compute='_compute_employee_count')
    active = fields.Boolean(default=True, tracking=True)

    @api.depends('employee_ids')
    def _compute_employee_count(self):
        for exemption in self:
            exemption.employee_count = len(exemption.employee_ids)
