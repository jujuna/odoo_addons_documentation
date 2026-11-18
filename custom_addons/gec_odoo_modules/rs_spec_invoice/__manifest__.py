{
    'name': 'RS Petroleum Invoice (ნსაფ)',
    'summary': "Issue rs.ge petroleum invoices from customer invoices with fuel lines",
    'description': "Files the rs.ge petroleum invoice (special tax invoice for oil products) from the customer invoice "
                   "instead of an ordinary e-invoice: petroleum products synced from rs.ge, sites, transport and driver, "
                   "save, send and "
                   "status from rs.ge. Full documentation: README.md and README_DEV.md in the module directory.",
    'version': '20.0.1.0.0',
    'author': 'GEC Business',
    'license': 'AGPL-3',
    'category': 'Accounting/Localizations',
    'depends': ['rs_base_methods', 'fleet', 'purchase', 'sale', 'stock', 'gec_vat_declaration'],
    'external_dependencies': {'python': ['zeep']},
    'data': [
        'views/rs_spec_site_views.xml',
        'views/account_move_views.xml',
        'views/account_move_reversal_views.xml',
        'views/product_template_views.xml',
        'views/second_unit_views.xml',
        'views/rs_buyer_inbox_wizard_views.xml',
        'views/rs_spec_menus.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
    'application': False,
}
