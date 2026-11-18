from datetime import timedelta

from odoo import api, fields, models

GC_BATCH_SIZE = 1000


class GecBankApiLogMixin(models.AbstractModel):
    """One row per bank API call, kept as the audit trail. Each bank adds its connection link and extra columns."""

    _name = 'gec.bank.api.log.mixin'
    _description = 'Bank API Log Mixin'
    _order = 'create_date desc, id desc'
    _rec_name = 'endpoint'

    endpoint = fields.Char(string='Endpoint', required=True, index=True)
    http_status = fields.Integer(string='HTTP Status')
    error_message = fields.Char(string='Error Message')
    request_payload = fields.Text(string='Request')
    response_payload = fields.Text(string='Response')
    duration_ms = fields.Integer(string='Duration (ms)')

    def _gec_bank_log_vacuum_domain(self):
        """Extra domain of the rows the vacuum may delete; override per bank.
        Default keeps every row: rows that moved money are the evidence of what left the company."""
        return [('id', '=', False)]

    @api.autovacuum
    def _gc_gec_bank_api_logs(self):
        """Delete logs older than the connection's retention, except rows ``_gec_bank_log_vacuum_domain`` protects."""
        if self._abstract:
            return
        Connection = self.env[self._fields['connection_id'].comodel_name].sudo()
        Log = self.sudo()
        done = remaining = 0
        for connection in Connection.search([('log_retention_days', '>', 0)]):
            cutoff = fields.Datetime.now() - timedelta(days=connection.log_retention_days)
            domain = [('connection_id', '=', connection.id), ('create_date', '<', cutoff),
                      *self._gec_bank_log_vacuum_domain()]
            batch = Log.search(domain, limit=GC_BATCH_SIZE)
            if not batch:
                continue
            done += len(batch)
            batch.unlink()
            remaining += Log.search_count(domain)
        return done, remaining
