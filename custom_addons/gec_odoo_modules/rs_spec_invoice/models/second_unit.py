from odoo import fields, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    rs_spec_alt_qty = fields.Float('Alt. Quantity', digits='Product Unit')
    rs_spec_alt_uom_id = fields.Many2one('uom.uom', string='Alt. Unit', ondelete='restrict')


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    rs_spec_alt_qty = fields.Float('Alt. Quantity', digits='Product Unit')
    rs_spec_alt_uom_id = fields.Many2one('uom.uom', string='Alt. Unit', ondelete='restrict')


class StockMove(models.Model):
    _inherit = 'stock.move'

    rs_spec_alt_qty = fields.Float('Alt. Quantity', digits='Product Unit', copy=False)
    rs_spec_alt_uom_id = fields.Many2one('uom.uom', string='Alt. Unit', ondelete='restrict', copy=False)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    rs_spec_alt_qty = fields.Float('Alt. Quantity', digits='Product Unit', copy=False)
    rs_spec_alt_uom_id = fields.Many2one('uom.uom', string='Alt. Unit', ondelete='restrict', copy=False)
