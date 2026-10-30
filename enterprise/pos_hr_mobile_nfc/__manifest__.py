# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'POS NFC Badges in Mobile',
    'category': 'Hidden',
    'summary': 'Identify employees on the POS with their NFC badge',
    'depends': ['pos_hr_mobile', 'pos_mobile'],
    'data': [
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_hr_mobile_nfc/static/src/app/**/*',
        ],
        'web.assets_backend': [
            'pos_mobile/static/src/app/hooks/nfc_reader.js',
            'pos_hr_mobile_nfc/static/src/views/**/*',
        ],
        'web.assets_unit_tests': [
            'pos_hr_mobile_nfc/static/tests/unit/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
