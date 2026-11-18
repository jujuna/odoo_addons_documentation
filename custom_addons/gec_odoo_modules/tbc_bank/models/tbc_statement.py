import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class TbcStatement(models.Model):
    _name = 'tbc.statement'
    _description = 'TBC Bank Statement Snapshot'
    _order = 'fetched_on desc, id desc'
    _rec_name = 'journal_id'

    connection_id = fields.Many2one('tbc.connection', string='Connection', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    journal_id = fields.Many2one('account.journal', string='Journal', required=True, ondelete='cascade', index=True)
    account_number = fields.Char(string='Account (IBAN)')
    currency_code = fields.Char(string='Currency')

    snapshot_type = fields.Selection([('live', 'Live (auto)'), ('period', 'Period (manual)')], string='Type', required=True, default='period',
        index=True)
    period_from = fields.Date(string='From')
    period_to = fields.Date(string='To')
    opening_balance = fields.Float(string='Opening Balance', digits=(16, 2))
    closing_balance = fields.Float(string='Closing Balance', digits=(16, 2))
    credit_sum = fields.Float(string='Total Credit (In)', digits=(16, 2))
    debit_sum = fields.Float(string='Total Debit (Out)', digits=(16, 2))
    fetched_on = fields.Datetime(string='Fetched On', default=fields.Datetime.now)

    @api.model
    def _fetch_and_store(self, connection, journal, period_from, period_to, snapshot_type):
        """Fetch a statement summary from TBC: 'live' updates the journal's single row, 'period' adds a row."""
        currency_code = journal.currency_id.name or journal.company_id.currency_id.name
        data = self.env['tbc.service'].get_account_statement(connection, journal._tbc_account_number(), currency_code, period_from, period_to)
        vals = self._statement_vals(connection, journal, currency_code, period_from, period_to, snapshot_type, data)
        if snapshot_type == 'live':
            existing = self.sudo().search([('journal_id', '=', journal.id), ('snapshot_type', '=', 'live')], limit=1)
            if existing:
                existing.write(vals)
                return existing
        return self.sudo().create(vals)

    def _statement_vals(self, connection, journal, currency_code, period_from, period_to, snapshot_type, data):
        """Map the TBC statement response to record values; balance keys are tried from a candidate list
        because TBC's docs and sandbox disagree on casing."""
        data = data or {}
        pick = self.env['tbc.service']._first_key
        return {
            'connection_id': connection.id,
            'journal_id': journal.id,
            'account_number': journal._tbc_account_number(),
            'currency_code': currency_code,
            'snapshot_type': snapshot_type,
            'period_from': period_from,
            'period_to': period_to,
            'opening_balance': pick(data, ('openingBalance', 'OpeningBalance', 'startBalance'), 0.0) or 0.0,
            'closing_balance': pick(data, ('closingBalance', 'ClosingBalance', 'endBalance'), 0.0) or 0.0,
            'credit_sum': pick(data, ('creditSum', 'CreditSum', 'totalCredit'), 0.0) or 0.0,
            'debit_sum': pick(data, ('debitSum', 'DebitSum', 'totalDebit'), 0.0) or 0.0,
            'fetched_on': fields.Datetime.now(),
        }

    @api.model
    def _cron_fetch_live_statements(self):
        today = fields.Date.today()
        month_start = today.replace(day=1)
        Connection = self.env['tbc.connection']
        Journal = self.env['account.journal']
        for connection in Connection.search([('state', 'in', ('active', 'error'))]):
            journals = Journal.search([('company_id', 'child_of', connection.company_id.id), ('is_tbc', '=', True)])
            journals = journals.filtered(lambda journal: journal.tbc_connection_id == connection)
            for journal in journals:
                if not journal.bank_account_number:
                    continue
                try:
                    with self.env.cr.savepoint():
                        self._fetch_and_store(connection, journal, month_start, today, 'live')
                except Exception:
                    _logger.exception("TBC live statement fetch failed for journal %s", journal.id)
