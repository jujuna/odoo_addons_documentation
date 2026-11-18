{
    'name': 'User Access Manager',
    'version': '0.10.0',
    'author': 'GEC',
    'category': 'Tools',
    'description': "Decide what each group of users can see and do: apps and menus, records, fields, buttons, reports, "
                   "actions, and when and from where they sign in. Beta.",
    'summary': 'Access Profiles, Hide Menus, Hide Fields, Hide Buttons, Record Rules, Read Only User, Allowed Journals and Warehouses, Login Hours, IP Restriction',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail', 'rpc', 'gec_user_audit'],
    'data': [
        'security/gec_access_security.xml',
        'data/ir_cron.xml',
        'data/gec_access_version_data.xml',
        'data/gec_access_group_data.xml',
        'wizard/gec_access_wizard_views.xml',
        'views/gec_access_profile_views.xml',
        'views/gec_access_version_views.xml',
        'views/res_users_views.xml',
        'views/menu.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'gec_access_manager/static/src/**/*',
        ],
        'web.assets_tests': [
            'gec_access_manager/static/tests/tours/**/*',
        ],
    },
    'images': ['static/description/banner.gif'],
    'uninstall_hook': 'uninstall_hook',
}
