from odoo import models
from odoo.exceptions import UserError


class MrpConsumptionWarning(models.TransientModel):
    _inherit = 'mrp.consumption.warning'

    def action_set_qty(self):
        if self.env.context.get('barcode_view') and (unscanned_lines := self.mrp_consumption_warning_line_ids.filtered(lambda l:
            l.move_id.has_tracking in ('lot', 'serial')
            and l.move_id._should_bypass_set_qty_producing()
            and l.move_id.uom_id.compare(l.product_consumed_qty_uom, l.product_expected_qty_uom) < 0
        )):
            raise UserError(self.env._(
                "You need to supply a Lot/Serial Number for product:\n%(products)s",
                products="\n".join(f"- {product.display_name}" for product in unscanned_lines.product_id),
            ))
        return super().action_set_qty()
