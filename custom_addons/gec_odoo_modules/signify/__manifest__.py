{
    'name': 'Signify E-Signature',
    'summary': 'Send documents for e-signature with Signify and bring the signed files back',
    'description': """
Send a PDF, DOC or DOCX attached to any Odoo record to Signify for signing. The status is
followed by a scheduled action, and the signed files and the evidence report are brought back
to Odoo.

Full documentation: README.md and README_DEV.md in the module directory.
""",
    'version': '20.0.1.0.0',
    'category': 'Sales/Sign',
    'author': 'GEC-Business Growth Services',
    'license': 'LGPL-3',
    'depends': [
        'base_setup',
        'mail',
        'phone_validation',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/signify_security.xml',
        'data/ir_cron_data.xml',
        'views/signify_document_views.xml',
        'views/res_config_settings_views.xml',
        'views/signify_connection_views.xml',
        'views/signify_templates.xml',
        'views/signify_menus.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'signify/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'signify/static/tests/**/*',
        ],
    },
    'installable': True,
    'application': True,
}
