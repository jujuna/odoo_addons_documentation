{
    'name': 'POS Wolt Drive',
    'category': 'Sales/Point of Sale',
    'summary': "Book Wolt couriers for your own Point of Sale delivery orders",
    'description': """
Wolt Drive for the Point of Sale:
- price and book a Wolt courier for a paid POS order with a customer address
- follow the courier status and tracking link in the POS and on the order
- cancel the courier before the pickup starts
    """,
    'version': '1.0',
    'depends': ['point_of_sale'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/pos_order_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_wolt_drive/static/src/app/**/*',
        ],
        'web.assets_tests': [
            'pos_wolt_drive/static/tests/tours/**/*',
        ],
    },
    'author': 'Gecbusiness',
    'license': 'OPL-1',
}
