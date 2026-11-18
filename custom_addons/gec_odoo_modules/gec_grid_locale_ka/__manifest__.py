{
    'name': 'Georgian Grid Locale (Timesheets)',
    'version': '20.0.1.0.5',
    'category': 'Localization',
    'summary': 'Georgian weekday and month names in grid column headers '
               '(Timesheets and every other grid view).',
    'description': """
Grid views build their own column headers. web_grid/static/src/views/grid_model.js
(_getDateColumnTitle) calls new Intl.DateTimeFormat(locale, ...).formatToParts()
directly, so on a Chromium built with "small-icu" — where Intl resolves ka-GE to
en-US — the Timesheets grid shows Mon, Tue, Wed however complete the Georgian
translations are. Check with:

    new Intl.DateTimeFormat("ka-GE").resolvedOptions().locale   // -> "en-US"

This is the same root cause the calendar had, but a separate call site, so the
calendar fix does not reach it. We substitute the Georgian names for that one
method, and only when the browser genuinely cannot resolve ka-GE.

The patch must live in web.assets_backend_lazy: that is the bundle web_grid
itself ships in, so @web_grid/... is not defined any earlier.
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['web_grid', 'gec_i18n_base'],
    'assets': {
        'web.assets_backend_lazy': [
            'gec_grid_locale_ka/static/src/georgian_grid_headers.js',
        ],
    },
    'data': [],
    'installable': True,
    'auto_install': True,
}
