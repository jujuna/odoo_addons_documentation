# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class L10n_Be281_XxWithholdingCheck(models.TransientModel):
    _name = 'l10n_be.281_xx.withholding.check'
    _description = '281.XX Withholding Taxes Check'
    _order = 'report, employee_id, date, origin'

    declaration_id = fields.Many2one('l10n_be.281_xx', required=True, ondelete='cascade')
    currency_id = fields.Many2one('res.currency', related='declaration_id.company_id.currency_id')
    report = fields.Char('Form', required=True)
    employee_id = fields.Many2one('hr.employee')
    origin = fields.Selection([
        ('281', 'Annual Form'),
        ('declared', 'Declared During the Year'),
        ('undeclared', 'Not Declared'),
    ], required=True)
    source = fields.Char('Declaration Type')
    document = fields.Reference(selection=[
        ('l10n_be.274_xx', '274.XX Sheet'),
        ('l10n_be.273_xx', '273.XX Sheet'),
        ('l10n_be.281_xx', '281.XX Form'),
    ])
    date = fields.Date()
    amount_281 = fields.Monetary('281 Withholding Taxes')
    declared_amount = fields.Monetary('Declared Withholding Taxes')
    difference = fields.Monetary(compute='_compute_difference', store=True)
    is_inconsistent = fields.Boolean(
        'Inconsistent',
        help="The withholding taxes of this employee on this form don't match the ones declared during the year.")
    note = fields.Char()

    @api.depends('amount_281', 'declared_amount')
    def _compute_difference(self):
        for line in self:
            line.difference = line.amount_281 - line.declared_amount
