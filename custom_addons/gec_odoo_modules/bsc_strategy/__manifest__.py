{
    'name': 'Balanced Scorecard',
    'version': '20.0.1.5.1',
    'category': 'Services/Strategy',
    'author': 'GEC - Business Growth Services',
    'summary': 'Manage organizational strategy with the Balanced Scorecard: '
               'perspectives, objectives, strategy map, KPIs, initiatives, '
               'reviews, and KPI figures filled automatically from Odoo data',
    'description': """
Balanced Scorecard
==================

A strategic management system, not a KPI dashboard.

* Perspectives (financial, customer, internal processes, learning & growth) - fully configurable
* Strategic objectives with weights and owners
* Strategy map: cause-effect links between objectives, recorded as explicit hypotheses
* KPIs with manual periodic measurement (target / actual / baseline, RAG status)
* Qualitative objectives that carry no KPI
* Strategic initiatives portfolio with approval gates and budget
* Periodic strategy reviews that produce decisions and corrective initiatives
* Execution: an approved initiative becomes an Odoo project or task, and its
  progress can follow the closed tasks instead of being typed in
* Automation: KPI figures pulled from vetted Odoo queries, proposed targets, and
  a strategy review opened automatically when a period closes - all guarded so
  that an empty result set is never published as a zero and a figure that jumps
  too far is held back for a human to confirm

* A manager dashboard per scorecard and period: index, completion, KPI status,
  trend over the cycle, what needs attention, the review and the portfolio
* A setup checklist on every scorecard, and inline tables for objectives, KPIs
  and cause-effect links
* One-click demo data (load and remove) and a built-in user guide, both in the
  language of the user
* A visual strategy map: perspectives as layers, objectives as cards coloured by
  status, cause-effect links as arrows - dashed where the hypothesis has never
  been checked against data - with an inspector panel beside it

* KPIs filled from Odoo data in a few clicks: a catalogue of ready-made
  measures (sales, invoicing, CRM, purchase, inventory, manufacturing, Point of
  Sale, project) offered only for the installed apps, with a live preview

Project execution is built in: an approved initiative becomes a project or a
single task, and its progress follows the tasks as they move. bsc_demo installs a worked example.
""",
    'website': 'https://gecbusiness.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web', 'project'],
    'data': [
        'security/bsc_groups.xml',
        # security/odoo19/ holds the legacy ir.model.access / ir.rule files; not loaded.
        'security/ir.access.csv',
        'data/ir_module.xml',
        'data/bsc_perspective_data.xml',
        'data/bsc_initiative_stage_data.xml',
        'data/bsc_task_stage_data.xml',
        'report/bsc_board_report.xml',
        'views/bsc_perspective_views.xml',
        'views/bsc_scorecard_views.xml',
        'views/bsc_objective_views.xml',
        'views/bsc_kpi_source_views.xml',
        'views/bsc_kpi_views.xml',
        'views/bsc_kpi_automation_views.xml',
        'views/bsc_kpi_connect_views.xml',
        'views/bsc_period_views.xml',
        'views/bsc_period_automation_views.xml',
        'views/bsc_measurement_views.xml',
        'views/bsc_measurement_automation_views.xml',
        'views/bsc_initiative_views.xml',
        'views/bsc_initiative_project_views.xml',
        'views/project_views.xml',
        'views/bsc_review_views.xml',
        'data/bsc_cron.xml',
        'data/bsc_automation_cron.xml',
        'data/bsc_project_cron.xml',
        'data/bsc_freeze_closed.xml',
        # Menus last: they reference the actions defined above.
        'views/bsc_menus.xml',
        'views/bsc_kpi_source_menus.xml',
        'views/bsc_strategy_map_views.xml',
        'views/bsc_objective_link_views.xml',
        'views/bsc_extra_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bsc_strategy/static/src/strategy_map.variables.scss',
            'bsc_strategy/static/src/strategy_map.scss',
            'bsc_strategy/static/src/strategy_map.js',
            'bsc_strategy/static/src/strategy_map.xml',
            'bsc_strategy/static/src/dashboard/dashboard.scss',
            'bsc_strategy/static/src/dashboard/dashboard.js',
            'bsc_strategy/static/src/dashboard/dashboard.xml',
            'bsc_strategy/static/src/guide/guide_action.js',
            'bsc_strategy/static/src/guide/guide_action.xml',
        ],
        # The target sits in the main backend bundle; both dark bundles include it.
        'web.assets_web_dark': [
            ('before',
             'bsc_strategy/static/src/strategy_map.variables.scss',
             'bsc_strategy/static/src/strategy_map.variables.dark.scss'),
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
