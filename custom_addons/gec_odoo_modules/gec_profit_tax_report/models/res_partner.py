from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    gec_cit_status = fields.Selection([
        ('enterprise', 'Georgian Enterprise'),
        ('exempt', 'Exempt from Profit Tax'),
        ('budget', 'Budget Organisation'),
        ('nbg_dia', 'NBG or Deposit Insurance Agency'),
        ('financial', 'Bank, Credit Union, Microfinance or Lending Entity'),
    ], string='Profit Tax Status', tracking=True,
        help="How the monthly profit tax declaration treats this contact. Empty: an individual, a foreign "
             "person or a non-commercial legal entity.\n"
             "Georgian Enterprise: resident LLC, JSC, cooperative, general or limited partnership taxed under "
             "the general rule. Dividends paid to it stay out of line 16.1.\n"
             "Exempt from Profit Tax: e.g. a free industrial zone enterprise, special trading company or "
             "virtual zone person. Dividends paid to it are taxed; deals with it feed lines 16.4 and 18.\n"
             "Budget Organisation: exempt, but left out of lines 16.4 and 18.1.1-18.1.3; gifts to it stay out of line 19.\n"
             "NBG or Deposit Insurance Agency: exempt, but left out of lines 16.4 and 18.1; gifts to it stay out of line 19.\n"
             "Bank, Credit Union, Microfinance or Lending Entity: dividends paid to it are taxed.")
    gec_cit_related_party = fields.Boolean(
        string='Related Party', company_dependent=True, tracking=True,
        help="Related to this company in a way that affects deal prices (Tax Code art. 18). Invoice lines with "
             "a market value then feed line 16.3 of the profit tax declaration, unless the contact is a Georgian "
             "Enterprise.")
    gec_cit_share = fields.Float(
        string='Share in Capital (%)', company_dependent=True, digits=(5, 2),
        help="This contact's share in this company's capital. A bank, credit union, microfinance organisation or "
             "lending entity reports loans to a non-resident or exempt shareholder, or to an individual shareholder "
             "with at least 1%, on line 18.4.")
    gec_cit_micro_business = fields.Boolean(
        string='Micro Business Status',
        help="An individual with micro business status. Purchases from them feed line 17.3, unless their income "
             "from this supply is taxed under the general rule: then leave it unticked.")
    gec_cit_fixed_tax = fields.Boolean(
        string='Fixed Tax Payer',
        help="Pays fixed tax on the activity purchased. Purchases from them feed line 17.3, except activities "
             "taxed at the rate of Tax Code art. 95.3.1.b: then leave it unticked.")
    gec_cit_charity = fields.Boolean(
        string='Charity Organisation',
        help="Holds charity status. Donations to it on line 19 are taxed only above 10% of last year's net profit.")
    gec_cit_listed_abroad = fields.Boolean(
        string='Shares Listed on a Recognised Foreign Exchange',
        help="Buying its shares or securities stays out of lines 18.2 and 18.3.")

    @api.model
    def _commercial_fields(self):
        return super()._commercial_fields() + [
            'gec_cit_status', 'gec_cit_related_party', 'gec_cit_micro_business', 'gec_cit_fixed_tax',
            'gec_cit_charity', 'gec_cit_listed_abroad']

    def _gec_cit_preferential(self):
        """Registered in a country with preferential taxation."""
        self.ensure_one()
        return bool(self.country_id.gec_cit_preferential)

    def _gec_cit_non_resident(self):
        """Registered outside Georgia; a contact without a country counts as resident."""
        self.ensure_one()
        return bool(self.country_id) and self.country_id.code != 'GE'
