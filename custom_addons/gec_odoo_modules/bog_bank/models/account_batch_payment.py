import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import LockError, UserError
from odoo.tools.translate import LazyTranslate

from ..services.bog_service import bog_key
from .account_payment_method import BOG_METHOD_CODE, BOG_NOT_PROCESSED_STATUSES
from .bog_sendable import BOG_STATUS_POLL_LIMIT

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)

# BOG caps a BULK-dispatch line at 10,000 GEL; anything above must go as MT103.
BOG_BULK_AMOUNT_LIMIT = 10000.0
# Self-imposed ceiling per POST (BOG documents none): keeps one request inside the timeout.
BOG_BULK_MAX_LINES = 500

# Package status letters (GET api/documents/bulk/status/{key}); they differ from document letters.
# The table has no executed state: a package is confirmed only through its lines.
BOG_PACKAGE_STATUS_STATES = {
    'U': 'created',  # Uploading file, checking
    'B': 'created',  # Documents are being created
    'I': 'created',  # Individual documents created
    'P': 'created',  # To be Signed
    'A': 'created',  # The bulk transfer is in process of signature
    'Z': 'created',  # Sign in progress
    'N': 'created',  # Processing
    'S': 'sent',     # Signed
    'C': 'failed',   # Canceled by Response
    'R': 'failed',   # Deleted
    'D': 'failed',   # File Duplicate
}
BOG_PACKAGE_STATUS_LABELS = {
    'U': _lt("Uploading file, checking"),
    'B': _lt("Documents are being created"),
    'I': _lt("Individual documents created"),
    'P': _lt("To be Signed"),
    'A': _lt("The bulk transfer is in process of signature"),
    'Z': _lt("Sign in progress"),
    'N': _lt("Processing"),
    'S': _lt("Signed"),
    'C': _lt("Canceled by Response"),
    'R': _lt("Deleted"),
    'D': _lt("File Duplicate"),
}
BOG_PACKAGE_DUPLICATE_STATUS = 'D'
# Written only by the BOG flows (gec_bank's write token).
BOG_BATCH_PROTECTED_FIELDS = frozenset({
    'bog_state', 'bog_bulk_key', 'bog_file_name', 'bog_bank_status', 'bog_error_message',
})


