from odoo import api, models
from odoo.exceptions import UserError
from .res_partner import GE_TAX_TREASURY_CODE


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    @api.model
    def _gec_state_treasury(self, company):
        """Return the State Treasury of the company: the one contact with Treasury Code 101001000.
        Contacts of the company or of no company are searched; none or several is refused, not guessed."""
        treasury = self.env['res.partner']._gec_state_treasury_partners(company)
        if not treasury:
            raise UserError(self.env._("No contact with Treasury Code 101001000 was found for %(company)s. Set that Treasury Code on the State "
                "Treasury contact.", company=company.display_name))
        if len(treasury) > 1:
            raise UserError(self.env._("Several contacts have Treasury Code 101001000 for %(company)s: %(partners)s. Keep that Treasury Code on the "
                "State Treasury only.", company=company.display_name, partners=', '.join(treasury.mapped('display_name'))))
        return treasury

    @api.model
    def _get_line_batch_key(self, line):
        """Pay the State Treasury in the company currency, with no bank account chosen yet, when paying a withholding tax line."""
        res = super()._get_line_batch_key(line)
        if self.env.context.get('gec_wht_tax_line_payment'):
            res['partner_id'] = self._gec_state_treasury(line.company_id).id
            res['currency_id'] = line.company_currency_id.id
            res['partner_bank_id'] = False
        return res

    @api.model
    def _get_batch_available_partner_banks(self, batch_result, journal):
        """Offer the bank accounts of the State Treasury, not those of the vendor of the bill."""
        if not self.env.context.get('gec_wht_tax_line_payment'):
            return super()._get_batch_available_partner_banks(batch_result, journal)
        company = min(batch_result['lines'].company_id, key=lambda c: len(c.sudo().parent_ids))
        treasury = self.env['res.partner'].browse(batch_result['payment_values']['partner_id'])
        return treasury.bank_ids.filtered(lambda bank: bank.company_id.id in (False, company.id))._origin

    @api.model
    def _get_batch_available_journals(self, batch_result):
        """Offer only journals in the company currency, as the Treasury is paid in it."""
        journals = super()._get_batch_available_journals(batch_result)
        if self.env.context.get('gec_wht_tax_line_payment'):
            journals = journals.filtered(lambda journal: not journal.currency_id or journal.currency_id == journal.company_id.currency_id)
        return journals

    def _compute_currency_id(self):
        """Pay a withholding tax line in the company currency, whatever the currency of the bill."""
        super()._compute_currency_id()
        if self.env.context.get('gec_wht_tax_line_payment'):
            for wizard in self:
                wizard.currency_id = wizard.company_id.currency_id

    def _convert_to_wizard_currency(self, installments):
        """A withholding tax is owed to the State Treasury in the GEL booked on the bill, not re-valued at the payment date."""
        if self.env.context.get('gec_wht_tax_line_payment') and self.currency_id == self.company_currency_id:
            return sum(installment['amount_residual'] for installment in installments)
        return super()._convert_to_wizard_currency(installments)

    @api.model
    def _get_payment_display_partner(self, lines, fallback_partner_id):
        """Name the State Treasury as the partner of the payment of a withholding tax line."""
        if self.env.context.get('gec_wht_tax_line_payment'):
            return self._gec_state_treasury(lines.company_id[:1]).id
        return super()._get_payment_display_partner(lines, fallback_partner_id)

    def _gec_check_withholding_payees(self):
        """Refuse paying withholding tax lines to a payee without Treasury Code 101001000, or no payee.
        Payee: the wizard's partner when one payment is edited, else each batch's partner."""
        batches = self._get_batches()
        all_tax_lines = self.env['account.move.line'].concat(batch['lines'] for batch in batches)._gec_withholding_tax_lines()
        edit_mode = self.can_edit_wizard and (len(batches[0]['lines']) == 1 or self.group_payment)
        for batch in batches:
            tax_lines = batch['lines'] & all_tax_lines
            if not tax_lines:
                continue
            if edit_mode:
                payee_id = self._get_payment_display_partner(self.line_ids, self.partner_id.id)
            else:
                payee_id = self._get_payment_display_partner(batch['lines'], batch['payment_values']['partner_id'])
            payee = self.env['res.partner'].browse(payee_id).commercial_partner_id
            if (payee.gec_treasury_code or '').strip() != GE_TAX_TREASURY_CODE:
                raise UserError(self.env._("%(documents)s books withholding tax, so it is paid to the State Treasury, but the payee %(payee)s has no "
                    "Treasury Code 101001000. Pay the State Treasury contact, or set that Treasury Code on the payee.",
                    documents=', '.join(tax_lines.move_id.mapped('display_name')), payee=payee.display_name or self.env._("(none)")))

    def _compute_unreconciled_paid_amount(self):
        """Ignore the vendor's payments in flight when paying a withholding tax.
        Core subtracts them from the amount to pay, but they went to the vendor, not to the State Treasury."""
        super()._compute_unreconciled_paid_amount()
        if self.env.context.get('gec_wht_tax_line_payment'):
            for wizard in self:
                wizard.unreconciled_paid_amount = 0.0

    def _compute_actionable_errors(self):
        """Drop core's "already paid" info when paying a withholding tax: that payment went to the vendor."""
        super()._compute_actionable_errors()
        if self.env.context.get('gec_wht_tax_line_payment'):
            for wizard in self.filtered('actionable_errors'):
                errors = {key: value for key, value in wizard.actionable_errors.items() if key != 'unreconciled_matched_payments'}
                wizard.actionable_errors = errors or False

    def _create_payments(self):
        """Check the payee of withholding tax lines on every Pay path; make the payment settle the line.
        An entry line or bill tax line needs a payment with an Outstanding account (checked on what core created); a bill tax line
        also needs a grouped wizard and refuses a write-off and an early payment discount."""
        entry_payment = self.company_id._gec_is_georgian() and any(move.move_type == 'entry' for move in self.line_ids.move_id)
        tax_payment = self.env.context.get('gec_wht_tax_line_payment')
        if tax_payment and not self.group_payment:
            self.group_payment = True
        if tax_payment:
            if self.can_edit_wizard:
                epd_lines = self.line_ids if self.early_payment_discount_mode else self.env['account.move.line']
            else:
                epd_lines = self.env['account.move.line'].concat(batch['lines'] for batch in self._get_batches()
                    if self._get_total_amounts_to_pay([batch])['epd_applied'])
            if epd_lines:
                raise UserError(self.env._("%(bills)s still have an early payment discount, which Odoo would take off the withholding tax. Pay the "
                    "vendor first, or pay the State Treasury after the discount date.", bills=', '.join(epd_lines.move_id.mapped('display_name'))))
        if (tax_payment and self.payment_difference_handling == 'reconcile' and not self.currency_id.is_zero(self.payment_difference)):
            raise UserError(self.env._("A withholding tax payment cannot write off a difference. Pay the amount due, or a part of it and keep the "
                "difference open."))
        self._gec_check_withholding_payees()
        payments = super()._create_payments()
        unsettled = payments.filtered(lambda payment: not payment.move_id)[:1]
        if (entry_payment or tax_payment) and unsettled:
            raise UserError(self.env._("Payment method %(method)s of %(journal)s has no Outstanding account, so this payment would not "
                "settle the journal entry line. Set one on the journal's Incoming or Outgoing Payments tab.",
                method=unsettled.payment_method_line_id.name, journal=unsettled.journal_id.display_name))
        return payments
