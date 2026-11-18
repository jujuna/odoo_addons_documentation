# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _configure_payroll_account_lb(self, companies):
        wages = 'lb_account_631200'                 # 631200 Wages
        bonuses = 'lb_account_631101'               # 631101 Earning taxable & other primes & gratifications
        transport = 'lb_account_631910'             # 631910 Personnel transportation
        schooling = 'lb_account_631950'             # 631950 Schooling - employees
        not_taxable = 'lb_account_631990'           # 631990 Primes, gratifications & allocatives (not taxable)
        nssf_cost = 'lb_account_635100'             # 635100 NSSF expenses & contributions
        eos_difference = 'lb_account_635500'        # 635500 Difference IEOS - Indemnity End of Service
        tax_borne = 'lb_account_641000'             # 641000 Income tax on salaries & remuneration
        due_to_personnel = 'lb_account_421101'      # 421101 Due to personnel
        personnel_receivable = 'lb_account_428001'  # 428001 Personals accounts receivable
        nssf_fa = 'lb_account_431101'               # 431101 NSSF payable - family allowances
        nssf_sm = 'lb_account_431102'               # 431102 NSSF payable - sickness & motherhood allowance
        nssf_eos = 'lb_account_431103'              # 431103 NSSF payable - end of service indemnity
        salary_tax = 'lb_account_441101'            # 441101 Taxes due on salaries
        other_payables = 'lb_account_461901'        # 461901 Miscellaneous operating accounts payable

        rules_mapping = defaultdict(dict)

        def rule(xml_id):
            return self.env.ref(f'l10n_lb_hr_payroll.{xml_id}')

        # ================================================ #
        #          Lebanon: Regular Pay Structure          #
        # ================================================ #

        # Salary (the overtime included), allowances and termination payments
        for xml_id in (
            'l10n_lb_rule_basic',
            'l10n_lb_rule_cost_of_living',
            'l10n_lb_rule_regular_allowance',
            'l10n_lb_rule_commission',
            'l10n_lb_rule_transport_extra',
            'l10n_lb_rule_housing_allowance',
            'l10n_lb_rule_other_allowance',
            'l10n_lb_rule_reimbursement',
            'l10n_lb_rule_leave_in_lieu',
        ):
            rules_mapping[rule(xml_id)]['debit'] = wages

        rules_mapping[rule('l10n_lb_rule_bonus')]['debit'] = bonuses
        rules_mapping[rule('l10n_lb_rule_end_of_service')]['debit'] = not_taxable
        rules_mapping[rule('l10n_lb_rule_transport_allowance')]['debit'] = transport
        rules_mapping[rule('l10n_lb_rule_education_grant')]['debit'] = schooling
        rules_mapping[rule('l10n_lb_rule_gross_up')]['debit'] = tax_borne

        # The NSSF family allowances are paid for the Fund and offset against the contributions due
        rules_mapping[rule('l10n_lb_rule_family_allowance')]['debit'] = nssf_fa

        # NSSF borne by the employer: cost vs liability of each branch
        for xml_id, account in (
            ('l10n_lb_rule_nssf_sm_employer', nssf_sm),
            ('l10n_lb_rule_nssf_fa_employer', nssf_fa),
            ('l10n_lb_rule_nssf_eos_employer', nssf_eos),
        ):
            rules_mapping[rule(xml_id)]['debit'] = nssf_cost
            rules_mapping[rule(xml_id)]['credit'] = account
        rules_mapping[rule('l10n_lb_rule_eos_settlement')]['debit'] = eos_difference
        rules_mapping[rule('l10n_lb_rule_eos_settlement')]['credit'] = nssf_eos

        # Amounts withheld from the employee (negative lines): credited to the liabilities and receivables
        for xml_id, account in (
            ('l10n_lb_rule_nssf_sm_employee', nssf_sm),
            ('l10n_lb_rule_income_tax', salary_tax),
            ('l10n_lb_rule_advance_recovery', personnel_receivable),
            ('l10n_lb_rule_loan_recovery', personnel_receivable),
            ('l10n_lb_rule_deduction', other_payables),
        ):
            rules_mapping[rule(xml_id)]['debit'] = account

        # Net salary payable to the employee
        rules_mapping[rule('l10n_lb_rule_net')]['credit'] = due_to_personnel

        self._configure_payroll_account(
            companies,
            "LB",
            account_refs=[
                wages, bonuses, transport, schooling, not_taxable, nssf_cost, eos_difference, tax_borne, due_to_personnel,
                personnel_receivable, nssf_fa, nssf_sm, nssf_eos, salary_tax, other_payables,
            ],
            rules_mapping=rules_mapping,
            default_account=wages,
        )
