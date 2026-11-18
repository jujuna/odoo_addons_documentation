import logging

from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.base.models.res_partner_bank import sanitize_account_number

from ..models.account_bank_statement_line import BASISBANK_MATCHABLE_STATES

_logger = logging.getLogger(__name__)

BASISBANK_IMPORT_LOCK_NS = 4342859


class BasisbankStatementImportWizard(models.TransientModel):
    _name = 'basisbank.statement.import.wizard'
    _description = 'Basis Bank Statement Import Wizard'

    journal_id = fields.Many2one('account.journal', string='Bank Journal', required=True, domain="[('is_basisbank', '=', True)]")
    start_date = fields.Date(string='From', required=True, default=fields.Date.context_today)
    end_date = fields.Date(string='To', required=True, default=fields.Date.context_today)
    currency_code = fields.Char(string='Currency', compute='_compute_currency_code')
    imported_count = fields.Integer(readonly=True)
    skipped_count = fields.Integer(readonly=True)
    confirmed_count = fields.Integer(readonly=True)

    @api.depends('journal_id.currency_id', 'journal_id.company_id.currency_id')
    def _compute_currency_code(self):
        """The journal's currency, never typed: lines are booked in it, so another currency would book wrong amounts."""
        for wizard in self:
            journal = wizard.journal_id
            wizard.currency_code = (journal.currency_id or journal.company_id.currency_id).name

    def action_import(self):
        """Fetch the statement for the date range, create bank statement lines, and report confirmed payments."""
        self.ensure_one()
        if self.start_date > self.end_date:
            raise UserError(_("'From' date must be earlier than or equal to 'To' date."))
        connection = self.journal_id.basisbank_connection_id
        if not connection:
            raise UserError(_("Selected journal has no Basis Bank connection."))
        service = self.env['basisbank.service']
        account = self.journal_id.bank_account_id.sanitized_account_number
        if not account:
            raise UserError(_("Journal has no IBAN configured."))

        all_items = service.fetch_report_items(connection, account, self.currency_code, self.start_date, self.end_date)

        line_vals, pre_skipped = self._build_line_vals(all_items)
        if not line_vals:
            return self._basisbank_import_notify(0, pre_skipped, 0)

        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", [BASISBANK_IMPORT_LOCK_NS, self.journal_id.id])
        confirmable = self.env['account.payment'].sudo().search([
            ('journal_id', '=', self.journal_id.id),
            ('basisbank_state', 'in', BASISBANK_MATCHABLE_STATES),
        ])
        statement_vals = [{
            'transactions': line_vals,
            'reference': _("Basis Bank %(start)s - %(end)s") % {'start': self.start_date, 'end': self.end_date},
        }]
        # import_file: core's auto-reconcile of more than 80 new lines must not commit inside this import (as core's CSV import)
        _statement_ids, duplicate_skipped, zero_skipped = self.journal_id.with_context(import_file=True)._create_bank_statements(
            statement_vals, raise_no_imported_file=False)
        imported = len(line_vals) - duplicate_skipped - zero_skipped
        skipped = duplicate_skipped + zero_skipped + pre_skipped
        confirmed = len(confirmable.filtered(lambda p: p.basisbank_state == 'confirmed'))
        self.write({
            'imported_count': imported,
            'skipped_count': skipped,
            'confirmed_count': confirmed,
        })
        return self._basisbank_import_notify(imported, skipped, confirmed)

    def _basisbank_import_notify(self, imported, skipped, confirmed):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Basis Bank"),
                'message': _("Imported %(imp)s lines, skipped %(skp)s, confirmed %(conf)s payments.") % {
                    'imp': imported,
                    'skp': skipped,
                    'conf': confirmed,
                },
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _build_line_vals(self, items):
        """Convert bank statement items into statement-line values; skip (and count) lines we cannot place."""
        line_vals = []
        skipped = 0
        for item in items:
            bank_id = item.get('BankInternalID')
            if not bank_id:
                skipped += 1
                _logger.warning("Basis Bank: skipped statement item with no BankInternalID on journal %s (DocNum %s).", self.journal_id.id,
                    item.get('DocNum'))
                continue
            sign = self._amount_sign(item)
            if sign is None:
                skipped += 1
                _logger.warning("Basis Bank: skipped statement line %s on journal %s; account %s matches neither DebitAcc nor CreditAcc.", bank_id,
                    self.journal_id.id, self.journal_id.bank_account_number)
                continue
            doc_date = self._parse_date(item.get('DocDate'))
            if not doc_date:
                skipped += 1
                _logger.warning("Basis Bank: skipped statement line %s on journal %s; its date %r cannot be read.", bank_id, self.journal_id.id,
                    item.get('DocDate'))
                continue
            raw_amount = float(item.get('Amount') or 0.0)
            if raw_amount < 0:
                _logger.warning("Basis Bank: statement item %s has a negative Amount (%s); direction is taken from the Debit/Credit account, not the "
                    "sign.", bank_id, raw_amount)
            amount = abs(raw_amount) * sign
            if sign > 0:
                cp_name = item.get('DebitAccName') or item.get('SenderAccName') or ''
                cp_acc = item.get('DebitAcc') or item.get('SenderAcc') or ''
            else:
                cp_name = item.get('CreditAccName') or item.get('ReceiverAccName') or ''
                cp_acc = item.get('CreditAcc') or item.get('ReceiverAcc') or ''
            line_vals.append({
                'journal_id': self.journal_id.id,
                'date': doc_date,
                'payment_ref': item.get('Descrip') or '/',
                'amount': amount,
                'partner_name': cp_name,
                'account_number': cp_acc,
                'ref': item.get('DocNum') and str(item.get('DocNum')) or '',
                'unique_import_id': f"basisbank/{self.journal_id.id}/{bank_id}",
            })
        return line_vals, skipped

    def _amount_sign(self, item):
        """Return +1 if our IBAN is the credit side (money in), -1 if the debit side (out), None if neither."""
        our_acc = self.journal_id.bank_account_id.sanitized_account_number
        debit = sanitize_account_number(item.get('DebitAcc') or item.get('SenderAcc'))
        credit = sanitize_account_number(item.get('CreditAcc') or item.get('ReceiverAcc'))
        if our_acc == debit:
            return -1
        if our_acc == credit:
            return 1
        return None

    @staticmethod
    def _parse_date(value):
        """The item's date, or None if unreadable; such an item is skipped rather than booked today."""
        if not value:
            return None
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S.%f'):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None
