import logging
import re

from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.base.models.res_partner_bank import sanitize_account_number

from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

from ..services.basisbank_service import RETRYABLE_SEND_CODES, TECHNICAL_ERROR_CODE, UNKNOWN_SEND_CODES, report_window
from .account_payment_method import BASIS_BANK_BIC, BASISBANK_METHOD_CODE

_logger = logging.getLogger(__name__)

BASISBANK_BIC_PATTERN = re.compile('[A-Z]{6}[A-Z0-9]{2}')
BASISBANK_SINGLE_SENDABLE_STATES = ('pending', 'awaiting_otp')
BASISBANK_CONFIRM_TIMEOUT_HOURS = 48
BASISBANK_AWAITING_REPORT_STATES = ('sending', 'sent', 'unknown')
# At the bank, or may be: the journal entry cannot be undone.
BASISBANK_AT_BANK_STATES = ('sending', 'sent', 'unknown', 'not_in_report', 'confirmed')
# States that block the claim of a send.
BASISBANK_CLAIM_BLOCKED_STATES = ('awaiting_approval', 'failed') + BASISBANK_AT_BANK_STATES
# Editing any of these after approval voids the approval (maker-checker).
BASISBANK_APPROVAL_CONTENT_FIELDS = ('amount', 'currency_id', 'partner_id', 'partner_bank_id', 'memo', 'payment_reference', 'journal_id',
    'basisbank_transfer_type', 'basisbank_treasury_code', 'basisbank_purpose_code', 'basisbank_receiver_country', 'basisbank_receiver_city',
    'basisbank_receiver_address', 'basisbank_intermediate_bank_code', 'basisbank_intermediate_bank_name', 'basisbank_detail_of_charges')
# Written only by the Basis flows (gec_bank write token).
BASISBANK_PROTECTED_FIELDS = frozenset({'basisbank_state', 'basisbank_approved_by', 'basisbank_approved_date', 'basisbank_bank_internal_id',
    'basisbank_error_code', 'basisbank_error_message', 'basisbank_sent_date', 'basisbank_bank_response'})


