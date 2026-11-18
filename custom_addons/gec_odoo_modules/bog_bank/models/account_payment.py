import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import LazyTranslate

from ..services.bog_service import bog_key
from .account_batch_payment import BOG_BULK_AMOUNT_LIMIT
from .account_payment_method import BOG_METHOD_CODE, BOG_NOT_PROCESSED_STATUSES

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)

BOG_TRANSFER_TYPES = [
    ('domestic', 'Domestic (GEL, Georgian bank)'),
    ('foreign', 'Foreign (SWIFT)'),
]

# ResultCode 0: "Document is Ready to Sign". The document exists; no money has moved.
BOG_RESULT_READY = 0
# Warn codes: BOG asks "create it anyway?". Never auto-retry; 363 is BOG's duplicate detector.
BOG_WARN_CODES = {333, 363, 444, 701}
BOG_DUPLICATE_CODE = 363
# CheckUniqueId answer: a document with this UniqueId was created in the last 7 days. Not in BOG's table.
BOG_UNIQUE_ID_EXISTS_CODE = 702
# A send never outlives a worker (limit_time_real), so 'sending' this long is stuck.
BOG_SENDING_STALE_MINUTES = 15
# Fields the document is built from; changing one after approval voids it.
BOG_DOCUMENT_FIELDS = frozenset({
    'amount', 'currency_id', 'partner_id', 'partner_bank_id', 'memo', 'journal_id',
    'bog_transfer_type', 'bog_value_date', 'bog_dispatch_type', 'bog_is_salary', 'bog_check_inn',
    'bog_beneficiary_name', 'bog_beneficiary_inn', 'bog_beneficiary_bank_code',
    'bog_additional_information', 'bog_attachment_ids',
})
# Written only by the BOG flows (gec_bank's write token).
BOG_PROTECTED_FIELDS = frozenset({
    'bog_document_no', 'bog_bank_status', 'bog_result_code', 'bog_reject_code', 'bog_warn_code',
    'bog_match_percent', 'bog_attachment_hashes', 'bog_bulk_key',
})

# Common result codes as sentences. Full table: https://api.bog.ge/docs/bonline/result/result-codes
BOG_RESULT_MESSAGES = {
    29: _lt("Beneficiary account number and ID code do not match."),
    30: _lt("Beneficiary account number or bank code is empty."),
    33: _lt("Sender ID not found, or the sender account is invalid."),
    39: _lt("Beneficiary account is invalid."),
    41: _lt("Beneficiary ID code is invalid."),
    47: _lt("The document's signature deadline expired."),
    48: _lt("Value date is invalid."),
    50: _lt("Amount format is invalid."),
    54: _lt("Transfer purpose (Nomination) is empty."),
    55: _lt("Purpose field exceeds 250 characters."),
    147: _lt("Invalid IBAN format."),
    155: _lt("Salary transfers may only be made to individuals."),
    333: _lt("Working balance is insufficient."),
    363: _lt("BOG detected this as a duplicate document."),
    444: _lt("Insufficient amount."),
    669: _lt("An invoice or contract must be attached to this transfer."),
    674: _lt("You do not have permission to transfer from this account."),
    677: _lt("Purpose (Nomination) is mandatory."),
    678: _lt("Dispatch type is mandatory."),
    701: _lt("The document failed BOG's validations."),
    702: _lt("A document with this request id already exists at BOG."),
    1001: _lt("You do not have transfer permission."),
}

