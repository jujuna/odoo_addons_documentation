{
    'name': 'Bank Channels',
    'summary': 'Shared base of the bank integrations: durable sends, audit logs, approvers, channel hooks',
    'description': """
Common base of the Georgian bank integrations (Basis Bank, TBC Bank, Bank of Georgia).

Holds what every bank client needs and none of them should write twice: the row writes
that let a send survive a crash, the audit log written on its own cursor, secret
redaction, the approver and connection mixins, and the channel hooks on
account.payment.method.line that a consumer such as Pay Salaries (gec_payroll_bank)
calls. Installing a bank module brings this module and no payroll.

Full documentation: README.md and README_DEV.md in the module directory.
""",
    'version': '20.0.1.2.0',
    'category': 'Accounting/Payment',
    'author': 'GEC - Business Growth Services',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'account_batch_payment',
        'gec_localization',
    ],
    'data': [
        'views/account_payment_views.xml',
        'views/account_journal_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gec_bank/static/src/js/*.js',
            'gec_bank/static/src/scss/*.scss',
            ('remove', 'gec_bank/static/src/scss/*.dark.scss'),
        ],
        'web.assets_web_dark': [
            'gec_bank/static/src/scss/*.dark.scss',
        ],
    },
    'installable': True,
    'application': False,
}
