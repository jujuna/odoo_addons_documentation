# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Laos - Accounting Reports',
    'summary': 'Financial statements and VAT return type for Laos',
    'category': 'Accounting/Localizations/Reporting',
    'description': """
Accounting reports for Laos: statement of financial position and statement of performance
(by function), as set by the Ministry of Finance Decision No. 0369 of 4 February 2020, and the
monthly VAT return (form 01/ອມພ).
    """,
    'depends': [
        'l10n_la',
        'account_reports',
    ],
    'data': [
        'data/account_return_data.xml',
        'data/balance_sheet.xml',
        'data/profit_and_loss.xml',
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
