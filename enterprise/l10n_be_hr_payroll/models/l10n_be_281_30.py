# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models


class L10n_Be281_30(models.Model):
    _name = 'l10n_be.281_30'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.30 Wizard'

    def _get_declaration_code(self):
        return '281.30'

    def _get_withholding_tag(self):
        return 'f30_2063_bedrijfsvoorheffing'

    def _get_eligible_employees(self, payslips):
        return payslips._l10n_be_filter_remuneration_form('281.30').employee_id

    def _get_atn_code_mapping(self):
        return {
            'ATN_HOUSING_FISCAL': 'B',
            'ATN_HEATING': 'C',
            'ATN_ELEC': 'D',
            'ATN.CAR': 'F',
            'ATN.LAP': 'H',
            'ATN.INT': 'I',
            'ATN.PHONE_AMT': 'J',
            'ATN.TAB': 'J',
            'ATN.MOB': 'K',
        }

    def _post_process_rendering_data_pdf(self, rendering_data):
        for sheet_values in rendering_data['employees_data']:
            for key, value in sheet_values.items():
                if key in ["f30_2089_numberpeople", "f30_2090_numberdays"]:
                    sheet_values[key] = f"{value}"
        return super()._post_process_rendering_data_pdf(rendering_data)
