from odoo import api, models
from odoo.exceptions import UserError

from .gec_vat_declaration import name_list


class AccountMove(models.Model):
    _inherit = 'account.move'

    def button_draft(self):
        # sudo: the user resetting a bill may not see the calculation
        rc_lines = self.env['gec.vat.rc.line'].sudo().search([('move_id', 'in', self.ids), ('declaration_id.state', '=', 'filed')])
        if rc_lines:
            raise UserError(self.env._("The filed declaration %(names)s lists %(moves)s: reset it to draft first.",
                names=', '.join(sorted(rc_lines.declaration_id.mapped('name'))),
                moves=name_list(self.env, sorted(rc_lines.move_id.mapped('display_name')))))
        return super().button_draft()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_filed_declaration(self):
        filed = ('declaration_id.state', '=', 'filed')
        # sudo: the user deleting a move may not see the declaration
        rc_lines = self.env['gec.vat.rc.line'].sudo().search([('move_id', 'in', self.ids), filed])
        invoice_lines = self.env['gec.vat.invoice.line'].sudo().search([('move_id', 'in', self.ids), filed])
        advance_lines = self.env['gec.vat.advance.line'].sudo().search([('settlement_id.final_move_id', 'in', self.ids), filed])
        if rc_lines or invoice_lines or advance_lines:
            declarations = rc_lines.declaration_id.mapped('name') + (invoice_lines.declaration_id | advance_lines.declaration_id).mapped('name')
            moves = rc_lines.move_id | invoice_lines.move_id | advance_lines.settlement_id.final_move_id
            raise UserError(self.env._("The filed declaration %(names)s lists %(moves)s: reset it to draft first.",
                names=', '.join(sorted(declarations)), moves=name_list(self.env, sorted(moves.mapped('display_name')))))
