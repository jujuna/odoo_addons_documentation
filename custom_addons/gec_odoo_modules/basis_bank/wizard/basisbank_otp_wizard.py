from odoo import _, fields, models
from odoo.exceptions import UserError


class BasisbankOtpWizard(models.TransientModel):
    _name = 'basisbank.otp.wizard'
    _description = 'Basis Bank OTP Wizard'

    batch_id = fields.Many2one('account.batch.payment', string='Batch', ondelete='cascade')
    payment_id = fields.Many2one('account.payment', string='Payment', ondelete='cascade')
    otp = fields.Char(string='Digipass OTP', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.batch_id and not self.payment_id:
            raise UserError(_("No batch or payment to send."))
        otp = (self.otp or '').strip()
        if not otp:
            raise UserError(_("The Digipass OTP is required."))
        payment = self.payment_id
        batch = self.batch_id
        self.unlink()
        if payment:
            return payment.basisbank_send_with_otp(otp)
        return batch.basisbank_send_with_otp(otp)
