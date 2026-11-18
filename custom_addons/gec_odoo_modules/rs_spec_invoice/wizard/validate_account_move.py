from odoo import models


class ValidateAccountMove(models.TransientModel):
    _inherit = 'validate.account.move'

    def validate_move(self):
        self.move_ids._rs_spec_mark_before_post()
        return super().validate_move()
