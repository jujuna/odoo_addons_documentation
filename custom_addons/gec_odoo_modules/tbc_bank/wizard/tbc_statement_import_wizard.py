import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Movement statusCode: 0 = Authorized, 1 = Waiting for second authorization, 2 = Waiting for authorization.
# Only authorized movements are booked; the others may still be cancelled.
TBC_MOVEMENT_AUTHORIZED = 0


class TbcStatementImportWizard(models.TransientModel):
    _name = 'tbc.statement.import.wizard'
    _description = 'TBC Bank Statement Import'

    journal_id = fields.Many2one('account.journal', string='Journal', required=True, domain="[('is_tbc', '=', True)]")
    account_number = fields.Char(string='Account (IBAN)', related='journal_id.bank_account_number', readonly=True)
    currency_code = fields.Char(string='Currency', compute='_compute_currency_code')
    start_date = fields.Datetime(string='From', required=True)
    end_date = fields.Datetime(string='To', required=True, default=fields.Datetime.now)

    @api.depends('journal_id.currency_id', 'journal_id.company_id.currency_id')
    def _compute_currency_code(self):
        """The journal's currency, never typed: lines are booked in it, so another currency would book wrong amounts."""
        for wizard in self:
            journal = wizard.journal_id
            wizard.currency_code = (journal.currency_id or journal.company_id.currency_id).name

    def action_import(self):
        self.ensure_one()
        connection = self.journal_id.tbc_connection_id[:1]
        if not connection:
            raise UserError(_("No TBC Bank connection is configured for this journal's company."))
        if not self.account_number:
            raise UserError(_("The journal has no bank account number (IBAN)."))
        if self.start_date > self.end_date:
            raise UserError(_("The 'From' date must be before the 'To' date."))

        service = self.env['tbc.service']
        movements = service.fetch_all_movements(connection, self.journal_id._tbc_account_number(), self.currency_code, self.start_date, self.end_date)
        unauthorized = [m for m in movements if not self._is_authorized(m)]
        created = self._create_statement_lines(movements)
        message = _("%s new statement line(s) imported.", created)
        if unauthorized:
            message += ' ' + _("%s movement(s) still awaiting authorization at TBC were not imported; "
                               "import this period again once they are authorized.", len(unauthorized))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("TBC Bank"),
                'message': message,
                'type': 'warning' if unauthorized else 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _create_statement_lines(self, movements):
        """Import the booked movements through core's statement import; return how many lines it created."""
        candidates = {}
        skipped = 0
        for movement in movements:
            if not self._is_authorized(movement):
                # Not booked yet: importing would auto-confirm an unexecuted payment, and the dedup key keeps the line.
                continue
            vals = self._movement_to_line_vals(movement)
            if not vals:
                skipped += 1
                continue
            candidates.setdefault(vals['unique_import_id'], vals)
        if skipped:
            _logger.warning("TBC statement import: skipped %s movement(s) with no usable id or date on journal %s", skipped, self.journal_id.id)
        if not candidates:
            return 0
        # import_file: core's auto-reconcile of more than 80 new lines must not commit inside this import (as core's CSV import)
        _statement_ids, duplicates, zero_amounts = self.journal_id.with_context(import_file=True)._create_bank_statements([{
            'transactions': list(candidates.values()),
            'reference': _("TBC Bank %(start)s - %(end)s", start=fields.Date.to_string(self.start_date), end=fields.Date.to_string(self.end_date)),
        }], raise_no_imported_file=False)
        return len(candidates) - duplicates - zero_amounts

    @staticmethod
    def _is_authorized(movement):
        """True for a booked movement; a missing statusCode counts as authorized."""
        status = movement.get('statusCode')
        return status is None or status == TBC_MOVEMENT_AUTHORIZED

    def _movement_to_line_vals(self, movement):
        """Map one TBC movement dict to account.bank.statement.line vals. documentDate is the real transaction
        date, date a uniform posting stamp; partnerAccountInfo is the counterparty, customerAccountInfo our
        own account."""
        movement_id = movement.get('movementId') or movement.get('paymentId')
        date = self._parse_date(movement.get('documentDate') or movement.get('date'))
        if not movement_id or not date:
            return False

        amount = movement.get('amount') or 0.0
        amount = -abs(amount) if movement.get('isDebit') else abs(amount)

        partner = movement.get('partnerAccountInfo') or {}
        if not isinstance(partner, dict):
            partner = {}
        partner_name = partner.get('partnerName')
        partner_account = partner.get('accountIban')

        return {
            'journal_id': self.journal_id.id,
            'date': date,
            'payment_ref': movement.get('purpose') or _("TBC movement %s", movement_id),
            'amount': amount,
            'partner_name': partner_name,
            'account_number': partner_account,
            'ref': str(movement.get('documentNumber') or movement_id),
            # Journal-scoped: unique_import_id is unique across all journals, a bare movement id would collide.
            'unique_import_id': 'tbcbank-%s-%s' % (self.journal_id.id, movement_id),
            # Only paymentId identifies an API transfer; other ids or references could confirm the wrong payment.
            'gec_bank_match_keys': str(movement['paymentId']) if movement.get('paymentId') else False,
        }

    @staticmethod
    def _parse_date(value):
        """Return the date of a TBC datetime string, or None; TBC times are local Tbilisi time and the line
        stores a date, so no UTC shift."""
        if not value:
            return None
        text = str(value).replace('Z', '')
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            try:
                return datetime.strptime(text[:10], '%Y-%m-%d').date()
            except ValueError:
                return None
