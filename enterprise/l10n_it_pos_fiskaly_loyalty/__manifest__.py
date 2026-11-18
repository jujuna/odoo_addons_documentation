# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': "Italy - Point of Sale Sign IT - Loyalty",
    'summary': 'Gift cards, eWallets and loyalty rewards with fiskaly SIGN IT',
    'description': """
Bridge between the Italian Point of Sale fiscalization (fiskaly SIGN IT) and the Point of Sale loyalty programs.
Gift cards and eWallets are declared as multi-purpose vouchers and loyalty rewards as discounts or gifts.
""",
    'category': 'Accounting/Localizations/Point of Sale',
    'depends': ['l10n_it_pos_fiskaly', 'pos_loyalty'],
    'auto_install': True,
    'assets': {
        'point_of_sale._assets_pos': [
            'l10n_it_pos_fiskaly_loyalty/static/src/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
