{
    'name': 'Finland - Accounting EDI',
    'description': "Accounting EDI for Finland",
    'category': 'Accounting/Localizations/EDI',
    'depends': ['account_edi', 'l10n_fi'],
    'data': [
        'data/account_edi_format_data.xml',
        'data/finvoice_export.xml',
        'views/account_move_views.xml',
    ],
    'auto_install': ['l10n_fi'],
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
