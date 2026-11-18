# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': "Italy - Point of Sale Sign IT",
    'summary': 'Software fiscalization for the Italian Point of Sale',
    'description': """
Software fiscalization for the Italian Point of Sale (fiskaly SIGN IT).
Records every commercial document with fiskaly, which transmits it to the Agenzia delle Entrate.
""",
    'category': 'Accounting/Localizations/Point of Sale',
    'depends': ['l10n_it', 'point_of_sale', 'pos_enterprise', 'pos_discount'],
    'data': [
        'views/account_tax_views.xml',
        'views/res_company_views.xml',
        'views/res_config_settings_views.xml',
        'views/pos_order_views.xml',
        'views/point_of_sale_dashboard.xml',
        'receipt/pos_order_receipt.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'l10n_it_pos_fiskaly/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'l10n_it_pos_fiskaly/static/tests/unit/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
