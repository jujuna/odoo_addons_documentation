from odoo import models, fields


class BudgetLine(models.Model):
    _inherit = 'budget.line'

    general_account_id = fields.Many2one(
        'account.account',
        string='GL Account',
        ondelete='restrict',
        index='btree_not_null',
        check_company=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        help="GL account this budget line applies to — the budget position "
             "(RP-xx / CP-xx).\n\n"
             "Odoo's own Budget vs Actual ignores this field: it matches actuals "
             "by account type only (income vs expense). Use the Analytic Margin "
             "report to compare budget and actual per GL account.",
    )