class AccountBatchPayment(models.Model):
    _name = 'account.batch.payment'
    _inherit = ['account.batch.payment', 'bog.sendable']

    is_bog = fields.Boolean(related='journal_id.is_bog')
    # BOG's id for the whole batch (a bare integer from the bulk endpoint).
    bog_bulk_key = fields.Char(string='BOG Batch Key', readonly=True, copy=False, index=True)
    bog_file_name = fields.Char(string='BOG File Name', readonly=True, copy=False,
                                help="The fileName the batch was submitted under. BOG requires "
                                     "it as a query parameter and shows it in Business Online.")
    bog_state = fields.Selection(
        selection=[('draft', 'Draft'),
                   ('sending', 'Sending'),
                   ('created', 'Created at Bank (unsigned)'),
                   ('sent', 'Sent / Signed'),
                   ('partial', 'Partially Failed'),
                   ('confirmed', 'Confirmed'),
                   ('failed', 'Failed'),
                   ('unknown', 'Unknown')],
        string='BOG Batch State', default='draft', readonly=True, copy=False, tracking=True,
        index=True)
    bog_bank_status = fields.Char(string='Bank Status (raw)', readonly=True, copy=False)
    bog_error_message = fields.Char(string='BOG Error', readonly=True, copy=False)

    bog_processing_mode = fields.Selection(related='journal_id.bog_connection_id.processing_mode',
                                           string='BOG Processing Mode')

    def _gec_bank_protected_fields(self):
        return super()._gec_bank_protected_fields() | BOG_BATCH_PROTECTED_FIELDS

    def action_bog_submit_approval(self):
        """Submit every pending BOG transfer of the batch for approval in one click."""
        self.ensure_one()
        return self.payment_ids.action_bog_submit_approval()

    def action_bog_approve(self):
        """Approve every BOG transfer of the batch awaiting approval, with the payment form's rules."""
        self.ensure_one()
        return self.payment_ids.action_bog_approve()

    def _bog_sendable_payments(self):
        """The members a send may still claim, read under a lock on the batch so the hourly poll cannot write it
        meanwhile; an unsettled earlier send blocks a new package."""
        self.ensure_one()
        try:
            self.lock_for_update(allow_referencing=True)
        except LockError:
            raise UserError(_("This batch is already being processed. Try again in a moment."))
        if not self.journal_id.is_bog:
            raise UserError(_("This batch is not on a Bank of Georgia journal."))
        unsettled = self.payment_ids.filtered(
            lambda p: p.gec_bank_state in ('sending', 'created', 'sent', 'unknown'))
        if unsettled:
            raise UserError(_(
                "An earlier send of this batch is not settled yet. Wait for the bank's status, "
                "recover the transfers whose outcome is unknown, or send the failed transfers "
                "from their own payment or in a new batch: %s",
                ', '.join(unsettled.mapped('display_name'))))
        # A warned transfer goes again only through Create Anyway on its payment.
        payments = self.payment_ids._gec_bank_own(BOG_METHOD_CODE).filtered(
            lambda p: p.gec_bank_state not in ('confirmed', 'failed', 'awaiting_confirmation'))
        if not payments:
            raise UserError(_("No sendable Bank of Georgia transfers in this batch."))
        if len(payments) > BOG_BULK_MAX_LINES:
            raise UserError(_("This batch has %(count)s sendable transfers. Split it into batches "
                              "of at most %(limit)s.",
                              count=len(payments), limit=BOG_BULK_MAX_LINES))
        return payments

    def _bog_build_file_name(self):
        """BOG requires a fileName on the bulk endpoint and shows it in Business Online."""
        self.ensure_one()
        base = self.name or ('BATCH-%s' % self.id)
        return re.sub(r'[^A-Za-z0-9_-]', '-', base)[:50]

    def action_bog_send_batch(self):
        """Send the whole batch through BOG's bulk endpoint in one call; the answer has no per-line result, so
        each payment is checked and reserved before the call."""
        self.ensure_one()
        self.check_access('write')
        self.env['account.payment']._gec_bank_check_user(BOG_METHOD_CODE)
        payments = self._bog_sendable_payments()
        connection = self._bog_connection()
        if len(set(payments.mapped('bog_transfer_type'))) > 1:
            raise UserError(_("A batch cannot mix domestic and foreign transfers. BOG has a "
                              "separate bulk endpoint for each."))
        for payment in payments:
            payment._bog_check_sendable()
            payment._bog_ensure_attachments_uploaded(connection)
        # Logged in before the claim: a login failure after it would leave every payment stuck in 'sending'.
        self.env['bog.service']._ensure_token(connection)

        previous_states = {payment: payment.gec_bank_state for payment in payments}
        previous_states[self] = self.bog_state
        documents = self._bog_claim(payments)

        file_name = self._bog_build_file_name()
        self._gec_bank_internal_write({'bog_state': 'sending', 'bog_file_name': file_name})

        service = self.env['bog.service']
        if payments[:1].bog_transfer_type == 'foreign':
            result = service.create_bulk_foreign(connection, documents, file_name)
        else:
            result = service.create_bulk_domestic(connection, documents, file_name)
        return self._bog_apply_bulk_result(result, payments, previous_states)

    def _bog_claim(self, payments):
        """Claim every payment durably and build its documents, or none: any failure undoes earlier claims."""
        documents = []
        claimed = {}
        try:
            for payment in payments:
                state = payment.gec_bank_state
                payment._bog_reserve_send()
                claimed[payment] = state
                documents.append(payment._bog_build_document())
        except Exception:
            service = self.env['gec.bank.service']
            for payment, state in claimed.items():
                service._durable_write(payment, {'gec_bank_state': state})
            raise
        return documents

    def _bog_apply_bulk_result(self, result, payments, previous_states=None):
        """Turn the bulk answer into states; no response or 5xx leaves every payment 'unknown'; 401/429 (refused
        before processing) gives every claim back."""
        self.ensure_one()
        http_status = result.get('http_status', 0)
        data = result.get('data')

        if http_status in BOG_NOT_PROCESSED_STATUSES:
            message = result.get('error_text') or str(http_status)
            self._gec_bank_internal_write({'bog_state': (previous_states or {}).get(self) or 'draft',
                                           'bog_error_message': message[:255]})
            for payment in payments:
                payment._gec_bank_release_claim((previous_states or {}).get(payment), message)
            return self._bog_notify(
                _("Bank of Georgia refused the batch before processing it (login or rate limit), so "
                  "nothing was created. Send it again later."), 'warning')

        if http_status == 0 or http_status >= 500:
            message = (result.get('error_text')
                       or _("Ambiguous result (timeout/server error)."))
            self._gec_bank_internal_write({'bog_state': 'unknown', 'bog_error_message': message[:255]})
            for payment in payments:
                payment._gec_bank_write_result({
                    'gec_bank_state': 'unknown',
                    'gec_bank_error': _("Batch send was ambiguous. Use Recover from BOG.")})
            return self._bog_notify(
                _("Bank of Georgia did not confirm this batch. The transfers may or may not "
                  "exist at the bank - recover each one before resending."), 'warning')

        if http_status >= 400:
            message = result.get('error_text') or _("Batch rejected.")
            self._gec_bank_internal_write({'bog_state': 'failed', 'bog_error_message': message[:255]})
            for payment in payments:
                payment._gec_bank_write_result({'gec_bank_state': 'failed',
                                                'gec_bank_error': message[:255]})
            return self._bog_notify(message, 'danger')

        bulk_key = data.get('UniqueKey') or data.get('uniqueKey') if isinstance(data, dict) else data
        bulk_key = bog_key(bulk_key) if isinstance(bulk_key, (int, float, str)) else ''
        if not bulk_key:
            self._gec_bank_internal_write({'bog_state': 'unknown',
                                   'bog_error_message': _("No batch key returned by Bank of Georgia.")})
            for payment in payments:
                payment._gec_bank_write_result({
                    'gec_bank_state': 'unknown',
                    'gec_bank_error': _("Batch send was ambiguous. Use Recover from BOG.")})
            return self._bog_notify(_("Bank of Georgia returned no batch key. Check Business Online."),
                                    'warning')

        self._gec_bank_internal_write({'bog_bulk_key': bulk_key, 'bog_state': 'created', 'bog_error_message': False})
        for payment in payments:
            payment._gec_bank_write_result({'gec_bank_state': 'created', 'bog_bulk_key': bulk_key,
                                            'gec_bank_error': False})

        # A status lookup must never fail a successful create. Flushed first: a database error of pending writes
        # must not be swallowed with the lookup's (the transaction would be aborted).
        self.env.flush_all()
        try:
            with self.env.cr.savepoint():
                self._bog_refresh_bulk_status()
        except Exception:
            _logger.exception("BOG: post-send bulk status refresh failed for batch %s", self.id)
        return self._bog_notify(_("%(count)s transfer(s) submitted as batch %(key)s.",
                                  count=len(payments), key=self.bog_bulk_key), 'success')

    def action_bog_send_batch_individually(self):
        """Send each payment through the single-document endpoint, for when the bulk endpoint refuses."""
        self.ensure_one()
        self.check_access('write')
        self.env['account.payment']._gec_bank_check_user(BOG_METHOD_CODE)
        payments = self._bog_sendable_payments()
        done, errors, _notice = payments._gec_bank_send_each(BOG_METHOD_CODE)
        self._gec_bank_internal_write({'bog_state': self._bog_state_from_members(), 'bog_bulk_key': False})
        return payments._gec_bank_report_sends(BOG_METHOD_CODE, done, errors)

    def action_bog_refresh_bulk_status(self):
        self.check_access('write')
        open_states = self.env['account.payment']._gec_bank_state_groups()['open']
        for batch in self:
            if not batch.bog_bulk_key:
                batch.payment_ids.filtered(lambda p: p.gec_bank_state in open_states)._gec_bank_refresh_status(BOG_METHOD_CODE)
            batch._bog_refresh_bulk_status()
        return True

    def _bog_refresh_bulk_status(self):
        """Read the package status and push each line's status onto its payment."""
        self.ensure_one()
        if not self.bog_bulk_key and not self._bog_adopt_orphan_package():
            self._gec_bank_internal_write({'bog_state': self._bog_state_from_members()})
            return
        connection = self._bog_connection()
        result = self.env['bog.service'].get_bulk_status(connection, self.bog_bulk_key)
        http_status = result.get('http_status', 0)
        if http_status == 0 or http_status >= 500:
            return
        data = result.get('data')
        if not isinstance(data, dict):
            return

        status = (data.get('Status') or data.get('status') or '').strip()
        lines = (data.get('DocumentStatuses') or data.get('documentStatuses')
                 or data.get('BulkLineStatus') or data.get('bulkLineStatus') or [])
        if isinstance(lines, dict):
            lines = [lines]
        matched = self._bog_apply_bulk_lines(lines) if isinstance(lines, list) else 0

        letter = status.upper()
        state = BOG_PACKAGE_STATUS_STATES.get(letter)
        vals = {'bog_bank_status': status or False}
        if state == 'failed':
            vals.update({'bog_state': 'failed', 'bog_error_message': self.env._(BOG_PACKAGE_STATUS_LABELS[letter])[:255]})
            self._gec_bank_internal_write(vals)
            self._bog_fail_members(letter)
            return
        if state:
            vals.update({'bog_state': self._bog_state_from_members(state), 'bog_error_message': False})
        elif status and not matched and status != self.bog_bank_status:
            self.message_post(body=_("Bank of Georgia returned an unrecognised batch status: %s. "
                                     "The batch state was left unchanged.") % status)
        self._gec_bank_internal_write(vals)

    def _bog_state_from_members(self, package_state=None):
        """The batch state from its transfers: a failure or a full confirmation wins over the package status; without a package they decide alone."""
        states = set(self.payment_ids.mapped('gec_bank_state'))
        held = self.env['account.payment']._gec_bank_state_groups()['held']
        if not package_state and states & {'sending', 'unknown'}:
            return 'unknown'
        if states and states <= {'failed'}:
            return 'failed'
        if 'failed' in states:
            return 'partial'
        if states and states <= {'confirmed'}:
            return 'confirmed'
        if package_state:
            return package_state
        if not states & held:
            return 'draft'
        if states - held:
            return 'partial'
        return 'created' if 'created' in states else 'sent'

    def _bog_adopt_orphan_package(self):
        """Take back the package key from the members when the batch lost it (the request rolled back after BOG
        accepted the package; the members' key is durable). True when the batch has a key again."""
        keys = set(self.payment_ids.filtered(
            lambda p: p.bog_bulk_key and p.gec_bank_state == 'created').mapped('bog_bulk_key'))
        if len(keys) != 1:
            return False
        self._gec_bank_internal_write({'bog_bulk_key': keys.pop(), 'bog_state': 'created'})
        self.message_post(body=_("The Bank of Georgia package key was restored from the batch's transfers."))
        return True

    def _bog_package_payments(self):
        """The members of the batch's current package."""
        self.ensure_one()
        return self.payment_ids.filtered(
            lambda p: self.bog_bulk_key and p.bog_bulk_key == self.bog_bulk_key)

    def _bog_fail_members(self, letter):
        """A rejected package fails its members; a File Duplicate makes them unknown (an earlier one may have run)."""
        members = self._bog_package_payments().filtered(
            lambda p: p.gec_bank_state in ('sending', 'created', 'sent'))
        if letter == BOG_PACKAGE_DUPLICATE_STATUS:
            note = _("Bank of Georgia reports this file as a duplicate of an earlier package. "
                     "Check Business Online before doing anything else: the earlier package may "
                     "have executed, and nothing was resent.")
            self.message_post(body=note)
            for payment in members:
                payment._gec_bank_write_result({'gec_bank_state': 'unknown', 'gec_bank_error': note[:255]})
            return
        for payment in members:
            payment._gec_bank_write_result({'gec_bank_state': 'failed',
                                            'gec_bank_error': _("The package was rejected by Bank of Georgia.")})

    def _bog_apply_bulk_lines(self, lines):
        """Map DocumentStatuses entries back onto payments and return how many matched."""
        self.ensure_one()
        package = self._bog_package_payments()
        by_unique_id = {p.gec_bank_request_id: p for p in package if p.gec_bank_request_id}
        by_document_no = {p.bog_document_no: p for p in package if p.bog_document_no}
        matched = 0
        for line in lines:
            if not isinstance(line, dict):
                continue
            unique_id = str(line.get('UniqueId') or line.get('uniqueId') or '').strip()
            document_no = str(line.get('DocumentNo') or line.get('documentNo') or '').strip()
            payment = by_unique_id.get(unique_id) or by_document_no.get(document_no)
            if not payment:
                continue
            matched += 1
            vals = {}
            unique_key = bog_key(line.get('UniqueKey') or line.get('uniqueKey'))
            if unique_key and not payment.gec_bank_reference:
                vals['gec_bank_reference'] = unique_key
            result_code = line.get('ResultCode')
            if result_code is not None:
                vals['bog_result_code'] = int(result_code or 0)
            reject_code = line.get('RejectCode')
            if reject_code not in (None, ''):
                vals['bog_reject_code'] = str(reject_code)
            match = line.get('Match')
            if match is not None:
                vals['bog_match_percent'] = float(match or 0.0)
            line_status = str(line.get('Status') or line.get('status') or '').strip()
            if line_status:
                vals['bog_bank_status'] = line_status
            vals.update(payment._bog_status_vals(line_status, reject_code))
            code = vals.get('bog_result_code')
            if code and code != payment.bog_result_code and vals.get('gec_bank_state') != 'failed':
                # A result code on a line BOG has not failed: shown once, the state is left to the status letter.
                payment.message_post(body=_("Bank of Georgia returned result code %(code)s for this transfer in "
                                            "its package: %(text)s Check it in Business Online.",
                                            code=code, text=payment._bog_result_text(code)))
            if vals:
                payment._gec_bank_write_result(vals)
        return matched

    @api.model
    def _cron_bog_bulk_status_poll(self):
        """Poll open batches, and batches without a key while a transfer of theirs is open or the batch is Unknown, least recently
        written first; a batch a user is sending is skipped. Connections in 'error' are polled too: one failed login must not stop it for good."""
        journals = self.env['account.journal'].with_context(active_test=False).search([('is_bog', '=', True)])
        journals = journals.filtered(lambda journal: journal.bog_connection_id.state in ('active', 'error'))
        batches = self.search([
            ('journal_id', 'in', journals.ids),
            '|',
            '&',
            ('bog_bulk_key', '!=', False),
            ('bog_state', 'in', ('created', 'sent', 'partial', 'unknown')),
            '&',
            '&',
            ('bog_bulk_key', '=', False),
            ('bog_state', '!=', 'sending'),
            '|',
            ('bog_state', '=', 'unknown'),
            ('payment_ids', 'any', [('gec_bank_state', 'in', ('created', 'sent', 'unknown'))]),
        ], order='write_date, id', limit=BOG_STATUS_POLL_LIMIT)
        for batch in batches.try_lock_for_update(allow_referencing=True).with_context(gec_bank_poll=True):
            try:
                with self.env.cr.savepoint():
                    batch._bog_refresh_bulk_status()
            except Exception:
                _logger.exception("BOG: bulk status refresh failed for batch %s", batch.id)

    def action_bog_cancel_batch(self):
        """DELETE the batch at BOG while it is still unsigned."""
        self.ensure_one()
        self.check_access('write')
        self.env['account.payment']._gec_bank_check_user(BOG_METHOD_CODE)
        if self.bog_state != 'created':
            raise UserError(_("Only a batch that is created but not yet signed can be cancelled."))
        if not self.bog_bulk_key:
            raise UserError(_("This batch has no Bank of Georgia batch key."))
        connection = self._bog_connection()
        result = self.env['bog.service'].delete_bulk(connection, self.bog_bulk_key)
        http_status = result.get('http_status', 0)
        if http_status and 200 <= http_status < 300:
            self._gec_bank_internal_write({'bog_state': 'failed', 'bog_error_message': _("Cancelled in Odoo.")})
            self._bog_package_payments().filtered(lambda p: p.gec_bank_state == 'created')._bog_cancel_locally()
            return self._bog_notify(_("The batch was cancelled at Bank of Georgia."), 'success')
        return self._bog_notify(_("Bank of Georgia refused the cancellation: %s")
                                % (result.get('error_text') or http_status), 'warning')
