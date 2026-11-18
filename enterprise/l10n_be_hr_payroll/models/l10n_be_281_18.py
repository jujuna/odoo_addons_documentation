# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from collections import defaultdict

from odoo import models
from odoo.addons.l10n_be_hr_payroll.models.utils import sum_values_by_group

_logger = logging.getLogger(__name__)

# Sources:
# - Technical Doc https://finances.belgium.be/fr/E-services/Belcotaxonweb/documentation-technique
# - "Avis aux débiteurs" https://finances.belgium.be/fr/entreprises/personnel_et_remuneration/avis_aux_debiteurs#q2


class L10n_Be281_18(models.Model):
    _name = 'l10n_be.281_18'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.18 Wizard'

    def _get_declaration_code(self):
        return '281.18'

    def _get_withholding_tag(self):
        return 'f18_2070_bedrijfsvoorheffing'

    def _include_untaxed_payslips(self):
        # The form is due even when the indemnities are not subject to the withholding tax: the cross-border workers
        # get theirs, with the supporting documents of the exemption kept for the administration (zone 2035)
        return True

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        # Box 7 e) (code 272): the arrears are taxable separately, they are declared apart from the indemnities
        arrear_payslips = {
            employee: employee_payslips[employee].filtered('l10n_be_arrear_salary') for employee in mapped_totals_by_employee
        }
        arrears_by_employee = sum_values_by_group(arrear_payslips, all_line_values, list(all_line_values))
        transferred_amounts = self._get_transferred_281_10_amounts(employee_payslips, all_line_values)
        for employee, mapped_total in mapped_totals_by_employee.items():
            mapped_total['arrears'] = defaultdict(float, arrears_by_employee[employee])
            # Boxes 8 and 10: the amounts of a 281.10 declared on the 281.18 instead
            mapped_total['transferred_281_10'] = defaultdict(float, transferred_amounts.get(employee, {}))
        return mapped_totals_by_employee

    def _get_transferred_281_10_amounts(self, employee_payslips, all_line_values):
        """Amounts of the 281.10 declared on the 281.18 of the employee instead, when he gets no 281.10 (no taxable
        remuneration of the year): the special social security contribution (box 10, zone 2071, "si pas soldé au
        niveau des fiches 281.10 ou 281.20") and the personal contributions to a complementary pension (box 8).
        The 281.10 decides which amounts it transfers.

        :param employee_payslips: {employee: payslips of the declaration}
        :param all_line_values: the payslip line values of the declaration, as in _get_precomputed_employee_data
        :return: {employee: {
            'special_contribution': zone 2071 (code 287),
            'group_insurance': zone 2068 (code 285, normal contributions and premiums),
            'individual_continuation': zone 2069 (code 283),
            'free_pension': zone 2128 (code 387, free complementary pension of the employees),
        }}, positive amounts in euros
        """
        if self.env.context.get('l10n_be_281_18_without_transfer'):
            return {}
        # The amounts of the employees whose 281.10 is not created, computed by the 281.10 on its own payslips and
        # payslip lines (all_line_values may lack the quantities it reads)
        sheet_281_10 = self.declaration_id.l10n_be_281_10_ids[:1]
        payslips = self.env['hr.payslip'].union(employee_payslips.values())._l10n_be_filter_remuneration_form('281.10')
        if not sheet_281_10 or not payslips:
            return {}
        line_values_281_10 = payslips._get_line_values(
            sheet_281_10._get_line_codes(), vals_list=['total', 'quantity'],
            extra_domain=sheet_281_10._get_fiscal_line_domain())
        return sheet_281_10._get_amounts_to_transfer_to_281_18(payslips.grouped('employee_id'), line_values_281_10)

    def _get_employees_with_own_form(self, payslips):
        """The employees of ``payslips`` with a 281.18 of their own: an amount to declare on it, the amounts of a
        281.10 transferred aside (they only follow a form the employee already has)."""
        self.ensure_one()
        sheet = self.with_context(l10n_be_281_18_without_transfer=True)
        return {
            employee for employee, amounts in sheet._get_income_amounts(payslips, sheet._get_income_lines()).items()
            if sheet._has_declared_income(amounts)
        }

    def _get_income_lines(self):
        return self._get_mapping_lines(self.declaration_id.year).filtered(
            lambda mapping_line: mapping_line.evaluation_type == 'salary_rule' or mapping_line.is_monetary,
        )

    def _check_employee_values(self, sheet_values, evaluation_plan, line_values):
        # A correction of an indemnity of a previous year makes the amounts of the year negative. Its recovery is
        # declared by hand (281.25, zone 2205 of Belcotax-on-web 2.0).
        reset_zones = self._reset_negative_amounts(sheet_values, evaluation_plan, {
            'f18_2064_ziekteofinvaliditeit': 'f18_2090_dagen',
            'f18_2065_beroepsziekte': 'f18_2091_dagen',
        })
        if not reset_zones:
            return []
        return [self.env._(
            "the negative amounts of the zones %(zones)s are set to 0 (with their days): declare the recovered "
            "amounts by hand (281.25 form, zone 2205 on Belcotax-on-web 2.0).",
            zones=', '.join(reset_zones),
        )]

    def _has_declared_income(self, amounts):
        # The negative amounts are set to 0 (_check_employee_values): only negative amounts make no form, the
        # employee is reported by _get_declaration_warnings
        return any(amount > 0 for amount in amounts)

    def _get_declaration_warnings(self):
        return self._get_employee_values_warnings(self.declaration_id.payslip_ids)

    def _post_process_rendering_data_pdf(self, rendering_data):
        # The days are not amounts
        for sheet_values in rendering_data['employees_data']:
            for key in ('f18_2090_dagen', 'f18_2091_dagen'):
                if key in sheet_values:
                    sheet_values[key] = self.env._("%s days", sheet_values[key])
        return super()._post_process_rendering_data_pdf(rendering_data)