class AccountPayment(models.Model):
    _name = 'account.payment'
    _inherit = ['account.payment', 'basisbank.sendable']

    basisbank_transfer_type = fields.Selection(selection=[
        ('internal', 'Internal (within Basis Bank)'),
        ('national', 'National (GEL to other GE bank)'),
        ('foreign', 'Foreign (SWIFT)'),
        ('treasury', 'Treasury'),
    ], string='Basis Bank Transfer Type', compute='_compute_basisbank_transfer_type', store=True, readonly=False,
        help="Set from the recipient: a Treasury Code gives Treasury, otherwise the bank of the recipient's account (Basis Bank: Internal; "
        "another Georgian bank in GEL: National; anything else: Foreign). You can change it.")
    basisbank_state = fields.Selection(selection=[
        ('pending', 'Pending'),
        ('awaiting_approval', 'Awaiting Approval'),
        ('awaiting_otp', 'Awaiting OTP'),
        ('sending', 'Sending'),
        ('sent', 'Sent to Bank'),
        ('unknown', 'Unknown'),
        ('not_in_report', 'Not in Bank Report'),
        ('confirmed', 'Confirmed by Statement'),
        ('failed', 'Failed'),
    ], string='Basis Bank State', compute='_compute_basisbank_state', store=True, readonly=True, copy=False, index=True, tracking=True)
    basisbank_bank_internal_id = fields.Char(string='Bank Internal ID', readonly=True, copy=False, index=True)
    basisbank_error_code = fields.Integer(string='Last Bank Error Code', readonly=True, copy=False)
    basisbank_error_message = fields.Char(string='Last Bank Error', readonly=True, copy=False)
    basisbank_treasury_code = fields.Char(string='Treasury Code', compute='_compute_basisbank_treasury_code', store=True, readonly=False,
        precompute=True)
    basisbank_purpose_code = fields.Char(string='Purpose Code')
    basisbank_receiver_country = fields.Char(string='Receiver Country', compute='_compute_basisbank_receiver', store=True, readonly=False,
        help="Two-letter country code, such as DE; filled from the contact.")
    basisbank_receiver_city = fields.Char(string='Receiver City', compute='_compute_basisbank_receiver', store=True, readonly=False)
    basisbank_receiver_address = fields.Char(string='Receiver Address', compute='_compute_basisbank_receiver', store=True, readonly=False)
    basisbank_intermediate_bank_code = fields.Char(string='Intermediate Bank BIC')
    basisbank_intermediate_bank_name = fields.Char(string='Intermediate Bank Name')
    basisbank_detail_of_charges = fields.Selection(selection=[
        ('SHA', 'Each side pays its bank (SHA)'),
        ('OUR', 'We pay all fees (OUR)'),
        ('BEN', 'Receiver pays all fees (BEN)'),
    ], string='Charges', default='SHA')
    is_basisbank = fields.Boolean(related='journal_id.is_basisbank', store=True)
    basisbank_approval_id = fields.Many2one(related='journal_id.basisbank_connection_id.approval_id', store=False)
    basisbank_can_approve = fields.Boolean(compute='_compute_basisbank_can_approve')

    _basisbank_internal_id_uniq = models.Constraint('unique (company_id, basisbank_bank_internal_id)',
        'Each Basis Bank reference can attach to only one payment per company.')

    @api.depends('is_basisbank', 'payment_type')
    def _compute_basisbank_state(self):
        """Outgoing Basis payments start at Pending; others have no Basis state.
        A state set by the send flow is kept even if the journal stops being a Basis journal."""
        for payment in self:
            if payment.is_basisbank and payment.payment_type == 'outbound':
                payment.basisbank_state = payment.basisbank_state or 'pending'
            elif payment.basisbank_state == 'pending':
                payment.basisbank_state = False
            else:
                payment.basisbank_state = payment.basisbank_state

    @api.depends('partner_id', 'partner_bank_id', 'currency_id', 'journal_id', 'payment_type', 'basisbank_treasury_code')
    def _compute_basisbank_transfer_type(self):
        """An outgoing Basis payment: a Treasury Code gives Treasury, else the recipient's bank gives Internal (Basis Bank), National (another
        Georgian bank, GEL) or Foreign; without a valid bank code (BIC) the type is left empty for the user to pick."""
        for payment in self:
            bic = bic_prefix(payment.partner_bank_id.bank_bic)
            if not (payment.journal_id.is_basisbank and payment.payment_type == 'outbound'):
                payment.basisbank_transfer_type = payment.basisbank_transfer_type
            elif payment.basisbank_treasury_code:
                payment.basisbank_transfer_type = 'treasury'
            elif not BASISBANK_BIC_PATTERN.fullmatch(bic):
                payment.basisbank_transfer_type = False
            elif bic == BASIS_BANK_BIC:
                payment.basisbank_transfer_type = 'internal'
            elif bic[4:6] == 'GE' and payment.currency_id.name == 'GEL':
                payment.basisbank_transfer_type = 'national'
            else:
                payment.basisbank_transfer_type = 'foreign'

    @api.depends('partner_id', 'journal_id', 'payment_type')
    def _compute_basisbank_receiver(self):
        """An outgoing Basis payment takes the recipient's country code, city and street from its contact; others keep their values."""
        for payment in self:
            partner = payment.partner_id.commercial_partner_id
            if payment.journal_id.is_basisbank and payment.payment_type == 'outbound':
                country, city, address = partner.country_id.code, partner.city, ', '.join(filter(None, (partner.street, partner.street2)))
            else:
                country, city, address = payment.basisbank_receiver_country, payment.basisbank_receiver_city, payment.basisbank_receiver_address
            payment.basisbank_receiver_country = country or False
            payment.basisbank_receiver_city = city or False
            payment.basisbank_receiver_address = address or False

    @api.depends('partner_id')
    def _compute_basisbank_treasury_code(self):
        """Take the contact's Treasury Code (or none) on a contact change; a value given in create wins."""
        for payment in self:
            payment.basisbank_treasury_code = (payment.partner_id.commercial_partner_id.gec_treasury_code or '').strip() or False

    @api.model
    def _get_method_codes_using_bank_account(self):
        """Show the recipient bank account for Basis transfers (not for treasury, which has none)."""
        res = super()._get_method_codes_using_bank_account()
        res.append(BASISBANK_METHOD_CODE)
        return res

    @api.model
    def _gec_bank_label_for(self, code):
        if code == BASISBANK_METHOD_CODE:
            return _("Basis Bank")
        return super()._gec_bank_label_for(code)

    @api.model
    def _gec_bank_user_group_for(self, code):
        if code == BASISBANK_METHOD_CODE:
            return 'basis_bank.group_basisbank_user'
        return super()._gec_bank_user_group_for(code)

    @api.constrains('partner_id', 'journal_id')
    def _check_basisbank_partner(self):
        for payment in self:
            if payment.journal_id and payment.journal_id.is_basisbank and not payment.partner_id:
                raise ValidationError(_("Basis Bank payments require a partner (vendor, employee, customer or treasury)."))

    @api.constrains('basisbank_transfer_type', 'basisbank_treasury_code')
    def _check_basisbank_required_by_type(self):
        for payment in self:
            if payment.is_basisbank and payment.basisbank_transfer_type == 'treasury' and not payment.basisbank_treasury_code:
                raise ValidationError(_("Treasury payments require a Treasury Code."))

    def _gec_bank_protected_fields(self):
        return super()._gec_bank_protected_fields() | BASISBANK_PROTECTED_FIELDS

    def _gec_bank_at_bank(self):
        """A Basis transfer on its way, at the bank, unconfirmed after the 48-hour check, or of unknown outcome."""
        return super()._gec_bank_at_bank() or (
            self.is_basisbank and self.payment_type == 'outbound'
            and self.basisbank_state in BASISBANK_AT_BANK_STATES)

    @api.model_create_multi
    def create(self, vals_list):
        """A payment created into an approved batch voids the batch's approval."""
        payments = super().create(vals_list)
        payments.batch_payment_id._basisbank_revoke_approval('draft')
        return payments

    def write(self, vals):
        """Changed content voids the approval of the payment and its batch; so does moving between batches."""
        old_batches = self.batch_payment_id if 'batch_payment_id' in vals else self.batch_payment_id.browse()
        res = super().write(vals)
        if any(field in vals for field in BASISBANK_APPROVAL_CONTENT_FIELDS):
            self._basisbank_revoke_approval('pending')
            self.batch_payment_id._basisbank_revoke_approval('draft')
        if 'batch_payment_id' in vals:
            (old_batches | self.batch_payment_id)._basisbank_revoke_approval('draft')
        return res

    def _basisbank_confirm_from_statement(self, bank_id=False):
        """Mark a Basis payment confirmed by the bank report or statement; only Basis state and sent flag change."""
        self.ensure_one()
        vals = dict({'basisbank_state': 'confirmed'}, **self._basisbank_payment_state_vals('confirmed'))
        if bank_id and not self.basisbank_bank_internal_id:
            vals['basisbank_bank_internal_id'] = bank_id
        self._gec_bank_internal_write(vals)
        return True

    def _basisbank_receiver_name(self):
        """Name of the receiving account's holder: the commercial partner holds the account, not a contact person."""
        self.ensure_one()
        return self.partner_bank_id.holder_name or self.commercial_partner_id.name or ''

    def basisbank_build_package_item(self):
        self.ensure_one()
        if self.basisbank_transfer_type == 'treasury':
            item = {'Amount': float(self.amount), 'TreasuryCode': self.basisbank_treasury_code or ''}
        else:
            item = {
                'Amount': float(self.amount),
                'ReceiverAcc': self.partner_bank_id.sanitized_account_number or '',
                'ReceiverAccName': self._basisbank_receiver_name(),
                'Descrip': self.memo or self.payment_reference or '',
            }
        item['DocNum'] = self.id
        if self.partner_id.vat:
            item['TaxPayerTaxCode'] = self.partner_id.vat
            item['TaxPayerName'] = self.partner_id.name or ''
        return item

    def basisbank_build_single_item(self):
        self.ensure_one()
        sender = self.journal_id.bank_account_id.sanitized_account_number or ''
        receiver_acc = self.partner_bank_id.sanitized_account_number or ''
        descrip = self.memo or self.payment_reference or ''
        common = {'SenderAcc': sender, 'Amount': float(self.amount), 'ClientInternalID': self.id, 'DocNum': self.id}
        transfer_type = self.basisbank_transfer_type
        if transfer_type == 'internal':
            return 'InternalTransfers', {**common, 'ReceiverAcc': receiver_acc, 'Ccy': self.currency_id.name, 'Descrip': descrip}
        if transfer_type == 'national':
            return 'NationalCurrencyTransfers', {
                **common,
                'ReceiverAcc': receiver_acc,
                'ReceiverAccName': self._basisbank_receiver_name(),
                'ReceiverBankCode': self.partner_bank_id.bank_bic or '',
                'Descrip': descrip,
                'TaxPayerTaxCode': self.partner_id.vat or '',
                'TaxPayerName': self.partner_id.name or '',
            }
        if transfer_type == 'foreign':
            return 'ForeignCurrencyTransfers', {
                **common,
                'Ccy': self.currency_id.name,
                'ReceiverAcc': receiver_acc,
                'ReceiverAccName': self._basisbank_receiver_name(),
                'ReceiverCountry': self.basisbank_receiver_country or '',
                'ReceiverCity': self.basisbank_receiver_city or '',
                'ReceiverAddress': self.basisbank_receiver_address or '',
                'ReceiverBankCode': self.partner_bank_id.bank_bic or '',
                'ReceiverBankName': self.partner_bank_id.bank_name or '',
                'PurposeCode': self.basisbank_purpose_code or '',
                'Descrip': descrip,
                'IntermediateBankCode': self.basisbank_intermediate_bank_code or '',
                'IntermediateBankName': self.basisbank_intermediate_bank_name or '',
                'DetailOfCharg': self.basisbank_detail_of_charges or 'SHA',
            }
        if transfer_type == 'treasury':
            return 'TreasuryTransfers', {
                **common,
                'TreasuryCode': self.basisbank_treasury_code or '',
                'TaxPayerTaxCode': self.partner_id.vat or '',
                'TaxPayerName': self.partner_id.name or '',
            }
        raise ValidationError(_("Basis Bank transfer type is not set on payment %s.") % self.display_name)

    def _basisbank_check_single_sendable(self):
        """Validate this single payment can be sent: outbound, on a Basis journal, with a recipient."""
        self.ensure_one()
        if self.payment_type != 'outbound':
            raise UserError(_("Only outbound payments can be sent to Basis Bank."))
        if not self.journal_id.is_basisbank:
            raise UserError(_("This payment is not on a Basis Bank journal."))
        if self.batch_payment_id and self.batch_payment_id.is_basisbank:
            raise UserError(_("This payment belongs to a Basis Bank batch. Send it from the batch, not individually."))
        if self.is_sent:
            raise UserError(_("This payment was already sent."))
        self._gec_bank_check_sendable()
        if not self.basisbank_transfer_type:
            raise UserError(_("Set a Basis Bank transfer type before sending."))
        self._basisbank_check_before_send()

    def _basisbank_check_before_send(self):
        """Refuse payments the bank would reject or the confirmation flow cannot follow, for single and batch sends.
        Lists every problem at once; a payment without a type is listed under the missing type only."""
        missing_type = self.filtered(lambda p: not p.basisbank_transfer_type)
        missing_account = untrusted = missing_bic = missing_memo = self.browse()
        foreign_errors = []
        wrong_currency = self.filtered(lambda p: p.basisbank_transfer_type in ('national', 'treasury') and p.currency_id.name != 'GEL')
        for payment in self:
            if payment in missing_type or payment.basisbank_transfer_type == 'treasury':
                continue
            if payment.basisbank_transfer_type == 'foreign':
                missing = [label for label, value in (
                    (_("Receiver Country"), payment.basisbank_receiver_country),
                    (_("Receiver City"), payment.basisbank_receiver_city),
                    (_("Receiver Address"), payment.basisbank_receiver_address),
                    (_("Charges (SHA/OUR/BEN)"), payment.basisbank_detail_of_charges),
                ) if not value]
                if missing:
                    foreign_errors.append(self.env._("%s: a foreign transfer needs %s; fill them in the payment's Basis Bank section.",
                        payment.display_name, ', '.join(missing)))
            if not (payment.partner_bank_id.account_number or '').strip():
                missing_account |= payment
                continue
            if not payment.partner_bank_id.allow_out_payment:
                untrusted |= payment
            if payment.basisbank_transfer_type in ('national', 'foreign') and not payment.partner_bank_id.bank_bic:
                missing_bic |= payment
            if not (payment.memo or payment.payment_reference or '').strip():
                missing_memo |= payment
        errors = []
        if missing_type:
            errors.append(_("Set a Basis Bank transfer type before sending. Payments without one: %s")
                          % ', '.join(missing_type.mapped('display_name')))
        if missing_account:
            errors.append(_("These payments have no receiver bank account: %s") % ', '.join(missing_account.mapped('display_name')))
        if untrusted:
            errors.append(_("These receiver accounts are not trusted for outbound "
                "payments (allow outgoing payments on the bank account first): %s") % ', '.join(untrusted.mapped('display_name')))
        if missing_bic:
            errors.append(_("These national/foreign payments have no receiver bank BIC: %s") % ', '.join(missing_bic.mapped('display_name')))
        if missing_memo:
            errors.append(_("These payments need a description/purpose before sending: %s") % ', '.join(missing_memo.mapped('display_name')))
        errors.extend(foreign_errors)
        if wrong_currency:
            errors.append(_("National and Treasury transfers must be in GEL: %s") % ', '.join(wrong_currency.mapped('display_name')))
        for method_line in self.payment_method_line_id:
            errors.extend(method_line._gec_bank_config_errors())
        if errors:
            raise UserError('\n\n'.join(errors))

    def action_basisbank_submit_for_approval(self):
        """Submit pending single payments for in-Odoo approval and notify the approvers."""
        for payment in self:
            connection = payment._basisbank_connection()
            if connection.processing_mode != 'odoo_approve':
                raise UserError(_("This connection does not require Odoo approval."))
            if payment.basisbank_state != 'pending':
                raise UserError(_("Only pending payments can be submitted for approval."))
            payment._basisbank_check_single_sendable()
            payment._basisbank_request_approval(connection, _("Payment submitted for Basis Bank approval."))
        return True

    def action_basisbank_send(self):
        """Open the OTP dialog; a draft payment is confirmed first, or the send's claim would block."""
        self.ensure_one()
        self._gec_bank_check_user(BASISBANK_METHOD_CODE)
        connection = self._basisbank_connection()
        self._basisbank_check_approved(connection)
        if connection.processing_mode != 'odoo_approve' and self.basisbank_state not in BASISBANK_SINGLE_SENDABLE_STATES:
            if self.basisbank_state == 'unknown':
                raise UserError(_("This payment is in an unknown state. Run Resync before sending again."))
            raise UserError(_("This payment cannot be sent in its current state."))
        if self.state == 'draft':
            self.action_post()
        self._basisbank_check_single_sendable()
        return self._basisbank_otp_dialog('payment_id')

    def basisbank_send_with_otp(self, otp):
        """Send this confirmed payment with the OTP and record the bank's answer.
        Claim and result are written durably, so a re-run never sends it twice."""
        self.ensure_one()
        self._gec_bank_check_user(BASISBANK_METHOD_CODE)
        self.check_access('write')
        if self.basisbank_state not in BASISBANK_SINGLE_SENDABLE_STATES:
            raise UserError(_("This payment cannot be sent from its current state."))

        connection = self._basisbank_connection()
        self._basisbank_check_approved(connection)
        self._basisbank_check_single_sendable()
        service = self.env['basisbank.service']
        key, item = self.basisbank_build_single_item()
        self._basisbank_ensure_session(connection)

        previous_state = self.basisbank_state
        self._basisbank_reserve_send()
        try:
            response = service.upload_single_batch(connection, otp, {key: [item]})
            return self._basisbank_apply_single_response(response, key, previous_state)
        except Exception:
            _logger.exception("Basis Bank single send failed for payment %s", self.id)
            if self.basisbank_state == 'sending':
                self._basisbank_write_result({'basisbank_state': 'unknown'})
            return self._basisbank_notify(_("Basis Bank request failed unexpectedly. Run Resync to find out whether the bank received it."),
                'warning')

    def _basisbank_apply_single_response(self, response, key, previous_state):
        """Record the bank's answer to this transfer; it never stays 'sending'.
        Wrong OTP or expired session: back to ``previous_state``; technical error: unknown until Resync."""
        self.ensure_one()
        service = self.env['basisbank.service']
        error_code = response.get('ErrorCode', TECHNICAL_ERROR_CODE)
        message = (response.get('ErrorMessage') or response.get('ErrorMsg') or service.error_message(error_code))
        if error_code in RETRYABLE_SEND_CODES:
            self._basisbank_write_result({'basisbank_state': previous_state, 'basisbank_sent_date': False, 'basisbank_bank_response': message})
            return self._basisbank_notify(message, 'warning')
        if error_code in UNKNOWN_SEND_CODES:
            self._basisbank_write_result({'basisbank_state': 'unknown', 'basisbank_bank_response': message})
            return self._basisbank_notify(_("Basis Bank reported a technical issue. Run Resync to confirm whether the transfer went through."),
                'warning')
        if error_code != 0:
            self._basisbank_reject(error_code, message)
            return self._basisbank_notify(message, 'danger')

        data = response.get('Data') or {}
        items = (data.get(key) or []) if isinstance(data, dict) else []
        item = next((entry for entry in items if str(entry.get('ClientInternalID')) == str(self.id)), None)
        if item is None:
            self._basisbank_write_result({'basisbank_state': 'unknown', 'basisbank_bank_response': message})
            return self._basisbank_notify(_("Basis Bank reported success but returned no transfer details. Run Resync to confirm whether the "
                "transfer went through."), 'warning')
        item_error = item.get('ErrorCode', 0)
        if item_error:
            self._basisbank_reject(item_error, item.get('Msg') or message)
            return self._basisbank_notify(item.get('Msg') or message, 'danger')
        self._basisbank_write_result({
            'basisbank_state': 'sent',
            'basisbank_bank_internal_id': item.get('BankInternalID') or False,
            'basisbank_error_code': 0,
            'basisbank_error_message': False,
            'basisbank_bank_response': message,
        })
        return self._basisbank_notify(_("Payment sent to Basis Bank."), 'success')

    def _basisbank_reject(self, error_code, message):
        """Record the bank's refusal (batch and single): payments become Rejected, their entries stay."""
        for payment in self:
            payment._basisbank_write_result({
                'basisbank_state': 'failed',
                'basisbank_error_code': error_code or 0,
                'basisbank_error_message': message or False,
                'basisbank_approved_by': False,
                'basisbank_approved_date': False,
            })

    # Whitelist: the UPDATE behind _basisbank_write_result is never built from arbitrary input.
    _BASISBANK_RESULT_COLUMNS = frozenset({'basisbank_state', 'basisbank_bank_internal_id', 'basisbank_error_code', 'basisbank_error_message',
        'basisbank_bank_response', 'basisbank_sent_date', 'basisbank_approved_by', 'basisbank_approved_date', 'is_sent', 'state'})

    def _basisbank_reserve_send(self, sent_date=None):
        """Claim this payment for one send, durably, before any money moves.
        Written on an independent cursor that commits at once; the UPDATE is the mutex."""
        self.ensure_one()
        claimed = self.env['basisbank.service']._reserve_send(
            self, {'basisbank_state': 'sending', 'basisbank_sent_date': sent_date or fields.Datetime.now()},
            'basisbank_state', BASISBANK_CLAIM_BLOCKED_STATES)
        if not claimed:
            raise UserError(_("This payment is already being sent, was already sent, or its outcome is unknown (run Resync). Reload it to see its "
                "current state."))

    def _basisbank_write_result(self, vals):
        """Record a send outcome durably so it survives a rollback (the claim was durable, so an ORM write would fail).
        The state change is posted here because ORM tracking is skipped."""
        self.ensure_one()
        unknown = set(vals) - self._BASISBANK_RESULT_COLUMNS
        if unknown:
            raise ValueError("_basisbank_write_result cannot write %s" % sorted(unknown))
        old_state = self.basisbank_state
        new_state = vals.get('basisbank_state')
        vals = dict(vals, **self._basisbank_payment_state_vals(new_state))
        durable = self.env['basisbank.service']._durable_write(self, vals)
        self._gec_bank_after_durable(vals)
        if durable and new_state and new_state != old_state:
            labels = dict(self._fields['basisbank_state']._description_selection(self.env))
            self.message_post(body=_("Basis Bank state: %(old)s → %(new)s", old=labels.get(old_state, old_state or '-'),
                new=labels.get(new_state, new_state)))
        if durable and vals.get('state') == 'rejected':
            self.message_post(body=_("Basis Bank rejected this transfer, so the payment is marked Rejected. To send it again, reset it to draft, "
                "correct it, use Reset to Pending and send it; otherwise cancel it."))

    def _basisbank_payment_state_vals(self, basisbank_state):
        """Mirror the Basis outcome on Odoo's payment fields: at the bank -> sent; refused -> Rejected."""
        if basisbank_state in ('sent', 'confirmed'):
            return self._gec_bank_mirror_vals('held')
        if basisbank_state == 'failed':
            return self._gec_bank_mirror_vals('rejected')
        return {}

    def _basisbank_find_report_item(self):
        """Read the bank report around the send date and return this payment's item, else None."""
        self.ensure_one()
        start, end = report_window(self._basisbank_confirmation_reference_date())
        items = self.env['basisbank.service'].fetch_report_items(self._basisbank_connection(),
            self.journal_id.bank_account_id.sanitized_account_number or '', self.currency_id.name or 'GEL', start, end)
        return self._basisbank_match_report_items(items).get(self)

    def _basisbank_match_report_items(self, items):
        """Pair payments with bank report items: BankInternalID first, then DocNum; returns ``{payment: item}``.
        A candidate must be a debit from the payment's own IBAN for its exact amount; the first wins."""
        by_bank_id = defaultdict(list)
        by_doc_num = defaultdict(list)
        for item in items:
            if item.get('BankInternalID') not in (None, ''):
                by_bank_id[str(item['BankInternalID'])].append(item)
            if item.get('DocNum') is not None:
                by_doc_num[str(item['DocNum'])].append(item)
        matches = {}
        for payment in self:
            candidates = by_doc_num.get(str(payment.id), [])
            if payment.basisbank_bank_internal_id:
                candidates = by_bank_id.get(payment.basisbank_bank_internal_id, []) + candidates
            item = next((c for c in candidates if payment._basisbank_item_amount_matches(c)), None)
            if item is not None:
                matches[payment] = item
        return matches

    def action_basisbank_resync(self):
        """Recover an unclear send: read the bank report and confirm this payment if the bank has it."""
        self.ensure_one()
        self._gec_bank_check_user(BASISBANK_METHOD_CODE)
        entry = self._basisbank_find_report_item()
        if entry is not None:
            self._basisbank_confirm_from_statement(bank_id=entry.get('BankInternalID'))
            return self._basisbank_notify(_("Payment confirmed by the bank statement."), 'success')
        return self._basisbank_notify(_("Not found on the statement yet. The transfer may still be pending."), 'warning')

    def _basisbank_item_amount_matches(self, entry):
        """Confirm a report item is an outbound debit from our IBAN for this payment's amount."""
        self.ensure_one()
        currency = self.currency_id
        if not currency:
            return False
        our_acc = self.journal_id.bank_account_id.sanitized_account_number
        debit_acc = sanitize_account_number(entry.get('DebitAcc') or entry.get('SenderAcc'))
        if our_acc and debit_acc and our_acc != debit_acc:
            return False
        try:
            item_amount = abs(float(entry.get('Amount') or 0.0))
        except (TypeError, ValueError):
            return False
        return currency.compare_amounts(item_amount, self.amount) == 0

    def _basisbank_confirmation_reference_date(self):
        """When the bank received (or should have received) this payment: own send date, else the batch's."""
        self.ensure_one()
        return self.basisbank_sent_date or self.batch_payment_id.basisbank_sent_date

    @api.model
    def _cron_basisbank_confirm_or_reset(self):
        """48-hour check: one report lookup per journal and currency for payments sent over 48 hours ago.
        Found: confirmed; rest: flagged Not in Bank Report with an activity, entry untouched.
        Only overdue payments on active-connection journals."""
        deadline = fields.Datetime.now() - timedelta(hours=BASISBANK_CONFIRM_TIMEOUT_HOURS)
        journals = self.env['account.journal'].search([
            ('is_basisbank', '=', True),
            ('bank_account_number', '!=', False),
        ]).filtered(lambda journal: journal.basisbank_connection_id.state == 'active')
        expired = self.search([
            ('journal_id', 'in', journals.ids),
            ('payment_type', '=', 'outbound'),
            ('state', 'in', ('paid', 'reconciled')),
            '|',
            ('basisbank_state', 'in', BASISBANK_AWAITING_REPORT_STATES),
            '&',
            ('basisbank_state', '=', 'pending'),
            ('batch_payment_id.basisbank_state', 'in', ('sending', 'unknown')),
            '|',
            ('basisbank_sent_date', '<=', deadline),
            '&',
            ('basisbank_sent_date', '=', False),
            ('batch_payment_id.basisbank_sent_date', '<=', deadline),
        ], limit=500, order='id')
        if not expired:
            return

        confirmed = flagged = self.browse()
        for payment in expired.filtered('is_matched'):
            try:
                with self.env.cr.savepoint():
                    payment._basisbank_confirm_from_statement()
                confirmed |= payment
            except Exception:
                _logger.exception("Basis Bank 48h check: could not confirm matched payment %s", payment.id)

        service = self.env['basisbank.service']
        login_failed = self.env['basisbank.connection']
        by_report = expired.filtered(lambda p: not p.is_matched).grouped(lambda p: (p.journal_id, p.currency_id.name or 'GEL'))
        for (journal, ccy), payments in by_report.items():
            connection = journal.basisbank_connection_id
            if connection in login_failed:
                continue
            start, end = report_window(min(p._basisbank_confirmation_reference_date() for p in payments))
            account = journal.bank_account_id.sanitized_account_number
            try:
                items = service.fetch_report_items(connection, account, ccy, start, end)
            except Exception:
                _logger.exception("Basis Bank 48h check: report lookup failed for journal %s (%s); will retry next run", journal.id, ccy)
                if connection.state != 'active' or not connection.ticket_is_valid():
                    login_failed |= connection
                continue
            matches = payments._basisbank_match_report_items(items)
            for payment in payments:
                item = matches.get(payment)
                try:
                    with self.env.cr.savepoint():
                        if item is not None:
                            payment._basisbank_confirm_from_statement(bank_id=item.get('BankInternalID'))
                            confirmed |= payment
                        else:
                            payment._basisbank_flag_not_in_report(start, end)
                            flagged |= payment
                except Exception:
                    _logger.exception("Basis Bank 48h check failed for payment %s", payment.id)

        self._basisbank_update_batches_after_check(confirmed, flagged)
        if confirmed or flagged:
            _logger.info("Basis Bank 48h check: %d confirmed, %d not in the report", len(confirmed), len(flagged))

    def _basisbank_flag_not_in_report(self, window_start, window_end):
        """Flag a payment the 48-hour check did not find and ask its creator to look at it.
        Entry untouched: the bank may still book it; Resync or the statement confirms it later."""
        self.ensure_one()
        note = _("Not found in the %(start)s – %(end)s Basis Bank report %(hours)s hours after sending. The journal entry was left as it is, because "
            "the bank may still book the transfer. Check with the bank, then use Resync, or Reset to Pending to send it again.", start=window_start,
            end=window_end, hours=BASISBANK_CONFIRM_TIMEOUT_HOURS)
        self._gec_bank_internal_write({'basisbank_state': 'not_in_report'})
        self.message_post(body=note)
        self.activity_schedule('mail.mail_activity_data_todo', user_id=self.create_uid.id, summary=_("Basis Bank transfer not confirmed"), note=note)

    @api.model
    def _basisbank_update_batches_after_check(self, confirmed, flagged):
        """Reflect the 48-hour check on the owning batches."""
        batches = (confirmed | flagged).batch_payment_id
        for batch in batches - batches._basisbank_set_done_when_confirmed():
            flagged_in_batch = flagged.filtered(lambda p: p.batch_payment_id == batch)
            if not flagged_in_batch:
                continue
            if batch.basisbank_state != 'failed':
                batch._gec_bank_internal_write({'basisbank_state': 'unknown'})
            batch.message_post(body=_("Basis Bank confirmation check: these payments were not found in the bank report %(hours)s hours after "
                "sending; their journal entries were left as they are: %(names)s. Check with the bank, then use Resync, or Reset to Pending to send "
                "them again.", hours=BASISBANK_CONFIRM_TIMEOUT_HOURS, names=', '.join(flagged_in_batch.mapped('display_name'))))

    def action_basisbank_reset_to_pending(self):
        """Put reviewed not-in-report/failed payments back at the start of the send flow.
        Re-checks the bank report first: an executed payment is confirmed instead, so a resend never duplicates it."""
        self._gec_bank_check_user(BASISBANK_METHOD_CODE)
        for payment in self:
            if payment.basisbank_state not in ('not_in_report', 'failed'):
                raise UserError(_("Only payments flagged 'Not in Bank Report' or 'Failed' can be reset to pending (%s).") % payment.display_name)
            if payment.state not in ('draft', 'paid'):
                raise UserError(_("Reset the journal entry of %s to draft before resetting it to pending.") % payment.display_name)
        confirmed = self.browse()
        to_reset = self.browse()
        for payment in self:
            entry = payment._basisbank_find_report_item()
            if entry is not None:
                payment._basisbank_confirm_from_statement(bank_id=entry.get('BankInternalID'))
                confirmed |= payment
            else:
                to_reset |= payment
        to_reset.filtered('is_sent').unmark_as_sent()
        to_reset._gec_bank_internal_write({
            'basisbank_state': 'pending',
            'basisbank_bank_internal_id': False,
            'basisbank_error_code': 0,
            'basisbank_error_message': False,
            'basisbank_sent_date': False,
            'basisbank_approved_by': False,
            'basisbank_approved_date': False,
        })
        if confirmed:
            return self._basisbank_notify(_("These payments were found in the bank report and "
                "confirmed instead of reset; do NOT resend them: %s") % ', '.join(confirmed.mapped('display_name')), 'warning')
        return True
