{
    'name': 'Georgia - VAT Declaration (rs.ge)',
    'version': '20.0.1.1.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'Monthly VAT declaration cell tabs proposed from the Georgian VAT report',
    'description': """
Builds the monthly Georgian VAT declaration as the rs.ge portal lays it out: the cell tabs
A I, A II, A III, Part III and III-19.6. Odoo proposes the editable cells from the l10n_ge VAT
report, the accountant adjusts them, and the locked cells are recomputed with the portal formulas.
    """,
    'author': 'GEC',
    'license': 'OEEL-1',
    'depends': ['gec_localization', 'account_asset', 'account_reports', 'rs_einvoice'],
    'data': [
        'data/gec.vat.cell.csv',
        'views/gec_vat_declaration_views.xml',
        'views/gec_vat_rc_declaration_views.xml',
        'views/menus.xml',
        'views/account_asset_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'data/gec_vat_fixed_asset_seed.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'gec_vat_declaration/static/src/components/focus_cell_hook.js',
            'gec_vat_declaration/static/src/components/gec_vat_grid/gec_vat_grid.js',
            'gec_vat_declaration/static/src/components/gec_vat_grid/gec_vat_grid.xml',
            'gec_vat_declaration/static/src/components/gec_vat_grid/gec_vat_grid.scss',
            'gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.js',
            'gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.xml',
            'gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.scss',
        ],
    },
}
