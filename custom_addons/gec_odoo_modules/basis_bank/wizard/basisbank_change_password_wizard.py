from odoo import _, fields, models
from odoo.exceptions import UserError


class BasisbankChangePasswordWizard(models.TransientModel):
    _name = 'basisbank.change.password.wizard'
    _description = 'Basis Bank Change Password Wizard'

    connection_id = fields.Many2one('basisbank.connection', string='Connection', required=True, ondelete='cascade')
    new_password = fields.Char(string='New Password', required=True)
    confirm_password = fields.Char(string='Confirm New Password', required=True)
    otp = fields.Char(string='Digipass OTP', required=True)

    def action_change_password(self):
        """Validate inputs and change the connection's Basis Bank password."""
        self.ensure_one()
        new_password = (self.new_password or '').strip()
        if not new_password:
            raise UserError(_("New password is required."))
        if new_password != (self.confirm_password or '').strip():
            raise UserError(_("The new password and its confirmation do not match."))
        otp = (self.otp or '').strip()
        if not otp:
            raise UserError(_("OTP is required."))
        self.connection_id.basisbank_change_password(new_password, otp)
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Basis Bank"),
                'message': _("Password changed successfully."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
