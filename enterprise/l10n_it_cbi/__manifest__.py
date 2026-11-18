{
    'name': 'Italy - CBI Credit Transfer',
    'author': 'Odoo S.A.',
    'category': 'Accounting/Localizations',
    'description': """
        Generates CBI XML files for SEPA Credit Transfers in Italy.
    """,
    'depends': [
        'l10n_it',
        'account_batch_payment',
    ],
    'data': [
        'data/account_payment_method.xml',
        'data/cbi_payment_request.xml',
        'views/account_batch_payment_views.xml',
    ],
    'auto_install': True,
    'license': 'OEEL-1',
}
