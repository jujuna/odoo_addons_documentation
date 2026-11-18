from odoo import fields, models
from odoo.exceptions import UserError


class AccountAsset(models.Model):
    _inherit = 'account.asset'

    gec_margin_scheme = fields.Selection([
        ('second_hand', 'Second-hand Goods'),
        ('art', 'Work of Art'),
        ('collectible', "Collectors' Item"),
        ('antique', 'Antique'),
    ], string='Margin Scheme',
        help="VAT margin scheme category (annex III-19⁶ of the rs.ge VAT declaration): when the asset is sold, its Asset Value is declared as the "
        "purchase price and the invoice line as the sale price.")


class AccountAssetVariant(models.Model):
    _inherit = 'account.asset.variant'

    def set_to_close(self, invoice_line_ids, date=None, message=None):
        """Remember on the invoice lines which asset they sold (core keeps no link). A new Sell or Dispose drops the
        asset's earlier link, except on an invoice that was credited."""
        taken = invoice_line_ids.filtered(lambda line: line.gec_sold_asset_id - self.asset_id and line.gec_sold_asset_id.state == 'close')
        if taken:
            raise UserError(self.env._("%(line)s already sold %(asset)s: sell each asset on its own invoice line, or click Set to Running on "
                "%(asset)s if it was sold by mistake.", line=taken[0].move_id.display_name, asset=taken[0].gec_sold_asset_id.name))
        res = super().set_to_close(invoice_line_ids, date=date, message=message)
        earlier = self.env['account.move.line'].search([('gec_sold_asset_id', '=', self.asset_id.id)])
        earlier.filtered(lambda line: not line.move_id.reversal_move_ids.filtered(lambda move: move.state == 'posted')).gec_sold_asset_id = False
        invoice_line_ids.gec_sold_asset_id = self.asset_id
        return res
