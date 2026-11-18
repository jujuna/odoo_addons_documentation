# Part of Odoo. See LICENSE file for full copyright and licensing details.
import re
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import remove_accents

CITI_PRODUCT_CODES = {
    'l10n_hk_citi_autopay': 'ATP',
    'l10n_hk_citi_autopay_payroll': 'HKP',
}


class L10nhkBankFormatCiti(models.AbstractModel):
    """
    Supports exporting batch payments in the Citibank GDFF format (PayLink AUTOPAY and AUTOPAY Payroll).
    Note that we do not support PayLink Cheque nor the invoice lines at the moment.
    """
    _inherit = 'l10n_hk.bank.format'

    @api.model
    def _validate(self, file_format, payload):
        if file_format in CITI_PRODUCT_CODES:
            if not payload.get('batches'):
                return [self.env._('The payment export payload is missing the payments information.')]

            errors = []
            today = fields.Date.context_today(self)
            if any(not today <= batch['header']['effective_date'] <= today + timedelta(days=20) for batch in payload['batches']):
                errors.append(self.env._("The Value Date must be between today and 20 days in advance for Citibank."))
            payments = [payment for batch in payload['batches'] for payment in batch['payments']]
            invalid_holder_names = [payment for payment in payments if not self._citi_sanitize(payment['bank_account'].holder_name)]
            if invalid_holder_names:
                errors.append(self.env._(
                    "The Account Holder Name is missing or only contains characters not allowed by Citibank. Please check it for the following bank accounts:\n%s",
                    "\n".join(f"- {payment['bank_account'].account_number}" for payment in invalid_holder_names),
                ))
            hkid_payments = [payment for payment in payments if payment['autopay_account_type'] == 'hkid']
            if hkid_payments:
                errors.append(self.env._(
                    "The HKID Autopay Payment Type is not supported by Citibank. Please change it for the following employees:\n%s",
                    "\n".join(f"- {payment['bank_account'].holder_name or self.env._('Unknown')}" for payment in hkid_payments),
                ))
            invalid_bank_accounts = [
                payment for payment in payments
                if payment['autopay_account_type'] == 'bban' and not (
                    re.fullmatch(r'\d{3}', payment['bank_account']._get_clearing_number('HK') or '')
                    and re.fullmatch(r'\d{9,12}', payment['bank_account'].sanitized_account_number or '')
                )
            ]
            if invalid_bank_accounts:
                errors.append(self.env._(
                    "Some bank accounts (%s) must have a 3-digit bank code and an account number of 9 to 12 digits (3-digit branch code + account number of 6 to 9 digits).",
                    ", ".join(payment['bank_account'].account_number for payment in invalid_bank_accounts),
                ))
            invalid_proxy_payments = [
                payment for payment in payments
                if payment['autopay_account_type'] in ('svid', 'mobn', 'emal')
                and (not payment.get('account_proxy_id') or (payment['autopay_account_type'] == 'emal' and '@' not in payment['account_proxy_id']))
            ]
            if invalid_proxy_payments:
                errors.append(self.env._(
                    "Some employees (%s) are missing a valid FPS proxy ID.",
                    ", ".join(payment['bank_account'].holder_name or self.env._("Unknown") for payment in invalid_proxy_payments),
                ))
            invalid_proxy_characters = [
                payment for payment in payments
                if payment['autopay_account_type'] in ('svid', 'mobn', 'emal') and payment.get('account_proxy_id')
                and any(self._citi_sanitize(part) != part for part in payment['account_proxy_id'].split('@'))
            ]
            if invalid_proxy_characters:
                errors.append(self.env._(
                    "The FPS proxy ID contains characters not allowed by Citibank. Please check it for the following employees:\n%s",
                    "\n".join(f"- {payment['bank_account'].holder_name or self.env._('Unknown')}" for payment in invalid_proxy_characters),
                ))
            invalid_fps_ids = [
                payment for payment in payments
                if payment['autopay_account_type'] == 'svid' and payment.get('account_proxy_id') and len(payment['account_proxy_id']) != 7
            ]
            if invalid_fps_ids:
                errors.append(self.env._(
                    "The FPS ID must be 7 characters long for Citibank. Please check it for the following employees:\n%s",
                    "\n".join(f"- {payment['bank_account'].holder_name or self.env._('Unknown')}" for payment in invalid_fps_ids),
                ))
            return errors

        return super()._validate(file_format, payload)

    @api.model
    def _generate(self, file_format, payload):
        if file_format in CITI_PRODUCT_CODES:
            return self._generate_citi_file(file_format, payload)

        return super()._generate(file_format, payload)

    def _generate_citi_file(self, file_format, payload):
        entries = []
        product_code = CITI_PRODUCT_CODES[file_format]
        for batch in payload['batches']:
            for payment in batch['payments']:
                entries.append(self._generate_citi_entry_detail(product_code, batch['header'], payment))

        document_name = payload.get("document_name", "AutoPay")
        return "\r\n".join(entries).encode('utf-8'), '.txt', self._prepare_file_name('CITI', document_name)

    def _generate_citi_entry_detail(self, product_code, headers, payment):
        # Values are keyed by their spec position (Ref No 1 to 113), joined with '@'.
        bank_account = payment["bank_account"]
        account_type = payment["autopay_account_type"]
        holder_name = bank_account.holder_name or ""
        values = {
            1: product_code,                                                            # Product Code (Length 3)
            2: "HK",                                                                    # Debit Account Country Code (Length 2)
            3: (headers["bank_account"].sanitized_account_number or "").lstrip("0"),    # Debit Account Number, without leading zeros (Length 35)
            4: headers["currency"],                                                     # Payment Currency (Length 3)
            5: f"{payment['amount']:.2f}",                                              # Payment Amount (Length 21)
            7: f"{headers['effective_date']:%Y%m%d}",                                   # Value Date (Length 8)
            20: self._citi_sanitize(holder_name).upper()[:20],                          # Beneficiary Name, uppercase (Length 20)
            36: self._citi_sanitize(payment.get("reference"))[:15],                     # Payment Details, Line 1 (Length 15)
        }
        if account_type == 'bban':
            account_number = bank_account.sanitized_account_number
            values[34] = f"{bank_account._get_clearing_number('HK')}-{account_number[:3]}-{account_number[3:].zfill(9)}"  # Beneficiary Bank Account: bank-branch-account, account zero-padded to 9 digits (Length 17)
            values[79] = "22"                                                           # Transaction Type: Salary Credits
        else:
            values[24] = account_type.upper()                                           # Beneficiary Other ID Type (Length 6)
            values[79] = "23"                                                           # Transaction Type: HK Faster Payments
            if account_type == 'emal':
                values[94], values[95] = payment["account_proxy_id"].rsplit("@", 1)     # Custom Fields 1 & 2: email account & domain names (Length 70)
            else:
                values[25] = payment["account_proxy_id"]                                # Beneficiary Other ID (Length 34)

        return "@".join(values.get(ref, "") for ref in range(1, 114))

    def _citi_sanitize(self, text):
        # Keep only the characters allowed by Citi, '@' excluded as it is the field separator.
        return re.sub(r"[^A-Za-z0-9 ?',.()+/&\-*:=#!$%]", "", remove_accents(text or "")).strip()
