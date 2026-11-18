from odoo import api, fields, models
from odoo.exceptions import UserError
from ..models.account_move import SPEC_K_TYPES, SPEC_K_TYPE_HELP


class AccountMoveReversal(models.TransientModel):
    _inherit = 'account.move.reversal'

    rs_spec_k_type = fields.Selection(SPEC_K_TYPES, string='Petroleum Correction Type', help=SPEC_K_TYPE_HELP)
    rs_spec_is_filed = fields.Boolean(string='Petroleum Invoice Filed', compute='_compute_rs_spec_is_filed')

    @api.depends('move_ids')
    def _compute_rs_spec_is_filed(self):
        for wizard in self:
            wizard.rs_spec_is_filed = any(move.rs_einv_is_spec and move.rs_einv_id for move in wizard.move_ids)

    def _rs_spec_assert_not_filed(self):
        spec = self.move_ids.filtered(lambda move: move.rs_einv_is_spec and move.rs_einv_id)
        if spec:
            raise UserError(self.env._("Petroleum invoice %s is filed on rs.ge: correct it with 'Replace RS invoice with a corrected invoice', or "
                "use Reverse with 'Only correct Odoo, not rs.ge'.", ", ".join(spec.mapped('display_name'))))

    def refund_moves(self):
        if self.rs_einv_flow != 'skip':
            self._rs_spec_assert_not_filed()
        return super().refund_moves()

    def modify_moves(self):
        if self.rs_spec_is_filed and self.rs_einv_flow == 'correct_reissue' and len(self.move_ids) == 1:
            return self.move_ids._rs_do_correct_reissue(k_type=self.rs_spec_k_type)
        self._rs_spec_assert_not_filed()
        return super().modify_moves()
