from odoo import _, fields, models
from odoo.exceptions import UserError


class RsAuthPinWizard(models.TransientModel):
    _name = 'rs.auth.pin.wizard'
    _description = 'RS 2-Step Authentication — PIN Entry'

    user_id = fields.Many2one('res.users', string='User', required=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True, default=lambda self: self.env.company,
        help="The company whose rs.ge login is being paired; the token and the device code are stored for it.")
    pin_token = fields.Char(string='PIN Token', required=True, readonly=True)
    masked_mobile = fields.Char(string='Phone', readonly=True, help="Masked mobile number where the SMS PIN was sent.")
    pin = fields.Char(string='SMS PIN', help="4-digit code that arrived on the phone shown above.")

    def action_confirm(self):
        self.ensure_one()
        if not self.pin or not self.pin.strip():
            raise UserError(_("Enter the SMS PIN first."))
        user = self.user_id.with_company(self.company_id)
        user._rs_rest_complete_pin(self.pin_token, self.pin.strip())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Revenue Service — REST (employee registry)"),
                'message': _("Device paired. RS will skip the SMS step for this device from now on. Token expires at %s.",
                    fields.Datetime.to_string(user.sudo().rs_token_expiry)),
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
