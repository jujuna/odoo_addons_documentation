{
    'name': 'Signify - Documents',
    'summary': 'Signed Signify files in Documents, send a document for signature from Documents',
    'version': '20.0.1.0.0',
    'category': 'Sales/Sign',
    'author': 'GEC-Business Growth Services',
    'license': 'LGPL-3',
    'depends': ['signify', 'documents'],
    'data': [
        'data/ir_actions_server_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': '_signify_documents_post_init',
    'auto_install': True,
    'installable': True,
    'application': False,
}
