# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class L10n_Be281_20(models.Model):
    _name = 'l10n_be.281_20'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.20 Wizard'

    def _get_declaration_code(self):
        return '281.20'

    def _get_withholding_tag(self):
        return 'f20_2066_totaalbedrijfsvoorheffing'

    def _get_eligible_employees(self, payslips):
        return payslips._l10n_be_filter_remuneration_form('281.20').employee_id

    def _get_atn_code_mapping(self):
        return {
            'ATNCARREGUL': '',
            'ATN_HOUSING_FISCAL': 'B',
            'ATN_HEATING': 'C',
            'ATN_ELEC': 'D',
            'ATN.CAR': 'F',
            'ATN.LAP': 'H',
            'ATN.INT': 'I',
            'ATN.PHONE_AMT': 'J',
            'ATN.TAB': 'J',
            'ATN.MOB': 'K',
            'ATN_PENSION': 'Z',
            'ATN_SOCIAL_CONTRIB': 'Z',
            'ATN_MISC': 'Z',
            'FUEL_CARD_PRIV': 'Z',
        }
