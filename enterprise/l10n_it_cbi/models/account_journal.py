from markupsafe import Markup

from odoo import fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.business_data import split_vat
from odoo.tools.bank_account_number import get_iban_part, validate_iban
from odoo.addons.account_batch_payment.models.sepa_mapping import sanitize_communication


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def _default_outbound_payment_methods(self):
        res = super()._default_outbound_payment_methods()
        if self.company_id.country_code == 'IT':
            if cbi_method := self.env.ref('l10n_it_cbi.account_payment_method_cbi_ct', raise_if_not_found=False):
                res |= cbi_method
        return res

    def _compute_outbound_payment_method_line_ids(self):
        super()._compute_outbound_payment_method_line_ids()
        self._assign_outstanding_account_to_payment_method_lines(
            'outbound',
            payment_method_codes=['cbi_ct'],
            chart_template='it',
        )

    def _l10n_it_sanitize_cbi_text(self, text, size=None):
        if not text:
            return ""
        text = text.replace("&", "e")
        clean_text = sanitize_communication(text, size=size)
        return clean_text.strip()

    def _create_cbi_credit_transfer_content(self, payments, batch_booking, seq_num, batch_date, priority):
        if not payments:
            raise UserError(self.env._("Cannot generate a CBI Payment Request for an empty batch."))

        if any(p.currency_id != self.env.ref('base.EUR') for p in payments):
            raise UserError(self.env._("Payments must all be in EUR"))

        for payment in payments:
            if not payment.partner_bank_id or not payment.partner_bank_id.account_number:
                raise UserError(self.env._("Payment %s is missing a destination bank account or IBAN.", payment.name))

        debtor_iban = self.bank_account_id.account_number.replace(" ", "")

        cuc = self.company_id.partner_id._get_additional_identifier('IT_CUC') or ""

        fiscal_id = split_vat(self.company_id.vat or '', 'IT')[1]
        company_partner = self.company_id.partner_id
        if not fiscal_id and 'l10n_it_codice_fiscale' in company_partner._fields:
            fiscal_id = company_partner['l10n_it_codice_fiscale']

        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())

        missing_address_partners = self.env['res.partner']
        transactions = []
        for index, payment in enumerate(payments, start=1):
            partner_bank = payment.partner_bank_id
            partner = payment.partner_id
            dest_iban = partner_bank.sanitized_account_number

            if not dest_iban.startswith("IT") and (not partner.city or not partner.country_id):
                missing_address_partners |= partner

            memo_text = payment.memo or payment.name
            transactions.append({
                'index': str(index),
                'e2e_name': self._l10n_it_sanitize_cbi_text(payment.name, size=35) or "NOTPROVIDED",
                'amount': f"{payment.currency_id.round(payment.amount):.2f}",
                'bank_bic': partner_bank.bank_bic,
                'partner_name': self._l10n_it_sanitize_cbi_text(partner.name, 70),
                'street': self._l10n_it_sanitize_cbi_text(partner.street, 70) or False,
                'zip': self._l10n_it_sanitize_cbi_text(partner.zip, 16) or False,
                'city': self._l10n_it_sanitize_cbi_text(partner.city, 35) or False,
                'country_code': partner.country_id.code or False,
                'dest_iban': dest_iban,
                'is_it_iban': dest_iban.startswith("IT"),
                'ustrd': self._l10n_it_sanitize_cbi_text(memo_text, 140) or False,
            })

        if missing_address_partners:
            partner_names = ", ".join(missing_address_partners.mapped('name'))
            raise UserError(self.env._("Missing address: %s", partner_names))

        qweb_values = {
            'msg_id': f"{cuc}{now.strftime('%Y%m%d%H%M%S')}{seq_num}"[:35],
            'cre_dt_tm': now.strftime("%Y-%m-%dT%H:%M:%S"),
            'nb_of_txs': str(len(payments)),
            'ctrl_sum': f"{sum(p.currency_id.round(p.amount) for p in payments):.2f}",
            'company_name': self._l10n_it_sanitize_cbi_text(self.company_id.name, 70),
            'cuc': cuc,
            'fiscal_id': fiscal_id,
            'batch_booking': "true" if batch_booking else "false",
            'priority': priority,
            'batch_date': batch_date,
            'debtor_iban': debtor_iban,
            'abi_code': "",
            'transactions': transactions,
        }

        if debtor_iban.startswith("IT"):
            try:
                if validate_iban(self.env, debtor_iban):
                    qweb_values['abi_code'] = get_iban_part(debtor_iban, 'bank')
            except ValidationError:
                pass

        return (
            Markup("<?xml version='1.0' encoding='UTF-8'?>\n")
            + self.env['ir.qweb']._render('l10n_it_cbi.l10n_it_cbi_payment_request_xml', qweb_values)
        )
