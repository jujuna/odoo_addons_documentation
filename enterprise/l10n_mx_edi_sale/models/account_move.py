from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def copy_data(self, default=None):
        """Extends 'account'.
        Credit notes for advance payments must have a specific description.
        See Anexo 20 (2026), Appendix 6, pg 73.
        """
        data_vals = super().copy_data(default)
        for move, move_vals in zip(self, data_vals):
            if (move.country_code == 'MX'
                and move.move_type == 'out_invoice'
                and move_vals['move_type'] == 'out_refund'
                and move._is_downpayment()
            ):
                for line_vals in move_vals['line_ids']:
                    if line_vals[2]['is_downpayment']:
                        line_vals[2]['name'] = 'Aplicación de anticipo'
        return data_vals
