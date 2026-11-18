from datetime import timedelta

from odoo import api, fields, models


class GlovoEvent(models.Model):
    _name = 'glovo.event'
    _description = 'Glovo Webhook Event'
    _order = 'id desc'
    _rec_name = 'glovo_order_id'
    _check_company_auto = True

    event_type = fields.Selection([('dispatched', 'Dispatched'), ('picked_up', 'Picked Up'), ('cancelled', 'Cancelled')], string='Event Type',
        required=True, readonly=True)
    glovo_order_id = fields.Char(string='Glovo Order ID', required=True, index=True, readonly=True)
    store_external_id = fields.Char(string='Store External ID', readonly=True)
    payload = fields.Text(string='Raw Payload', readonly=True)
    state = fields.Selection([('received', 'Received'), ('processed', 'Processed'), ('failed', 'Failed')], string='State', required=True,
        default='received')
    error = fields.Text(string='Error')
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True, default=lambda self: self.env.company)

    # Glovo retries each notification up to 3 times; one row per order and event type.
    _order_event_uniq = models.Constraint('UNIQUE(glovo_order_id, event_type)', 'This Glovo event was already received for this order.')

    @api.autovacuum
    def _gc_processed_events(self):
        """Retention: glovo_base.event_retention_days (default 90), any state; 0 keeps everything."""
        retention_days = self.env['ir.config_parameter'].sudo().get_int('glovo_base.event_retention_days', 90)
        if retention_days <= 0:
            return
        deadline = fields.Datetime.now() - timedelta(days=retention_days)
        limit = 10000
        events = self.search([('write_date', '<=', deadline)], order='id', limit=limit)
        events.unlink()
        return len(events), len(events) == limit
