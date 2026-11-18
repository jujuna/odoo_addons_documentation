{
    'name': 'Georgia - Income Tax Declaration (rs.ge Form 30)',
    'version': '20.0.1.15.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'Monthly withholding declaration annex export for eservices.rs.ge',
    'description': """
Builds the monthly withholding declaration (rs.ge Form 30): annex A from paid payslips and
payment withholding lines, annex E for recipients who pay their own tax, annex D for company
cars used privately, and the main part (cells 16-69). Validates every row against the rs.ge
classifiers and exports one SpreadsheetML file per annex for the portal import.
Full documentation: README.md and README_DEV.md in the module directory.
    """,
    'author': 'GEC',
    'license': 'OEEL-1',
    'depends': ['geo_payroll', 'gec_localization', 'l10n_account_withholding_tax', 'hr_fleet'],
    'data': [
        'data/rs.form30.category.csv',
        'data/rs.form30.income.type.csv',
        'data/rs.form30.rate.rule.csv',
        'data/rs.form30.car.engine.csv',
        'data/rs.form30.service.type.csv',
        'data/rs.form30.summary.cell.csv',
        'data/rs_form30_data.xml',
        'views/rs_form30_classifier_views.xml',
        'views/rs_form30_account_rule_views.xml',
        'views/rs_form30_declaration_views.xml',
        'views/res_partner_views.xml',
        'views/account_tax_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/hr_work_location_views.xml',
        'wizard/rs_form30_tax_change_views.xml',
        'wizard/rs_form30_explain_views.xml',
        'wizard/rs_form30_set_withholding_tax_views.xml',
        'views/menus.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'gec_income_tax_report/static/src/components/rs_form30_grid/rs_form30_grid.js',
            'gec_income_tax_report/static/src/components/rs_form30_grid/rs_form30_grid.xml',
            'gec_income_tax_report/static/src/components/rs_form30_grid/rs_form30_grid.scss',
            'gec_income_tax_report/static/src/components/rs_form30_car_grid/rs_form30_car_grid.js',
            'gec_income_tax_report/static/src/components/rs_form30_car_grid/rs_form30_car_grid.xml',
            'gec_income_tax_report/static/src/components/rs_form30_service_grid/rs_form30_service_grid.js',
            'gec_income_tax_report/static/src/components/rs_form30_service_grid/rs_form30_service_grid.xml',
            'gec_income_tax_report/static/src/components/rs_form30_summary_grid/rs_form30_summary_grid.js',
            'gec_income_tax_report/static/src/components/rs_form30_summary_grid/rs_form30_summary_grid.xml',
        ],
    },
    'installable': True,
    'application': False,
}
