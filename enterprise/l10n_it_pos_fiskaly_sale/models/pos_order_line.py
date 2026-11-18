from odoo import models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    def _l10n_it_fiskaly_entry_text(self):
        self.ensure_one()
        line = self.refunded_orderline_id or self
        if line.sale_order_line_id and line.order_id.config_id.default_product_id == line.product_id:
            return line.sale_order_line_id.name[:256]
        return super()._l10n_it_fiskaly_entry_text()

    def _l10n_it_fiskaly_is_global_discount(self):
        self.ensure_one()
        return super()._l10n_it_fiskaly_is_global_discount() or (
            self.order_id.config_id.down_payment_product_id == self.product_id
            and self.price_subtotal_incl < 0
        )
