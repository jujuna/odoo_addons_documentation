from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountTax(models.Model):
    _inherit = 'account.tax'

    gec_is_withholding = fields.Boolean(string="Withholding Tax (GE)",
        help="Georgian withholding tax: a negative percent tax booked on the vendor bill line. 'Included in Price' = Tax Excluded: the person bears "
        "the tax (deducted from the payable). Tax Included: the company pays it on top. On journal entries it is only a label.")

    @api.constrains('gec_is_withholding', 'amount_type', 'amount', 'is_withholding_tax', 'price_include_override')
    def _check_gec_is_withholding(self):
        """A Georgian withholding tax must be a percent tax with a negative amount (0 is a "no withholding" label),
        not Withhold-on-payment, with Included in Price set: any other shape books wrong amounts on a bill."""
        for tax in self.filtered('gec_is_withholding'):
            if not (
                tax.amount_type == 'percent'
                and tax.amount <= 0
                and not tax.is_withholding_tax
                and tax.price_include_override in ('tax_excluded', 'tax_included')
            ):
                raise ValidationError(self.env._("%s: a Georgian withholding tax must be a percent tax with a negative or zero amount, not ticked "
                    "Withhold, and Included in Price set (Tax Excluded or Tax Included).", tax.display_name))

    @api.model
    def _prepare_base_line_for_taxes_computation(self, record, **kwargs):
        """Withholding taxes are only a label on manual entries and bank reconciliation lines (a negative tax there is balanced on suspense).
        Decided here, not when taxes are computed: bank reconciliation deletes the line in between."""
        base_line = super()._prepare_base_line_for_taxes_computation(record, **kwargs)
        if (
            isinstance(record, models.BaseModel)
            and record._name == 'account.move.line'
            and record.move_id.move_type == 'entry'
            and not record.move_id.origin_payment_id
        ):
            base_line['calculate_withholding_taxes'] = True
            base_line['filter_tax_function'] = lambda t: not t.is_withholding_tax and not t.gec_is_withholding
        return base_line

    @api.model
    def _ge_partner_product_taxes(self, taxes, partner, product, company, type_tax_use, fiscal_position, date=None):
        """Not Taxed product wins; else the partner's default tax replaces the product's taxes.
        For a VAT payer a withholding default is added to the product's (already mapped) taxes, never mapped itself."""
        if not company._gec_is_georgian():
            return taxes
        if product.not_taxed:
            return self.env['account.tax']
        partner = partner.commercial_partner_id.with_company(company)
        if type_tax_use == 'sale':
            partner_tax = partner.property_sale_tax_id or partner.sudo().with_company(company.root_id).property_sale_tax_id.with_env(partner.env)
        else:
            partner_tax = self._gec_partner_purchase_tax(partner, company, date)
        partner_tax = partner_tax.filtered('active')
        if not partner_tax:
            return taxes
        if partner_tax.gec_is_withholding:
            return taxes | partner_tax if partner.gec_vat_payer else partner_tax
        return fiscal_position.map_tax(partner_tax)

    @api.model
    def _gec_partner_purchase_tax(self, partner, company, date):
        """Return the partner's Default Purchase Tax for a document of ``date``; a hook for dated tax versions."""
        partner = partner.with_company(company)
        # sudo: a user allowed only the branch cannot switch to the root company; core reads the root default the same way
        return partner.property_purchase_tax_id or partner.sudo().with_company(company.root_id).property_purchase_tax_id.with_env(partner.env)
