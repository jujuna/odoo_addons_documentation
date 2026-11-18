from odoo import models, fields, api


class RsWaybillOperation(models.Model):
    _name = 'rs.waybill.operation'
    _description = 'RS Waybill Operation Log / Queue'
    _order = 'create_date desc'


    waybill_id = fields.Many2one('rs.waybill', string='Waybill', required=True, ondelete='cascade', index=True)
    operation_type = fields.Selection([('save', 'Save'),
                                      ('send', 'Send / Activate'),
                                      ('send_vd', 'Send Backdated'),
                                      ('close', 'Close'),
                                      ('close_vd', 'Close Backdated'),
                                      ('refuse', 'Refuse / Cancel'),
                                      ('delete', 'Delete Draft'),
                                      ('correct', 'Correct (multi-step)'),
                                      ('sync', 'Sync from RS'),], string='Operation Type', required=True)
    state = fields.Selection([('pending', 'Pending'),
                              ('done', 'Done'),
                              ('failed', 'Failed'),
                              ('retried', 'Retried'),], default='pending', required=True, index=True)
    idempotency_key = fields.Char(string='Idempotency Key', index=True, help='UUID / hash that prevents duplicate sends on retry.')
    request_xml = fields.Text(string='Request XML')
    response_xml = fields.Text(string='Response XML')
    error_message = fields.Char(string='Error Message')
    retry_count = fields.Integer(default=0)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, readonly=True)
    done_date = fields.Datetime(string='Done At', readonly=True)
    create_date = fields.Datetime(string='Create Date', readonly=True)
