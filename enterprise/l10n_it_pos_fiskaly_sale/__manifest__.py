# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': "Italy - Point of Sale Sign IT - Sale",
    'summary': 'Down payments and settled sale orders with fiskaly SIGN IT',
    'description': """
Bridge between the Italian Point of Sale fiscalization (fiskaly SIGN IT) and the sale orders settled in the Point of Sale.
Down payments are declared as sales, deducted from the settled order as discounts, and settled lines keep the description of the sale order line.
""",
    'category': 'Accounting/Localizations/Point of Sale',
    'depends': ['l10n_it_pos_fiskaly', 'pos_sale'],
    'auto_install': True,
    'assets': {
        'point_of_sale._assets_pos': [
            'l10n_it_pos_fiskaly_sale/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'l10n_it_pos_fiskaly_sale/static/tests/unit/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
