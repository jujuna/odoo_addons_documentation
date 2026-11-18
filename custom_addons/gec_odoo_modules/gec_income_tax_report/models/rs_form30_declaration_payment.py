from odoo import models
from odoo.tools import float_compare


class RsForm30DeclarationPayment(models.Model):
    _inherit = 'rs.form30.declaration'

    def _withholding_lines(self):
        self.ensure_one()
        return self.env['account.payment.withholding.line'].search([
            ('company_id', '=', self.company_id.id),
            ('payment_id.state', 'in', ('paid', 'reconciled')),
            ('payment_id.payment_type', '=', 'outbound'),
            ('payment_id.date', '>=', self.date_from),
            ('payment_id.date', '<=', self.date_to),
        ])

    def _payment_line_vals(self):
        """One row per withholding line of a confirmed outbound payment dated in the month."""
        self.ensure_one()
        lines = self._withholding_lines()
        company = self.company_id
        vals_list = []
        for line in lines:
            payment = line.payment_id
            partner = payment.partner_id
            if partner._rs_form30_pays_own_tax():
                continue
            tax, warnings = self._rs_form30_row_tax(line.tax_id, payment.date)
            classification, classification_warnings = self._recipient_classification(partner, payment.date)
            if tax.amount_type != 'percent':
                warnings.append("Tax %s is not a percentage, set the rate manually." % tax.name)
            warnings.extend(classification_warnings)
            if not payment.move_id:
                warnings.append("Payment has no journal entry, the withholding is not booked.")
            recipient = self._rs_form30_recipient_vals(partner)
            if partner.is_company and not recipient['first_name']:
                warnings.append("Legal form not detected in the company name.")
            vals_list.append({
                **classification,
                'source': 'payment',
                'withholding_line_id': line.id,
                **recipient,
                'income_type_id': tax.rs_form30_income_type_id.id,
                'amount': payment.currency_id._convert(line.base_amount, company.currency_id, company, payment.date),
                'tax_amount': payment.currency_id._convert(line.amount, company.currency_id, company, payment.date),
                'date': payment.date,
                'rate': abs(tax.amount) if tax.amount_type == 'percent' else 0.0,
                'warning': ' '.join(warnings),
                'issue_level': self._rs_form30_issue_level(warnings),
            })
        return vals_list

    def _service_line_vals(self):
        """Annex E rows: service fees to recipients who pay their own tax."""
        self.ensure_one()
        company = self.company_id
        vals_list = []
        for line in self._withholding_lines():
            payment = line.payment_id
            partner = payment.partner_id
            if not partner._rs_form30_pays_own_tax():
                continue
            warnings = []
            if float_compare(line.amount, 0.0, precision_rounding=line.comodel_currency_id.rounding) > 0:
                warnings.append("Tax was withheld from a recipient who pays their own tax: it is not in annex E, check the document.")
            vals_list.append({
                **self._rs_form30_recipient_vals(partner),
                'withholding_line_id': line.id,
                'country_id': partner.country_id.id,
                'service_type_id': line.tax_id.rs_form30_service_type_id.id,
                'amount': payment.currency_id._convert(line.base_amount, company.currency_id, company, payment.date),
                'warning': ' '.join(warnings),
                'issue_level': self._rs_form30_issue_level(warnings),
            })
        return vals_list
