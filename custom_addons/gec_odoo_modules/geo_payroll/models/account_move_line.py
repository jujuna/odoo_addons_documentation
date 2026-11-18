from odoo import api, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.depends('move_id.payslip_ids')
    def _compute_gec_can_pay(self):
        """Hide the journal-entry Pay button on payslip entries; the payslip has its own."""
        super()._compute_gec_can_pay()
        candidates = self.filtered('gec_can_pay')
        if not candidates:
            return
        # sudo: accountants without payroll rights open these entries.
        payslip_moves = self.env['hr.payslip'].sudo().search([('move_id', 'in', candidates.move_id.ids)]).move_id
        for line in candidates:
            if line.move_id in payslip_moves:
                line.gec_can_pay = False
