{
    'name': 'BOG Bank Integration',
    'summary': 'Send transfers and import statements from BOG Bank (BIS) via OAuth2',
    'description': """
Sends payment orders to Bank of Georgia Business Online and imports account statements for
reconciliation, using OAuth2 client credentials. Salaries are paid through Pay Salaries
(gec_payroll_bank), where Bank of Georgia is one of the banks to choose.

Setup, and the API differences from the TBC and Basis Bank modules: README.md in the module
folder.
""",
    'version': '20.0.1.1.0',
    'category': 'Accounting/Payment',
    'author': 'GEC-Business Growth Services',
    'license': 'LGPL-3',
    'depends': [
        'account_accountant',
        'account_bank_statement_import',
        'account_batch_payment',
        'gec_bank',
        'mail',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/bog_groups.xml',
        'data/bog_payment_method.xml',
        'data/ir_cron_data.xml',
        'views/account_journal_views.xml',
        'views/bog_connection_views.xml',
        'views/bog_approval_views.xml',
        'views/bog_api_log_views.xml',
        'views/bog_statement_import_wizard_views.xml',
        'views/bog_statement_views.xml',
        'views/account_payment_views.xml',
        'views/account_batch_payment_views.xml',
        'views/bog_menus.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'bog_bank/static/src/scss/*.scss',
        ],
    },
    'installable': True,
    'application': True,
}
