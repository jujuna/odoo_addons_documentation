# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _configure_payroll_account_ge(self, companies):
        salaries = 'ge_account_720100'              # 720100 Salaries & Wages
        allowances = 'ge_account_720110'            # 720110 Allowances & Bonuses
        overtime = 'ge_account_720200'              # 720200 Overtime & Commissions
        termination = 'ge_account_720700'          # 720700 Termination & Severance Benefits
        other_costs = 'ge_account_720900'           # 720900 Personnel Cost Others
        pension_cost = 'ge_account_721000'          # 721000 Pension & Post-Employment Contributions
        employer_taxes = 'ge_account_721100'        # 721100 Payroll Taxes (Employer)
        employee_receivable = 'ge_account_140310'   # 140310 Receivables from Employees
        payroll_advances = 'ge_account_150310'      # 150310 Payroll Advances
        salaries_payable = 'ge_account_310310'      # 310310 Salaries Payable
        other_liabilities = 'ge_account_310990'     # 310990 Other Short-Term Liabilities
        pit_payable = 'ge_account_331310'           # 331310 Employee Personal Income Tax (PIT) Accrued
        pension_payable = 'ge_account_332010'       # 332010 Pension Contribution Accrued

        rules_mapping = defaultdict(dict)

        def rule(xml_id):
            return self.env.ref(f'l10n_ge_hr_payroll.{xml_id}')

        # ================================================ #
        #          Georgia: Regular Pay Structure          #
        # ================================================ #

        # Salary and paid time
        rules_mapping[rule('l10n_ge_rule_basic')]['debit'] = salaries

        for xml_id in (
            'l10n_ge_rule_regular_allowance',
            'l10n_ge_rule_housing_allowance',
            'l10n_ge_rule_other_allowance',
            'l10n_ge_rule_bonus',
        ):
            rules_mapping[rule(xml_id)]['debit'] = allowances

        rules_mapping[rule('l10n_ge_rule_commission')]['debit'] = overtime

        for xml_id in (
            'l10n_ge_rule_severance',
            'l10n_ge_rule_leave_in_lieu',
            'l10n_ge_rule_other_termination_payment',
        ):
            rules_mapping[rule(xml_id)]['debit'] = termination

        for xml_id in ('l10n_ge_rule_per_diem', 'l10n_ge_rule_reimbursement'):
            rules_mapping[rule(xml_id)]['debit'] = other_costs
        rules_mapping[rule('l10n_ge_rule_gross_up')]['debit'] = employer_taxes

        # Funded pension paid by the employer: cost vs liability towards the Pension Fund
        rules_mapping[rule('l10n_ge_rule_pension_employer')]['debit'] = pension_cost
        rules_mapping[rule('l10n_ge_rule_pension_employer')]['credit'] = pension_payable

        # Amounts withheld from the employee (negative lines): credited to the liabilities and receivables
        for xml_id, account in (
            ('l10n_ge_rule_pension_employee', pension_payable),
            ('l10n_ge_rule_income_tax', pit_payable),
            ('l10n_ge_rule_attachment_of_salary', other_liabilities),
            ('l10n_ge_rule_advance_recovery', payroll_advances),
            ('l10n_ge_rule_loan_recovery', employee_receivable),
            ('l10n_ge_rule_damage_recovery', employee_receivable),
            ('l10n_ge_rule_deduction', employee_receivable),
        ):
            rules_mapping[rule(xml_id)]['debit'] = account

        # Net salary payable to the employee
        rules_mapping[rule('l10n_ge_rule_net')]['credit'] = salaries_payable

        self._configure_payroll_account(
            companies,
            "GE",
            account_refs=[
                salaries, allowances, overtime, termination, other_costs, pension_cost, employer_taxes,
                employee_receivable, payroll_advances, salaries_payable, other_liabilities, pit_payable,
                pension_payable,
            ],
            rules_mapping=rules_mapping,
            default_account=salaries,
        )
