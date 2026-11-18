import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .account_payment_method import TBC_METHOD_CODE

_logger = logging.getLogger(__name__)

# Business transfer types <-> the TBC API `transferType` value.
TBC_TRANSFER_TYPES = [
    ('own', 'To Own Account'),
    ('internal', 'Within TBC (another TBC account)'),
    ('national', 'To Other Bank (GEL / national)'),
    ('treasury', 'Treasury'),
    ('foreign', 'To Other Bank (Foreign / SWIFT)'),
]
TBC_TRANSFER_TYPE_API = {
    'own': 'TransferToOwnAccount',
    'internal': 'TransferWithinBank',
    'national': 'TransferToOtherBankNationalCurrency',
    'treasury': 'TreasuryTransfer',
    'foreign': 'TransferToOtherBankForeignCurrency',
}

# TBC's docs say 'Finished' but their example returns 'Completed': accept both.
TBC_STATUS_OK = {'Finished', 'Completed'}
TBC_STATUS_FAILED = {'Failed', 'Cancelled', 'Deleted', 'Error'}
# 400 code for a resend of a registered transferExternalId: the transfer exists, so it is looked up, not failed.
TBC_DUPLICATE_CODE = 'DUPLICATED_SINGLE_TRANSFER_REQUEST'
TREASURY_CODE_LENGTH = 9
# National and treasury transfers are in lari.
TBC_NATIONAL_CURRENCY = 'GEL'
# TBC answers an unknown external id with 400 and this title, not 404 as the docs say.
TBC_EXTERNAL_ID_NOT_FOUND = 'external id is not found'
# Answers TBC gives before processing a transfer (failed login, rate limit): nothing was created.
TBC_NOT_PROCESSED_STATUSES = (401, 429)
# No send outlives a worker (limit_time_real): a payment 'sending' longer than this is stuck.
TBC_SENDING_STALE_MINUTES = 15
# Georgian IBAN: GEkk + 2-letter bank code + 16 digits; TBC is 'TB'.
GE_IBAN_LENGTH = 22
TBC_IBAN_BANK_CODE = 'TB'


def georgian_bank_code(account_number):
    """Bank code of a Georgian IBAN ('TB' for TBC), or None for anything else."""
    number = (account_number or '').replace(' ', '').upper()
    if number.startswith('GE') and len(number) == GE_IBAN_LENGTH:
        return number[4:6]
    return None


