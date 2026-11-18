{
    'name': "Platform Order Provider: Glovo",
    'version': '1.0',
    'category': 'Sales/Point of Sale',
    'summary': "Receive Glovo orders in the Point of Sale",
    'description': """
Integrates Glovo with the Point of Sale through the platform order framework. Glovo order
notifications (dispatched, picked up, cancelled) create and update POS orders, and marking the
food ready in the POS tells Glovo the order is ready for pickup. Orders are delivered by Glovo
couriers.
Full documentation: README.md and README_DEV.md in the module directory.
""",
    'author': 'GEC',
    'license': 'Other proprietary',
    'depends': ['pos_platform_order', 'glovo_base'],
    'data': [
        'data/platform_order_provider_data.xml',
        'data/ir_cron_data.xml',
        'views/platform_order_provider_views.xml',
        'views/glovo_event_views.xml',
        'views/pos_platform_order_glovo_menus.xml',
        'wizard/pos_glovo_order_resolve_views.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_platform_order_glovo/static/src/app/**/*',
        ],
        'pos_preparation_display.assets': [
            'pos_platform_order_glovo/static/src/pos_preparation_display_app/**/*',
        ],
        'web.assets_tests': [
            'pos_platform_order_glovo/static/tests/tours/**/*',
        ],
        'pos_preparation_display.assets_tour_tests': [
            'pos_platform_order_glovo/static/tests/preparation_display/**/*',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
}
