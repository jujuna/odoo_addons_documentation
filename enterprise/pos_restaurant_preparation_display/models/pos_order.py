from odoo import models, api


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _load_pos_preparation_data_fields(self):
        res = super()._load_pos_preparation_data_fields()
        return res + ['table_id', 'customer_count']

    def write(self, vals):
        # Notify the preparation display when an order is transferred to another
        # table, so it reflects the new table without needing to be reloaded.
        moved = self.env['pos.order']
        if 'table_id' in vals or 'floating_order_name' in vals:
            moved = self.filtered(
                lambda o: ('table_id' in vals and o.table_id.id != vals['table_id'])
                or ('floating_order_name' in vals and o.floating_order_name != vals['floating_order_name'])
            )
        res = super().write(vals)
        if moved:
            self.env['pos.prep.order']._notify_pdis(moved.ids)
        return res
