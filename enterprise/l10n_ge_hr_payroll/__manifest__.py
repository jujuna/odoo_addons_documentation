# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Georgia - Payroll',
    'countries': ['ge'],
    'category': 'Human Resources/Payroll',
    'description': """
Georgia Payroll Rules
=====================
- Funded pension (Law on Funded Pensions of 2018): 2% employee and 2% employer of the taxable salary, without
  ceiling, for the participants; the State co-financing (2% up to GEL 24,000 a year, 1% up to 60,000) shown for
  information
- Personal income tax withheld at source (Tax Code, art. 81, 82 and 154): 20% of the salary less the employee
  pension contribution, or the rate of the income tax regime of the company (international and R&D service
  companies, innovative start-ups, Free Industrial Zone), less the annual privileges of GEL 3,000 and 6,000 of the
  employee used cumulatively over the calendar year
- Labour Code: sick leave paid by the employer, severance of 1 or 2 months depending on the departure reason and
  the notice period, unused annual leave paid on the departure, deductions within 50% of the net pay
- Net salary basis: income tax and pension borne by the employer, grossed up
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
        'data/hr_departure_reason_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_contract_template_views.xml',
        'views/hr_employee_departure_views.xml',
        'views/hr_departure_reason_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'demo': [
        'data/l10n_ge_hr_payroll_demo.xml',
    ],
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'post_init_hook': '_l10n_ge_hr_payroll_post_install',
}
