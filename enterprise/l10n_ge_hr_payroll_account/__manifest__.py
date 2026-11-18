# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Georgia - Payroll with Accounting',
    'category': 'Human Resources',
    'description': """
Accounting Data for Georgia Payroll Rules
=========================================
Salary journal and default accounts of the Georgian chart of accounts: salaries and wages (720100), allowances and
bonuses (720110), commissions (720200), termination and severance benefits (720700), other personnel costs
(720900), pension contributions (721000), employer payroll taxes (721100) for the income tax and pension borne by
the employer, employee personal income tax accrued (331310), pension contribution accrued (332010), salaries
payable (310310), payroll advances (150310), receivables from employees (140310), other short-term liabilities
(310990).
    """,
    'depends': ['hr_payroll_account', 'l10n_ge', 'l10n_ge_hr_payroll'],
    'data': [
        'data/account_chart_template_data.xml',
        'data/hr_salary_rule_data.xml',
    ],
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'auto_install': ['l10n_ge_hr_payroll', 'hr_payroll_account'],
}
