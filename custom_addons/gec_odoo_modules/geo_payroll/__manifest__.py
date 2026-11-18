{
    'name': 'GEO Payroll - Wage Types & Work Logs',
    'version': '20.0.1.34.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Daily/unit wage types, employee work logs (overtime/daily/unit) paid through salary rules',
    'description': """
Pay schemes on the contract version (fixed, hourly, daily, per unit and combinations),
employee work logs for overtime, daily and unit work paid through salary rules, benefit
and advance programs, Georgian income tax and pension rules with art. 82 exemptions, and
the account configuration for the Georgian chart.

Full documentation: README.md and README_DEV.md in the module directory.
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['hr_payroll', 'hr_payroll_account', 'project', 'timesheet_grid', 'uom',
                'gec_localization'],
    'data': [
        'data/res_partner_data.xml',
        'data/res_partner_bank_data.xml',
        'data/hr_rule_parameter_data.xml',
        'data/payroll_structure_data.xml',
        'data/payroll_benefit_data.xml',
        'data/payroll_overtime_data.xml',
        'data/payroll_tax_exemption_data.xml',
        'data/hr_payroll_warning_data.xml',
        'data/public_holiday_repair_data.xml',
        'views/hr_version_views.xml',
        'views/res_partner_views.xml',
        'views/hr_work_log_views.xml',
        'views/hr_payslip_views.xml',
        'views/gec_payroll_timesheet_waiver_views.xml',
        'views/hr_payroll_unit_rate_views.xml',
        'views/hr_payroll_benefit_views.xml',
        'views/hr_payroll_tax_exemption_views.xml',
        'security/ir.access.csv',
    ],
    'countries': ['ge'],
    'installable': True,
}
