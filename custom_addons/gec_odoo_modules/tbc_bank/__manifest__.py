{
    'name': 'TBC Bank Integration',
    'summary': 'Send transfers and import statements from TBC Bank (BIS) via OAuth2',
    'description': """
Connects Odoo to TBC Bank's Business Integration Services (BIS) API over OAuth2. Imports
account movements as bank statement lines for reconciliation, and sends payments and batch
payments as TBC transfers with optional maker-checker approval. Salaries are paid through
Pay Salaries (gec_payroll_bank), where TBC is one of the banks to choose.

Full documentation: README.md and README_DEV.md in the module directory.
""",
    'version': '20.0.1.7.0',
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
        'security/tbc_groups.xml',
        'data/tbc_payment_method.xml',
        'data/ir_cron_data.xml',
        'views/account_journal_views.xml',
        'views/tbc_connection_views.xml',
        'views/tbc_approval_views.xml',
        'views/tbc_api_log_views.xml',
        'views/tbc_statement_import_wizard_views.xml',
        'views/tbc_statement_views.xml',
        'views/account_payment_views.xml',
        'views/account_batch_payment_views.xml',
        'views/tbc_menus.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'tbc_bank/static/src/scss/*.scss',
        ],
    },
    'installable': True,
    'application': True,
}
