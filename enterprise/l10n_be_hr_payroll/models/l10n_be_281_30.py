# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models

# Box 9: the nature of the reimbursed expenses, in the language of the beneficiary (zone 2027: 1 Dutch, 2 French,
# 3 German), French by default
REIMBURSED_EXPENSE_NATURES = {
    'travel': {1: 'verplaatsingskosten', 2: 'déplacement', 3: 'Reisekosten'},
    'other': {1: 'diversen', 2: 'divers', 3: 'verschiedene'},
}


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

    def _get_reimbursed_expense_code_mapping(self):
        # The expenses reimbursed by the payslip, as on the 281.20 (box 19 a), with their nature
        return {
            'REP.FEES': 'other',
            'REP.FEES.VOLATILE': 'other',
            'HOME_FEES': 'other',
            'EXPENSES': 'other',
            'EXPENSE_MANUAL': 'other',
        }

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        expense_mapping = self._get_reimbursed_expense_code_mapping()
        # The taxable remuneration (salary, benefits in kind, bonuses...) is added up from the amounts it is made of, as
        # on the 281.10, so that each one is declared in the year it is attached to
        all_payslips = self.env['hr.payslip'].union(employee_payslips.values())
        base_values = all_payslips._l10n_be_get_gross_wage_base_values(*self._get_declaration_period())
        for employee, mapped_total in mapped_totals_by_employee.items():
            # Boxes 6a / 7f: the whole taxable remuneration of the beneficiary is declared with the presence tokens,
            # as the beneficiary is left out of the 281.10 and the 281.20. The residence is the one of the version of
            # each payslip: a beneficiary moving abroad during the year has income in both boxes.
            income = {'resident': 0.0, 'non_resident': 0.0}
            for payslip in employee_payslips[employee]:
                residence = 'resident' if payslip.version_id.l10n_be_resident_situation == 'resident' else 'non_resident'
                income[residence] += sum(
                    all_line_values[code][payslip.id]['total'] for code in ['PRESENCE_TOKEN', *expense_mapping]
                ) + sum(values[payslip.id] for values in base_values.values())
            mapped_total['resident_income'] = income['resident']
            mapped_total['non_resident_income'] = income['non_resident']
            # The reimbursed expenses are part of the taxable income too, and box 9 repeats them with their nature
            lang_code = self._get_lang_code(employee.lang)
            reimbursed_expenses = 0.0
            natures = []
            for code, nature in expense_mapping.items():
                amount = mapped_total.get(code, 0)
                if not amount:
                    continue
                reimbursed_expenses += amount
                label = REIMBURSED_EXPENSE_NATURES[nature].get(lang_code, REIMBURSED_EXPENSE_NATURES[nature][2])
                if label not in natures:
                    natures.append(label)
            # Belcotax-on-web refuses a negative amount
            reimbursed_expenses = max(reimbursed_expenses, 0.0)
            mapped_total['reimbursed_expenses'] = reimbursed_expenses
            mapped_total['reimbursed_expenses_nature'] = ', '.join(natures) if reimbursed_expenses else ''
        return mapped_totals_by_employee

    def _post_process_rendering_data_pdf(self, rendering_data):
        for sheet_values in rendering_data['employees_data']:
            for key, value in sheet_values.items():
                if key in ["f30_2089_numberpeople", "f30_2090_numberdays"]:
                    sheet_values[key] = f"{value}"
        return super()._post_process_rendering_data_pdf(rendering_data)
