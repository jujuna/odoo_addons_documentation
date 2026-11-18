import logging

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.gec_bank.models.account_payment_method_line import GEC_BANK_HANDOFF_STATES

_logger = logging.getLogger(__name__)

GEC_PAYROLL_STALE_HOURS = 48
GEC_PAYROLL_ALERT_STATES = ('pending', 'prepared')
GEC_PAYROLL_URGENT_STATES = ('partial', 'failed', 'uncertain')
GEC_PAYROLL_TERMINAL_STATES = ('transmitted', 'confirmed')
GEC_PAYROLL_BATCH_WRITE_TOKEN = object()
GEC_PAYROLL_IMMUTABLE_FIELDS = frozenset({'payment_ids', 'journal_id', 'date', 'gec_payroll_is_batch', 'gec_payroll_kind', 'gec_payroll_channel_id',
    'payslip_run_id', 'gec_payroll_manual_ack'})


class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    gec_payroll_is_batch = fields.Boolean(string='Payroll Batch', readonly=True, copy=False, index=True)
    gec_payroll_kind = fields.Selection(selection=[('salary', 'Salary'), ('authority', 'Authority')], string='Payroll Purpose', readonly=True,
        copy=False)
    gec_payroll_channel_id = fields.Many2one('account.payment.method.line', string='Payroll Channel', readonly=True, copy=False, ondelete='restrict')
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Pay Run', readonly=True, copy=False, ondelete='set null', index='btree_not_null')
    gec_payroll_manual_ack = fields.Boolean(string='Recorded Only', readonly=True, copy=False)
    gec_payroll_stale_notified = fields.Boolean(readonly=True, copy=False)
    gec_payroll_last_notified_state = fields.Selection(selection=[(state,
        state.replace('_', ' ').title()) for state in sorted(GEC_BANK_HANDOFF_STATES)], readonly=True, copy=False)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_transmitted_payroll(self):
        """A payroll batch with payments is the bank handoff record and stays.
        A rejected salary is paid again the core way: cancel its payment, mark the payslip unpaid, run Pay Salaries."""
        blocked = self.filtered(lambda batch: batch.gec_payroll_is_batch and batch.payment_ids)
        if blocked:
            raise UserError(_("A payroll batch with payments cannot be deleted: it is the record of what was sent to the bank. To pay a rejected "
                "salary again, reset its payment to draft and cancel it, use Mark Unpaid on the payslip, then Pay Salaries: %s",
                ', '.join(blocked.mapped('display_name'))))

    def write(self, vals):
        protected = GEC_PAYROLL_IMMUTABLE_FIELDS & set(vals)
        internal = (self.env.context.get('gec_payroll_batch_write_token') is GEC_PAYROLL_BATCH_WRITE_TOKEN)
        if (protected and not internal and (any(self.mapped('gec_payroll_is_batch')) or vals.get('gec_payroll_is_batch'))):
            raise UserError(_("The routing and payments of a generated payroll batch cannot be changed."))
        return super().write(vals)

    @api.constrains('gec_payroll_is_batch', 'gec_payroll_channel_id', 'journal_id', 'payment_ids', 'date')
    def _check_gec_payroll_envelope(self):
        for batch in self.filtered('gec_payroll_is_batch'):
            wrong = batch.payment_ids.filtered(lambda payment:
                payment.journal_id != batch.journal_id
                or payment.payment_method_line_id != batch.gec_payroll_channel_id
                or payment.company_id != batch.company_id
                or payment.date != batch.date)
            if wrong:
                raise ValidationError(_("Payroll batch payments must keep the exact channel, "
                    "journal, company, and date chosen by the payroll run: %s", ', '.join(wrong.mapped('display_name'))))

    def _gec_payroll_handoff_state(self):
        self.ensure_one()
        channel = self.gec_payroll_channel_id
        if not channel:
            return 'prepared' if self.state == 'draft' else 'transmitted'
        state = channel._gec_bank_handoff_state(self)
        if state not in GEC_BANK_HANDOFF_STATES:
            _logger.error("Payroll channel %s returned unknown handoff state %r for batch %s", channel.display_name, state, self.id)
            return 'uncertain'
        return state

    @api.model
    def _cron_gec_payroll_stale_batches(self):
        """Flag payroll batches nobody transmitted: their payslips already read Paid.
        A batch the bank confirmed in full is done for good and is not read again."""
        deadline = fields.Datetime.now() - timedelta(hours=GEC_PAYROLL_STALE_HOURS)
        candidates = self.sudo().search([
            ('gec_payroll_is_batch', '=', True),
            ('gec_payroll_manual_ack', '=', False),
            ('gec_payroll_last_notified_state', '!=', 'confirmed'),
        ], order='id')
        for batch in candidates:
            try:
                with self.env.cr.savepoint():
                    state = batch._gec_payroll_handoff_state()
                    if state == batch.gec_payroll_last_notified_state:
                        continue
                    if state in GEC_PAYROLL_TERMINAL_STATES:
                        batch.write({'gec_payroll_last_notified_state': state, 'gec_payroll_stale_notified': True})
                        continue
                    if state in GEC_PAYROLL_URGENT_STATES:
                        note = _("The bank did not confirm this payroll batch (%(state)s). Its payslips are already marked paid. Check with the bank "
                            "before reversing or resending anything - the transfer may still have executed.", state=state)
                    elif state in GEC_PAYROLL_ALERT_STATES and batch.create_date <= deadline:
                        note = _("This payroll batch was created over %(hours)s hours ago and has still not been sent to the bank. Its payslips are "
                            "already marked paid, but no money has moved. Send it, or cancel its payments.", hours=GEC_PAYROLL_STALE_HOURS)
                    else:
                        continue
                    batch.activity_schedule('mail.mail_activity_data_todo', user_id=batch.create_uid.id,
                        summary=_("Payroll batch not confirmed by the bank"), note=note)
                    batch.message_post(body=note)
                    batch.write({'gec_payroll_last_notified_state': state, 'gec_payroll_stale_notified': True})
            except Exception:
                _logger.exception("Could not inspect payroll batch %s", batch.id)
        return True
