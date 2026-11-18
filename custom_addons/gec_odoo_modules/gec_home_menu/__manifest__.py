{
    'name': 'Home Menu: Groups and Pinned Apps',
    'summary': 'Home menu with inline search, pinned apps, app groups and an all-apps view',
    'description': """
Extends the enterprise home menu without editing it: a visible search box that filters
apps and menu items inline, a per-user "Pinned apps" card, apps shown in cards by their
module category (Accounting, Sales, Human Resources, ...; the order can be changed by drag and
drop) or as one flat "All apps" grid, and a close button.
Studio's home menu keeps the standard behaviour.
""",
    'version': '20.0.1.0.0',
    'category': 'Productivity',
    'author': 'GEC - Business Growth Services',
    'license': 'LGPL-3',
    'depends': ['mail', 'web_enterprise'],
    'assets': {
        'web.assets_backend': [
            'gec_home_menu/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
