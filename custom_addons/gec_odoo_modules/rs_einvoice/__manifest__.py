{
    'name': 'RS E-Invoice (SOAP)',
    'summary': 'Send invoices/credit notes to Revenue Service via SOAP API',
    'description': 'Georgian Revenue Service (rs.ge) e-invoice integration. '
                    'Files customer invoices on rs.ge, sends them to the buyer, '
                    'mirrors what the buyer does back onto the Odoo invoice, and '
                    'turns supplier invoices from rs.ge into vendor bills that are '
                    'accepted or rejected from Odoo. Logins are stored per user and '
                    'per company. Full documentation: README.md and README_DEV.md '
                    'in the module directory.',
    'version': '20.0.1.1.0',
    'author': 'GEC Business',
    'license': 'AGPL-3',
    'depends': [
        'accountant',
        'account_edi_ubl_cii',
    ],
    'external_dependencies': {
        'python': ['zeep'],
    },
    'data': [
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
        'views/rs_correction_wizard_views.xml',
        'views/rs_buyer_inbox_wizard_views.xml',
        'views/rs_replace_preview_wizard_views.xml',
        'views/rs_einvoice_view_wizard_views.xml',
        'views/account_move_views.xml',
        'views/account_move_view_data_views.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'rs_einvoice/static/src/scss/rs_einvoice.scss',
            'rs_einvoice/static/src/scss/rs_einvoice_snapshot.scss',
            'rs_einvoice/static/src/js/rse_lines_field.js',
            'rs_einvoice/static/src/xml/rse_lines_field.xml',
        ],
    },
    'installable': True,
    'application': True
}
