{
    'name': 'RS Employee Registry',
    'summary': "Sync employees with Revenue Service's Employee Registry (eapi.rs.ge)",
    'description': """
Syncs employees with the Georgian Revenue Service Employee Registry (eapi.rs.ge).

Each employee's Sync Mode (Automatic, Manual or Disabled) decides who changes their RS
status. RS credentials are stored per user through the RS base module.

Setup: README.md in the module folder.
""",
    'version': '20.0.1.1.0',
    'author': 'GEC Business',
    'license': 'AGPL-3',
    'category': 'Human Resources',
    'depends': [
        'hr',
    ],
    'data': [
        'data/ir_cron.xml',
        'views/res_country_views.xml',
        'views/res_config_settings_views.xml',
        'views/employee_registry_rs_log_views.xml',
        'views/employee_registry_rs_browser_views.xml',
        'views/hr_employee_views.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
    'application': False,
}
