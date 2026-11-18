import datetime
import hashlib
import hmac
import json
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from requests.exceptions import HTTPError

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import HttpCase

from odoo.addons.point_of_sale.tests.common import CommonPosTest

REQUESTS = 'odoo.addons.pos_platform_order_wolt.utils.wolt_request.requests'


def _response(payload=None, status=200):
    response = MagicMock()
    response.ok = status < 400
    response.status_code = status
    response.content = json.dumps(payload).encode() if payload is not None else b''
    response.json.return_value = payload
    response.text = response.content.decode()
    if status >= 400:
        response.raise_for_status.side_effect = HTTPError(f"{status} error", response=response)
    return response


class WoltCommon(CommonPosTest, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.startClassPatcher(patch.object(cls.registry['ir.cron'], '_commit_progress', return_value=float('inf')))
        cls.provider = cls.env['platform.order.provider'].search([('code', '=', 'wolt'), ('company_id', '=', cls.env.company.id)], limit=1)
        cls.provider._setup_payment_method(cls.provider)
        cls.provider._setup_pricelist(cls.provider)
        cls.provider.write({
            'state': 'test',
            'wolt_client_id': 'cid',
            'wolt_client_secret': 'csecret',
        })
        cls.provider.action_wolt_generate_webhook_secret()
        cls.company_b = cls.setup_other_company(name='Company B')['company']

        cls.vat18_incl = cls.env['account.tax'].create({
            'name': 'VAT 18 incl',
            'amount': 18,
            'price_include_override': 'tax_included',
        })
        cls.vat18_excl = cls.env['account.tax'].create({'name': 'VAT 18 excl', 'amount': 18})
        cls.vat18_b = cls.env['account.tax'].with_company(cls.company_b).create({
            'name': 'VAT 18 company B',
            'amount': 18,
            'price_include_override': 'tax_included',
            'company_id': cls.company_b.id,
        })
        cls.categ = cls.env['pos.category'].create({'name': 'Burgers'})
        extras = cls.env['product.attribute'].create({
            'name': 'Extras',
            'display_type': 'multi',
            'create_variant': 'no_variant',
            'value_ids': [Command.create({'name': 'Cheese'}), Command.create({'name': 'Bacon'})],
        })
        cls.burger = cls.env['product.template'].create({
            'name': 'Burger',
            'available_in_pos': True,
            'list_price': 10.0,
            'pos_categ_ids': [Command.set(cls.categ.ids)],
            'taxes_id': [Command.set(cls.vat18_incl.ids)],
            'attribute_line_ids': [Command.create({'attribute_id': extras.id, 'value_ids': [Command.set(extras.value_ids.ids)]})],
        })
        cls.cheese = cls.burger.attribute_line_ids.product_template_value_ids.filtered(lambda v: v.name == 'Cheese')
        cls.cheese.price_extra = 2.0
        cls.cola = cls.env['product.template'].create({
            'name': 'Cola',
            'available_in_pos': True,
            'list_price': 3.0,
            'pos_categ_ids': [Command.set(cls.categ.ids)],
            'taxes_id': [Command.set(cls.vat18_excl.ids)],
        })
        cls.water = cls.env['product.template'].create({
            'name': 'Water',
            'available_in_pos': True,
            'list_price': 2.0,
            'taxes_id': [Command.clear()],
        })
        cls.soup = cls.env['product.template'].create({
            'name': 'Soup',
            'available_in_pos': True,
            'list_price': 5.0,
            'taxes_id': [Command.set((cls.vat18_incl | cls.vat18_b).ids)],
        })
        crust = cls.env['product.attribute'].create({'name': 'Crust', 'value_ids': [Command.create({'name': 'Thin'})]})
        size = cls.env['product.attribute'].create({
            'name': 'Size',
            'value_ids': [Command.create({'name': 'Small'}), Command.create({'name': 'Large'})],
        })
        cls.pizza = cls.env['product.template'].create({
            'name': 'Pizza',
            'available_in_pos': True,
            'list_price': 12.0,
            'taxes_id': [Command.set(cls.vat18_incl.ids)],
            'attribute_line_ids': [
                Command.create({'attribute_id': crust.id, 'value_ids': [Command.set(crust.value_ids.ids)]}),
                Command.create({'attribute_id': size.id, 'value_ids': [Command.set(size.value_ids.ids)]}),
            ],
        })
        pizza_values = cls.pizza.attribute_line_ids.product_template_value_ids
        cls.thin = pizza_values.filtered(lambda v: v.name == 'Thin')
        cls.large = pizza_values.filtered(lambda v: v.name == 'Large')

        cls.config = cls.pos_config_usd
        cls.config_branch = cls.env['pos.config'].create({
            'name': 'Branch POS',
            'journal_id': cls.company_data['default_journal_sale'].id,
            'payment_method_ids': [Command.set(cls.provider.default_payment_method_id.ids)],
        })
        cls.config.payment_method_ids |= cls.provider.default_payment_method_id
        cls.store = cls._create_store(cls.provider, cls.config, 'Main', 'VENUE1')
        cls.token = cls.env['platform.order.wolt.token'].search([('store_id', '=', cls.store.id)])
        cls.store_branch = cls._create_store(cls.provider, cls.config_branch, 'Branch', 'VENUE2')
        cls.config.open_ui()
        cls.config_branch.open_ui()

        cls.provider_b = cls.provider.copy({'company_id': cls.company_b.id})
        cls.provider_b._setup_payment_method(cls.provider_b)
        cls.provider_b._setup_pricelist(cls.provider_b)
        cls.provider_b.write({
            'state': 'test',
            'wolt_client_id': 'cid-b',
            'wolt_client_secret': 'csecret-b',
        })
        cls.provider_b.action_wolt_generate_webhook_secret()
        cls.config_b = cls.env['pos.config'].with_company(cls.company_b).create({
            'name': 'POS Company B',
            'company_id': cls.company_b.id,
            'payment_method_ids': [Command.set(cls.provider_b.default_payment_method_id.ids)],
        })
        cls.store_b = cls._create_store(cls.provider_b, cls.config_b, 'Main B', 'VENUE1')
        cls.config_b.open_ui()

    @classmethod
    def _create_store(cls, provider, config, name, venue_id):
        store = cls.env['platform.order.entity'].create({
            'name': name,
            'provider_id': provider.id,
            'external_id': venue_id,
            'config_id': config.id,
            'payment_method_id': provider.default_payment_method_id.id,
            'pricelist_line_ids': [Command.create({
                'name': 'Default',
                'external_key': 'default',
                'pricelist_id': provider.default_pricelist_id.id,
            })],
        })
        cls.env['platform.order.wolt.token'].create({
            'store_id': store.id,
            'access_token': 'AT1',
            'refresh_token': 'RT1',
            'expiry': fields.Datetime.now() + datetime.timedelta(hours=1),
        })
        return store

    def _order(self, order_id='W1', delivery_type='homedelivery', acceptance='to_be_accepted_by_venue', **extra):
        return {
            'id': order_id,
            'order_number': '042',
            'type': 'instant',
            'order_status': 'received',
            'venue': {'id': 'VENUE1'},
            'consumer_comment': 'No onions',
            'consumer_name': 'Nino G.',
            'consumer_phone_number': None,
            'delivery': {
                'type': delivery_type,
                'self_delivery': False,
                'location': None,
                'status': 'estimated',
            },
            'order_handling': {'acceptance_status': acceptance},
            'items': [
                {
                    'pos_id': f'product_template_{self.burger.id}',
                    'name': 'Burger',
                    'count': 2,
                    'options': [{'value_pos_id': f'product_template_attribute_value_{self.cheese.id}', 'count': 1}],
                    'item_price': {
                        'total': {'amount': 2200, 'currency': 'USD'},
                        'price_breakdown': {'total_before_discounts': {'amount': 2400, 'currency': 'USD'}},
                    },
                },
                {
                    'pos_id': f'product_template_{self.cola.id}',
                    'name': 'Cola',
                    'count': 1,
                    'options': [],
                    'item_price': {'total': {'amount': 300, 'currency': 'USD'}},
                },
            ],
            **extra,
        }

    def _preorder(self, order_id='W3', status='waiting'):
        return self._order(order_id, type='preorder', pre_order={'preorder_time': '2026-10-28T12:00:00Z', 'pre_order_status': status})

    def _item(self, template, amount, count=1, options=()):
        return {
            'pos_id': f'product_template_{template.id}',
            'name': template.name,
            'count': count,
            'options': list(options),
            'item_price': {'total': {'amount': amount, 'currency': 'USD'}},
        }

    def _self_delivery(self):
        return {
            'consumer_phone_number': '+995555123456',
            'delivery': {
                'type': 'homedelivery',
                'self_delivery': True,
                'location': {
                    'street_address': 'Rustaveli 1',
                    'city': 'Tbilisi',
                    'zip_code': '0108',
                },
            },
        }

    def _post(self, payload, secret=None):
        body = json.dumps(payload).encode()
        secret = secret or self.provider.sudo().wolt_webhook_secret
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {'WOLT-SIGNATURE': signature, 'Content-Type': 'application/json'}
        return self.url_open('/wolt/webhook', data=body, headers=headers)

    def _notification(self, status, order_id='W1', notification_type='order.notification', venue_id='VENUE1'):
        return {
            'id': 'n1',
            'type': notification_type,
            'created_at': '2026-10-27T10:00:00Z',
            'order': {'id': order_id, 'venue_id': venue_id, 'status': status},
        }

    def _wolt_order(self, order_id='W1'):
        return self.env['pos.order'].search([('platform_order_ref', '=', order_id)])

    @contextmanager
    def _mock_wolt(self, orders=None):
        """Answers Wolt: a GET returns the payload (or raises the exception, or returns the response) kept in `orders` for that order,
        every other call is accepted. Yields the list of calls as 'METHOD /path'."""
        orders = {} if orders is None else orders
        calls = []

        def fake_request(method, url, **kwargs):
            path = url.split('woltapi.com')[1]
            calls.append(f'{method} {path}')
            if method != 'GET':
                return _response(status=202)
            answer = orders[path.rsplit('/', 1)[1]]
            if isinstance(answer, Exception):
                raise answer
            return _response(answer) if isinstance(answer, dict) else answer

        with patch(f'{REQUESTS}.request', side_effect=fake_request):
            yield calls

    def _close_pos_session(self):
        self.config.current_session_id.state = 'closed'

    def _messages(self, order):
        return ' '.join(str(body) for body in order.message_ids.mapped('body'))

    def _user_error(self):
        """Odoo's own assertRaises rolls the changes back: this one keeps them, to check what the code did before it raised."""
        return unittest.TestCase.assertRaises(self, UserError)
