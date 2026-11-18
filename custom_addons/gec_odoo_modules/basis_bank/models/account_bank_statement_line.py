import logging

from odoo import _, api, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

BASISBANK_PREFIX = 'basisbank/'
# States in which a payment may still turn out to be on the statement.
BASISBANK_MATCHABLE_STATES = ('sending', 'sent', 'unknown', 'not_in_report')


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._basisbank_auto_match()
        return lines

    def _basisbank_auto_match(self):
        """Confirm sent payments from new statement lines (transfers by BankInternalID, packages by DocNum).
        Also 'sending'/'unknown' and Resync-confirmed payments, found by the line's journal (branch payments)."""
        basisbank_lines = self.filtered(lambda l: l.unique_import_id and BASISBANK_PREFIX in l.unique_import_id and l.amount < 0)
        if not basisbank_lines:
            return
        line_refs = []
        bank_ids = set()
        doc_nums = set()
        for line in basisbank_lines:
            bank_id = self._basisbank_extract_bank_id(line.unique_import_id)
            doc_num = int(line.ref) if line.ref and line.ref.isdigit() else None
            line_refs.append((line, bank_id, doc_num))
            if bank_id:
                bank_ids.add(bank_id)
            if doc_num is not None:
                doc_nums.add(doc_num)

        Payment = self.env['account.payment'].sudo()
        open_payments = Domain('journal_id', 'in', basisbank_lines.journal_id.ids) & Domain.OR([
            Domain('basisbank_state', 'in', BASISBANK_MATCHABLE_STATES),
            Domain([('basisbank_state', '=', 'confirmed'), ('is_matched', '=', False)]),
        ])
        by_bank_id = {}
        if bank_ids:
            for payment in Payment.search(Domain('basisbank_bank_internal_id', 'in', list(bank_ids)) & open_payments):
                by_bank_id[payment.basisbank_bank_internal_id] = payment
        by_id = {}
        if doc_nums:
            for payment in Payment.search(Domain('id', 'in', list(doc_nums)) & Domain('basisbank_bank_internal_id', '=', False) & open_payments):
                by_id[payment.id] = payment

        confirmed = Payment.browse()
        for line, bank_id, doc_num in line_refs:
            payment = Payment.browse()
            if bank_id and bank_id in by_bank_id:
                payment = by_bank_id[bank_id]
            elif doc_num is not None and doc_num in by_id:
                payment = by_id[doc_num]
            if not payment or payment in confirmed:
                continue
            if payment.journal_id != line.journal_id:
                continue
            if not line._gec_bank_matches_payment(payment):
                continue
            try:
                with self.env.cr.savepoint():
                    if payment.basisbank_state != 'confirmed':
                        payment._basisbank_confirm_from_statement(bank_id=bank_id)
                    line._gec_bank_reconcile_payment(payment)
            except Exception:
                _logger.exception("Basis Bank: could not auto-confirm payment %s from statement line %s", payment.id, line.id)
                payment.message_post(body=_("Found in the imported bank statement but could not be confirmed automatically. Check and confirm it "
                    "manually (e.g. via Resync)."))
                continue
            confirmed |= payment

        confirmed.batch_payment_id._basisbank_set_done_when_confirmed()

    @staticmethod
    def _basisbank_extract_bank_id(unique_import_id):
        idx = unique_import_id.find(BASISBANK_PREFIX)
        if idx == -1:
            return ''
        tail = unique_import_id[idx + len(BASISBANK_PREFIX):]
        parts = tail.split('/', 1)
        return parts[1] if len(parts) == 2 else ''
