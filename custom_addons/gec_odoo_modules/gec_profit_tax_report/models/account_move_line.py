from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    gec_cit_cell_id = fields.Many2one(
        'rs.cit.cell', string='Profit Tax Row', ondelete='restrict', index='btree_not_null',
        domain="[('kind', '=', 'auto'), ('measure', 'not in', ('market', 'register'))]",
        help="Row of the monthly profit tax declaration this item feeds, instead of the row set on its account.")
    gec_cit_market_value = fields.Monetary(
        string='Market Value', currency_field='company_currency_id', copy=False,
        help="Market value of this invoice line in company currency, for a deal with a related party or a person "
             "exempt from profit tax. A sale below it, or a purchase above it, adds the difference to line 16.3 "
             "or 16.4 of the profit tax declaration.")
