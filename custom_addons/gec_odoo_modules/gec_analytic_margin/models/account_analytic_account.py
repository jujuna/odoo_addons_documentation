from odoo import models, fields


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    gec_function_component_id = fields.Many2one(
        'gec.margin.component', string='Function',
        domain="[('is_function', '=', True)]", ondelete='restrict',
        help="What this cost centre's money is for, in a company reporting its P&L by function: Cost of Sales for a delivery team, R&D for product engineering, Sales & Marketing, G&A. Personnel and overhead booked here are read under it. An activity's own function takes precedence for the cost it charges out.",
    )

    gec_revenue_stream_id = fields.Many2one(
        'gec.revenue.stream', string='Revenue Stream', ondelete='restrict',
        help="Revenue booked on this analytic account is this kind of revenue — "
             "set it on a product line (Licenses, Support Contracts) when one "
             "income account carries every kind. Takes precedence over the "
             "stream on the GL account.",
    )
    gec_headcount = fields.Integer(
        string='Headcount',
        help="Number of employees attributed to this analytic account. Used as "
             "the allocation base by rules whose driver is 'Headcount share'. "
             "Only needed on the accounts an allocation targets.",
    )
