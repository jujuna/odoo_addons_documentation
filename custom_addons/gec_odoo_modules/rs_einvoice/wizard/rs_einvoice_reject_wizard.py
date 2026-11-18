from odoo import models, fields, _
from odoo.exceptions import UserError


class RsRejectWizard(models.TransientModel):
    _name = 'rs.einvoice.reject.wizard'
    _description = 'RS E-Invoice Buyer Rejection Wizard'

    move_id = fields.Many2one('account.move', string='Vendor Bill', required=True, readonly=True, ondelete='cascade')
    reason = fields.Text(string='Rejection Reason', required=True,
        help="This is sent to the supplier on rs.ge. Be specific so they can fix the invoice on the first try (for example: 'Quantity differs — "
        "invoice says 12, delivery says 10' or 'VAT rate should be 0% — intra-EU export').")

    _MAX_REASON_LEN = 480

    def action_confirm(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if len(reason) > self._MAX_REASON_LEN:
            raise UserError(_("Rejection reason is too long (%(n)d characters). rs.ge would cut it without warning — shorten to %(max)d characters "
                "or fewer.", n=len(reason), max=self._MAX_REASON_LEN))
        self.move_id._rs_do_buyer_reject(reason)
        return {'type': 'ir.actions.act_window_close'}
