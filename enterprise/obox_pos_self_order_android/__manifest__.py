{
    'name': 'PoS Self Order & Obox Android',
    'category': 'Hidden',
    'depends': ['obox_pos_mobile', 'obox_pos_self_order', 'obox_point_of_sale_android', 'pos_self_order_mobile'],
    'description': "Obox Kiosk support in the Odoo Android app",
    'auto_install': True,
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'pos_self_order.assets': [
            'obox_pos_mobile/static/src/app/utils/device_address.js',
            'obox_pos_mobile/static/src/app/plugins/pos_ticket_printer_plugin.js',
            'obox_pos_self_order_android/static/src/app/**/*',
        ],
        'web.assets_backend': [
            'obox_pos_self_order_android/static/src/backend/**/*',
        ],
        'web.assets_unit_tests': [
            'obox_pos_self_order_android/static/tests/unit/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
