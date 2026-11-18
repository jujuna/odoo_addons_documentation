from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

from .account_payment_method import BASIS_BANK_BIC, BASISBANK_METHOD_CODE

BASISBANK_HANDOFF_STATES = {
    'draft': 'prepared',
    'awaiting_approval': 'prepared',
    'awaiting_otp': 'prepared',
    'sending': 'pending',
    'sent_pending_confirm': 'transmitted',
    'awaiting_ib_confirmation': 'transmitted',
    'done': 'confirmed',
    'failed': 'failed',
    'unknown': 'uncertain',
}


class AccountPaymentMethodLine(models.Model):
    _inherit = 'account.payment.method.line'

    def _gec_bank_channel_kind(self):
        if self.code == BASISBANK_METHOD_CODE:
            return 'api'
        return super()._gec_bank_channel_kind()

    def _gec_bank_extra_config_errors(self):
        errors = super()._gec_bank_extra_config_errors()
        if self.code != BASISBANK_METHOD_CODE:
            return errors
        # sudo: the connection state is configuration; Payroll Administrators need no Basis group.
        connection = self.journal_id.basisbank_connection_id[:1].sudo()
        return errors + connection._gec_bank_unusable_errors(self.journal_id.company_id)

    def _gec_bank_check(self, kind, lines):
        """Name every recipient whose bank account has no BIC, before anything is created.
        Basis routes by the receiver bank's BIC, filled only from a Georgian IBAN; Treasury recipients are skipped."""
        errors = super()._gec_bank_check(kind, lines)
        if self.code != BASISBANK_METHOD_CODE:
            return errors
        journal_bic = bic_prefix(self.journal_id.bank_bic)
        missing = set()
        for line in lines:
            if (line.partner_id.commercial_partner_id.gec_treasury_code or '').strip():
                continue
            bank = line._gec_bank_recipient_account(journal_bic)
            if bank and not bank.bank_bic:
                missing.add(f"{line.partner_id.display_name} ({bank.account_number})")
        if missing:
            errors.append(_("Basis Bank needs the bank (BIC) of these recipients' accounts. Enter the full Georgian IBAN, which fills in the bank, "
                "or set the BIC on the account: %s", ', '.join(sorted(missing))))
        return errors

    def _gec_bank_payment_vals(self, kind, payment):
        """Transfer type of a payroll payment: Treasury Code gives treasury (no receiver account);
        else internal or national by BIC."""
        vals = super()._gec_bank_payment_vals(kind, payment)
        if self.code != BASISBANK_METHOD_CODE:
            return vals
        if payment.currency_id.name != 'GEL':
            raise UserError(_("Basis payroll payments must be in GEL: %s", payment.display_name))
        treasury_code = (payment.partner_id.commercial_partner_id.gec_treasury_code or '').strip()
        if treasury_code:
            vals['basisbank_transfer_type'] = 'treasury'
            vals['basisbank_treasury_code'] = treasury_code
            return vals
        bic = payment.partner_bank_id.bank_bic
        if not bic:
            raise UserError(_("%s has no receiver bank BIC.", payment.display_name))
        if not (payment.memo or payment.payment_reference or '').strip():
            raise UserError(_("%s has no payment purpose/description.", payment.display_name))
        vals['basisbank_transfer_type'] = 'internal' if bic_prefix(bic) == BASIS_BANK_BIC else 'national'
        return vals

    def _gec_bank_batch_vals(self, kind):
        vals = super()._gec_bank_batch_vals(kind)
        if self.code == BASISBANK_METHOD_CODE:
            vals['basisbank_salary'] = kind == 'salary'
        return vals

    def _gec_bank_handoff_state(self, batch):
        if self.code != BASISBANK_METHOD_CODE:
            return super()._gec_bank_handoff_state(batch)
        states = set(batch.payment_ids.mapped('basisbank_state'))
        rejected = states & {'failed', 'not_in_report'}
        if rejected and states - rejected:
            return 'partial'
        if states == {'failed'}:
            return 'failed'
        if 'unknown' in states or 'not_in_report' in states:
            return 'uncertain'
        return BASISBANK_HANDOFF_STATES.get(batch.basisbank_state, 'prepared')
