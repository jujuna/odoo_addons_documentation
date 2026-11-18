{
    'name': 'Georgia - Property Tax Declaration (rs.ge Form 15)',
    'version': '20.0.1.4.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'Annual enterprise property tax declaration (annex V-01) for eservices.rs.ge',
    'description': """
Builds parts III (property other than land) and IV (land) of the annual enterprise property tax
declaration, annex V-01, from fixed assets and a land plot register, validates them against the
rs.ge classifiers and exports the SpreadsheetML files the portal imports.
    """,
    'author': 'GEC',
    'license': 'OEEL-1',
    'depends': ['account_asset'],
    'data': [
        'security/ir.access.csv',
        'data/rs.form15.property.type.csv',
        'data/rs.form15.territory.csv',
        'data/rs.form15.exemption.basis.csv',
        'data/rs.form15.land.territory.csv',
        'data/rs.form15.land.type.csv',
        'data/rs.form15.land.rate.csv',
        'data/rs.form15.revaluation.coefficient.csv',
        'data/rs.form15.year.csv',
        'views/rs_form15_classifier_views.xml',
        'views/account_asset_views.xml',
        'views/rs_form15_land_plot_views.xml',
        'views/rs_form15_declaration_views.xml',
        'wizard/rs_form15_explain_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gec_property_tax_report/static/src/components/rs_form15_grid/rs_form15_grid.js',
            'gec_property_tax_report/static/src/components/rs_form15_grid/rs_form15_grid.xml',
            'gec_property_tax_report/static/src/components/rs_form15_grid/rs_form15_grid.scss',
            'gec_property_tax_report/static/src/components/rs_form15_part3_grid/rs_form15_part3_grid.js',
            'gec_property_tax_report/static/src/components/rs_form15_part4_grid/rs_form15_part4_grid.js',
            'gec_property_tax_report/static/src/components/rs_form15_land_territory_field/rs_form15_land_territory_field.js',
            'gec_property_tax_report/static/src/components/rs_form15_land_territory_field/rs_form15_land_territory_field.xml',
            'gec_property_tax_report/static/src/components/rs_form15_rate_field/rs_form15_rate_field.js',
            'gec_property_tax_report/static/src/components/rs_form15_rate_field/rs_form15_rate_field.xml',
            'gec_property_tax_report/static/src/components/rs_form15_land_plot_list/rs_form15_land_plot_list.js',
        ],
    },
    'installable': True,
    'application': False,
}
