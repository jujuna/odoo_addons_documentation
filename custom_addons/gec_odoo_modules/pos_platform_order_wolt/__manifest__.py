{
    'name': 'Platform Order Provider: Wolt',
    'category': 'Sales/Point of Sale',
    'summary': "Receive and manage Wolt marketplace orders in the Point of Sale",
    'description': """
Wolt Marketplace integration for the Point of Sale:
- link venues with Wolt self-service onboarding (SSIO)
- receive Wolt orders through signed webhooks, accept / reject / ready / delivered
- push the menu, item prices and availability to Wolt
- set the venue online or offline and push opening hours
    """,
    'version': '1.0',
    'depends': ['pos_platform_order'],
    'data': [
        'data/platform_order_provider_data.xml',
        'data/ir_cron_data.xml',
        'views/platform_order_provider_views.xml',
        'views/platform_order_entity_views.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_platform_order_wolt/static/src/app/**/*',
        ],
        'web.assets_tests': [
            'pos_platform_order_wolt/static/tests/tours/**/*',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'author': 'Gecbusiness',
    'license': 'OPL-1',
}
