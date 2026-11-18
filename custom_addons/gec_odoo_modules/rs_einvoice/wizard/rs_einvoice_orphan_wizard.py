from odoo import models, fields


class RsOrphanResolveWizard(models.TransientModel):
    """Link an rs.ge draft created by a timed-out SOAP call; party is verified before linking."""
    _name = 'rs.einvoice.orphan.resolve.wizard'
    _description = 'RS E-Invoice Orphan Resolver'

    move_id = fields.Many2one('account.move', string='Move', required=True, readonly=True, ondelete='cascade')
    candidate_id = fields.Char(string='Suspected rs.ge ID', required=True,
        help="Open rs.ge in your browser, find the orphan in your recent drafts list, and paste its ID here.")

    def action_confirm(self):
        self.ensure_one()
        self.move_id._rs_do_resolve_orphan(self.candidate_id)
        return {'type': 'ir.actions.act_window_close'}
