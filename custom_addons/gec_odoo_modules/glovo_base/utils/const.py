STAGE_BASE_URL = 'https://stageapi.glovoapp.com'
PRODUCTION_BASE_URL = 'https://api.glovoapp.com'

STORE_HEADER = 'Glovo-Store-Address-External-Id'

READY_FOR_PICKUP_PATH = '/api/v0/integrations/orders/{order_id}/ready_for_pickup'
CUSTOMER_PICKED_UP_PATH = '/api/v0/integrations/orders/{order_id}/customer_picked_up'

HTTP_STATUS_MEANINGS = {
    200: "Notification received",
    202: "Accepted with remarks (see the response body)",
    204: "Successful operation",
    400: "Bad request: correct the request before retrying",
    401: "Unauthorized: check the Glovo token",
    404: "Not found: check the order ID and store external ID",
    409: "Conflict: the order is not in a state that allows this operation",
    429: "Too many requests: wait before retrying",
    500: "Glovo server error: transient, retried with backoff",
    503: "Endpoint disabled: contact Glovo before retrying",
}

REQUEST_TIMEOUT = 10
MAX_RETRIES = 2
BACKOFF_SECONDS = 1
# All attempts of one call together, so a cashier waits about this long at most
TOTAL_TIMEOUT = 15
# No new attempt starts with less time than this left
MIN_ATTEMPT_SECONDS = 2
