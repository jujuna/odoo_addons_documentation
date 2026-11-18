from odoo import models, fields


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    # The same function lines as the P&L, so headcount and cost are split the same way.
    gec_function_component_id = fields.Many2one(
        'gec.margin.component', string='P&L Function',
        domain="[('is_function', '=', True)]", ondelete='restrict',
        help="What this department's people are for — Cost of Sales for "
             "implementation and support, R&D for product engineering, Sales & "
             "Marketing, G&A. The dashboard splits average FTE by it.",
    )
