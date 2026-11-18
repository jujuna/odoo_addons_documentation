from odoo import api, fields, models
from odoo.exceptions import AccessError


class AccountTax(models.Model):
    _inherit = 'account.tax'

    rs_form30_income_type_id = fields.Many2one('rs.form30.income.type', string='Form 30 Income Type', ondelete='set null',
        help="Income type reported on rs.ge Form 30 for payments withheld with this tax")
    rs_form30_service_type_id = fields.Many2one('rs.form30.service.type', string='Form 30 Service Type', ondelete='set null',
        help="Service kind reported in Form 30 annex E when the recipient settles their own tax")
    rs_form30_annex_e = fields.Boolean(string='Declare in Annex E',
        help="Bills whose lines carry this tax are declared in Form 30 annex E, amount only: the vendor pays their own tax and nothing is withheld.")
    rs_form30_rule_ids = fields.One2many(related='rs_form30_income_type_id.rate_rule_ids', readonly=False, string='Shared RS Declaration Rules')
    rs_form30_date_from = fields.Date(string='Form 30 Valid From', copy=False)
    rs_form30_date_to = fields.Date(string='Form 30 Valid To', copy=False)
    rs_form30_previous_tax_id = fields.Many2one('account.tax', string='Previous Tax', copy=False, ondelete='restrict', check_company=True)

    _rs_form30_date_order = models.Constraint('CHECK (rs_form30_date_from IS NULL OR rs_form30_date_to IS NULL OR rs_form30_date_from <= '
        'rs_form30_date_to)', 'Form 30 Valid To must be on or after Valid From.')

    def action_rs_form30_change(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(self.env._("Only accounting managers can apply Tax / RS changes."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Apply Tax / RS Change"),
            'res_model': 'rs.form30.tax.change',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_tax_id': self.id},
        }

    def _rs_form30_version_on(self, date):
        self.ensure_one()
        tax, seen = self, set()
        while tax and tax.id not in seen:
            seen.add(tax.id)
            if tax.rs_form30_date_from and date < tax.rs_form30_date_from:
                tax = tax.rs_form30_previous_tax_id
            elif tax.rs_form30_date_to and date > tax.rs_form30_date_to:
                tax = self.env['account.tax'].with_context(active_test=False).search([
                    ('rs_form30_previous_tax_id', '=', tax.id),
                    ('company_id', '=', tax.company_id.id),
                    ('rs_form30_date_from', '<=', date),
                ], order='rs_form30_date_from desc', limit=1)
            else:
                return tax
        return self.browse()

    @api.model
    def _gec_partner_purchase_tax(self, partner, company, date):
        tax = super()._gec_partner_purchase_tax(partner, company, date)
        if not tax or not date:
            return tax
        return tax._rs_form30_version_on(date) or tax

    @api.model
    def _rs_form30_map_ge_taxes(self, companies=None):
        """Fill empty Form 30 income type and Annex E flag on Georgian taxes from data/template/account.tax-ge.csv."""
        tax_data = self.env['account.chart.template']._parse_csv('ge', 'account.tax', module='gec_income_tax_report')
        if companies is None:
            companies = self.env['res.company'].search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        for company in companies:
            template = self.env['account.chart.template'].with_company(company)
            for xmlid, values in tax_data.items():
                tax = template.ref(xmlid, raise_if_not_found=False)
                if not tax:
                    continue
                if values.get('rs_form30_income_type_id') and not tax.rs_form30_income_type_id:
                    tax.rs_form30_income_type_id = self.env.ref(f"gec_income_tax_report.{values['rs_form30_income_type_id']}")
                if values.get('rs_form30_annex_e') and not tax.rs_form30_annex_e:
                    tax.rs_form30_annex_e = True
