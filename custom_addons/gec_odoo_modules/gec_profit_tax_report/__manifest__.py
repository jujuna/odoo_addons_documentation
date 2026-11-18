{
    'name': 'Georgia - Profit Tax Declaration (rs.ge Form II-086)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'Monthly profit tax declaration built from posted accounting',
    'description': """
Builds the monthly profit tax declaration (rs.ge form II-086) from posted journal items: part I, part III
lines 16-29 in both columns, part IV for gambling organisers and the annexes 1, 1.1-1.7, 2, 3 and 4, following
the rs.ge filling instruction (MoF Order 996, article 40.1). It classifies contacts and countries, keeps a
register of taxed loans and advances for the money-back lines, books the profit tax on confirm, handles
corrected declarations and exports an XLSX workbook.

Full documentation: README.md and README_DEV.md in the module directory.
    """,
    'author': 'GEC',
    'license': 'OEEL-1',
    'depends': ['gec_localization'],
    'data': [
        'data/rs.cit.cell.csv',
        'data/rs_cit_data.xml',
        'views/rs_cit_cell_views.xml',
        'views/rs_cit_declaration_views.xml',
        'views/account_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'gec_profit_tax_report/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
