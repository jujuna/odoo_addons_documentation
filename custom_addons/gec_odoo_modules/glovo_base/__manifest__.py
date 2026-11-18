{
    'name': "Glovo Base",
    'version': '1.0',
    'category': 'Hidden',
    'summary': "Glovo Partners API client and webhook event inbox",
    'description': """
Shared base for Glovo integrations. Provides a plain Python client for the Glovo Partners API
order lifecycle endpoints and an inbox model that stores the webhook notifications received
from Glovo. Holds no credentials and has no Point of Sale dependency.
""",
    'author': 'GEC',
    'license': 'Other proprietary',
    'depends': ['base'],
    'data': [
        'views/glovo_event_views.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
}
