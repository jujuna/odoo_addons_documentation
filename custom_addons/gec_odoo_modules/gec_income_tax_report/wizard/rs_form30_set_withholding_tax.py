from odoo import Command, api, fields, models


class RsForm30SetWithholdingTax(models.TransientModel):
    """Pick the Withholding Tax of a posted entry's expense lines."""
    _name = 'rs.form30.set.withholding.tax'
    _description = 'Set Withholding Tax'
    _check_company_auto = True

    move_id = fields.Many2one('account.move', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='move_id.company_id')
    line_ids = fields.Many2many('account.move.line', 'rs_form30_set_wht_line_rel', 'wizard_id', 'line_id', string='Expense Lines',
        domain="[('move_id', '=', move_id), ('balance', '>', 0)]")
    tax_id = fields.Many2one('account.tax', string='Withholding Tax', required=True, ondelete='cascade', check_company=True,
        domain="[('gec_is_withholding', '=', True), ('rs_form30_income_type_id', '!=', False), ('company_id', 'parent_of', company_id)]")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        move = self.env['account.move'].browse(defaults.get('move_id'))
        if move:
            move._rs_form30_check_can_set_withholding()
            expense_lines, candidates = move._rs_form30_candidates(move._rs_form30_get_rules(), move._rs_form30_get_taxes())
            lines = expense_lines | move.line_ids.filtered(lambda line: line.balance > 0 and line.tax_ids.filtered('gec_is_withholding'))
            current = lines.tax_ids.filtered('gec_is_withholding')
            defaults['line_ids'] = [Command.set(lines.ids)]
            if len(current) == 1:
                defaults['tax_id'] = current.id
            elif not current and len(candidates) == 1:
                defaults['tax_id'] = candidates.id
        return defaults

    def action_apply(self):
        """Set the chosen tax on the selected lines as a hand pick (never replaced by the proposal), then repost the
        entry. The entry goes to draft first because core refuses tax changes on posted lines."""
        self.ensure_one()
        move = self.move_id
        move._rs_form30_check_can_set_withholding()
        move._check_fiscal_lock_dates()
        move.button_draft()
        for line in self.line_ids:
            old = line.tax_ids.filtered('gec_is_withholding') - self.tax_id
            vals = {'tax_ids': [Command.unlink(tax.id) for tax in old] + [Command.link(self.tax_id.id)]}
            if line.rs_form30_proposed_tax_id == self.tax_id:
                vals['rs_form30_proposed_tax_id'] = False
            line.write(vals)
        move.action_post()
        return {'type': 'ir.actions.act_window_close'}
