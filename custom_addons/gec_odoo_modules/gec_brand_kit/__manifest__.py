{
    'name': 'Brand Kit: Backend Branding from a ZIP',
    'summary': 'Import a brand kit ZIP to restyle the whole backend: colors, font, logo, favicon, home background',
    'description': """
Upload one ZIP (brand.json + images + optional font files) under Settings > Brand Kit and apply
it: the backend colors are compiled from the kit through Odoo's SCSS variables (light and dark
mode), the logo and report colors are written to every company, and the favicon, browser title,
web-app manifest and home menu background follow the kit. Reset restores Odoo's default look.
One brand per database.
""",
    'version': '20.0.1.0.0',
    'category': 'Productivity',
    'author': 'GEC - Business Growth Services',
    'license': 'LGPL-3',
    'depends': ['mail', 'web_enterprise'],
    'data': [
        'data/gec_brand_kit_data.xml',
        'views/gec_brand_kit_views.xml',
        'views/gec_brand_kit_import_views.xml',
        'views/webclient_templates.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web._assets_primary_variables': [
            ('before', 'web_enterprise/static/src/scss/primary_variables.scss',
             'gec_brand_kit/static/src/scss/brand_variables.scss'),
        ],
        'web.dark_mode_variables': [
            ('before', 'gec_brand_kit/static/src/scss/brand_variables.scss',
             'gec_brand_kit/static/src/scss/brand_variables.dark.scss'),
        ],
        'web.report_assets_common': [
            'gec_brand_kit/static/src/scss/report_fonts.scss',
        ],
        'web.assets_backend': [
            'gec_brand_kit/static/src/js/*.js',
            'gec_brand_kit/static/src/scss/home_menu_background.scss',
            'gec_brand_kit/static/src/scss/brand_theme.scss',
            'gec_brand_kit/static/src/scss/georgian_fonts.scss',
            'gec_brand_kit/static/src/scss/brand_preview.scss',
            'gec_brand_kit/static/src/xml/*.xml',
        ],
    },
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
