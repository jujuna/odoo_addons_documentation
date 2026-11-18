from odoo import fields, models
from odoo.exceptions import UserError


class GosmsSendWizard(models.TransientModel):
    _name = 'gosms.send.wizard'
    _description = "Send SMS"

    numbers = fields.Char("Phone Numbers", help="Separate the numbers with commas.")
    body = fields.Text("Message")
    urgent = fields.Boolean("Deliver even to numbers that blocked SMS", help="Use it only for messages that must arrive, such as security alerts.")

    def action_send(self):
        self.ensure_one()
        if not self.env.company.gosms_sms_enabled:
            raise UserError(self.env._('Turn on "Send Odoo SMS through GoSMS" in Settings first.'))
        composer = self.env['sms.composer'].new({'composition_mode': 'numbers', 'numbers': self.numbers})
        # sudo: sms.sms is system-only, as in the core composer
        sms = self.env['sms.sms'].sudo().create([{
            'number': number,
            'body': self.body,
            'gosms_urgent': self.urgent,
        } for number in composer.sanitized_numbers.split(',')])
        sms.send()
        failed = sms.filtered(lambda sms: sms.state == 'error')
        message = self.env._("%(sent)s of %(total)s SMS sent.", sent=len(sms) - len(failed), total=len(sms))
        # sudo: the message log is for administrators, every user who sends needs the reason
        domain = [('sms_uuid', 'in', failed.mapped('uuid')), ('failure_reason', '!=', False)]
        reason = self.env['gosms.message'].sudo().search(domain, limit=1, order='id').failure_reason
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning' if failed else 'success',
                'message': f'{message} {reason}' if reason else message,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
