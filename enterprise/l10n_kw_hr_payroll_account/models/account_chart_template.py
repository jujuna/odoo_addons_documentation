# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _configure_payroll_account_kw(self, companies):
        employee_payables = 'kw_account_200103'
        company_payable = 'kw_account_200105'
        leave_days_provision = 'kw_account_200502'
        eos_provision = 'kw_account_200503'
        eos_indemnity = 'kw_account_500202'
        basic_salary = 'kw_account_500301'
        leave_salary = 'kw_account_500305'
        other_allowances = 'kw_account_500308'
        unemployment_pension = 'kw_account_500310'
        salary_deductions = 'kw_account_500311'
        basic_pension = 'kw_account_500312'

        rules_mapping = defaultdict(dict)

        # ================================================ #
        #           KW Employee Payroll Structure          #
        # ================================================ #

        basic_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_basic_salary')
        rules_mapping[basic_rule]['debit'] = basic_salary

        basic_pension_emp_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_basic_pension_emp')
        rules_mapping[basic_pension_emp_rule]['debit'] = basic_pension

        sick_leave_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_sick_leave')
        rules_mapping[sick_leave_rule]['debit'] = salary_deductions

        basic_pension_comp_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_basic_pension_comp')
        rules_mapping[basic_pension_comp_rule]['debit'] = unemployment_pension
        rules_mapping[basic_pension_comp_rule]['credit'] = company_payable

        unemp_emp_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_unemp_emp')
        rules_mapping[unemp_emp_rule]['debit'] = employee_payables

        unemp_comp_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_unemp_comp')
        rules_mapping[unemp_comp_rule]['debit'] = unemployment_pension
        rules_mapping[unemp_comp_rule]['credit'] = company_payable

        attachment_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_attach_salary')
        rules_mapping[attachment_rule]['debit'] = salary_deductions

        assignment_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_assign_salary')
        rules_mapping[assignment_rule]['debit'] = salary_deductions

        child_support_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_child_support')
        rules_mapping[child_support_rule]['debit'] = other_allowances

        eos_provision_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_eos_provision')
        rules_mapping[eos_provision_rule]['debit'] = eos_indemnity
        rules_mapping[eos_provision_rule]['credit'] = eos_provision

        annual_leave_provision_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_annual_leave_provision')
        rules_mapping[annual_leave_provision_rule]['debit'] = leave_salary
        rules_mapping[annual_leave_provision_rule]['credit'] = leave_days_provision

        eos_benefit_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_eos_benefit')
        rules_mapping[eos_benefit_rule]['debit'] = eos_provision

        remaining_leaves_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_remaining_leaves_compensation')
        rules_mapping[remaining_leaves_rule]['debit'] = other_allowances

        deduction_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_deduction')
        rules_mapping[deduction_rule]['debit'] = salary_deductions

        reimbursement_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_reimbursement')
        rules_mapping[reimbursement_rule]['debit'] = other_allowances

        net_rule = self.env.ref('l10n_kw_hr_payroll.l10n_kw_monthly_pay_net')
        rules_mapping[net_rule]['credit'] = employee_payables

        self._configure_payroll_account(
            companies,
            "KW",
            account_refs=[
                employee_payables, company_payable, leave_days_provision, eos_provision, eos_indemnity, basic_salary,
                leave_salary, other_allowances, unemployment_pension, salary_deductions, basic_pension
            ],
            rules_mapping=rules_mapping,
            default_account=employee_payables
        )
