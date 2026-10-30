# Part of Odoo. See LICENSE file for full copyright and licensing details.
from collections import defaultdict

from odoo import models
from odoo.addons.l10n_be_hr_payroll.models.utils import sum_values_by_group


class L10n_Be281_13(models.Model):
    _name = 'l10n_be.281_13'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.13 Wizard'

    def _get_declaration_code(self):
        return '281.13'

    def _get_withholding_tag(self):
        return 'f13_2078_bedrijfsvoorheffing'

    def _get_eligible_employees(self, payslips):
        return payslips._l10n_be_filter_economic_unemployment().employee_id

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        # Box 11: the arrears are declared apart from the complements of the year
        arrear_payslips = {
            employee: employee_payslips[employee].filtered('l10n_be_arrear_salary') for employee in mapped_totals_by_employee
        }
        arrears_by_employee = sum_values_by_group(arrear_payslips, all_line_values, list(all_line_values))
        for employee, mapped_total in mapped_totals_by_employee.items():
            mapped_total['arrears'] = defaultdict(float, arrears_by_employee[employee])
        return mapped_totals_by_employee

    def _post_process_rendering_data_pdf(self, rendering_data):
        for sheet_values in rendering_data['employees_data']:
            for key, value in sheet_values.items():
                if key in ['f13_2089_werkloosheidzonder', 'f13_2091_werkloosheidmetancienniteit']:
                    sheet_values[key] = self.env._("%s days", value)
        return super()._post_process_rendering_data_pdf(rendering_data)
