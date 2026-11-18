from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

# bank sync is daily work, as in core (account_online_synchronization grants it to account.group_account_basic)
BANK_SYNC = {
    'account.online.link': {'perm_create': True, 'perm_write': True, 'perm_unlink': True},
    'account.online.account': {'perm_create': True, 'perm_write': True, 'perm_unlink': True},
}

TEMPLATES = [
    {
        'key': 'salesperson',
        'name': _lt("Salesperson"),
        'description': _lt(
            "Sells to and follows up their own customers, opportunities and quotations. Cannot see the configuration, "
            "sales reports, costs or margins. Cannot export."),
        'requires': ['sale'],
        'apps': [
            {'app': 'sale.sale_menu_root', 'level': 'user', 'own_records': True},
            {'app': 'crm.crm_menu_root', 'level': 'user', 'own_records': True, 'optional': True},
        ],
        'hide_menus': ['sale.menu_sale_report'],
        'switches': {'block_export': True, 'hide_costs': True},
    },
    {
        'key': 'sales_readonly',
        'name': _lt("Sales Read Only"),
        'description': _lt("Sees the sales documents, but cannot change or export them."),
        'requires': ['sale'],
        'apps': [{'app': 'sale.sale_menu_root', 'level': 'readonly'}],
        'switches': {'block_export': True},
    },
    {
        'key': 'accountant',
        'name': _lt("Accountant without Configuration"),
        'description': _lt(
            "Does the daily accounting: invoices, bills, payments, entries and reports. "
            "The accounting configuration is hidden and read only."),
        'requires': ['account'],
        'apps': [{'app': ('accountant.menu_accounting', 'account.menu_finance'), 'level': 'user'}],
        # the app dashboard opens the journals, which are configuration; bank sync comes from BANK_SYNC
        'models': {
            'account.journal': {'perm_create': False, 'perm_write': False, 'perm_unlink': False},
            **BANK_SYNC,
        },
    },
    {
        'key': 'auditor',
        'name': _lt("Auditor"),
        'description': _lt(
            "Sees everything the user's Odoo groups allow. Changes nothing and cannot export or import. The Settings "
            "app is hidden."),
        'requires': [],
        'switches': {
            'strictness': 'override',
            'global_readonly': True,
            'block_export': True,
            'block_import': True,
            'hide_settings_menu': True,
        },
    },
    {
        'key': 'warehouse',
        'name': _lt("Warehouse Operator"),
        'description': _lt(
            "Receives, moves and delivers goods. Cannot see the inventory configuration, product costs or stock "
            "valuation."),
        'requires': ['stock'],
        'apps': [{'app': 'stock.menu_stock_root', 'level': 'user'}],
        'switches': {'hide_costs': True},
    },
    {
        'key': 'purchase',
        'name': _lt("Purchase User"),
        'description': _lt(
            "Creates and follows requests for quotation and purchase orders. "
            "The purchase configuration is hidden."),
        'requires': ['purchase'],
        'apps': [{'app': 'purchase.menu_purchase_root', 'level': 'user'}],
    },
    {
        'key': 'cashier',
        'name': _lt("Cashier"),
        'description': _lt(
            "Sells at the point of sale. Cannot see the point of sale configuration, its reports, costs or margins."),
        'requires': ['point_of_sale'],
        'apps': [{'app': 'point_of_sale.menu_point_root', 'level': 'user'}],
        'hide_menus': ['point_of_sale.menu_point_rep'],
        # the app dashboard opens the point of sale settings themselves
        'models': {'pos.config': {'perm_create': False, 'perm_write': False, 'perm_unlink': False}},
        'switches': {'hide_costs': True},
    },
    {
        'key': 'hr_officer',
        'name': _lt("HR Officer without Salaries"),
        'description': _lt(
            "Manages employees without seeing their wages. The Payroll app, if installed, is hidden."),
        'requires': ['hr'],
        'apps': [{'app': 'hr.menu_hr_root', 'level': 'user'}],
        'hide_menus': [('hr_payroll.menu_hr_payroll_root', 'om_hr_payroll.menu_hr_payroll_root')],
        # hr.employee inherits the wage of hr.version: a rule on one model does not cover the other
        'fields': [('hr.version', 'wage', 'hide'), ('hr.employee', 'wage', 'hide')],
    },
    {
        'key': 'app_user',
        'name': _lt("App User without Configuration"),
        'description': _lt(
            "For any app: its configuration is hidden and read only."),
        'requires': [],
        'any_app': True,
        'apps': [{'app': None, 'level': 'user'}],
        'models': BANK_SYNC,
    },
    {
        'key': 'app_readonly',
        'name': _lt("App Read Only"),
        'description': _lt("For any app: users can read everything in it, but change nothing."),
        'requires': [],
        'any_app': True,
        'apps': [{'app': None, 'level': 'readonly'}],
    },
]

TEMPLATES_BY_KEY = {template['key']: template for template in TEMPLATES}
