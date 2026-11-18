from odoo import api, fields, models
from odoo.tools.business_data import split_vat

GE_TAX_TREASURY_CODE = '101001000'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    gec_contact_category_ids = fields.Many2many('gec.contact.category', string='Contact Categories', compute='_compute_gec_contact_category_ids',
        store=True, readonly=False, recursive=True, copy=True,
        help='User-defined contact categories. Child contacts inherit their parent’s categories.')
    property_sale_tax_id = fields.Many2one('account.tax', company_dependent=True, check_company=True, ondelete='restrict', string="Default Sales Tax",
        domain="[('type_tax_use', '=', 'sale'), ('is_withholding_tax', '=', False)]", help="Replaces the product's sales taxes on quotations, sales "
        "orders and customer invoices for this contact. The fiscal position still applies afterwards.")
    property_purchase_tax_id = fields.Many2one('account.tax', company_dependent=True, check_company=True, ondelete='restrict',
        string="Default Purchase Tax", domain="[('type_tax_use', '=', 'purchase')]",
        help="Replaces the product's purchase taxes on purchase orders and vendor bills for this contact: a VAT, a withholding tax (the person bears "
        "it or the company pays it) or a 0% \"no withholding\" label. For a VAT Payer, a withholding tax or label is added to the product's taxes "
        "instead of replacing them. One tax only; add any other tax on the line by hand.")
    gec_vat_payer = fields.Boolean(string="VAT Payer", tracking=True, help="Registered for VAT: purchase orders and vendor bills keep the product's "
        "VAT and add this contact's Default Purchase Tax when it is a withholding tax or a \"no withholding\" label. Unticked, that default replaces "
        "the product's taxes. Bills pulled from rs.ge keep only their own VAT: add the label by hand.")
    gec_treasury_code = fields.Char(string='Treasury Code', tracking=True, help="Set on budget recipients such as the State Treasury (taxes: "
        "101001000). Pay Salaries pays such a contact by this code instead of a bank account, and the bank sends a treasury transfer.")

    @api.depends('parent_id.gec_contact_category_ids')
    def _compute_gec_contact_category_ids(self):
        for partner in self:
            partner.gec_contact_category_ids = (partner.parent_id.gec_contact_category_ids if partner.parent_id else partner.gec_contact_category_ids)

    @api.depends('vat', 'country_id')
    def _compute_is_company(self):
        """A Georgian 11-digit personal number belongs to a person (sole traders too), not a company.

        Core counts every contact with a Tax ID as a company. Legal entities (9 digits) and other countries keep it."""
        super()._compute_is_company()
        for partner in self:
            if partner.is_company and partner._gec_has_georgian_personal_number():
                partner.is_company = False

    def _gec_has_georgian_personal_number(self):
        """Whether the Tax ID is an 11-digit Georgian personal number: GE prefix, country Georgia,
        or no country at all (as rs.ge waybill drivers and sellers are created)."""
        self.ensure_one()
        prefix, number = split_vat((self.vat or '').strip())
        if not (number.isdigit() and len(number) == 11):
            return False
        if prefix:
            return prefix == 'GE'
        return not self.country_id or self.country_code == 'GE'

    @api.model
    def _commercial_fields(self):
        return super()._commercial_fields() + ['property_sale_tax_id', 'property_purchase_tax_id', 'gec_vat_payer']

    @api.model
    def _gec_state_treasury_partners(self, company):
        return self.search([('gec_treasury_code', '=', GE_TAX_TREASURY_CODE), *self._check_company_domain(company)])

    @api.model
    def _gec_recompute_georgian_company_flag(self):
        """Recompute contacts stored as companies with a Georgian personal number (archived included).

        The compute alone runs only on a Tax ID or country change; called by the data <function> on install/upgrade."""
        companies = self.with_context(active_test=False).search_fetch([('is_company', '=', True), ('vat', '!=', False)], ['vat', 'country_id'])
        stale = companies.filtered(lambda partner: partner._gec_has_georgian_personal_number())
        if stale:
            self.env.add_to_compute(self._fields['is_company'], stale)
            stale._recompute_recordset(['is_company'])
