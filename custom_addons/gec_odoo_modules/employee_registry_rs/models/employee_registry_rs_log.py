import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

RETENTION_DAYS = 90


class EmployeeRegistryRsLog(models.Model):
    _name = 'employee.registry.rs.log'
    _description = 'RS Employee Registry API Log'
    _order = 'create_date desc'
    _rec_name = 'endpoint'

    endpoint = fields.Char(required=True, readonly=True)
    employee_id = fields.Many2one('hr.employee', ondelete='set null', readonly=True)
    company_id = fields.Many2one('res.company', compute='_compute_company_id', store=True, readonly=False, index=True, ondelete='cascade')
    request_payload = fields.Text(readonly=True)
    response_payload = fields.Text(readonly=True)
    status_id = fields.Integer(readonly=True, index=True)
    status_text = fields.Char(readonly=True)
    success = fields.Boolean(compute='_compute_success', store=True, index=True)
    error_message = fields.Text(readonly=True)

    @api.depends('employee_id')
    def _compute_company_id(self):
        """The employee's company, else the one already set or the active one; decides who may read the row."""
        for rec in self:
            rec.company_id = rec.employee_id.company_id or rec.company_id or self.env.company

    @api.depends('status_id', 'error_message')
    def _compute_success(self):
        for rec in self:
            rec.success = rec.status_id == 0 and not rec.error_message

    @api.model
    def _cron_rotate_logs(self):
        cutoff = fields.Datetime.now() - timedelta(days=RETENTION_DAYS)
        old_logs = self.sudo().search([('create_date', '<', cutoff)])
        count = len(old_logs)
        if count:
            old_logs.unlink()
            _logger.info("RS Employee Registry log rotation: deleted %s rows older than %s days.", count, RETENTION_DAYS)
