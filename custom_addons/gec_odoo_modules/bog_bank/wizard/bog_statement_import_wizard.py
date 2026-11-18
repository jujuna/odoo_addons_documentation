import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.bog_service import bog_key

_logger = logging.getLogger(__name__)


class BogStatementImportWizard(models.TransientModel):
    _name = 'bog.statement.import.wizard'
    _description = 'Bank of Georgia Statement Import'

    journal_id = fields.Many2one('account.journal', string='Journal', required=True,
                                 domain="[('is_bog', '=', True)]")
    account_number = fields.Char(string='Account (IBAN)', related='journal_id.bank_account_number',
                                 readonly=True)
    currency_code = fields.Char(string='Currency', compute='_compute_currency_code')
    # Dates only: the v2 statement path takes YYYY-MM-DD.
    start_date = fields.Date(string='From', required=True)
    end_date = fields.Date(string='To', required=True, default=fields.Date.context_today)

    @api.depends('journal_id.currency_id', 'journal_id.company_id.currency_id')
    def _compute_currency_code(self):
        """The journal's currency, never typed: the lines are booked in it."""
        for wizard in self:
            journal = wizard.journal_id
            wizard.currency_code = (journal.currency_id or journal.company_id.currency_id).name

    def action_import(self):
        self.ensure_one()
        connection = self.journal_id.bog_connection_id[:1]
        if not connection:
            raise UserError(_("No Bank of Georgia connection is configured for this journal's company."))
        if not self.account_number:
            raise UserError(_("The journal has no bank account number (IBAN)."))
        if self.start_date > self.end_date:
            raise UserError(_("The 'From' date must be before the 'To' date."))

        records = self.env['bog.service'].fetch_all_records(
            connection, self.account_number, self.currency_code, self.start_date, self.end_date)
        created = self._create_statement_lines(records)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Bank of Georgia"),
                'message': _("%s new statement line(s) imported.") % created,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _create_statement_lines(self, records):
        """Import the entries through core's statement import; return how many lines it created."""
        candidates = {}
        skipped = 0
        for record in records:
            vals = self._record_to_line_vals(record)
            if not vals:
                skipped += 1
                continue
            candidates.setdefault(vals['unique_import_id'], vals)
        if skipped:
            _logger.warning("BOG statement import: skipped %s record(s) with no usable id or date "
                            "on journal %s", skipped, self.journal_id.id)
        if not candidates:
            return 0
        # import_file: core's auto-reconcile of more than 80 new lines must not commit inside this import (as core's CSV import)
        _statement_ids, duplicates, zero_amounts = self.journal_id.with_context(import_file=True)._create_bank_statements([{
            'transactions': list(candidates.values()),
            'reference': _("Bank of Georgia %(start)s - %(end)s",
                           start=fields.Date.to_string(self.start_date),
                           end=fields.Date.to_string(self.end_date)),
        }], raise_no_imported_file=False)
        return len(candidates) - duplicates - zero_amounts

    def _record_to_line_vals(self, record):
        """Map one api/v2/statement record to bank statement line values (camelCase or PascalCase keys)."""
        if not isinstance(record, dict):
            return False
        pick = self.env['bog.service']._first_key

        entry_id = bog_key(pick(record, ('entryId', 'EntryId')))
        entry_date = self._parse_date(pick(record, ('entryDate', 'EntryDate')))
        if not entry_id or not entry_date:
            return False

        # BOG gives debit and credit separately: money in is positive, out negative.
        credit = float(pick(record, ('entryAmountCredit', 'EntryAmountCredit'), 0.0) or 0.0)
        debit = float(pick(record, ('entryAmountDebit', 'EntryAmountDebit'), 0.0) or 0.0)
        amount = credit - debit

        sender = pick(record, ('senderDetails', 'SenderDetails'), {}) or {}
        beneficiary = pick(record, ('beneficiaryDetails', 'BeneficiaryDetails'), {}) or {}
        counterparty = sender if amount > 0 else beneficiary
        if not isinstance(counterparty, dict):
            counterparty = {}

        document_no = pick(record, ('entryDocumentNumber', 'EntryDocumentNumber'))
        document_key = bog_key(pick(record, ('documentKey', 'DocumentKey')))
        label = (pick(record, ('documentNomination', 'DocumentNomination'))
                 or pick(record, ('entryComment', 'EntryComment'))
                 or _("BOG entry %s") % entry_id)

        return {
            'journal_id': self.journal_id.id,
            'date': entry_date,
            'payment_ref': label,
            'amount': amount,
            'partner_name': pick(counterparty, ('name', 'Name')),
            'account_number': pick(counterparty, ('accountNumber', 'AccountNumber')),
            'ref': str(document_no or entry_id),
            # unique_import_id is unique globally, so scope it to the journal.
            'unique_import_id': 'bogbank-%s-%s' % (self.journal_id.id, entry_id),
            'gec_bank_match_keys': ' '.join(str(k) for k in (document_key, document_no) if k),
        }

    @staticmethod
    def _parse_date(value):
        """The local calendar date of a BOG entry timestamp (first 10 characters, no UTC shift)."""
        if not value:
            return None
        text = str(value)[:10]
        try:
            return datetime.strptime(text, '%Y-%m-%d').date()
        except ValueError:
            return None
