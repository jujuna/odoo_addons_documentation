{
    'name': 'Georgian Translations: Services',
    'version': '20.0.2.0.0',
    'category': 'Localization',
    'summary': 'Georgian (ka_GE) translations for the Services apps and their bridge modules.',
    'description': """
Georgian translations for Project, Timesheets, Helpdesk, Field Service,
Appointments, Frontdesk and Rooms, including every bridge module whose name
starts with one of these apps.

One file per Odoo addon: i18n_extra/<addon>/ka_GE.po. gec_i18n_base makes Odoo
read it whenever it loads that addon's translations, so the addon does not have
to be installed before this module. Upgrading this module re-applies its files
to records that already hold a Georgian value.
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['gec_i18n_base'],
    'data': [],
    'installable': True,
    'auto_install': True,
}
