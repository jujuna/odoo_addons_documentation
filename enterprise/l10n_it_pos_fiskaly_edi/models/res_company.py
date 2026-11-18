from odoo import models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _l10n_it_fiskaly_tax_id_number(self):
        self.ensure_one()
        return self.l10n_it_codice_fiscale or super()._l10n_it_fiskaly_tax_id_number()
