from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    gec_sold_asset_id = fields.Many2one('account.asset', string='Sold Asset', readonly=True, copy=False, index='btree_not_null', ondelete='set null',
        help="The asset this line sold, set by the asset's Sell action; read by the VAT declaration's annex III-19⁶.")
    gec_rc_service = fields.Char(string='Service Type',
        help="Service type shown on the reverse-charge VAT calculation (annex III-19); empty = the product name.")
