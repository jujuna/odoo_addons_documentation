from odoo import api, fields, models
from odoo.exceptions import UserError

_RS_SYNCED_LINE_FIELDS = ('product_id', 'quantity', 'price_unit', 'discount', 'product_uom_id', 'tax_ids', 'name')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    rs_line_id = fields.Char(string='rs.ge Line ID', copy=False, readonly=True,
        help="ID of the rs.ge line this bill line was imported from. Reimport Lines matches on it first, then on the line name.")

    def _rs_check_sent_correction_lines(self, moves):
        """A draft seller correction already sent to the buyer must keep the lines rs.ge holds; posting it runs with the context key."""
        if self.env.su or self.env.context.get('rs_post_accepted_correction'):
            return
        for move in moves:
            if move.state == 'draft' and move._rs_is_sale_correction() and move.rs_einv_status in ('5', '8'):
                raise UserError(self.env._("%s was sent to the buyer on rs.ge: its lines can no longer change.", move.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        move_ids = {vals['move_id'] for vals in vals_list if vals.get('move_id') and vals.get('display_type', 'product') == 'product'}
        self._rs_check_sent_correction_lines(self.env['account.move'].browse(move_ids))
        return super().create(vals_list)

    def write(self, vals):
        if any(field in vals for field in _RS_SYNCED_LINE_FIELDS):
            self._rs_check_sent_correction_lines(self.filtered(lambda line: line.display_type == 'product').move_id)
        return super().write(vals)

    def unlink(self):
        self._rs_check_sent_correction_lines(self.filtered(lambda line: line.display_type == 'product').move_id)
        return super().unlink()
