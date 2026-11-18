{
    'name': 'GoSMS',
    'summary': 'Send SMS, receive replies and confirm actions with one-time codes through GoSMS.ge',
    'description': """
Connects Odoo to GoSMS.ge: Odoo's own SMS (chatter, SMS Marketing) go out through it, every message is logged in a GoSMS list,
delivery reports and replies come back by webhook, and any module can ask for a one-time SMS code before a button runs.
""",
    'version': '20.0.1.0.0',
    'category': 'Marketing/Email Marketing',
    'author': 'GEC-Business Growth Services',
    'license': 'LGPL-3',
    'depends': [
        'base_setup',
        'sms',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/gosms_message_views.xml',
        'views/gosms_send_wizard_views.xml',
        'views/gosms_confirm_wizard_views.xml',
        'views/gosms_menus.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
    'application': True,
}
