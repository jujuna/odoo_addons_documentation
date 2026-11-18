{
    'name': 'Georgian Translations: Base & Discuss',
    'version': '20.0.2.0.0',
    'category': 'Localization',
    'summary': 'Georgian (ka_GE) translations for the framework and common apps, '
               'plus the loader that serves every gec_i18n_* area module.',
    'description': """
Georgian translations for Framework (base, web, mail/Discuss, portal, auth, html
editor and builder, IAP, SMS), Contacts, Calendar, Products, Units of Measure,
Payments and the AI app.

This module also carries what every other gec_i18n_* module relies on:

* i18n_patch.py: Odoo reads an addon's translations only from that addon's own
  folder. We extend odoo/tools/translate.py:get_po_paths() so that Odoo also
  reads <area module>/i18n_extra/<addon>/ka_GE.po whenever it reads the addon's
  own files: on install, upgrade and language load (labels, menus, views), at
  runtime (Python and JavaScript strings) and for the Apps list. An addon
  installed later is therefore translated at its own install, in any order.
* Upgrading an area module force-applies its files, so improved translations
  reach records that already hold a Georgian value (see hooks.py). The same runs
  from Settings > Translations > Apply Georgian Translations (GEC).
* The Georgian FullCalendar locale: FullCalendar ships none, so calendar
  weekday headers, month titles and week numbers stayed English.

One file per Odoo addon, in the area module of the app the addon's name starts
with (purchase_stock lives in gec_i18n_supply_chain, sale_stock in gec_i18n_sales).
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['web'],
    'data': [
        'data/force_apply_action.xml',
    ],
    'assets': {
        'web.fullcalendar_lib': [
            'gec_i18n_base/static/src/fullcalendar_locale_ka.js',
        ],
        'web.assets_backend': [
            'gec_i18n_base/static/src/georgian_names.js',
            'gec_i18n_base/static/src/georgian_date_names.js',
        ],
    },
    'installable': True,
    'auto_install': True,
}
