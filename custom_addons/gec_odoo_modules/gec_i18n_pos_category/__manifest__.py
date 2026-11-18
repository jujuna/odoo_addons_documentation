{
    'name': 'Georgian Translations: POS Category Names',
    'version': '20.0.1.0.0',
    'category': 'Localization',
    'summary': "Show Point of Sale category paths in the user's language.",
    'description': """
Point of Sale category lists, tags and pickers show the category's full path
("Bar / Drinks"). Odoo stores that path once, in the language it was computed in,
which is English after an industry import, while the category names themselves
are translated. This module builds the shown path from the translated names, as
website_sale does for eCommerce categories. The name search matches the translated
name and the translated path, so a file exported in Georgian imports back.
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'gec_i18n_base'],
    'data': [],
    'installable': True,
    'auto_install': True,
}
