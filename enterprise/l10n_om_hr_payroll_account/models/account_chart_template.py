# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _configure_payroll_account_om(self, companies):
        employee_payables = 'om_account_200103'
        spf_employer_payable = 'om_account_200105'
        leave_days_provision = 'om_account_200502'
        eos_provision = 'om_account_200503'
        eos_indemnity = 'om_account_500202'
        basic_salary = 'om_account_500301'
        leave_salary = 'om_account_500305'
        other_allowances = 'om_account_500308'
        spf_employer_contribution = 'om_account_500310'
        salary_deductions = 'om_account_500311'

        rules_mapping = defaultdict(dict)

        # ================================================ #
        #           OM Employee Payroll Structure          #
        # ================================================ #

        basic_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_monthly_pay_basic_salary')
        rules_mapping[basic_rule]['debit'] = basic_salary

        bonus_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_monthly_pay_bonus')
        rules_mapping[bonus_rule]['debit'] = other_allowances

        # The rule computes a negative amount, so debit and credit are swapped
        spf_comp_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_spf_company_contribution')
        rules_mapping[spf_comp_rule]['debit'] = spf_employer_payable
        rules_mapping[spf_comp_rule]['credit'] = spf_employer_contribution

        spf_emp_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_spf_employee_contribution')
        rules_mapping[spf_emp_rule]['debit'] = employee_payables

        other_allowance_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_monthly_pay_other_allowance')
        rules_mapping[other_allowance_rule]['debit'] = other_allowances

        eos_provision_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_end_of_service_provision')
        rules_mapping[eos_provision_rule]['debit'] = eos_indemnity
        rules_mapping[eos_provision_rule]['credit'] = eos_provision

        remaining_leaves_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_remaining_leave_days_compensation')
        rules_mapping[remaining_leaves_rule]['debit'] = leave_days_provision

        annual_leave_provision_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_annual_leaves_provision')
        rules_mapping[annual_leave_provision_rule]['debit'] = leave_salary
        rules_mapping[annual_leave_provision_rule]['credit'] = leave_days_provision

        annual_leave_payout_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_annual_leaves_provision_payout')
        rules_mapping[annual_leave_payout_rule]['debit'] = leave_days_provision

        eos_benefit_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_end_of_service_benefit')
        rules_mapping[eos_benefit_rule]['debit'] = eos_provision

        expenses_reimbursement_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_monthly_pay_expenses_reimbursement')
        rules_mapping[expenses_reimbursement_rule]['debit'] = salary_deductions

        deduction_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_monthly_pay_deduction')
        rules_mapping[deduction_rule]['debit'] = salary_deductions

        net_rule = self.env.ref('l10n_om_hr_payroll.l10n_om_monthly_pay_net')
        rules_mapping[net_rule]['credit'] = employee_payables

        self._configure_payroll_account(
            companies,
            "OM",
            account_refs=[
                employee_payables, spf_employer_payable, leave_days_provision, eos_provision, eos_indemnity,
                basic_salary, leave_salary, other_allowances, spf_employer_contribution, salary_deductions
],
            rules_mapping=rules_mapping,
            default_account=employee_payables
        )
