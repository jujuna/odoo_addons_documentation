import logging
from types import MappingProxyType
from urllib.parse import quote

import requests

_logger = logging.getLogger(__name__)

API_URLS = MappingProxyType({
    True: 'https://daas-public-api.development.dev.woltapi.com',
    False: 'https://daas-public-api.wolt.com',
})
TIMEOUT = 10


class DriveClient:
    def __init__(self, config):
        # sudo: cashiers book couriers but must not read the merchant key
        self.config = config.sudo()
        self.base_url = API_URLS[self.config.wolt_drive_test_mode]

    def _request(self, method, path, **kwargs):
        headers = {'Authorization': f'Bearer {self.config.wolt_drive_api_key}'}
        response = requests.request(method, self.base_url + path, headers=headers, timeout=TIMEOUT, **kwargs)
        if not response.ok:
            _logger.warning("Wolt Drive %s %s failed: %s", method, path, response.status_code)
        return response

    def _venue_path(self, action):
        return f'/v1/venues/{quote(self.config.wolt_drive_venue_id)}{action}'

    def shipment_promise(self, payload):
        return self._request('POST', self._venue_path('/shipment-promises'), json=payload)

    def create_delivery(self, payload):
        return self._request('POST', self._venue_path('/deliveries'), json=payload)

    def cancel(self, reference, reason):
        return self._request('PATCH', f'/order/{quote(reference)}/status/cancel', json={'reason': reason})

    def register_webhook(self, callback_url, secret):
        return self._request('POST', f'/v1/merchants/{quote(self.config.wolt_drive_merchant_id)}/webhooks', json={
            'callback_url': callback_url,
            'client_secret': secret,
            'callback_config': {'exponential_retry_backoff': {'exponent_base': 2, 'max_retry_count': 5}},
        })

    def list_webhooks(self):
        return self._request('GET', f'/v1/merchants/{quote(self.config.wolt_drive_merchant_id)}/webhooks')

    def delete_webhook(self, webhook_id):
        return self._request('DELETE', f'/v1/merchants/{quote(self.config.wolt_drive_merchant_id)}/webhooks/{quote(webhook_id)}')