# Document status letters (GET api/documents/status/{key}). An unlisted letter, 'N' Incomplete,
# leaves the state alone. The package table (account_batch_payment.py) reuses the letters.
BOG_DOCUMENT_STATUS_STATES = {
    'A': 'created',    # To be Signed
    'Z': 'created',    # Sign In Progress
    'S': 'sent',       # Signed
    'T': 'sent',       # In Progress
    'P': 'confirmed',  # Completed
    'R': 'failed',     # Rejected
    'D': 'failed',     # Cancelled by Bank
    'C': 'failed',     # Cancelled by Response
}
BOG_DOCUMENT_STATUS_LABELS = {
    'A': _lt("To be Signed"),
    'Z': _lt("Sign In Progress"),
    'S': _lt("Signed"),
    'T': _lt("In Progress"),
    'P': _lt("Completed"),
    'R': _lt("Rejected"),
    'D': _lt("Cancelled by Bank"),
    'C': _lt("Cancelled by Response"),
    'N': _lt("Incomplete"),
}
# RejectCode of a status answer.
BOG_REJECT_MESSAGES = {
    12: _lt("Wrong IBAN format."),
    13: _lt("Treasury code not set."),
    14: _lt("Beneficiary account is incorrect."),
    15: _lt("Wrong destination."),
    16: _lt("Fonts cannot be read."),
    17: _lt("Insufficient funds."),
    18: _lt("Blocked card."),
    19: _lt("Expired card."),
    20: _lt("Card error."),
    21: _lt("The recipient account and name do not match."),
    22: _lt("Cancelled; contact the bank for more information."),
}


