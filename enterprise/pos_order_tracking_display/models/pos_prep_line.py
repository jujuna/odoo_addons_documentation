from odoo import models


class PosPrepLine(models.Model):
    _inherit = 'pos.prep.line'

    def change_state_status(self, todos):
        res = super().change_state_status(todos)
        # Status changes now happen on the preparation lines themselves,
        # so refresh each affected customer display after its regular
        # preparation-display notification has been sent.
        for pdis in self.stage_id.prep_display_ids:
            pdis._send_orders_to_customer_display()
        return res

    def change_prep_line_stage(self, prep_display_id, direction=1):
        res = super().change_prep_line_stage(prep_display_id, direction)
        self.env['pos.prep.display'].browse(int(prep_display_id))._send_orders_to_customer_display()
        return res
