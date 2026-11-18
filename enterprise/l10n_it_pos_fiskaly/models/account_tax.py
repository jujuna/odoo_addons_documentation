from odoo import api, fields, models

# Keep in sync with vatExemptions in static/src/app/services/pos_store.js.
VAT_EXEMPTIONS = [
    ('NOT_SUBJECT', "Not subject (Non soggette)"),
    ('NOT_TAXABLE', "Not taxable (Non imponibili)"),
    ('CAUSE_1', "Exempt (Esenti)"),
    ('CAUSE_2', "Exclusive Art. 15"),
    ('CAUSE_3', "Marginal scheme (Regime del margine)"),
    ('CAUSE_4', "Other (Altre non IVA)"),
]

VAT_EXEMPTION_BY_NATURA = {
    'N1': 'CAUSE_2',
    'N2': 'NOT_SUBJECT',
    'N3': 'NOT_TAXABLE',
    'N4': 'CAUSE_1',
    'N5': 'CAUSE_3',
    'N6': 'CAUSE_4',
    'N7': 'CAUSE_4',
}


class AccountTax(models.Model):
    _inherit = 'account.tax'

    l10n_it_fiskaly_vat_exemption = fields.Selection(
        selection=VAT_EXEMPTIONS,
        string="Fiskaly VAT Exemption",
        compute='_compute_l10n_it_fiskaly_vat_exemption',
        store=True,
        readonly=False,
    )

    @api.depends('l10n_it_exempt_reason')
    def _compute_l10n_it_fiskaly_vat_exemption(self):
        for tax in self:
            natura = tax.l10n_it_exempt_reason
            tax.l10n_it_fiskaly_vat_exemption = natura and VAT_EXEMPTION_BY_NATURA.get(natura.split('.')[0])

    @api.model
    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), 'l10n_it_fiskaly_vat_exemption']
