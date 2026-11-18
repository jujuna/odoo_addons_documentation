{
    'name': "Chile - E-Invoicing Delivery Guide (Res. 154)",
    'countries': ['cl'],
    'category': 'Accounting/Localizations/EDI',
    'sequence': 12,
    'description': """
Transport data required on the electronic delivery guide by SII Res. Ex. N° 154 de 2025.
    """,
    'depends': ['l10n_cl_edi_stock'],
    'data': [
        'template/dte_template.xml',
        'views/l10n_cl_edi_vehicle_views.xml',
        'views/stock_picking_views.xml',
        'views/report_delivery_guide.xml',
        'views/menuitems.xml',
        'security/ir.access.csv',
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
