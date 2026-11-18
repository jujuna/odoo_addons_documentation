import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class BogStatement(models.Model):
    _name = 'bog.statement'
    _description = 'Bank of Georgia Statement Snapshot'
    _order = 'fetched_on desc, id desc'
    _rec_name = 'journal_id'

    connection_id = fields.Many2one('bog.connection', string='Connection', required=True,
                                    ondelete='cascade', index=True)
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    journal_id = fields.Many2one('account.journal', string='Journal', required=True,
                                 ondelete='cascade', index=True)
    account_number = fields.Char(string='Account (IBAN)')
    currency_code = fields.Char(string='Currency')

    snapshot_type = fields.Selection([('live', 'Live (auto)'),
                                      ('period', 'Period (manual)')],
                                     string='Type', required=True, default='period', index=True)
    period_from = fields.Date(string='From')
    period_to = fields.Date(string='To')
    closing_balance = fields.Float(string='Closing Balance', digits=(16, 2))
    credit_sum = fields.Float(string='Total Credit (In)', digits=(16, 2))
    debit_sum = fields.Float(string='Total Debit (Out)', digits=(16, 2))
    entry_count = fields.Integer(string='Entries')
    fetched_on = fields.Datetime(string='Fetched On', default=fields.Datetime.now)

    @api.model
    def _fetch_and_store(self, connection, journal, period_from, period_to, snapshot_type):
        """Fetch a summary from BOG and store it: 'live' updates one row per journal, 'period' adds a row."""
        currency_code = journal.currency_id.name or journal.company_id.currency_id.name
        data = self.env['bog.service'].get_statement_summary(
            connection, journal.bank_account_number, currency_code, period_from, period_to)
        vals = self._statement_vals(connection, journal, currency_code,
                                    period_from, period_to, snapshot_type, data)
        if snapshot_type == 'live':
            existing = self.sudo().search([('journal_id', '=', journal.id),
                                           ('snapshot_type', '=', 'live')], limit=1)
            if existing:
                existing.write(vals)
                return existing
        return self.sudo().create(vals)

    def _statement_vals(self, connection, journal, currency_code,
                        period_from, period_to, snapshot_type, data):
        """Map api/v2/statement/summary onto record values; closing balance is the last daily `balance`."""
        pick = self.env['bog.service']._first_key
        data = data if isinstance(data, dict) else {}
        summary = pick(data, ('globalSummary', 'GlobalSummary'), {}) or {}
        dailies = pick(data, ('dailySummaries', 'DailySummaries'), []) or []
        last_day = dailies[-1] if isinstance(dailies, list) and dailies else {}

        return {
            'connection_id': connection.id,
            'journal_id': journal.id,
            'account_number': journal.bank_account_number,
            'currency_code': currency_code,
            'snapshot_type': snapshot_type,
            'period_from': period_from,
            'period_to': period_to,
            'closing_balance': pick(last_day, ('balance', 'Balance'), 0.0) or 0.0,
            'credit_sum': pick(summary, ('creditSum', 'CreditSum'), 0.0) or 0.0,
            'debit_sum': pick(summary, ('debitSum', 'DebitSum'), 0.0) or 0.0,
            'entry_count': sum(int(pick(d, ('entryCount', 'EntryCount'), 0) or 0)
                               for d in dailies if isinstance(d, dict)),
            'fetched_on': fields.Datetime.now(),
        }

    @api.model
    def _cron_fetch_live_statements(self):
        today = fields.Date.today()
        month_start = today.replace(day=1)
        Connection = self.env['bog.connection']
        Journal = self.env['account.journal']
        for connection in Connection.search([('state', 'in', ('active', 'error'))]):
            journals = Journal.search([('company_id', 'child_of', connection.company_id.id), ('is_bog', '=', True)])
            journals = journals.filtered(lambda journal: journal.bog_connection_id == connection)
            for journal in journals:
                if not journal.bank_account_number:
                    continue
                try:
                    with self.env.cr.savepoint():
                        self._fetch_and_store(connection, journal, month_start, today, 'live')
                except Exception:
                    _logger.exception("BOG live statement fetch failed for journal %s", journal.id)