# Fields the order is built from; changing one after approval voids the approval.
TBC_ORDER_FIELDS = frozenset({
    'amount', 'currency_id', 'partner_id', 'partner_bank_id', 'memo', 'journal_id',
    'tbc_transfer_type', 'tbc_additional_description', 'tbc_beneficiary_tax_code',
    'tbc_treasury_code', 'tbc_taxpayer_code', 'tbc_taxpayer_name', 'tbc_beneficiary_name',
    'tbc_beneficiary_address', 'tbc_beneficiary_bank_code', 'tbc_beneficiary_bank_name',
    'tbc_intermediary_bank_code', 'tbc_intermediary_bank_name', 'tbc_charge_details',
})


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    is_tbc = fields.Boolean(related='journal_id.is_tbc')
    tbc_processing_mode = fields.Selection(related='journal_id.tbc_connection_id.processing_mode', string='TBC Processing Mode', readonly=True)
    # No default: a default lands in the create values and wins over the compute.
    tbc_transfer_type = fields.Selection(TBC_TRANSFER_TYPES, string='TBC Transfer Type', compute='_compute_tbc_transfer_type', store=True,
        readonly=False, precompute=True, help="Set from the recipient account; change it only for a treasury transfer or to correct an unusual case.")
    tbc_bank_status = fields.Char(string='TBC Status (raw)', readonly=True, copy=False, help="The transfer status exactly as TBC last returned it.")
    tbc_additional_description = fields.Char(string='Additional Description')
    tbc_beneficiary_tax_code = fields.Char(string='Beneficiary Tax Code')
    tbc_beneficiary_name = fields.Char(string='Beneficiary Name')
    tbc_beneficiary_address = fields.Char(string='Beneficiary Address')
    tbc_beneficiary_bank_code = fields.Char(string='Beneficiary Bank (BIC/Code)')
    tbc_beneficiary_bank_name = fields.Char(string='Beneficiary Bank Name')
    tbc_intermediary_bank_code = fields.Char(string='Intermediary Bank (BIC/Code)')
    tbc_intermediary_bank_name = fields.Char(string='Intermediary Bank Name')
    # TBC accepts only SHA and OUR for TransferToOtherBankForeignCurrency.
    tbc_charge_details = fields.Selection([('SHA', 'SHA'), ('OUR', 'OUR')], string='Charge Details')
    tbc_treasury_code = fields.Char(string='Treasury Code', compute='_compute_tbc_treasury_code', store=True, readonly=False, precompute=True)
    tbc_taxpayer_code = fields.Char(string='Taxpayer Code')
    tbc_taxpayer_name = fields.Char(string='Taxpayer Name')

    @api.depends('partner_id', 'partner_bank_id', 'currency_id')
    def _compute_tbc_transfer_type(self):
        """Pick the transfer type TBC expects for the recipient (a mismatch is rejected as a bad 'Account
        Number' format). Without a recipient account the type is kept; a stale 'treasury' becomes
        'national'."""
        for payment in self:
            if (payment.partner_id.commercial_partner_id.gec_treasury_code or '').strip():
                payment.tbc_transfer_type = 'treasury'
                continue
            number = payment.partner_bank_id.sanitized_account_number
            if not number:
                current = payment.tbc_transfer_type
                payment.tbc_transfer_type = 'national' if current in (False, 'treasury') else current
                continue
            bank_code = georgian_bank_code(number)
            if bank_code == TBC_IBAN_BANK_CODE:
                own = payment.partner_bank_id.partner_id == payment.company_id.partner_id
                payment.tbc_transfer_type = 'own' if own else 'internal'
            elif bank_code and payment.currency_id.name == TBC_NATIONAL_CURRENCY:
                payment.tbc_transfer_type = 'national'
            else:
                payment.tbc_transfer_type = 'foreign'

    @api.depends('partner_id')
    def _compute_tbc_treasury_code(self):
        """Set the Treasury Code to the contact's code on a contact change, so the old one never stays."""
        for payment in self:
            code = (payment.partner_id.commercial_partner_id.gec_treasury_code or '').strip()
            payment.tbc_treasury_code = code or False

    @api.depends('journal_id.is_tbc')
    def _compute_gec_bank_code(self):
        """Recompute the code when the journal turns TBC or not."""
        super()._compute_gec_bank_code()

    @api.model
    def _get_method_codes_using_bank_account(self):
        return super()._get_method_codes_using_bank_account() + [TBC_METHOD_CODE]

    @api.model
    def _gec_bank_label_for(self, code):
        if code == TBC_METHOD_CODE:
            return _("TBC Bank")
        return super()._gec_bank_label_for(code)

    @api.model
    def _gec_bank_user_group_for(self, code):
        if code == TBC_METHOD_CODE:
            return 'tbc_bank.group_tbc_user'
        return super()._gec_bank_user_group_for(code)

    def _gec_bank_treasury_transfer(self):
        """Only a Treasury transfer type skips the receiver account; any other type pays creditAccount."""
        if self.gec_bank_code != TBC_METHOD_CODE:
            return super()._gec_bank_treasury_transfer()
        return self.tbc_transfer_type == 'treasury'

    def _gec_bank_connection_record(self):
        if self.gec_bank_code != TBC_METHOD_CODE:
            return super()._gec_bank_connection_record()
        # sudo: a configuration read; see account.journal._compute_tbc_connection_id.
        return self.journal_id.tbc_connection_id[:1].sudo()

    def _gec_bank_send_one(self):
        if self.gec_bank_code != TBC_METHOD_CODE:
            return super()._gec_bank_send_one()
        return self._tbc_send_one()

    def _gec_bank_refresh_one(self):
        if self.gec_bank_code != TBC_METHOD_CODE:
            return super()._gec_bank_refresh_one()
        return self._tbc_refresh_status()

    def _gec_bank_new_request_vals(self):
        """A numeric request id below 10^9 (TBC accepts the number as a string), not used by another transfer of
        the company: a collision would fail the claim on the unique constraint."""
        if self.gec_bank_code != TBC_METHOD_CODE:
            return super()._gec_bank_new_request_vals()
        request_id = self.gec_bank_request_id
        while not request_id:
            request_id = str(uuid.uuid4().int % (10 ** 9))
            # sudo: the request id must be unique across all the company's TBC payments, including ones this user cannot read.
            if self.sudo().search_count([
                ('company_id', '=', self.company_id.id),
                ('payment_method_id', '=', self.payment_method_id.id),
                ('gec_bank_request_id', '=', request_id),
            ], limit=1):
                request_id = False
        return {'gec_bank_request_id': request_id}

    def _gec_bank_payload_fields(self):
        if self.gec_bank_code != TBC_METHOD_CODE:
            return super()._gec_bank_payload_fields()
        return TBC_ORDER_FIELDS

    def _gec_bank_check_instructions(self):
        if self.gec_bank_code != TBC_METHOD_CODE:
            return super()._gec_bank_check_instructions()
        return self._tbc_check_order()

    def _gec_bank_protected_fields(self):
        return super()._gec_bank_protected_fields() | {'tbc_bank_status'}

    @api.model
    def _gec_bank_result_columns(self):
        return super()._gec_bank_result_columns() | {'tbc_bank_status'}

    def _tbc_notify(self, message, level):
        return self._gec_bank_notify(_("TBC Bank"), message, level)

    def action_tbc_submit_approval(self):
        return self._gec_bank_submit_approval(TBC_METHOD_CODE)

    def action_tbc_approve(self):
        return self._gec_bank_approve(TBC_METHOD_CODE)

    def action_tbc_send(self):
        return self._gec_bank_send_transfers(TBC_METHOD_CODE)

    def _tbc_send_one(self):
        """Send this transfer to TBC; checks run first so a bad setup fails before the payment is claimed."""
        self.ensure_one()
        self._gec_bank_check_transfer(TBC_METHOD_CODE)
        connection = self._gec_bank_connection()
        self._tbc_check_order()
        # Logged in before the claim: a login failure after it would leave the payment stuck in 'sending'.
        self.env['tbc.service']._ensure_token(connection)
        previous_state = self.gec_bank_state
        self._gec_bank_reserve_send()
        order = self._tbc_build_order()
        result = self.env['tbc.service'].import_single_transfer(connection, order)
        return self._tbc_apply_send_result(result, previous_state)

    def _tbc_apply_send_result(self, result, previous_state=None):
        """Turn TBC's answer to the order into a payment state; 401/429 (refused before processing) gives the
        claim back to ``previous_state``."""
        self.ensure_one()
        http_status = result.get('http_status', 0)
        data = result.get('data') or {}

        if http_status in TBC_NOT_PROCESSED_STATUSES:
            self._gec_bank_release_claim(previous_state, result.get('error_text') or str(http_status))
            return self._tbc_notify(_("TBC refused the request before processing it (login or rate limit), "
                                      "so nothing was created. Send it again later."), 'warning')

        # No response or 5xx: the transfer might exist, so 'unknown'; never retry, the user recovers it.
        if http_status == 0 or http_status >= 500:
            self._gec_bank_write_result({
                'gec_bank_state': 'unknown',
                'gec_bank_error': (result.get('error_text') or _("TBC did not confirm the transfer. Use Recover from TBC before resending."))[:255],
            })
            return self._tbc_notify(_("TBC did not confirm this transfer. "
                                      "It may or may not have gone through — use 'Recover from TBC' before resending."), 'warning')

        if http_status >= 400 and data.get('code') == TBC_DUPLICATE_CODE:
            return self._tbc_resolve_duplicate()

        # 4xx: the transfer was not created.
        if http_status >= 400:
            self._gec_bank_write_result({
                'gec_bank_state': 'failed',
                'gec_bank_error': (result.get('error_text') or _("Transfer rejected."))[:255],
            })
            return True

        # 2xx (207 Multi-Status): the docs name the success array 'succeed' and 'succeeded'.
        succeeded = data.get('succeeded') or data.get('succeed') or []
        failed = data.get('failed') or []
        if failed:
            error_list = [err for item in failed for err in (item.get('errors') or [])]
            if any('duplicat' in str(err).lower() for err in error_list):
                return self._tbc_resolve_duplicate()
            errors = '; '.join(str(err) for err in error_list)
            self._gec_bank_write_result({
                'gec_bank_state': 'failed',
                'gec_bank_error': (errors or _("Transfer rejected by TBC."))[:255],
            })
            return True
        transfer_id = succeeded[0].get('transferId') if succeeded else None
        if transfer_id:
            self._gec_bank_write_result({
                'gec_bank_reference': str(transfer_id),
                'gec_bank_state': 'sent',
                'gec_bank_error': False,
            })
            # 'direct' mode confirms at the bank at once; the lookup is best-effort and must not fail the send.
            # Flushed first, so a database error of pending writes is not swallowed with the lookup's.
            if self._gec_bank_processing_mode() == 'direct':
                self.env.flush_all()
                try:
                    with self.env.cr.savepoint():
                        self._tbc_refresh_status()
                except Exception:
                    _logger.exception("TBC: post-send status refresh failed for payment %s", self.id)
        else:
            self._gec_bank_write_result({'gec_bank_state': 'unknown', 'gec_bank_error': _("No transfer id returned by TBC.")})
        return True

    def _tbc_resolve_duplicate(self):
        """TBC answered DUPLICATED_SINGLE_TRANSFER_REQUEST: the transfer exists, so park it 'unknown' and look it up."""
        self.ensure_one()
        self._gec_bank_write_result({
            'gec_bank_state': 'unknown',
            'gec_bank_error': _("TBC already has this transfer (duplicate request). Use Recover from TBC; do not create a new payment."),
        })
        # Not action_tbc_recover(): its 404 branch would call the transfer safe to resend.
        self.env.flush_all()
        try:
            with self.env.cr.savepoint():
                result = self.env['tbc.service'].get_single_transfer_by_external_id(self._gec_bank_connection(), self.gec_bank_request_id)
                transfer_id = (result.get('data') or {}).get('transferId')
                if transfer_id:
                    self._gec_bank_write_result({
                        'gec_bank_reference': str(transfer_id),
                        'gec_bank_state': 'sent',
                        'gec_bank_error': False,
                    })
                    self._tbc_refresh_status()
                    return self._tbc_notify(_("TBC already had this transfer (id %s); it was not sent "
                                              "twice. Status refreshed.", transfer_id), 'warning')
        # Best-effort: TBC already holds the transfer and the payment is durably Unknown; a failed lookup must leave that guidance, not raise.
        except Exception:
            _logger.exception("TBC: lookup after duplicate request failed for payment %s", self.id)
        return self._tbc_notify(_("TBC already registered this transfer. Use 'Recover from TBC' to load "
                                  "its status - do not pay it again."), 'warning')

    def _tbc_check_order(self):
        """Reject a wrong channel setup and what TBC is documented to reject, before anything is reserved."""
        self.ensure_one()
        problems = self.payment_method_line_id._gec_bank_config_errors()
        if self.amount <= 0:
            problems.append(_("The amount must be greater than 0."))
        if not self.journal_id._tbc_account_number():
            problems.append(_("Journal %s has no bank account number (IBAN).", self.journal_id.display_name))
        transfer_type = self.tbc_transfer_type
        if not transfer_type:
            problems.append(_("Choose a TBC Transfer Type."))
        if transfer_type == 'treasury':
            if self.currency_id.name != TBC_NATIONAL_CURRENCY:
                problems.append(_("A treasury transfer must be in GEL."))
            code = (self.tbc_treasury_code or '').strip()
            if not (code.isdigit() and len(code) == TREASURY_CODE_LENGTH):
                problems.append(_("A treasury transfer needs a %s-digit Treasury Code.", TREASURY_CODE_LENGTH))
        elif not (self.partner_bank_id and self.partner_bank_id.sanitized_account_number):
            problems.append(_("The recipient bank account is missing."))
        bank_code = georgian_bank_code(self.partner_bank_id.sanitized_account_number)
        if transfer_type in ('internal', 'own') and self.partner_bank_id and bank_code != TBC_IBAN_BANK_CODE:
            problems.append(_("The recipient account is not a TBC account; use 'To Other Bank'."))
        if transfer_type in ('national', 'foreign') and bank_code == TBC_IBAN_BANK_CODE:
            problems.append(_("The recipient account is a TBC account; use 'Within TBC' (or 'To Own Account')."))
        if transfer_type == 'national' and self.partner_bank_id and not bank_code:
            problems.append(_("'To Other Bank (GEL / national)' needs a Georgian IBAN; use 'To Other Bank (Foreign / SWIFT)'."))
        if transfer_type == 'foreign':
            if not (self.tbc_beneficiary_name or self.partner_id.name):
                problems.append(_("Beneficiary Name is required for a foreign transfer."))
            if not self.tbc_beneficiary_address:
                problems.append(_("Beneficiary Address is required for a foreign transfer."))
            if not self.tbc_beneficiary_bank_code:
                problems.append(_("Beneficiary Bank (BIC/Code) is required for a foreign transfer."))
            if self.tbc_charge_details not in ('SHA', 'OUR'):
                problems.append(_("Charge Details must be SHA or OUR for a foreign transfer."))
        if problems:
            raise UserError(_("TBC transfer %(name)s cannot be sent:\n%(problems)s", name=self.display_name,
                              problems='\n'.join('- %s' % p for p in problems)))

    def action_tbc_reset_to_pending(self):
        """Put a failed transfer back to Pending; one TBC created gets a new request id, as TBC refuses the old one.
        Unknown or unfinished sends go through Recover from TBC."""
        self.ensure_one()
        self.check_access('write')
        self._gec_bank_check_user(TBC_METHOD_CODE)
        self._gec_bank_check_own(TBC_METHOD_CODE)
        if self.gec_bank_state != 'failed':
            raise UserError(_("Only a failed transfer can be reset to pending."))
        dead_at_bank = bool(self.gec_bank_reference)
        if dead_at_bank:
            # Not a result column, so written directly, before the state: the next claim mints the new id.
            self.env['gec.bank.service']._durable_write(self, {'gec_bank_request_id': False})
        self._gec_bank_write_result({
            'gec_bank_state': 'pending',
            'gec_bank_reference': False,
            'gec_bank_error': False,
        })
        if dead_at_bank:
            self.message_post(body=_("%s reset this transfer to pending. TBC had failed the earlier "
                                     "transfer, so a new send uses a new request id.", self.env.user.name))
        else:
            self.message_post(body=_("%s reset this transfer to pending. A new send will reuse the same request id.", self.env.user.name))
        return True

    def action_tbc_confirm_manual(self):
        """Mark a Sent transfer as confirmed when the statement did not match it; an Unknown one is recovered."""
        return self._gec_bank_confirm_manual(TBC_METHOD_CODE)

    def action_tbc_recover(self):
        """Ask TBC for the transferId of our external id, then refresh the status. Only TBC's "not found" on a send
        older than 15 minutes allows a resend; the test environment accepts a resent id."""
        self.ensure_one()
        self.check_access('write')
        self._gec_bank_check_user(TBC_METHOD_CODE)
        self._gec_bank_check_own(TBC_METHOD_CODE)
        if self.gec_bank_state not in self._gec_bank_state_groups()['uncertain']:
            raise UserError(_("Only a transfer whose send did not finish, or whose outcome is unknown, can be recovered from TBC."))
        if not self.gec_bank_request_id:
            raise UserError(_("No TBC request id on this payment to recover from."))
        stale = fields.Datetime.now() - timedelta(minutes=TBC_SENDING_STALE_MINUTES)
        if self.gec_bank_state == 'sending' and self.write_date > stale:
            raise UserError(_("This transfer may still be on its way to TBC (sending started less than %s "
                              "minutes ago). Try 'Recover from TBC' again later.", TBC_SENDING_STALE_MINUTES))
        connection = self._gec_bank_connection()
        result = self.env['tbc.service'].get_single_transfer_by_external_id(connection, self.gec_bank_request_id)
        http_status = result.get('http_status', 0)
        data = result.get('data') or {}
        not_found = http_status == 404 or (http_status == 400 and TBC_EXTERNAL_ID_NOT_FOUND in str(data.get('title') or '').lower())
        if not_found:
            if self.write_date > stale:
                return self._tbc_notify(_(
                    "TBC has no record of this transfer yet, but it may still be processing the send that "
                    "timed out. Try 'Recover from TBC' again after %s minutes.", TBC_SENDING_STALE_MINUTES), 'warning')
            self._gec_bank_write_result({'gec_bank_state': 'pending', 'gec_bank_error': _("TBC has no record of it — safe to resend.")})
            return self._tbc_notify(_("TBC has no record of this transfer. You can resend it."), 'warning')
        transfer_id = data.get('transferId')
        if transfer_id:
            self._gec_bank_write_result({
                'gec_bank_reference': str(transfer_id),
                'gec_bank_state': 'sent',
                'gec_bank_error': False,
            })
            self._tbc_refresh_status()
            return self._tbc_notify(_("Transfer found at TBC (id %s); status refreshed.", transfer_id), 'success')
        return self._tbc_notify(_("Could not resolve the transfer yet. Try again shortly."), 'warning')

    def _tbc_build_order(self):
        """Build one TBC singleTransferOrders entry from this payment."""
        self.ensure_one()
        credit_account = self.partner_bank_id.sanitized_account_number
        # Amount and beneficiary use the payment currency, the debit side the company account's.
        ccy = self.currency_id.name
        debit_ccy = (self.journal_id.currency_id or self.journal_id.company_id.currency_id).name

        order = {
            'transferType': TBC_TRANSFER_TYPE_API[self.tbc_transfer_type],
            'transferExternalId': self.gec_bank_request_id or None,
            'debitAccount': {'accountNumber': self.journal_id._tbc_account_number(), 'accountCurrencyCode': debit_ccy},
            'creditAccount': {'accountNumber': credit_account, 'accountCurrencyCode': ccy},
            'amount': {'amount': self.amount, 'currency': ccy},
            'description': (self.memo or self.partner_id.display_name or _("TBC transfer"))[:140],
            'beneficiaryName': self.tbc_beneficiary_name or self.partner_id.name,
        }
        if self.tbc_additional_description:
            order['additionalDescription'] = self.tbc_additional_description[:210]
        if self.tbc_transfer_type == 'national':
            order['beneficiaryTaxCode'] = self.tbc_beneficiary_tax_code
        if self.tbc_transfer_type == 'treasury':
            # The treasury code identifies the recipient; creditAccount is not used for TreasuryTransfer.
            order.pop('creditAccount')
            order.pop('beneficiaryName')
            order.update({
                'treasuryCode': (self.tbc_treasury_code or '').strip(),
                'taxpayerCode': self.tbc_taxpayer_code,
                'taxpayerName': self.tbc_taxpayer_name,
            })
        elif not credit_account:
            # Never send {"accountNumber": false}.
            order.pop('creditAccount')
        if self.tbc_transfer_type == 'foreign':
            order.update({
                'beneficiaryAddress': self.tbc_beneficiary_address,
                'beneficiaryBankCode': self.tbc_beneficiary_bank_code,
                'beneficiaryBankName': self.tbc_beneficiary_bank_name,
                'intermediaryBankCode': self.tbc_intermediary_bank_code,
                'intermediaryBankName': self.tbc_intermediary_bank_name,
                'chargeDetails': self.tbc_charge_details,
            })
        # Drop empty keys: TBC may reject null fields.
        return {k: v for k, v in order.items() if v not in (None, False, '')}

    def action_tbc_refresh_status(self):
        return self._gec_bank_refresh_status(TBC_METHOD_CODE)

    def _tbc_refresh_status(self):
        """Ask TBC for the status: a final success confirms, a final failure fails. A confirmed transfer is
        never failed here; the answer is posted for a person to check."""
        self.ensure_one()
        if not self.gec_bank_reference:
            return
        connection = self._gec_bank_connection()
        data = self.env['tbc.service'].get_single_transfer_status(connection, self.gec_bank_reference)
        info = (data or {}).get('singleTransferData') or {}
        status = (data or {}).get('status') or info.get('transferStatus')
        if not status:
            return
        vals = {'tbc_bank_status': str(status)[:255]}
        if status in TBC_STATUS_OK:
            if self.gec_bank_state != 'confirmed':
                vals.update({'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'status'})
        elif status in TBC_STATUS_FAILED:
            if self.gec_bank_state == 'confirmed':
                self.message_post(body=_(
                    "TBC now reports this transfer as %s, but it is already confirmed, so its "
                    "state was left unchanged. Check it with TBC.", status))
            else:
                vals.update({
                    'gec_bank_state': 'failed',
                    'gec_bank_error': (info.get('errorDetailEN') or info.get('failureReasonEn') or status)[:255],
                })
        self._gec_bank_write_result(vals)

    @api.model
    def _cron_tbc_status_poll(self):
        """Poll TBC's open transfers until TBC reports a final status, least recently written first."""
        return self._gec_bank_poll_status(TBC_METHOD_CODE, 'tbc_connection_id', 'write_date, id')
