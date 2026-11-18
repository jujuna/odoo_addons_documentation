from odoo import fields, models

STATUS_TO_STATE = {'DELIVERED': 'delivered', 'EXPIRED': 'expired', 'UNDELIVERED': 'undelivered'}
STATUS_TO_PROVIDER_ERROR = {'EXPIRED': 'expired', 'UNDELIVERED': 'not_delivered'}


class GosmsMessage(models.Model):
    _name = 'gosms.message'
    _description = "SMS Message"
    _order = 'id desc'
    _rec_name = 'number'

    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade', default=lambda self: self.env.company)
    kind = fields.Selection([('sms', "SMS"), ('code', "Confirmation Code")], required=True, readonly=True, default='sms')
    direction = fields.Selection([('outgoing', "Outgoing"), ('inbound', "Incoming")], required=True, readonly=True)
    number = fields.Char("Phone Number", readonly=True)
    partner_id = fields.Many2one('res.partner', "Contact", readonly=True, ondelete='set null')
    body = fields.Text("Message", readonly=True)
    state = fields.Selection([
        ('sent', "Sent"),
        ('delivered', "Delivered"),
        ('expired', "Expired"),
        ('undelivered', "Not Delivered"),
        ('error', "Failed"),
        ('received', "Received"),
    ], "Status", readonly=True)
    failure_reason = fields.Char("Reason", readonly=True)
    segments = fields.Integer(readonly=True)
    encoding = fields.Char(readonly=True)
    gosms_id = fields.Char("GoSMS ID", index=True, readonly=True)
    event_id = fields.Char(readonly=True)
    sms_uuid = fields.Char(index=True, readonly=True)

    _company_event_unique = models.Constraint('unique(company_id, event_id)', "This message was already received.")

    def _gosms_set_status(self, status):
        if status not in STATUS_TO_STATE:
            return
        self.state = STATUS_TO_STATE[status]
        trackers = self.env['sms.tracker'].search([('sms_uuid', 'in', self.mapped('sms_uuid'))])
        if status in STATUS_TO_PROVIDER_ERROR:
            trackers._action_update_from_provider_error(STATUS_TO_PROVIDER_ERROR[status])
        else:
            trackers._action_update_from_sms_state('sent')

    def action_check_status(self):
        self.ensure_one()
        status = self.company_id._gosms_call('checksms', {'messageId': int(self.gosms_id)})['status']
        self._gosms_set_status(status)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'message': self.env._("GoSMS status: %s.", status),
            },
        }
