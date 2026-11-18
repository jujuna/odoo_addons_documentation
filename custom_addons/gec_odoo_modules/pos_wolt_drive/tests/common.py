import base64
import hashlib
import hmac
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from odoo.fields import Command

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon

REQUESTS = 'odoo.addons.pos_wolt_drive.utils.drive_request.requests'
SECRET = 'S' * 64
LOCATION = {'coordinates': {'lat': 41.7, 'lon': 44.8}, 'formatted_address': 'Rustaveli Ave 1, Tbilisi'}
PROMISE = {
    'id': 'P1',
    'created_at': '2026-10-27T12:00:00Z',
    'valid_until': '2026-10-27T12:10:00Z',
    'is_binding': True,
    'time_estimate_minutes': 35,
    'price': {'amount': 860, 'currency': 'GEL'},
    'pickup': {'venue_id': 'DV1', 'location': LOCATION, 'options': {'min_preparation_time_minutes': 20}, 'eta_minutes': 20},
    'dropoff': {'location': LOCATION, 'eta_minutes': 35},
}
DELIVERY = {
    'id': 'D1',
    'status': 'INFO_RECEIVED',
    'wolt_order_reference_id': 'WOLTREF1',
    'tracking': {'id': 'T1', 'url': 'https://track.wolt.com/T1'},
    'price': {'amount': 860, 'currency': 'GEL'},
    'pickup': {'eta': '2026-10-27T12:30:00Z', 'location': LOCATION},
    'dropoff': {'eta': None, 'location': LOCATION},
}
WEBHOOK_CALLBACK_CONFIG = {'exponential_retry_backoff': {'exponent_base': 2, 'max_retry_count': 5}}


def _response(payload=None, status=200):
    response = MagicMock(ok=status < 400, status_code=status)
    if payload is None:
        response.json.side_effect = ValueError("No JSON body")
        response.text = '<html>Bad Gateway</html>'
    else:
        response.json.return_value = payload
        response.text = json.dumps(payload)
    return response


def _webhook_config(webhook_id, callback_url):
    return {
        'id': webhook_id,
        'callback_url': callback_url,
        'callback_config': WEBHOOK_CALLBACK_CONFIG,
        'created_at': '2026-10-27T12:00:00Z',
        'modified_at': '2026-10-27T12:00:00Z',
        'disabled': False,
        'subscribed_events': ['order.received', 'order.delivered'],
    }


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _jwt(payload, secret, alg='HS256'):
    signing_input = f"{_b64(json.dumps({'alg': alg, 'typ': 'JWT'}).encode())}.{_b64(json.dumps(payload).encode())}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f'{signing_input}.{_b64(signature)}'


class WoltDriveCommon(TestPointOfSaleHttpCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wolt_config = cls.main_pos_config
        cls.wolt_config.write({
            'wolt_drive_venue_id': 'DV1',
            'wolt_drive_merchant_id': 'M1',
            'wolt_drive_api_key': 'KEY',
            'wolt_drive_preparation_minutes': 20,
        })
        cls.wolt_config.sudo().wolt_drive_webhook_secret = SECRET
        cls.unregistered_config = cls.env['pos.config'].create({
            'name': 'Shop Without Status Updates',
            'module_pos_restaurant': False,
            'journal_id': cls.wolt_config.journal_id.id,
            'payment_method_ids': [Command.set(cls.bank_payment_method.ids)],
            'wolt_drive_venue_id': 'DV2',
            'wolt_drive_merchant_id': 'M2',
            'wolt_drive_api_key': 'KEY2',
        })
        cls.customer, cls.customer_without_address, cls.customer_without_phone = cls.env['res.partner'].create([
            {
                'name': 'Nino',
                'phone': '+995555123456',
                'street': 'Rustaveli Ave 1',
                'city': 'Tbilisi',
                'zip': '0108',
            },
            {
                'name': 'Tamar Without Address',
                'phone': '+995555123457',
            },
            {
                'name': 'Giorgi Without Phone',
                'street': 'Chavchavadze Ave 5',
                'city': 'Tbilisi',
            },
        ])
        cls.cashier = cls.env['res.users'].create({
            'name': 'Wolt Cashier',
            'login': 'wolt_cashier',
            'group_ids': [
                Command.link(cls.env.ref('base.group_user').id),
                Command.link(cls.env.ref('point_of_sale.group_pos_user').id),
            ],
        })
        cls.wolt_config.with_user(cls.pos_user).open_ui()
        cls.unregistered_config.with_user(cls.pos_user).open_ui()
        cls.order = cls._create_order(cls.customer)
        cls.order_without_address = cls._create_order(cls.customer_without_address)
        cls.order_without_phone = cls._create_order(cls.customer_without_phone)
        cls.order_unregistered_pos = cls._create_order(cls.customer, cls.unregistered_config)

    @classmethod
    def _create_order(cls, partner, config=None, amount=26.2, state='paid'):
        return cls.env['pos.order'].create({
            'session_id': (config or cls.wolt_config).current_session_id.id,
            'partner_id': partner.id,
            'amount_total': amount,
            'amount_paid': amount,
            'amount_tax': 0,
            'amount_return': 0,
            'state': state,
            'lines': [Command.create({
                'product_id': cls.wall_shelf.product_variant_id.id,
                'qty': 1,
                'price_unit': amount,
                'price_subtotal': amount,
                'price_subtotal_incl': amount,
            })],
        })

    @contextmanager
    def _wolt_answers(self, *answers):
        """Every Wolt HTTP call returns the next answer; an answer that is an exception is raised."""
        with patch(REQUESTS) as requests:
            requests.request.side_effect = answers
            yield requests.request

    def _paths(self, request):
        return [(call.args[0], urlsplit(call.args[1]).path) for call in request.call_args_list]

    def _set_courier(self, status, ref='WOLTREF1', attempt=1, order=None):
        order = order or self.order
        order.write({
            'wolt_drive_status': status,
            'wolt_drive_ref': ref,
            'wolt_drive_attempt': attempt,
        })
        return order

    def _webhook_url(self, config=None):
        return f'/wolt_drive/webhook/{(config or self.wolt_config).id}'

    def _post_raw(self, body, config=None):
        return self.url_open(self._webhook_url(config), data=body, headers={'Content-Type': 'application/json'})

    def _post_event(self, event_type, details=None, config=None, secret=SECRET, alg='HS256'):
        details = {'id': 'EV1', 'venue_id': 'DV1', 'wolt_order_reference_id': 'WOLTREF1', **(details or {})}
        token = _jwt({'type': event_type, 'dispatched_at': '2026-10-27T12:00:00Z', 'details': details}, secret, alg)
        response = self._post_raw(json.dumps({'token': token}), config)
        self.env.invalidate_all()
        return response
