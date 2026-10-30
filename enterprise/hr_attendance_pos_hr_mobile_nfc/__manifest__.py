# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Attendances NFC Badges in Mobile',
    'category': 'Human Resources/Attendances',
    'summary': 'NFC badge enrolment in Mobile',
    'depends': ['hr_attendance', 'pos_hr_mobile_nfc'],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'data': [
        'views/hr_employee_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hr_attendance_pos_hr_mobile_nfc/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'hr_attendance_pos_hr_mobile_nfc/static/tests/**/*.test.js',
        ],
    },
}
