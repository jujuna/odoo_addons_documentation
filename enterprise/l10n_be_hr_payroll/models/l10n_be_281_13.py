# Part of Odoo. See LICENSE file for full copyright and licensing details.
from collections import defaultdict

from odoo import models
from odoo.tools import float_round
from odoo.addons.l10n_be_hr_payroll.models.utils import sum_values_by_group


class L10n_Be281_13(models.Model):
    _name = 'l10n_be.281_13'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.13 Wizard'

    def _get_declaration_code(self):
        return '281.13'

    def _get_withholding_tag(self):
        return 'f13_2078_bedrijfsvoorheffing'

    def _include_untaxed_payslips(self):
        # The complements of a resident of a treaty country (cross-border workers), without withholding tax, are
        # declared on a 281.13 as well ("avis aux débiteurs" 281.13, "Conventions internationales"), with the
        # supporting documents of the exemption kept for the administration (zone 2035)
        return True

    def _get_eligible_employees(self, payslips):
        # The days of temporary unemployment alone are no income: a form only for the employees paid a complement
        # (or withheld a tax on it), as the 281.18 does. A worker without complement (CP 200 without the
        # EUC_CP200 input, worker codes without EUB) gets no empty form.
        return super()._get_eligible_employees(payslips._l10n_be_filter_economic_unemployment())

    def _get_income_lines(self):
        return self._get_mapping_lines(self.declaration_id.year).filtered(
            lambda mapping_line: mapping_line.evaluation_type == 'salary_rule' or mapping_line.is_monetary,
        )

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        # Box 11: the arrears are declared apart from the complements of the year
        arrear_payslips = {
            employee: employee_payslips[employee].filtered('l10n_be_arrear_salary') for employee in mapped_totals_by_employee
        }
        arrears_by_employee = sum_values_by_group(arrear_payslips, all_line_values, list(all_line_values))
        without_complement_codes = self.env['hr.payslip']._l10n_be_get_unemployment_without_complement_codes()
        # Boxes 10 and 11: the complements are the taxable amount of the nature 13 (category TAXABLE_13), as for the
        # 274.13: the complements of the employer's own are declared with the legal ones
        taxable_13 = self.env['hr.payslip'].union(employee_payslips.values())._l10n_be_get_declaration_base(
            'TAXABLE_13', *self._get_declaration_period())
        for employee, mapped_total in mapped_totals_by_employee.items():
            mapped_total['arrears'] = defaultdict(float, arrears_by_employee[employee])
            mapped_total['taxable_13'] = sum(taxable_13[p.id] for p in employee_payslips[employee])
            mapped_total['arrears']['taxable_13'] = sum(taxable_13[p.id] for p in arrear_payslips[employee])
            # Zone 2089: the days of temporary unemployment of the year the complement is paid for, not the ones of
            # the arrears (they belong to their own year), nor the days without complement (collective closure, days
            # paid as salary). A half day is rounded up.
            days = sum(
                wd.number_of_days for wd in employee_payslips[employee].worked_days_line_ids
                if wd.work_entry_type_id.l10n_be_economic_unemployment and wd.code not in without_complement_codes
                and not wd.payslip_id.l10n_be_arrear_salary)
            mapped_total['unemployment_days'] = int(float_round(days, precision_digits=0, rounding_method='HALF-UP'))
        return mapped_totals_by_employee

    def _check_employee_values(self, sheet_values, evaluation_plan, line_values):
        # A correction of a complement of a previous year makes the amounts of the year negative. Its recovery is
        # declared in boxes 7, 11 and 18 of the form, by hand.
        reset_zones = self._reset_negative_amounts(sheet_values, evaluation_plan, {
            'f13_2060_bedrag': 'f13_2089_werkloosheidzonder',
            'f13_2064_bedrag': 'f13_2091_werkloosheidmetancienniteit',
        })
        if not reset_zones:
            return []
        return [self.env._(
            "the negative amounts of the zones %(zones)s are set to 0 (with their days): declare the recovered "
            "amounts by hand (boxes 7, 11 and 18 of the 281.13).",
            zones=', '.join(reset_zones),
        )]

    def _has_declared_income(self, amounts):
        # The negative amounts are set to 0 (_check_employee_values): only negative amounts make no form, the
        # employee is reported by _get_declaration_warnings
        return any(amount > 0 for amount in amounts)

    def _get_declaration_warnings(self):
        return self._get_employee_values_warnings(self.declaration_id.payslip_ids._l10n_be_filter_economic_unemployment())

    def _post_process_rendering_data_pdf(self, rendering_data):
        for sheet_values in rendering_data['employees_data']:
            for key, value in sheet_values.items():
                if key in ['f13_2089_werkloosheidzonder', 'f13_2091_werkloosheidmetancienniteit']:
                    sheet_values[key] = self.env._("%s days", value)
        return super()._post_process_rendering_data_pdf(rendering_data)
