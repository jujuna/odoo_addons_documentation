from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.basisbank_service import report_window


class BasisbankResyncWizard(models.TransientModel):
    _name = 'basisbank.resync.wizard'
    _description = 'Basis Bank Resync Wizard'

    batch_id = fields.Many2one('account.batch.payment', string='Batch', required=True, ondelete='cascade')
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    matched_count = fields.Integer(readonly=True)
    unmatched_count = fields.Integer(readonly=True)
    summary = fields.Text(readonly=True)

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        if result.get('batch_id'):
            batch = self.env['account.batch.payment'].browse(result['batch_id'])
            result['start_date'], result['end_date'] = report_window(batch.basisbank_sent_date)
        return result

    def action_resync(self):
        """Re-read the statement and confirm the batch's payments by the shared report matching rule."""
        self.ensure_one()
        batch = self.batch_id
        connection = batch.journal_id.basisbank_connection_id
        if not connection:
            raise UserError(_("Journal has no Basis Bank connection."))
        service = self.env['basisbank.service']
        account = batch.journal_id.bank_account_id.sanitized_account_number or ''
        ccy = batch.currency_id.name or 'GEL'

        all_items = service.fetch_report_items(connection, account, ccy, self.start_date, self.end_date)

        open_payments = batch.payment_ids.filtered(lambda p: p.basisbank_state not in ('confirmed', 'failed'))
        matches = open_payments._basisbank_match_report_items(all_items)
        for payment, item in matches.items():
            payment._basisbank_confirm_from_statement(bank_id=item.get('BankInternalID'))
        unmatched = open_payments.filtered(lambda p: p not in matches).mapped('display_name')

        matched = len(matches)

        if matched:
            batch._basisbank_set_done_when_confirmed()

        self.write({
            'matched_count': matched,
            'unmatched_count': len(unmatched),
            'summary': _("Confirmed %s payments. Still unmatched: %s") % (matched, ', '.join(unmatched) or _("none")),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
