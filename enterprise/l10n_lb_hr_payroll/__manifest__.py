# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Lebanon - Payroll',
    'countries': ['lb'],
    'category': 'Human Resources/Payroll',
    'description': """
Lebanon Payroll Rules
=====================
- National Social Security Fund: sickness and maternity (3% employee, 8% employer) and family allowances (6%
  employer) within their monthly ceilings, end-of-service indemnity (8.5% employer, uncapped, until 64); NSSF
  family allowances paid with the salary for the Fund
- Income tax on salaries and wages (Title II of Legislative Decree No. 144/1959): cumulative withholding over the
  calendar year, family deduction and bands prorated to the days of work, daily deduction of the daily and
  hourly workers, rounded up to LBP 10,000
- Salaries in LBP or in a foreign currency: the NSSF ceilings and allowances, the tax deductions and bands are
  converted at the rate of the Lebanese pound of the company
- Overtime paid by its time types (+50%, an extra day's pay on the public holidays), sick leave split into full
  pay, half pay and unpaid by the years of service, end-of-service indemnity of the foreign employees outside the
  NSSF branch, payroll warning of the wages below the official minimum wage
    """,
    'depends': ['hr_payroll'],
    'auto_install': ['hr_payroll'],
    'data': [
        'data/resource_calendar_data.xml',
        'data/hr_rule_parameter_data.xml',
        'data/hr_salary_rule_category_data.xml',
        'data/hr_payroll_structure_type_data.xml',
        'data/hr_work_entry_type_data.xml',
        'data/hr_payroll_structure_data.xml',
        'data/hr_salary_rule_data.xml',
        'data/hr_time_rule_data.xml',
        'data/hr_payroll_warning_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_contract_template_views.xml',
    ],
    'demo': [
        'data/l10n_lb_hr_payroll_demo.xml',
    ],
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'post_init_hook': '_l10n_lb_hr_payroll_post_install',
}
