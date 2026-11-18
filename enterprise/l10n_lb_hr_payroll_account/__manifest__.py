# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Lebanon - Payroll with Accounting',
    'category': 'Human Resources',
    'description': """
Accounting Data for Lebanon Payroll Rules
=========================================
Salary journal and default accounts of the Lebanese chart of accounts: wages (631200), bonuses (631101),
personnel transportation (631910), schooling (631950), end-of-service indemnity paid by the employer (631990),
NSSF expenses and contributions (635100), end-of-service indemnity difference (635500), income tax on salaries
borne by the employer (641000), due to personnel (421101), personnel receivable (428001) for the advances and
loans, NSSF payables for the family allowances (431101), the sickness and maternity (431102) and the
end-of-service indemnity (431103), taxes due on salaries (441101), miscellaneous payables (461901) for the other
deductions.
    """,
    'depends': ['hr_payroll_account', 'l10n_lb_account', 'l10n_lb_hr_payroll'],
    'data': [
        'data/account_chart_template_data.xml',
        'data/hr_salary_rule_data.xml',
    ],
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'auto_install': ['l10n_lb_hr_payroll', 'hr_payroll_account'],
}
