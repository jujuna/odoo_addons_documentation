from odoo import models


class L10nGeCitWizard(models.TransientModel):
    _inherit = 'l10n.ge.cit.wizard'

    def _gec_default_dividend_wht_tax(self):
        self.ensure_one()
        tax = super()._gec_default_dividend_wht_tax()
        visited = set()
        while tax and tax.id not in visited:
            visited.add(tax.id)
            successor = self.env['account.tax'].search([
                ('rs_form30_previous_tax_id', '=', tax.id),
                ('company_id', '=', tax.company_id.id),
                ('rs_form30_date_from', '<=', self.date),
            ], order='rs_form30_date_from desc', limit=1)
            if not successor:
                break
            tax = successor
        return tax
