{
    'name': 'Declarations',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'One app for the rs.ge declarations: VAT, income tax, profit tax and property tax',
    'description': """
Gathers the rs.ge declarations in one app. The overview shows a card per installed declaration module (VAT,
Income Tax Form 30, Profit Tax II-086, Property Tax) with its latest period and drafts. The declaration menus
and their configuration menus move from Accounting into this app; the declaration modules themselves are not
changed. Uninstalling this module puts the menus back in Accounting.

Full documentation: README.md and README_DEV.md in the module directory.
    """,
    'author': 'GEC',
    'license': 'OEEL-1',
    'depends': ['account'],
    'data': [
        'security/ir.access.csv',
        'data/gec_declaration_card_data.xml',
        'views/gec_declaration_card_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': True,
}
