from odoo import _, models

from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

from .account_payment import TREASURY_CODE_LENGTH, georgian_bank_code
from .account_payment_method import TBC_METHOD_CODE


class AccountPaymentMethodLine(models.Model):
    _inherit = 'account.payment.method.line'

    def _gec_bank_transfer_flow(self):
        """A TBC channel on a TBC journal runs the shared transfer flow."""
        if self.code == TBC_METHOD_CODE:
            return self.journal_id.is_tbc
        return super()._gec_bank_transfer_flow()

    def _gec_bank_channel_kind(self):
        if self.code == TBC_METHOD_CODE:
            return 'api'
        return super()._gec_bank_channel_kind()

    def _gec_bank_extra_config_errors(self):
        """A TBC channel needs its company's TBC connection, and it must not be blocked."""
        errors = super()._gec_bank_extra_config_errors()
        if self.code != TBC_METHOD_CODE:
            return errors
        # sudo: the connection state is configuration; Payroll Administrators need no TBC group.
        connection = self.journal_id.tbc_connection_id[:1].sudo()
        return errors + connection._gec_bank_unusable_errors(self.journal_id.company_id)

    def _gec_bank_check(self, kind, lines):
        """Refuse early what TBC would only refuse at Send: a Treasury Code recipient needs a 9-digit code;
        everyone else a Georgian IBAN (any other account becomes a SWIFT transfer, which payroll data cannot
        fill)."""
        errors = super()._gec_bank_check(kind, lines)
        if self.code != TBC_METHOD_CODE:
            return errors
        journal_bic = bic_prefix(self.journal_id.bank_bic)
        bad_codes, foreign = set(), set()
        for line in lines:
            partner = line.partner_id.commercial_partner_id
            code = (partner.gec_treasury_code or '').strip()
            if code:
                if not (code.isdigit() and len(code) == TREASURY_CODE_LENGTH):
                    bad_codes.add(f"{partner.display_name} ({code})")
                continue
            bank = line._gec_bank_recipient_account(journal_bic)
            if bank and not georgian_bank_code(bank.sanitized_account_number):
                foreign.add(f"{line.partner_id.display_name} ({bank.account_number})")
        if bad_codes:
            errors.append(_("TBC pays the State Treasury by a 9-digit Treasury Code. Correct the Treasury "
                            "Code of: %s", ', '.join(sorted(bad_codes))))
        if foreign:
            errors.append(_("TBC pays payroll only into Georgian IBANs. Pay these recipients another way, "
                            "or give them a Georgian account: %s", ', '.join(sorted(foreign))))
        return errors

    def _gec_bank_payment_vals(self, kind, payment):
        """A Treasury Code recipient makes a TBC treasury transfer; others keep the type set from the IBAN."""
        vals = super()._gec_bank_payment_vals(kind, payment)
        if self.code != TBC_METHOD_CODE:
            return vals
        code = (payment.partner_id.commercial_partner_id.gec_treasury_code or '').strip()
        if code:
            vals.update(tbc_transfer_type='treasury', tbc_treasury_code=code)
        return vals
