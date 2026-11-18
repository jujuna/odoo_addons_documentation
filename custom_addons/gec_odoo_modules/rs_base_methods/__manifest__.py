{
    'name': 'RS Base Methods',
    'summary': "Shared base for Revenue Service integrations — per-user credentials, auth helpers, and invoice-from-waybill wizard",
    'version': '20.0.1.1.0',
    'author': 'GEC Business',
    'license': 'AGPL-3',
    'category': 'Technical',
    'depends': [
        'base',
        'employee_registry_rs',
        'rs_einvoice',
        'rs_waybill',
        'sale_stock',
    ],
    'external_dependencies': {
        'python': ['zeep'],
    },
    'data': [
        'views/rs_auth_pin_wizard_views.xml',
        'views/res_users_views.xml',
        'views/account_move_views.xml',
        'views/sale_order_views.xml',
        'views/rs_invoice_from_waybill_wizard_views.xml',
        'views/rs_waybill_views.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
    'application': False,
}
