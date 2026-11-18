import json
from contextvars import ContextVar
from functools import wraps

from odoo import fields, models
from odoo.addons.base.models.res_users import _jsonable
from odoo.exceptions import UserError
from odoo.http import request

_confirmed = ContextVar('gec_gosms_confirmed', default=None)


def gosms_confirm(phone_path):
    """Run the button only after the user types the SMS code sent to ``phone_path`` (one phone, through many2one fields).

    Users who click must not be able to edit that phone. Decorate your own buttons only: the dialog calls the method again."""
    def decorator(fn):
        @wraps(fn)
        def wrapped(self, *args, **kwargs):
            if _confirmed.get() == (self._name, tuple(self.ids), fn.__name__):
                return fn(self, *args, **kwargs)
            if not request:
                raise UserError(self.env._("This action needs an SMS code, so it can only be run from the Odoo screen."))
            if len(self) != 1:
                raise UserError(self.env._("Select one record at a time: each SMS code confirms one record."))
            numbers = self.mapped(phone_path)
            if len(numbers) != 1 or not numbers[0]:
                raise UserError(self.env._("Add a phone number first: the confirmation code is sent to it by SMS."))
            phone = self._phone_format(number=numbers[0])
            if not phone:
                raise UserError(self.env._("The phone number %s is not valid. Correct it and try again.", numbers[0]))
            phone = phone.lstrip('+')
            company = self._mail_get_companies(default=self.env.company)[self.id]
            otp = company._gosms_send_code(phone)
            # sudo: request, phone and hash are NO_ACCESS so users cannot change where the code goes, as in core identitycheck
            wizard = self.env['gosms.confirm.wizard'].sudo().create({
                'request': json.dumps([{k: v for k, v in self.env.context.items() if _jsonable(v)}, self._name, self.ids, fn.__name__, args, kwargs]),
                'company_id': company.id,
                'phone': phone,
                'otp_hash': otp['hash'],
                'attempts_left': otp.get('rate_limit_remaining'),
            })
            return wizard._gosms_action()
        wrapped._gosms_confirm = True
        return wrapped
    return decorator


class GosmsConfirmWizard(models.TransientModel):
    _name = 'gosms.confirm.wizard'
    _description = "SMS Code Confirmation"

    request = fields.Char(readonly=True, groups=fields.NO_ACCESS)
    company_id = fields.Many2one('res.company', readonly=True, ondelete='cascade', groups=fields.NO_ACCESS)
    phone = fields.Char(readonly=True, groups=fields.NO_ACCESS)
    otp_hash = fields.Char(readonly=True, groups=fields.NO_ACCESS)
    attempts_left = fields.Integer(readonly=True)
    code = fields.Char(store=False)

    def _gosms_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'name': self.env._("Code sent to %s", self._phone_format(number=f'+{self.phone}', force_format='INTERNATIONAL')),
            'target': 'new',
            'views': [(False, 'form')],
            'context': {'dialog_size': 'medium'},
        }

    def action_resend(self):
        self.ensure_one()
        self.check_access('read')
        wizard = self.sudo()  # sudo: the hash is NO_ACCESS; the check above limits this to the user's own dialog
        otp = wizard.company_id._gosms_send_code(wizard.phone)
        wizard.write({'otp_hash': otp['hash'], 'attempts_left': otp.get('rate_limit_remaining')})
        return wizard._gosms_action()

    def action_confirm(self):
        self.ensure_one()
        self.check_access('read')
        code = self.env.context.get('gosms_code')
        if not code:
            raise UserError(self.env._("Type the code from the SMS first."))
        wizard = self.sudo()  # sudo: request, phone and hash are NO_ACCESS; the check above limits this to the user's own dialog
        answer = wizard.company_id._gosms_check_code(wizard.phone, wizard.otp_hash, code)
        if not answer['verify']:
            left = answer.get('rate_limit_remaining')
            if left is None:
                raise UserError(self.env._("The code is wrong. Check the SMS and try again."))
            raise UserError(self.env._("The code is wrong. Attempts left: %s.", left))
        wizard.otp_hash = False
        ctx, model, ids, method, args, kwargs = json.loads(wizard.request)
        records = self.env(context=ctx)[model].browse(ids)
        action = getattr(records, method)
        assert getattr(action, '_gosms_confirm', False)
        token = _confirmed.set((model, tuple(ids), method))
        try:
            result = action(*args, **kwargs)
        finally:
            _confirmed.reset(token)
        if isinstance(records, self.pool['mail.thread']):
            phone = self._phone_format(number=f'+{wizard.phone}', force_format='INTERNATIONAL')
            records._message_log_batch(dict.fromkeys(records.ids, self.env._("Confirmed with the SMS code sent to %s.", phone)))
        return result
