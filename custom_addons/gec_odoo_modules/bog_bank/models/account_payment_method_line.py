from odoo import _, models

from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

from .account_batch_payment import BOG_BULK_AMOUNT_LIMIT
from .account_payment_method import BOG_METHOD_CODE

# Batch states that stay uncertain whatever its payments say.
BOG_BATCH_HANDOFF_STATES = {'sending': 'uncertain', 'unknown': 'uncertain'}


class AccountPaymentMethodLine(models.Model):
    _inherit = 'account.payment.method.line'

    def _gec_bank_transfer_flow(self):
        """A BOG channel on a BOG journal runs the shared transfer flow."""
        if self.code == BOG_METHOD_CODE:
            return self.journal_id.is_bog
        return super()._gec_bank_transfer_flow()

    def _gec_bank_channel_kind(self):
        if self.code == BOG_METHOD_CODE:
            return 'api'
        return super()._gec_bank_channel_kind()

    def _gec_bank_extra_config_errors(self):
        """A BOG channel needs its company's BOG connection, and it must not be blocked."""
        errors = super()._gec_bank_extra_config_errors()
        if self.code != BOG_METHOD_CODE:
            return errors
        # sudo: connection state is configuration; Payroll Administrators have no BOG group.
        connection = self.journal_id.bog_connection_id[:1].sudo()
        return errors + connection._gec_bank_unusable_errors(self.journal_id.company_id)

    def _gec_bank_check(self, kind, lines):
        """Refuse before creation what BOG refuses at Send: Treasury recipients, non-Georgian IBAN, unknown BIC."""
        errors = super()._gec_bank_check(kind, lines)
        if self.code != BOG_METHOD_CODE:
            return errors
        journal_bic = bic_prefix(self.journal_id.bank_bic)
        treasury, foreign, no_bic = set(), set(), set()
        for line in lines:
            partner = line.partner_id.commercial_partner_id
            if (partner.gec_treasury_code or '').strip():
                treasury.add(partner.display_name)
                continue
            bank = line._gec_bank_recipient_account(journal_bic)
            if not bank:
                continue
            number = bank.sanitized_account_number or ''
            if not (number.startswith('GE') and len(number) == 22):
                foreign.add(f"{line.partner_id.display_name} ({bank.account_number})")
            elif not bank.bank_bic:
                no_bic.add(f"{line.partner_id.display_name} ({bank.account_number})")
        if treasury:
            errors.append(_(
                "Our Bank of Georgia connection sends no treasury transfers yet. Pay these "
                "recipients through another bank: %s", ', '.join(sorted(treasury))))
        if foreign:
            errors.append(_(
                "Bank of Georgia pays payroll only into Georgian IBANs. Pay these recipients "
                "another way, or give them a Georgian account: %s", ', '.join(sorted(foreign))))
        if no_bic:
            errors.append(_(
                "Bank of Georgia needs the bank (BIC) of these recipients' accounts. Enter the "
                "full Georgian IBAN, which fills in the bank, or set the BIC on the account: %s",
                ', '.join(sorted(no_bic))))
        return errors

    def _gec_bank_payment_vals(self, kind, payment):
        """Make a payroll payment a BOG domestic transfer; only a salary is flagged IsSalary (code 155)."""
        vals = super()._gec_bank_payment_vals(kind, payment)
        if self.code != BOG_METHOD_CODE:
            return vals
        bulk = payment.currency_id.compare_amounts(payment.amount, BOG_BULK_AMOUNT_LIMIT) <= 0
        vals.update({
            'bog_transfer_type': 'domestic',
            'bog_is_salary': kind == 'salary',
            'bog_dispatch_type': 'BULK' if bulk else 'MT103',
        })
        return vals

    def _gec_bank_handoff_map(self):
        """A Warn answer created no document; a created one is unsigned, so the 48-hour alert applies."""
        mapping = super()._gec_bank_handoff_map()
        if self.code == BOG_METHOD_CODE:
            mapping.update(awaiting_confirmation='prepared', created='pending')
        return mapping

    def _gec_bank_transfer_handoff_states(self, batch):
        """A batch still 'sending' or 'unknown' is uncertain: the bulk call may have reached the bank."""
        states = super()._gec_bank_transfer_handoff_states(batch)
        if self.code == BOG_METHOD_CODE and batch.bog_state in BOG_BATCH_HANDOFF_STATES:
            states.add(BOG_BATCH_HANDOFF_STATES[batch.bog_state])
        return states
