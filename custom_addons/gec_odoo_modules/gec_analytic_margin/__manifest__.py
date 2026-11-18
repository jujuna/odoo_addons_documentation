{
    'name': 'Analytic Margin & Cost Allocation',
    'version': '20.0.1.22.0',
    'category': 'Accounting/Accounting',
    'author': 'GEC - Business Growth Services',
    'summary': 'Activity-Based Costing, a P&L per project, product and customer, '
               'and a benchmark dashboard on top of analytic accounting.',
    'description': """
Margin analysis and cost allocation on top of Odoo's analytic accounting.

Configurable P&L model: components, classification rules and a margin ladder are
records, not code. Each margin level becomes a real column on the report. The
P&L reads by nature or by function (Cost of Sales, R&D, Sales & Marketing, G&A),
per company.

Cost allocation with two engines: proportional drivers (revenue share,
headcount, direct cost, equal, manual) and full two-stage Activity-Based
Costing with measured driver quantities, practical capacity, idle capacity and
rate variance.

Reports: Margin Statement down to the invoice, Margin Analysis, Activity Rates,
Planned vs Actual, and a dashboard measured against a software-vendor
benchmark: margins, recurring and product revenue, retention, customer
concentration, revenue per FTE, utilization, project margin at completion,
backlog, unbilled work and cash margin. Every card opens the proof behind it.

Allocation writes analytic lines only. Journal entries are never modified and
every run is reversible.
""",
    'depends': [
        'account',
        'account_budget',
        # A Many2one comodel must exist when the registry is built.
        'project',
        'account_reports',
        'hr_timesheet',
    ],
    'data': [
        'security/gec_abc_groups.xml',
        'data/gec_margin_component_data.xml',
        'data/gec_margin_classification_rule_data.xml',
        'data/gec_margin_level_data.xml',
        'data/gec_revenue_stream_data.xml',
        'data/gec_allocation_cron.xml',
        'views/gec_margin_component_views.xml',
        'views/gec_margin_level_views.xml',
        'views/gec_revenue_stream_views.xml',
        'views/account_account_views.xml',
        'views/account_analytic_account_views.xml',
        'views/project_project_views.xml',
        'views/project_tags_views.xml',
        'views/hr_department_views.xml',
        'views/account_analytic_plan_views.xml',
        'views/account_analytic_distribution_model_views.xml',
        'views/budget_views.xml',
        'views/gec_activity_views.xml',
        'views/gec_allocation_rule_views.xml',
        'views/gec_allocation_run_views.xml',
        'views/gec_activity_rate_views.xml',
        'views/gec_activity_plan_views.xml',
        'wizard/gec_allocation_preview_views.xml',
        'wizard/gec_abc_health_views.xml',
        'views/gec_margin_report_views.xml',
        'views/res_config_settings_views.xml',
        'views/menuitems.xml',
        'views/gec_margin_dashboard_views.xml',
        'views/gec_forecast_snapshot_views.xml',
        # Last: the statement's menu hangs off the one menuitems.xml declares.
        'data/gec_margin_statement_report.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'gec_analytic_margin/static/src/js/margin_statement_filters.js',
            'gec_analytic_margin/static/src/xml/filters.xml',
            'gec_analytic_margin/static/src/xml/warnings.xml',
            'gec_analytic_margin/static/src/dashboard/dashboard.js',
            'gec_analytic_margin/static/src/dashboard/dashboard.xml',
            'gec_analytic_margin/static/src/dashboard/dashboard.scss',
        ],
        'web.assets_tests': [
            'gec_analytic_margin/static/tests/tours/margin_statement_tour.js',
            'gec_analytic_margin/static/tests/tours/dashboard_tour.js',
        ],
    },
    # OPL-1: the statement is built on account_reports (Enterprise).
    'license': 'OPL-1',
    'installable': True,
    'post_init_hook': 'post_init_hook',
}
