{
    'name': 'RS Customs Declarations',
    'summary': "Fetch and archive Georgian customs (Asycuda) declarations from rs.ge for the authenticated company",
    'version': '20.0.1.0.0',
    'author': 'GEC Business',
    'license': 'AGPL-3',
    'category': 'Accounting/Localization',
    'depends': [
        'base',
        'rs_base_methods',
    ],
    'data': [
        'views/customs_declaration_line_views.xml',
        'views/fetch_customs_wizard_views.xml',
        'views/menu.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
    'application': True,
}
