from odoo import Command, api, fields, models

FIXED_ASSET_ACCOUNT_XMLIDS = ('ge_account_211210', 'ge_account_211310', 'ge_account_211510', 'ge_account_211420', 'ge_account_211410',
    'ge_account_216990', 'ge_account_210120')
FIXED_ASSET_SEEDED_KEY = 'gec_vat_declaration.fixed_asset_accounts_seeded'


class ResCompany(models.Model):
    _inherit = 'res.company'

    gec_vat_fixed_asset_account_ids = fields.Many2many('account.account', 'res_company_gec_vat_fixed_asset_rel', 'company_id', 'account_id',
        string='Fixed-asset accounts (VAT declaration)', check_company=True, help="Bill lines on these accounts are fixed-asset purchases: "
        "their VAT goes to column 5 of annex A III of the VAT declaration, the rest to column 4.")

    def _gec_vat_companies(self):
        """The company and its own branches with the same Tax ID, as the VAT report (sudo: unreadable branches)."""
        self.ensure_one()
        return self.sudo()._get_branches_with_same_vat().filtered_domain([('id', 'child_of', self.id)])

    def _gec_vat_branch_warning(self):
        self.ensure_one()
        # sudo: the branch tree may hold companies the user cannot read
        company = self.sudo()
        same_vat = sorted(company._get_branches_with_same_vat(), key=lambda comp: len(comp.parent_path.split('/')))
        if company.parent_id and company != same_vat[0]:
            return self.env._("%(company)s is not the main branch of its VAT number: the declaration is normally filed by the main branch.",
                company=company.name)
        return False

    def _gec_lock_tax_month(self, date_to):
        """Lock tax postings up to date_to as core's tax return does: revoke active tax-lock exceptions, never lower the lock
        (sudo: accountants cannot write res.company)."""
        self.env['account.lock_exception'].sudo().search([
            ('company_id', 'in', self.ids),
            ('state', '=', 'active'),
            ('lock_date_field', '=', 'tax_lock_date'),
        ]).action_revoke()
        self.filtered(lambda c: not c.tax_lock_date or c.tax_lock_date < date_to).sudo().write({'tax_lock_date': date_to})

    @api.model
    def _gec_vat_seed_fixed_asset_accounts(self, companies=None):
        if companies is None:
            companies = self.search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        for company in companies.filtered(lambda company: not company.gec_vat_fixed_asset_account_ids):
            template = self.env['account.chart.template'].with_company(company)
            accounts = [template.ref(xmlid, raise_if_not_found=False) for xmlid in FIXED_ASSET_ACCOUNT_XMLIDS]
            company.gec_vat_fixed_asset_account_ids = [Command.set([account.id for account in accounts if account])]

    @api.model
    def _gec_vat_seed_fixed_asset_accounts_once(self):
        """Seed once per database, so an accountant who clears the list is not overruled by a later upgrade. The flag
        covers upgrades only: a chart load re-seeds the empty list of a root company."""
        params = self.env['ir.config_parameter']
        if not params.get_bool(FIXED_ASSET_SEEDED_KEY):
            self._gec_vat_seed_fixed_asset_accounts()
            params.set_bool(FIXED_ASSET_SEEDED_KEY, True)
