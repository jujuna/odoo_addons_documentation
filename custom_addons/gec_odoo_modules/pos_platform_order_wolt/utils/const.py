from types import MappingProxyType

PROVIDER_CODE = 'wolt'

# Wolt hosts per provider state: 'test' uses Wolt's development environment, 'enabled' production.
API_URLS = MappingProxyType({
    'test': 'https://pos-integration-service.development.dev.woltapi.com',
    'enabled': 'https://pos-integration-service.wolt.com',
})
TOKEN_URLS = MappingProxyType({
    'test': 'https://integrations-authentication-service.development.dev.woltapi.com/oauth2/token',
    'enabled': 'https://integrations-authentication-service.wolt.com/oauth2/token',
})
INTEGRATE_URLS = MappingProxyType({
    'test': 'https://developer.development.dev.woltapi.com/integrate',
    'enabled': 'https://developer.wolt.com/integrate',
})

WEBHOOK_ROUTE = '/wolt/webhook'
OAUTH_CALLBACK_ROUTE = '/wolt/oauth/callback'
MENU_IMAGE_ROUTE = '/wolt/menu/image'

DELIVERY_TYPE_MAPPING = MappingProxyType({'homedelivery': 'delivery', 'takeaway': 'pickup', 'eatin': 'dine_in'})
ORDER_STATUS_MAPPING = MappingProxyType({'DELIVERED': 'delivered', 'CANCELED': 'cancelled'})
# order_status values of an order Wolt is still working on (GET /v2/orders); delivered and rejected are final
LIVE_ORDER_STATUSES = ('received', 'fetched', 'acknowledged', 'production', 'ready')

# acceptance_status values that need no accept call from Odoo (Wolt auto-accepts, or already accepted)
ACCEPTED_ON_ARRIVAL_STATUSES = ('to_be_accepted_by_wolt', 'auto_accepted_by_wolt', 'accepted_by_venue')

REJECT_CODES = ('GENERIC', 'ITEMS_UNAVAILABLE', 'VENUE_CLOSING_SOON')

WEEKDAYS = ('MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY')
