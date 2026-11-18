import logging

from odoo import _, api, fields, models
from odoo.exceptions import LockError, UserError

from ..services.basisbank_service import RETRYABLE_SEND_CODES, TECHNICAL_ERROR_CODE, TRANSFER_GROUPS, UNKNOWN_SEND_CODES
from .account_payment_method import BASISBANK_METHOD_CODE

_logger = logging.getLogger(__name__)


BASISBANK_ENDPOINT_KIND = {'package_gel': 'gel', 'package_salary': 'salary', 'package_treasury': 'treasury'}

BASISBANK_SENDABLE_STATES = ('draft', 'awaiting_otp')
# Written only by the Basis flows (gec_bank write token).
BASISBANK_BATCH_PROTECTED_FIELDS = frozenset({'basisbank_state', 'basisbank_approved_by', 'basisbank_approved_date', 'basisbank_sent_date',
    'basisbank_bank_response'})


class AccountBatchPayment(models.Model):
    _name = 'account.batch.payment'
    _inherit = ['account.batch.payment', 'basisbank.sendable']

    basisbank_endpoint = fields.Selection(selection=[
        ('package_gel', 'GEL Package'),
        ('package_salary', 'Salary Package'),
        ('package_treasury', 'Treasury Package'),
        ('single_batch', 'Single Transfers Batch'),
    ], string='Basis Bank Endpoint', compute='_compute_basisbank_endpoint', store=True, index=True)
    basisbank_state = fields.Selection(selection=[
        ('draft', 'Draft'),
        ('awaiting_approval', 'Awaiting Approval'),
        ('awaiting_otp', 'Awaiting OTP'),
        ('sending', 'Sending'),
        ('sent_pending_confirm', 'Sent (Pending Confirmation)'),
        ('awaiting_ib_confirmation', 'Awaiting Confirmation in Internet Banking'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        ('unknown', 'Unknown'),
    ], string='Basis Bank State', default='draft', readonly=True, copy=False, tracking=True, index=True)
    basisbank_approval_id = fields.Many2one(related='journal_id.basisbank_connection_id.approval_id', store=False)
    basisbank_can_approve = fields.Boolean(compute='_compute_basisbank_can_approve')
    is_basisbank = fields.Boolean(related='journal_id.is_basisbank', store=True)
    basisbank_salary = fields.Boolean(default=False, copy=False)

    _basisbank_pkg_uniq = models.Constraint('unique (journal_id, basisbank_endpoint, name)',
        'A package with the same name already exists for this journal and endpoint.')

    @api.depends('payment_ids.basisbank_transfer_type', 'payment_ids.currency_id', 'journal_id.is_basisbank', 'basisbank_salary')
    def _compute_basisbank_endpoint(self):
        for batch in self:
            if not batch.journal_id.is_basisbank or not batch.payment_ids:
                batch.basisbank_endpoint = False
                continue
            types = set(batch.payment_ids.mapped('basisbank_transfer_type'))
            types.discard(False)
            currencies = set(batch.payment_ids.mapped('currency_id.name'))
            gel_only = currencies == {'GEL'}
            if batch.basisbank_salary and gel_only and batch._basisbank_uniform_sender():
                batch.basisbank_endpoint = 'package_salary'
            elif types == {'internal'} and gel_only and batch._basisbank_uniform_sender():
                batch.basisbank_endpoint = 'package_gel'
            elif types == {'treasury'} and gel_only and batch._basisbank_uniform_sender():
                batch.basisbank_endpoint = 'package_treasury'
            else:
                batch.basisbank_endpoint = 'single_batch'

    def _gec_bank_protected_fields(self):
        return super()._gec_bank_protected_fields() | BASISBANK_BATCH_PROTECTED_FIELDS

    def _basisbank_uniform_sender(self):
        self.ensure_one()
        return len(set(self.payment_ids.mapped('journal_id.bank_account_number'))) == 1

    def write(self, vals):
        res = super().write(vals)
        if 'payment_ids' in vals:
            self._basisbank_revoke_approval('draft')
        return res

    def action_basisbank_submit_for_approval(self):
        """Submit draft batches for in-Odoo approval and notify the approvers."""
        for batch in self:
            connection = batch._basisbank_connection()
            if connection.processing_mode != 'odoo_approve':
                raise UserError(_("This connection does not require Odoo approval."))
            if batch.basisbank_state != 'draft':
                raise UserError(_("Only draft batches can be submitted for approval."))
            batch._basisbank_request_approval(connection, _("Batch submitted for approval."))
        return True

    def action_send_basisbank(self):
        """Open the OTP dialog; drafts are confirmed first, or the send's claim would block."""
        self.ensure_one()
        self.env['account.payment']._gec_bank_check_user(BASISBANK_METHOD_CODE)
        if self.batch_type != 'outbound':
            raise UserError(_("Only outbound batches can be sent to Basis Bank."))
        connection = self._basisbank_connection()
        self._basisbank_check_approved(connection)
        if connection.processing_mode != 'odoo_approve' and self.basisbank_state not in BASISBANK_SENDABLE_STATES:
            if self.basisbank_state == 'unknown':
                raise UserError(_("This batch is in an unknown state. Run the Resync wizard before sending again."))
            raise UserError(_("This batch cannot be sent in its current state."))
        drafts = self._basisbank_payments_to_send().filtered(lambda p: p.state == 'draft')
        if drafts:
            drafts.action_post()
        self._basisbank_check_payments()
        return self._basisbank_otp_dialog('batch_id')

    def basisbank_send_with_otp(self, otp):
        """Send the batch's pending payments with the OTP and record the bank's answer.
        Claims and results are written durably per payment, so a re-run never sends twice."""
        self.ensure_one()
        self.env['account.payment']._gec_bank_check_user(BASISBANK_METHOD_CODE)
        self.check_access('write')
        try:
            self.lock_for_update()
        except LockError:
            raise UserError(_("This batch is already being processed. Try again in a moment."))

        if self.basisbank_state not in BASISBANK_SENDABLE_STATES:
            raise UserError(_("This batch cannot be sent from its current state."))

        connection = self._basisbank_connection()
        self._basisbank_check_approved(connection)
        service = self.env['basisbank.service']
        self._basisbank_check_payments()
        payments = self._basisbank_payments_to_send()
        request = self._basisbank_build_request()
        self._basisbank_ensure_session(connection)

        sent_date = fields.Datetime.now()
        self._basisbank_claim(payments, sent_date)
        self._gec_bank_internal_write({'basisbank_state': 'sending', 'basisbank_sent_date': sent_date})
        try:
            response = self._basisbank_send_request(service, connection, otp, request)
            return self._basisbank_apply_response(response, payments, connection)
        except Exception:
            _logger.exception("Basis Bank send failed for batch %s", self.name)
            self._basisbank_mark_unknown(payments.filtered(lambda p: p.basisbank_state == 'sending'))
            return self._basisbank_notify(_("Basis Bank request failed unexpectedly. Run the "
                "Resync wizard to find out whether the bank received it."), 'warning')

    def _basisbank_mark_unknown(self, payments):
        """The bank's outcome is unclear: the payments and this batch stay Unknown until Resync."""
        for payment in payments:
            payment._basisbank_write_result({'basisbank_state': 'unknown'})
        self._gec_bank_internal_write({'basisbank_state': 'unknown'})

    def _basisbank_claim(self, payments, sent_date):
        """Claim every payment of this send durably, or none: on a failure, earlier claims go back to Pending."""
        claimed = self.env['account.payment']
        try:
            for payment in payments:
                payment._basisbank_reserve_send(sent_date)
                claimed |= payment
        except UserError:
            service = self.env['basisbank.service']
            for payment in claimed:
                service._durable_write(payment, {'basisbank_state': 'pending', 'basisbank_sent_date': False})
            raise

    def _basisbank_payments_to_send(self):
        """Members still Pending; ones the bank already confirmed are not sent again after a reset."""
        self.ensure_one()
        return self.payment_ids.filtered(lambda p: p.basisbank_state == 'pending')

    def _basisbank_check_payments(self):
        self.ensure_one()
        payments = self.payment_ids
        if not payments:
            raise UserError(_("This batch has no payments to send."))
        if self.batch_type != 'outbound':
            raise UserError(_("Only outbound batches can be sent to Basis Bank."))
        if not self.journal_id.is_basisbank:
            raise UserError(_("This batch is not on a Basis Bank journal; it cannot be sent."))
        non_outbound = payments.filtered(lambda p: p.payment_type != 'outbound')
        if non_outbound:
            raise UserError(_("Only outbound payments can be sent to Basis Bank: %s") % ', '.join(non_outbound.mapped('display_name')))
        bad_state = payments.filtered(lambda p: p.basisbank_state not in ('pending', 'confirmed'))
        if bad_state:
            raise UserError(_("These payments are not in a fresh 'Pending' state and may already be at the bank. Do not re-send them; run Resync or "
                "Reset to Pending first: %s") % ', '.join(bad_state.mapped('display_name')))
        to_send = self._basisbank_payments_to_send()
        if not to_send:
            raise UserError(_("Every payment of this batch is already confirmed by the bank; there is nothing to send."))
        already_sent = to_send.filtered('is_sent')
        if already_sent:
            raise UserError(_("These payments were already sent: %s") % ', '.join(already_sent.mapped('display_name')))
        to_send._gec_bank_check_sendable()
        to_send._basisbank_check_before_send()

    def _basisbank_build_request(self):
        self.ensure_one()
        endpoint = self.basisbank_endpoint
        payments = self._basisbank_payments_to_send()
        if endpoint in BASISBANK_ENDPOINT_KIND:
            return {
                'mode': 'package',
                'kind': BASISBANK_ENDPOINT_KIND[endpoint],
                'sender': self.journal_id.bank_account_id.sanitized_account_number or '',
                'items': [p.basisbank_build_package_item() for p in payments],
            }
        if endpoint == 'single_batch':
            groups = {key: [] for key in TRANSFER_GROUPS}
            for payment in payments:
                key, item = payment.basisbank_build_single_item()
                groups[key].append(item)
            return {'mode': 'single', 'groups': groups}
        raise UserError(_("Unknown Basis Bank endpoint."))

    def _basisbank_send_request(self, service, connection, otp, request):
        self.ensure_one()
        if request['mode'] == 'package':
            return service.upload_package(connection, request['kind'], request['sender'], self.name, otp, request['items'])
        return service.upload_single_batch(connection, otp, request['groups'])

    def _basisbank_apply_response(self, response, payments, connection):
        """Record the bank's answer; no payment stays 'sending'. Op 7 answers per transfer, packages per package.
        Payment missing from the answer: 'unknown'; wrong OTP or expired session: Pending and Awaiting OTP."""
        self.ensure_one()
        service = self.env['basisbank.service']
        error_code = response.get('ErrorCode', TECHNICAL_ERROR_CODE)
        message = (response.get('ErrorMessage') or response.get('ErrorMsg') or service.error_message(error_code))
        self._gec_bank_internal_write({'basisbank_bank_response': message})

        if error_code in RETRYABLE_SEND_CODES:
            for payment in payments:
                payment._basisbank_write_result({'basisbank_state': 'pending', 'basisbank_sent_date': False})
            self._gec_bank_internal_write({'basisbank_state': 'awaiting_otp', 'basisbank_sent_date': False})
            return self._basisbank_notify(message, 'warning')
        if error_code in UNKNOWN_SEND_CODES:
            self._basisbank_mark_unknown(payments)
            return self._basisbank_notify(_("Basis Bank reported a technical issue. Run the Resync wizard to confirm whether the transfer went "
                "through."), 'warning')
        if error_code != 0:
            payments._basisbank_reject(error_code, message)
            self._gec_bank_internal_write({'basisbank_state': 'failed'})
            return self._basisbank_notify(message, 'danger')

        sent = rejected = self.env['account.payment']
        if self.basisbank_endpoint == 'single_batch':
            data = response.get('Data') or {}
            items_by_id = {
                str(item['ClientInternalID']): item
                for key in (TRANSFER_GROUPS if isinstance(data, dict) else ())
                for item in data.get(key) or []
                if item.get('ClientInternalID') is not None
            }
            for payment in payments:
                item = items_by_id.get(str(payment.id))
                if item is None:
                    continue
                item_error = item.get('ErrorCode', 0)
                if item_error:
                    payment._basisbank_reject(item_error, item.get('Msg') or service.error_message(item_error))
                    rejected |= payment
                else:
                    payment._basisbank_write_result({
                        'basisbank_state': 'sent',
                        'basisbank_bank_internal_id': item.get('BankInternalID') or False,
                        'basisbank_error_code': 0,
                        'basisbank_error_message': False,
                    })
                    sent |= payment
        else:
            for payment in payments:
                payment._basisbank_write_result({'basisbank_state': 'sent', 'basisbank_error_code': 0, 'basisbank_error_message': False})
            sent = payments

        unaccounted = payments - sent - rejected
        if unaccounted:
            self._basisbank_mark_unknown(unaccounted)
            self.message_post(body=_("Basis Bank did not report these payments in the "
                "response; run the Resync wizard to confirm them: %s") % ', '.join(unaccounted.mapped('display_name')))
            return self._basisbank_notify(_("Some transfers were not reported by the bank. Run the Resync wizard."), 'warning')
        if not sent:
            self._gec_bank_internal_write({'basisbank_state': 'failed'})
            return self._basisbank_notify(_("All transfers were rejected by the bank."), 'danger')
        self._gec_bank_internal_write({
            'basisbank_state': 'sent_pending_confirm' if connection.processing_mode != 'bank_confirm' else 'awaiting_ib_confirmation',
        })
        return self._basisbank_notify(_("Batch sent to Basis Bank."), 'success')

    def _basisbank_set_done_when_confirmed(self):
        """Close batches whose payments the bank all confirmed and return them; rejected members are ignored."""
        def closed(batch):
            live = batch.payment_ids.filtered(lambda p: p.basisbank_state != 'failed')
            return bool(live) and all(p.basisbank_state == 'confirmed' for p in live)
        done = self.filtered(closed)
        done._gec_bank_internal_write({'basisbank_state': 'done'})
        return done

    def action_basisbank_reset_to_pending(self):
        """Put a batch the bank did not fully take back to Draft, approval cleared, to restart the send flow.
        Flagged members are re-checked by their reset; one Sent or Unknown blocks it; confirmed stay unsent."""
        self.ensure_one()
        self.env['account.payment']._gec_bank_check_user(BASISBANK_METHOD_CODE)
        if self.basisbank_state not in ('unknown', 'failed'):
            raise UserError(_("Only a batch in state Unknown or Failed can be reset to pending."))
        undecided = self.payment_ids.filtered(lambda p: p.basisbank_state in ('sending', 'sent', 'unknown'))
        if undecided:
            raise UserError(_("These payments may still be at the bank. Run Resync, or "
                "wait for the 48-hour check, before resetting the batch: %s") % ', '.join(undecided.mapped('display_name')))
        resettable = self.payment_ids.filtered(lambda p: p.basisbank_state in ('not_in_report', 'failed'))
        if not resettable:
            raise UserError(_("No payment of this batch needs to be sent again."))
        notice = resettable.action_basisbank_reset_to_pending()
        if not self._basisbank_payments_to_send():
            self._basisbank_set_done_when_confirmed()
            return notice
        self._gec_bank_internal_write({
            'basisbank_state': 'draft',
            'basisbank_sent_date': False,
            'basisbank_approved_by': False,
            'basisbank_approved_date': False,
        })
        self.message_post(body=_("%(user)s reset this batch to draft. Only its pending payments will be sent again: %(names)s.",
            user=self.env.user.display_name, names=', '.join(self._basisbank_payments_to_send().mapped('display_name'))))
        return notice

    def action_basisbank_resync(self):
        self.ensure_one()
        return {
            'name': _("Resync from Basis Bank"),
            'type': 'ir.actions.act_window',
            'res_model': 'basisbank.resync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_batch_id': self.id},
        }
