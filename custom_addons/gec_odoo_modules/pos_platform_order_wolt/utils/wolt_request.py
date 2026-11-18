import logging
from urllib.parse import quote

import requests

from odoo.exceptions import UserError

from odoo.addons.pos_platform_order_wolt.utils import const

_logger = logging.getLogger(__name__)

TIMEOUT = 10


class WoltClient:
    def __init__(self, store):
        # sudo: POS users trigger order actions but must not read the venue tokens
        self.store = store.sudo()
        if self.store.provider_id.state == 'disabled':
            raise UserError(store.env._("Enable the Wolt provider (test or production) first."))
        self.base_url = const.API_URLS[self.store.provider_id.state]

    def _request(self, method, path, **kwargs):
        response = requests.request(method, self.base_url + path, timeout=TIMEOUT,
            headers={'Authorization': f'Bearer {self.store._wolt_get_access_token()}'}, **kwargs)
        if not response.ok:
            _logger.warning("Wolt %s %s failed: %s %s", method, path, response.status_code, response.text[:500])
        response.raise_for_status()
        return response.json() if response.content else None

    def _order_path(self, order_ref, action=''):
        return f'/orders/{quote(order_ref)}{action}'

    def _venue_path(self, action=''):
        return f'/venues/{quote(self.store.external_id)}{action}'

    def get_order(self, order_ref):
        return self._request('GET', f'/v2/orders/{quote(order_ref)}')

    def accept_order(self, order_ref, self_delivery=False):
        action = '/self-delivery/accept' if self_delivery else '/accept'
        return self._request('PUT', self._order_path(order_ref, action), json={})

    def confirm_preorder(self, order_ref):
        return self._request('PUT', self._order_path(order_ref, '/confirm-preorder'))

    def reject_order(self, order_ref, reason, code):
        return self._request('PUT', self._order_path(order_ref, '/reject'), json={'reason': reason, 'code': code})

    def mark_ready(self, order_ref):
        return self._request('PUT', self._order_path(order_ref, '/ready'))

    def mark_delivered(self, order_ref):
        return self._request('PUT', self._order_path(order_ref, '/delivered'))

    def get_venue_status(self):
        return self._request('GET', self._venue_path('/status'))

    def set_online(self, online):
        return self._request('PATCH', self._venue_path('/online'), json={'status': 'ONLINE' if online else 'OFFLINE'})

    def set_opening_times(self, availability):
        return self._request('PATCH', self._venue_path('/opening-times'), json={'availability': availability})

    def create_menu(self, menu):
        return self._request('POST', f'/v1/restaurants/{quote(self.store.external_id)}/menu', json=menu)

    def update_items(self, items):
        return self._request('PATCH', self._venue_path('/items'), json={'data': items})

    @staticmethod
    def request_token(provider, data):
        if provider.state == 'disabled':
            raise UserError(provider.env._("Enable the Wolt provider (test or production) first."))
        response = requests.post(const.TOKEN_URLS[provider.state], data=data, timeout=TIMEOUT,
            auth=(provider.wolt_client_id, provider.wolt_client_secret))
        if not response.ok:
            _logger.warning("Wolt token request failed: %s %s", response.status_code, response.text[:500])
        response.raise_for_status()
        return response.json()
