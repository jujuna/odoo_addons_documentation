{
    'name': 'Georgian Translations: Industries',
    'version': '20.0.2.1.0',
    'category': 'Localization',
    'summary': 'Georgian (ka_GE) translations for the Odoo Industry packages.',
    'description': """
Georgian translations for the Industry packages installed from Apps > Industries:
Hotel (with the Booking engine it builds on), Property Management (with Property
Listing and Property Assets & Distribution), Spa Resort, Hair Salon, Cleaning
Services, Fitness Center, Sports Facilities, and the shared Industry base data.
These packages are imported as data modules and are not on the addons path.

One file per Odoo addon: i18n_extra/<addon>/ka_GE.po. gec_i18n_base applies these
files to records that already exist whenever this module is installed or upgraded,
and from Settings > Translations > Apply Georgian Translations (GEC). Because
Odoo reads an imported package's terms only from its own zip, this module also
re-applies its files every time an industry package is installed, upgraded or
re-imported, and adds its JavaScript strings to the ones the web client receives.

It also keeps what an import copies out of reach of translation files: the
"Start here!" Knowledge article is re-rendered in Georgian while it still has the
template's blocks (an article with blocks added or removed by hand is kept; words
changed inside the template's blocks are replaced on the next upgrade, the old
text staying in the article's version history), and an import started from Apps > Industries no longer links
its demo bookings to the remote module (such bookings could not be opened; links
left by earlier imports are cleared on install, upgrade and import).
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['gec_i18n_base', 'base_import_module'],
    'data': [],
    'installable': True,
    'auto_install': True,
}
