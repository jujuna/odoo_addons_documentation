import logging
import time
from urllib.parse import quote

import requests

from odoo.addons.glovo_base.utils import const

_logger = logging.getLogger(__name__)


class GlovoError(requests.HTTPError):

    def __init__(self, response):
        meaning = const.HTTP_STATUS_MEANINGS.get(response.status_code, "Unexpected response")
        super().__init__(f"Glovo HTTP {response.status_code}: {meaning}. {response.text[:500]}".strip(), response=response)


class GlovoBadRequestError(GlovoError):
    pass


class GlovoUnauthorizedError(GlovoError):
    pass


class GlovoNotFoundError(GlovoError):
    pass


class GlovoConflictError(GlovoError):
    pass


class GlovoRateLimitError(GlovoError):
    pass


class GlovoEndpointDisabledError(GlovoError):
    pass


class GlovoServerError(GlovoError):
    pass


ERRORS_BY_STATUS = {
    400: GlovoBadRequestError,
    401: GlovoUnauthorizedError,
    404: GlovoNotFoundError,
    409: GlovoConflictError,
    429: GlovoRateLimitError,
    503: GlovoEndpointDisabledError,
}


class GlovoClient:

    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token

    def ready_for_pickup(self, order_id, store_external_id):
        """Tell Glovo the order is ready for the Glovo courier."""
        return self._request('PUT', const.READY_FOR_PICKUP_PATH.format(order_id=quote(str(order_id))), store_external_id)

    def customer_picked_up(self, order_id, store_external_id):
        """Tell Glovo the customer collected the order (customer pickup orders only)."""
        return self._request('PUT', const.CUSTOMER_PICKED_UP_PATH.format(order_id=quote(str(order_id))), store_external_id)

    def _request(self, method, path, store_external_id):
        """Send one call, retrying with backoff on 429 and 5xx except 503 (endpoint disabled per the spec),
        and once on a timeout or connection error. All attempts together stay within const.TOTAL_TIMEOUT.
        """
        headers = {'Authorization': self.token, 'Content-Type': 'application/json', const.STORE_HEADER: store_external_id}
        url = self.base_url + path
        deadline = time.monotonic() + const.TOTAL_TIMEOUT
        network_retried = False
        for attempt in range(const.MAX_RETRIES + 1):
            remaining = deadline - time.monotonic()
            try:
                response = requests.request(method, url, headers=headers, timeout=min(const.REQUEST_TIMEOUT, remaining))
            except (requests.Timeout, requests.ConnectionError) as error:
                if network_retried or attempt == const.MAX_RETRIES or deadline - time.monotonic() < const.MIN_ATTEMPT_SECONDS:
                    raise
                network_retried = True
                _logger.warning("Glovo %s %s failed (%s), retrying once", method, path, error)
                continue
            status = response.status_code
            if status < 400:
                return response
            retryable = status == 429 or (status >= 500 and status != 503)
            delay = const.BACKOFF_SECONDS * 2 ** attempt
            if (not retryable or attempt == const.MAX_RETRIES or deadline - time.monotonic() - delay < const.MIN_ATTEMPT_SECONDS):
                break
            _logger.warning("Glovo %s %s returned %s, retrying in %ss", method, path, status, delay)
            time.sleep(delay)

        error_class = ERRORS_BY_STATUS.get(status, GlovoServerError if status >= 500 else GlovoError)
        raise error_class(response)
