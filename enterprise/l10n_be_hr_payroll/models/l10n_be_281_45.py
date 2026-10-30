# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import models

_logger = logging.getLogger(__name__)

_WITHHOLDING_FIELD = 'f45_2063_roerendevoorheffing'

# Sources:
# - Technical Doc https://finances.belgium.be/fr/E-services/Belcotaxonweb/documentation-technique
# - "Avis aux débiteurs" https://finances.belgium.be/fr/entreprises/personnel_et_remuneration/avis_aux_debiteurs#q2


class L10n_Be281_45(models.Model):
    _name = 'l10n_be.281_45'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.45 Wizard'

    def _get_declaration_code(self):
        return '281.45'

    def _get_withholding_tag(self):
        return _WITHHOLDING_FIELD

    def _get_income_lines(self):
        return self._get_mapping_lines(self.declaration_id.year).filtered(
            lambda mapping_line: mapping_line.tag != _WITHHOLDING_FIELD
            and (mapping_line.evaluation_type == 'salary_rule' or mapping_line.is_monetary)
        )