class AccountPayment(models.Model):
    """Bank of Georgia transfers on gec_bank's shared transfer flow."""

    _name = 'account.payment'
    _inherit = ['account.payment', 'bog.sendable']

    is_bog = fields.Boolean(related='journal_id.is_bog')
    bog_processing_mode = fields.Selection(related='journal_id.bog_connection_id.processing_mode',
                                           string='BOG Processing Mode', readonly=True)

    # awaiting_confirmation: BOG warned and did not create the document. created: at the bank, unsigned.
    gec_bank_state = fields.Selection(
        selection_add=[('sending',),
                       ('awaiting_confirmation', 'Awaiting Confirmation'),
                       ('created', 'Created at Bank (unsigned)'),
                       ('sent',)],
        ondelete={'awaiting_confirmation': 'set pending', 'created': 'set unknown'})

    bog_transfer_type = fields.Selection(BOG_TRANSFER_TYPES, string='BOG Transfer Type',
                                         default='domestic')
    bog_dispatch_type = fields.Selection([('MT103', 'MT103 (individual)'),
                                          ('BULK', 'BULK (standard, <= 10,000 GEL)')],
                                         string='Dispatch Type', default='MT103')

    # The last package (bulk send) of this transfer; a new claim clears it.
    bog_bulk_key = fields.Char(string='BOG Batch Key', readonly=True, copy=False,
                               index='btree_not_null')
    bog_document_no = fields.Char(string='Document No.', readonly=True, copy=False,
                                  help="Max 16 characters. Also the only handle for recovering "
                                       "a timed-out send through today's activities.")

    bog_bank_status = fields.Char(string='Bank Status (raw)', readonly=True, copy=False,
                                  help="The Status letter exactly as BOG returned it.")
    bog_result_code = fields.Integer(string='Result Code', readonly=True, copy=False)
    bog_reject_code = fields.Char(string='Reject Code', readonly=True, copy=False)
    bog_match_percent = fields.Float(string='Name Match %', readonly=True, copy=False,
                                     help="How closely the beneficiary name matches the account "
                                          "holder at BOG. Only returned for domestic transfers.")

    bog_value_date = fields.Date(string='Value Date', default=fields.Date.context_today,
                                 help="The date BOG should process the document.")
    bog_is_salary = fields.Boolean(string='Is Salary', default=False,
                                   help="Salary transfers may only be sent to individuals.")
    bog_check_inn = fields.Boolean(string='Verify Beneficiary ID', default=False,
                                   help="Ask BOG to confirm the account belongs to the given ID. "
                                        "Only valid for transfers within Bank of Georgia.")

    # Warn code of the last send; separate from bog_result_code so the confirm buttons can key on it.
    bog_warn_code = fields.Integer(string='Pending Warning Code', readonly=True, copy=False)

    bog_attachment_ids = fields.Many2many(
        'ir.attachment', 'bog_payment_attachment_rel', 'payment_id', 'attachment_id',
        string='BOG Attachments',
        help="Invoices or contracts to send with this transfer. Result code 669 rejects "
             "some transfers until one is attached.")
    bog_attachment_hashes = fields.Char(
        string='BOG Attachment Hashes', readonly=True, copy=False,
        help="Space-separated externalFileHash values returned by BOG for the files of the last send. Every send "
             "uploads the files again.")

    bog_beneficiary_name = fields.Char(string='Beneficiary Name')
    bog_beneficiary_inn = fields.Char(string='Beneficiary ID / Tax Code')
    bog_beneficiary_bank_code = fields.Char(string='Beneficiary Bank Code (RTGS/BIC)')
    bog_additional_information = fields.Char(string='Additional Information',
                                             help="Foreign transfers only. Max 210 characters.")

    @api.depends('journal_id.is_bog')
    def _compute_gec_bank_code(self):
        """The BOG channel runs the transfer flow only on a BOG journal."""
        super()._compute_gec_bank_code()

    @api.model
    def _get_method_codes_using_bank_account(self):
        return super()._get_method_codes_using_bank_account() + [BOG_METHOD_CODE]

    def _gec_bank_protected_fields(self):
        return super()._gec_bank_protected_fields() | BOG_PROTECTED_FIELDS

    @api.model
    def _gec_bank_state_groups(self):
        """A created document is at the bank, held. A Warn answer is in doubt and still approved."""
        groups = super()._gec_bank_state_groups()
        for name in ('at_bank', 'held', 'open'):
            groups[name].add('created')
        for name in ('uncertain', 'in_approval'):
            groups[name].add('awaiting_confirmation')
        return groups

    @api.model
    def _gec_bank_result_columns(self):
        return super()._gec_bank_result_columns() | {
            'bog_bank_status', 'bog_result_code', 'bog_reject_code', 'bog_warn_code',
            'bog_match_percent', 'bog_attachment_hashes', 'bog_bulk_key'}

    @api.model
    def _gec_bank_label_for(self, code):
        if code == BOG_METHOD_CODE:
            return _("Bank of Georgia")
        return super()._gec_bank_label_for(code)

    @api.model
    def _gec_bank_user_group_for(self, code):
        if code == BOG_METHOD_CODE:
            return 'bog_bank.group_bog_user'
        return super()._gec_bank_user_group_for(code)

    def _gec_bank_connection_record(self):
        if self.gec_bank_code != BOG_METHOD_CODE:
            return super()._gec_bank_connection_record()
        # sudo: a configuration read, not a data read.
        return self.journal_id.bog_connection_id[:1].sudo()

    def _gec_bank_send_one(self):
        if self.gec_bank_code != BOG_METHOD_CODE:
            return super()._gec_bank_send_one()
        return self._bog_send_one()

    def _gec_bank_refresh_one(self):
        if self.gec_bank_code != BOG_METHOD_CODE:
            return super()._gec_bank_refresh_one()
        return self._bog_refresh_status()

    def _gec_bank_new_request_vals(self):
        """UniqueId and DocumentNo stay the same on every retry; a new UniqueId is a new document to BOG."""
        if self.gec_bank_code != BOG_METHOD_CODE:
            return super()._gec_bank_new_request_vals()
        return {'gec_bank_request_id': self.gec_bank_request_id or str(uuid.uuid4()),
                'bog_document_no': self.bog_document_no or ('ODOO%s' % self.id)[:16],
                'bog_bulk_key': False}

    def _gec_bank_payload_fields(self):
        if self.gec_bank_code != BOG_METHOD_CODE:
            return super()._gec_bank_payload_fields()
        return BOG_DOCUMENT_FIELDS

    def _bog_result_text(self, result_code):
        """Readable sentence for a BOG ResultCode, falling back to the number."""
        if result_code is None:
            return ''
        known = BOG_RESULT_MESSAGES.get(int(result_code))
        return self.env._(known) if known else self.env._("Bank of Georgia result code %s.", result_code)

    def action_bog_submit_approval(self):
        return self._gec_bank_submit_approval(BOG_METHOD_CODE)

    def action_bog_approve(self):
        return self._gec_bank_approve(BOG_METHOD_CODE)

    def action_bog_send(self):
        return self._gec_bank_send_transfers(BOG_METHOD_CODE)

    def _bog_reserve_send(self):
        """Claim this payment for one send; return its UniqueId and DocumentNo."""
        vals = self._gec_bank_reserve_send()
        return vals['gec_bank_request_id'], vals['bog_document_no']

    def _bog_check_sendable(self):
        """Refuse, before anything is reserved, a payment that must not go out. A warned transfer goes again
        only through Create Anyway, so a person decides on BOG's warning."""
        self.ensure_one()
        self._gec_bank_check_transfer(BOG_METHOD_CODE)
        if self.gec_bank_state == 'awaiting_confirmation' and not self.env.context.get('bog_create_anyway'):
            raise UserError(_("Bank of Georgia warned about %s and did not create it. Check the warning, "
                              "then use Create Anyway on the payment.", self.display_name))
        self._gec_bank_check_instructions()

    def _gec_bank_check_instructions(self):
        """Refuse a payment to a contact with a Treasury Code, then a wrongly set up channel."""
        if self.gec_bank_code != BOG_METHOD_CODE:
            return super()._gec_bank_check_instructions()
        if (self.partner_id.commercial_partner_id.gec_treasury_code or '').strip():
            raise UserError(_(
                "%s is a treasury payment. Our Bank of Georgia connection does not send "
                "treasury transfers yet: pay it through Basis or TBC.", self.display_name))
        if self.bog_transfer_type == 'foreign':
            raise UserError(_(
                "%s is a foreign transfer. Our Bank of Georgia connection does not build BOG's foreign "
                "document yet (charges, beneficiary address and country): pay it through Business Online "
                "or TBC.", self.display_name))
        errors = self.payment_method_line_id._gec_bank_config_errors()
        if errors:
            raise UserError('\n'.join(errors))
        account_currency = self.journal_id.currency_id or self.journal_id.company_id.currency_id
        if self.currency_id != account_currency:
            raise UserError(_(
                "%(name)s is in %(currency)s, but the journal's account is in %(account)s. Bank of Georgia "
                "debits the journal's account in its own currency: pay from a %(currency)s journal.",
                name=self.display_name, currency=self.currency_id.name, account=account_currency.name))
        if (self.bog_transfer_type == 'domestic' and self.bog_dispatch_type == 'BULK'
                and self.currency_id.name == 'GEL'
                and self.currency_id.compare_amounts(self.amount, BOG_BULK_AMOUNT_LIMIT) > 0):
            raise UserError(_("%(name)s: Bank of Georgia accepts BULK dispatch only up to %(limit)s GEL. "
                              "Set Dispatch Type to MT103.", name=self.display_name, limit=BOG_BULK_AMOUNT_LIMIT))

    def _bog_prepare_send(self):
        """The connection, logged in and with attachments uploaded, before the payment is claimed as 'sending':
        a login failure after the claim would leave it stuck in 'sending' with nothing sent."""
        connection = self._gec_bank_connection()
        self.env['bog.service']._ensure_token(connection)
        self._bog_ensure_attachments_uploaded(connection)
        return connection

    def _bog_send_one(self):
        self.ensure_one()
        self._bog_check_sendable()
        connection = self._bog_prepare_send()
        previous_state = self.gec_bank_state
        self._bog_reserve_send()
        document = self._bog_build_document()
        service = self.env['bog.service']
        if self.bog_transfer_type == 'foreign':
            result = service.create_foreign(connection, [document])
        else:
            result = service.create_domestic(connection, [document])
        return self._bog_apply_send_result(result, previous_state)

    def _bog_apply_send_result(self, result, previous_state=None):
        """Turn a create-document response into a state; never raises. No response or 5xx: 'unknown'; 401/429:
        back to ``previous_state``; other 4xx: failed; a 200 may still carry a failure or Warn code."""
        self.ensure_one()
        http_status = result.get('http_status', 0)
        data = result.get('data')

        if http_status in BOG_NOT_PROCESSED_STATUSES:
            self._gec_bank_release_claim(previous_state, result.get('error_text') or str(http_status))
            return self._bog_notify(
                _("Bank of Georgia refused the request before processing it (login or rate limit), so "
                  "nothing was created. Send it again later."), 'warning')

        if http_status == 0 or http_status >= 500:
            self._gec_bank_write_result({
                'gec_bank_state': 'unknown',
                'gec_bank_error': (result.get('error_text')
                                   or _("Ambiguous result (timeout/server error). "
                                        "Use Recover from BOG."))[:255],
            })
            return self._bog_notify(
                _("Bank of Georgia did not confirm this transfer (timeout/server error). "
                  "It may or may not exist at the bank - use 'Recover from BOG' before resending."),
                'warning')

        if http_status >= 400:
            self._gec_bank_write_result({'gec_bank_state': 'failed',
                                         'gec_bank_error': (result.get('error_text')
                                                            or _("Transfer rejected."))[:255]})
            return True

        first = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
        if not isinstance(first, dict):
            first = {}
        result_code = first.get('ResultCode')
        document_key = bog_key(first.get('UniqueKey'))
        match = first.get('Match')

        vals = {'bog_result_code': int(result_code or 0)}
        if match is not None:
            vals['bog_match_percent'] = float(match or 0.0)

        if result_code is not None and int(result_code) != BOG_RESULT_READY:
            code = int(result_code)
            message = self._bog_result_text(code)
            if code == BOG_UNIQUE_ID_EXISTS_CODE:
                message = _("Bank of Georgia already holds a document with this request id. Use "
                            "'Recover from BOG' to load it; do not create a new payment.")
                vals.update({'gec_bank_state': 'unknown', 'bog_warn_code': code,
                             'gec_bank_error': message[:255]})
                self._gec_bank_write_result(vals)
                return self._bog_notify(message, 'warning')
            if code == BOG_DUPLICATE_CODE:
                # Not offered as Create Anyway: resending past a duplicate pays twice.
                message = _("%s Check Business Online before doing anything else - the "
                            "original document may already exist.") % message
                vals.update({'gec_bank_state': 'failed', 'bog_warn_code': code,
                             'gec_bank_error': message[:255]})
                self._gec_bank_write_result(vals)
                return self._bog_notify(message, 'danger')
            if code in BOG_WARN_CODES:
                vals.update({'gec_bank_state': 'awaiting_confirmation', 'bog_warn_code': code,
                             'gec_bank_error': message[:255]})
                self._gec_bank_write_result(vals)
                return self._bog_notify(
                    _("%s Bank of Georgia did not create the document. Fix the cause, then "
                      "use 'Create Anyway' to submit it again.") % message, 'warning')
            vals.update({'gec_bank_state': 'failed', 'bog_warn_code': 0,
                         'gec_bank_error': message[:255]})
            self._gec_bank_write_result(vals)
            return self._bog_notify(message, 'danger')

        if not document_key:
            vals.update({'gec_bank_state': 'unknown',
                         'gec_bank_error': _("No document key returned by Bank of Georgia.")})
            self._gec_bank_write_result(vals)
            return True

        # Who signs depends on the API app registration, so the status check decides 'sent'.
        vals.update({'gec_bank_reference': document_key,
                     'gec_bank_state': 'created',
                     'bog_warn_code': 0,
                     'gec_bank_error': False})
        self._gec_bank_write_result(vals)
        self._bog_check_name_match()

        # A status lookup must never fail a successful create. Flushed first: a database error of pending writes
        # must not be swallowed with the lookup's (the transaction would be aborted).
        self.env.flush_all()
        try:
            with self.env.cr.savepoint():
                self._bog_refresh_status()
        except Exception:
            _logger.exception("BOG: post-send status refresh failed for payment %s", self.id)
        return True

    def _bog_check_name_match(self):
        """Post a note when BOG's beneficiary-name match is below the connection threshold."""
        self.ensure_one()
        connection = self.journal_id.bog_connection_id[:1].sudo()
        threshold = connection.match_threshold if connection else 0.0
        if not threshold or not self.bog_match_percent:
            return
        if self.bog_match_percent < threshold:
            self.message_post(body=_(
                "Bank of Georgia matched the beneficiary name at only %(match).0f%% "
                "(threshold %(threshold).0f%%). Check the recipient before this document "
                "is signed.", match=self.bog_match_percent, threshold=threshold))

    def action_bog_create_anyway(self):
        """Re-submit a document BOG declined with a Warn code (never the duplicate 363). The same UniqueId is
        reused with CheckUniqueId, so a document created after all gets code 702."""
        self.ensure_one()
        self._gec_bank_check_own(BOG_METHOD_CODE)
        if self.gec_bank_state != 'awaiting_confirmation':
            raise UserError(_("This transfer is not waiting for confirmation."))
        if self.bog_warn_code == BOG_DUPLICATE_CODE:
            raise UserError(_("Bank of Georgia flagged this as a duplicate. Check Business "
                              "Online and reset the transfer manually if it really is new."))
        self.message_post(body=_("%(user)s chose to submit this transfer again after Bank of "
                                 "Georgia warning %(code)s.",
                                 user=self.env.user.name, code=self.bog_warn_code))
        return self.with_context(bog_create_anyway=True)._bog_send_one()

    def action_bog_reset_to_pending(self):
        """Clear a failed or warned transfer to send again, by hand: only Business Online shows if a resend is safe.
        A document BOG created gets a new UniqueId and DocumentNo: BOG refuses the old UniqueId for 7 days (702)."""
        self.ensure_one()
        self.check_access('write')
        self._gec_bank_check_user(BOG_METHOD_CODE)
        self._gec_bank_check_own(BOG_METHOD_CODE)
        if self.gec_bank_state not in ('failed', 'awaiting_confirmation', 'sending', 'unknown'):
            raise UserError(_("Only a failed, warned or unknown transfer can be reset."))
        stale = fields.Datetime.now() - timedelta(minutes=BOG_SENDING_STALE_MINUTES)
        if self.gec_bank_state == 'sending' and self.write_date > stale:
            raise UserError(_(
                "This transfer may still be on its way to Bank of Georgia (sending started less "
                "than %s minutes ago). Reset it only after that.", BOG_SENDING_STALE_MINUTES))
        dead_at_bank = self.gec_bank_state == 'failed' and bool(self.gec_bank_reference)
        if dead_at_bank:
            # Not a result column, so written directly, before the state: the next claim mints the new UniqueId.
            self.env['gec.bank.service']._durable_write(self, {
                'gec_bank_request_id': False,
                'bog_document_no': ('ODOO%s-%s' % (self.id, uuid.uuid4().hex[:4]))[:16]})
        self._gec_bank_write_result({
            'gec_bank_state': 'pending',
            'bog_warn_code': 0,
            'gec_bank_reference': False,
            'bog_bulk_key': False,
            'gec_bank_error': False,
        })
        if dead_at_bank:
            self.message_post(body=_("%s reset this transfer to pending. Bank of Georgia had rejected or "
                                     "cancelled its document, so a new send uses a new request id "
                                     "(UniqueId).") % self.env.user.name)
        else:
            self.message_post(body=_("%s reset this transfer to pending. A new send will reuse the "
                                     "same request id (UniqueId).") % self.env.user.name)
        return True

    def action_bog_upload_attachments(self):
        """Upload every attached file to BOG and keep the returned hashes."""
        self.ensure_one()
        self.check_access('write')
        self._gec_bank_check_user(BOG_METHOD_CODE)
        self._gec_bank_check_own(BOG_METHOD_CODE)
        connection = self._gec_bank_connection()
        self._bog_ensure_attachments_uploaded(connection)
        return self._bog_notify(_("%s file(s) uploaded to Bank of Georgia.")
                                % len(self.bog_attachment_ids), 'success')

    def _bog_ensure_attachments_uploaded(self, connection):
        """Upload at every send: the bank must get the files the payment has now, and a file deleted from the chatter changes no field."""
        self.ensure_one()
        service = self.env['bog.service']
        hashes = []
        for attachment in self.bog_attachment_ids:
            content = attachment.sudo().raw
            if not content:
                raise UserError(_("Attachment %s has no content to upload.")
                                % attachment.display_name)
            hashes.append(service.upload_file(connection, attachment.name, content))
        joined = ' '.join(hashes) or False
        if joined != (self.bog_attachment_hashes or False):
            self._gec_bank_write_result({'bog_attachment_hashes': joined})

    def _bog_build_document(self):
        """Build the BOG document dict; CheckUniqueId makes a resend safe (code 702). No PayerInn: it is only for
        a treasury payment on behalf of a third person (code 59), never sent here (bog.md F6)."""
        self.ensure_one()
        partner_bank = self.partner_bank_id
        partner = self.partner_id

        # SourceAccountNumber goes as the journal stores it: BOG's docs and collection differ on the suffix.
        document = {
            'Nomination': (self.memo or (partner.display_name if partner else '')
                           or _("Bank of Georgia transfer"))[:250],
            'UniqueId': self.gec_bank_request_id,
            'CheckUniqueId': True,
            'Amount': self.amount,
            'Currency': self.currency_id.name,
            'DocumentNo': self.bog_document_no,
            'ValueDate': (self.bog_value_date or fields.Date.context_today(self)).strftime('%Y-%m-%d'),
            'SourceAccountNumber': self.journal_id.bank_account_number,
            'BeneficiaryAccountNumber': partner_bank.account_number if partner_bank else False,
            'BeneficiaryBankCode': (self.bog_beneficiary_bank_code
                                    or (partner_bank.bank_bic if partner_bank else False)),
            'BeneficiaryInn': self.bog_beneficiary_inn or (partner.vat if partner else False),
            'BeneficiaryName': self.bog_beneficiary_name or (partner.name if partner else False),
            'IsSalary': bool(self.bog_is_salary),
            'DispatchType': self.bog_dispatch_type or 'MT103',
        }
        # CheckInn works only inside Bank of Georgia (result code 28 elsewhere).
        if self.bog_check_inn:
            document['CheckInn'] = True
        if self.bog_transfer_type == 'foreign' and self.bog_additional_information:
            document['AdditionalInformation'] = self.bog_additional_information[:210]

        # Drop empty keys; AttachmentIds is added after, only when there is something to attach.
        document = {k: v for k, v in document.items() if v not in (None, False, '')}
        hashes = [h for h in (self.bog_attachment_hashes or '').split() if h]
        if hashes:
            document['AttachmentIds'] = hashes
        return document

    def action_bog_refresh_status(self):
        return self._gec_bank_refresh_status(BOG_METHOD_CODE)

    def _bog_status_vals(self, status, reject_code=None):
        """State values for a status letter. A confirmed transfer, or one reset after a failure, is never moved back."""
        letter = (status or '').strip().upper()
        state = BOG_DOCUMENT_STATUS_STATES.get(letter)
        moving = self._gec_bank_state_groups()['open'] | {'sending'}
        if state == 'failed' and self.gec_bank_state in moving:
            reason = BOG_REJECT_MESSAGES.get(int(reject_code)) if str(reject_code or '').isdigit() else None
            return {'gec_bank_state': 'failed', 'gec_bank_error': self.env._(reason or BOG_DOCUMENT_STATUS_LABELS[letter])[:255]}
        if state == 'confirmed' and self.gec_bank_state != 'confirmed':
            return {'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'status', 'gec_bank_error': False}
        if state in ('created', 'sent') and self.gec_bank_state in moving and state != self.gec_bank_state:
            return {'gec_bank_state': state, 'gec_bank_error': False}
        return {}

    def _bog_refresh_status(self):
        """Ask BOG for the document status; only a known letter moves the state."""
        self.ensure_one()
        if not self.gec_bank_reference:
            return
        connection = self._gec_bank_connection()
        result = self.env['bog.service'].get_document_status(connection, self.gec_bank_reference)
        if result.get('http_status', 0) == 0 or result.get('http_status', 0) >= 500:
            return
        data = result.get('data')
        if not isinstance(data, dict):
            return

        status = (data.get('Status') or '').strip()
        reject_code = data.get('RejectCode')
        result_code = data.get('ResultCode')
        match = data.get('Match')

        vals = {'bog_bank_status': status or False}
        if reject_code not in (None, ''):
            vals['bog_reject_code'] = str(reject_code)
        if result_code is not None:
            vals['bog_result_code'] = int(result_code or 0)
        if match is not None:
            vals['bog_match_percent'] = float(match or 0.0)
        vals.update(self._bog_status_vals(status, reject_code))
        if status and status.strip().upper() not in BOG_DOCUMENT_STATUS_LABELS and status != self.bog_bank_status:
            self.message_post(body=_("Bank of Georgia returned an unrecognised document status: "
                                     "%s. The payment state was left unchanged.") % status)
        self._gec_bank_write_result(vals)

    @api.model
    def _cron_bog_status_poll(self):
        """Poll BOG's open documents until a final status, least recently written first."""
        return self._gec_bank_poll_status(BOG_METHOD_CODE, 'bog_connection_id', 'write_date, id')

    def action_bog_recover(self):
        """Resolve an 'unknown' or stuck 'sending' payment without resending it. BOG has no lookup by our
        UniqueId, so today's activities are searched for our DocumentNo."""
        self.ensure_one()
        self.check_access('write')
        self._gec_bank_check_user(BOG_METHOD_CODE)
        self._gec_bank_check_own(BOG_METHOD_CODE)
        if self.gec_bank_state not in ('sending', 'unknown'):
            raise UserError(_("Only a transfer whose send did not finish, or whose outcome is "
                              "unknown, can be recovered from Bank of Georgia."))
        if not self.bog_document_no:
            raise UserError(_("No document number on this payment to recover from."))
        connection = self._gec_bank_connection()
        activities = self.env['bog.service'].get_today_activities(
            connection, self.journal_id.bank_account_number, self.currency_id.name)
        if not isinstance(activities, list):
            return self._bog_notify(_("Bank of Georgia returned no activity list. Try again shortly."),
                                    'warning')

        wanted = (self.bog_document_no or '').strip().upper()
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            doc_no = str(activity.get('DocNo') or activity.get('docNo') or '').strip().upper()
            if doc_no and doc_no == wanted:
                key = bog_key(activity.get('DocKey') or activity.get('docKey'))
                if not key:
                    return self._bog_notify(
                        _("The document was found at Bank of Georgia, but without its document key, so the payment is left as it is. "
                          "Try Recover from BOG again later."), 'warning')
                self._gec_bank_write_result({
                    'gec_bank_reference': key,
                    'gec_bank_state': 'created',
                    'gec_bank_error': False,
                })
                self._bog_refresh_status()
                return self._bog_notify(
                    _("The document was found at Bank of Georgia; its status was refreshed."),
                    'success')

        # Today's activities cover only the current day, so "not found" is not proof.
        return self._bog_notify(
            _("No document with number %s was found in today's activities. If it was sent on an "
              "earlier day, check Business Online before resending.") % self.bog_document_no,
            'warning')

    def action_bog_cancel_document(self):
        """DELETE the document at BOG while it is still unsigned."""
        self.ensure_one()
        self.check_access('write')
        self._gec_bank_check_user(BOG_METHOD_CODE)
        self._gec_bank_check_own(BOG_METHOD_CODE)
        if self.gec_bank_state != 'created':
            raise UserError(_("Only a document that is created but not yet signed can be cancelled."))
        if not self.gec_bank_reference:
            raise UserError(_("This payment has no Bank of Georgia document key."))
        connection = self._gec_bank_connection()
        result = self.env['bog.service'].delete_document(connection, self.gec_bank_reference)
        http_status = result.get('http_status', 0)
        if http_status and 200 <= http_status < 300:
            self._gec_bank_write_result({'gec_bank_state': 'failed',
                                         'gec_bank_error': _("Cancelled in Odoo.")})
            return self._bog_notify(_("The document was cancelled at Bank of Georgia."), 'success')
        return self._bog_notify(_("Bank of Georgia refused the cancellation: %s")
                                % (result.get('error_text') or http_status), 'warning')

    def _bog_cancel_locally(self):
        """Mark payments failed after their batch was cancelled at the bank (no further call)."""
        for payment in self:
            payment._gec_bank_write_result({'gec_bank_state': 'failed',
                                            'gec_bank_error': _("Cancelled with its batch.")})

    def action_bog_confirm_manual(self):
        """Manually confirm a signed (Sent) document the statement did not auto-match."""
        return self._gec_bank_confirm_manual(BOG_METHOD_CODE)