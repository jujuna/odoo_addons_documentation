from odoo import models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _rs_try_create_waybill(self):
        """The ნსაფ replaces the rs.ge waybill: a transfer of petroleum products only gets none."""
        products = self.move_ids.product_id
        if products and not products.filtered(lambda product: not product.rs_spec_rs_id):
            return
        return super()._rs_try_create_waybill()
