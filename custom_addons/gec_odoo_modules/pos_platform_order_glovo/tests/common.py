import json
from unittest.mock import patch

from odoo.fields import Command

from odoo.addons.glovo_base.utils.glovo_client import GlovoClient
from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon

CLIENT = 'odoo.addons.glovo_base.utils.glovo_client'


class TestGlovoCommon(TestPointOfSaleHttpCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['pos.printer'].search([]).unlink()
        cls.provider = cls.env['platform.order.provider'].create({
            'name': 'Glovo Lock', 'code': 'glovo', 'state': 'test', 'glovo_token': 'lock-token',
            'company_id': cls.env.company.id, 'default_pricelist_id': cls.main_pos_config.pricelist_id.id,
        })
        cls.store = cls.env['platform.order.entity'].create({
            'name': 'Glovo Lock Store', 'external_id': 'LOCK-STORE', 'provider_id': cls.provider.id,
            'config_id': cls.main_pos_config.id, 'payment_method_id': cls.bank_payment_method.id,
        })
        cls.glovo_product = cls.desk_organizer.product_variant_id
        cls.glovo_product.default_code = 'LOCK-P1'
        cls.cash = cls.main_pos_config._get_cash_payment_method()

    def _webhook(self, event, order_id, **extra):
        payload = {
            'order_id': order_id, 'store_id': 'LOCK-STORE', 'order_code': f'LOCK{order_id}', 'pick_up_code': '433',
            'payment_method': 'DELAYED', 'currency': 'USD', 'estimated_total_price': 2000,
            'partner_discounted_products_total': 2000, 'is_picked_up_by_customer': False,
            'courier': {'name': 'Lock Courier', 'phone_number': '+995555000000'},
            'products': [{'id': 'LOCK-P1', 'purchased_product_id': 'A1', 'quantity': 2, 'price': 1000, 'attributes': []}],
            **extra,
        }
        response = self.url_open(f'/glovo/order/{event}', data=json.dumps(payload),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'lock-token'})
        event_rec = self.env['glovo.event'].search([('glovo_order_id', '=', order_id), ('event_type', '=', event)])
        return response.status_code, event_rec.state, event_rec.error

    def _glovo_order(self, order_id):
        return self.env['pos.order'].search([('platform_order_ref', '=', order_id), ('platform_order_store_id', '=', self.store.id)])


# glovo_api.md has no example body for any notification: these follow the Order (:254) and OrderCancelled (:5304) schemas
def glovo_order_payload(order_id, store_id='LOCK-STORE', products=None, **extra):
    products = products or [glovo_product('SC-PLAIN', 1000, quantity=2)]
    total = sum(product['quantity'] * product['price'] for product in products)
    return {
        'order_id': order_id,
        'store_id': store_id,
        'payment_method': 'DELAYED',
        'currency': 'USD',
        'order_code': f'SC{order_id}',
        'pick_up_code': '433',
        'estimated_total_price': total,
        'courier': {'name': 'Scenario Courier', 'phone_number': '+995555000000'},
        'customer': {'name': 'W F', 'phone_number': 'N/A', 'hash': '11111111-2222-3333-4444-555555555555', 'invoicing_details': None},
        'products': products,
        'bundled_orders': [],
        'is_picked_up_by_customer': False,
        'partner_discounts_products': 0,
        'partner_discounted_products_total': total,
        'service_fee': None,
        **extra,
    }


def glovo_cancelled_payload(order_id, store_id='LOCK-STORE', **extra):
    return {'order_id': order_id, 'store_id': store_id, 'cancel_reason': 'USER_ERROR', 'payment_strategy': 'PAY_NOTHING', **extra}


def glovo_product(code, price, quantity=1, **extra):
    return {'id': code, 'purchased_product_id': f'P-{code}', 'name': f'Glovo {code}', 'quantity': quantity, 'price': price, 'attributes': [], **extra}


def glovo_attribute(code, name, price, quantity=1):
    return {'id': code, 'name': name, 'quantity': quantity, 'price': price}


def glovo_sub_product(code, name, price, quantity=1, discount=0, attributes=()):
    return {'id': code, 'name': name, 'quantity': quantity, 'price': price, 'discount': discount, 'attributes': list(attributes)}


class TestGlovoScenarioCommon(TestGlovoCommon):
    """Taxes, products, a second company with its own Glovo store of the same ID, and a second store of the first company."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.store.company_id
        Tax = cls.env['account.tax']
        tax_values = {'amount_type': 'percent', 'type_tax_use': 'sale', 'company_id': cls.company_a.id}
        cls.tax_included = Tax.create({**tax_values, 'name': 'Scenario 18% included', 'amount': 18, 'price_include_override': 'tax_included'})
        cls.tax_excluded = Tax.create({**tax_values, 'name': 'Scenario 10% excluded', 'amount': 10, 'price_include_override': 'tax_excluded'})
        cls.products = {}
        for code, taxes in (
            ('SC-PLAIN', Tax),
            ('SC-INCL', cls.tax_included),
            ('SC-EXCL', cls.tax_excluded),
            ('SC-COMBO', cls.tax_included),
            ('SC-ATTR', cls.tax_excluded),
        ):
            cls.products[code] = cls.env['product.product'].create({
                'name': f'Scenario {code}',
                'default_code': code,
                'list_price': 1.0,
                'available_in_pos': True,
                'company_id': cls.company_a.id,
                'taxes_id': [Command.set(taxes.ids)],
            })
        cls.unmapped_product = cls.env['product.product'].create({
            'name': 'Scenario unmapped',
            'available_in_pos': True,
            'taxes_id': [Command.clear()],
        })

        cls.company_b = cls.setup_other_company(name='Glovo Company B')['company']
        cls.provider_b = cls.env['platform.order.provider'].create({
            'name': 'Glovo B',
            'code': 'glovo',
            'state': 'test',
            'glovo_token': 'token-b',
            'company_id': cls.company_b.id,
            'default_pricelist_id': cls.env['product.pricelist'].create({
                'name': 'Glovo B', 'currency_id': cls.company_b.currency_id.id, 'company_id': cls.company_b.id,
            }).id,
        })
        cls.store_b = cls.env['platform.order.entity'].create({
            'name': 'Glovo B Store',
            'external_id': 'LOCK-STORE',
            'provider_id': cls.provider_b.id,
        })
        cls.store_2 = cls.env['platform.order.entity'].create({
            'name': 'Glovo Lock Store 2',
            'external_id': 'LOCK-STORE-2',
            'provider_id': cls.provider.id,
            'config_id': cls.main_pos_config.id,
            'payment_method_id': cls.bank_payment_method.id,
        })
        cls.pos_admin.company_ids = [Command.link(cls.company_b.id)]

    def setUp(self):
        super().setUp()
        self.no_order = self.env['pos.order']
        self.network = self.startPatcher(patch(f'{CLIENT}.requests.request', side_effect=AssertionError("Glovo must be mocked")))
        self.addCleanup(lambda: self.assertFalse(self.network.called, "a test reached the Glovo network"))
        # the cron commits after each event; a test cursor refuses commits
        self.startPatcher(patch.object(self.env.registry['ir.cron'], '_commit_progress', return_value=1.0))

    def _open_pos(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def _open_pos_b(self):
        config_b = self.env['pos.config'].with_company(self.company_b).create({'name': 'Glovo Shop B', 'module_pos_restaurant': False})
        self.store_b.config_id = config_b
        config_b.with_company(self.company_b).open_ui()

    def _notify(self, event_type, order_id, token='lock-token', store_id='LOCK-STORE', **extra):
        payload = (glovo_cancelled_payload if event_type == 'cancelled' else glovo_order_payload)(order_id, store_id, **extra)
        response = self.url_open(
            f'/glovo/order/{event_type}', data=json.dumps(payload), headers={'Content-Type': 'application/json', 'Authorization': token})
        self.env.invalidate_all()
        return response

    def _events(self, order_id, event_type=None):
        domain = [('glovo_order_id', '=', order_id)] + ([('event_type', '=', event_type)] if event_type else [])
        return self.env['glovo.event'].search(domain, order='id')

    def _result(self, event):
        return event.state, event.error, event.order_id

    def _order_status(self, order):
        return order.state, order.platform_order_status, len(order.payment_ids)

    def _food_ready(self, order):
        with patch.object(GlovoClient, 'ready_for_pickup', return_value=None) as ready:
            return order.with_user(self.pos_user).platform_order_status_update_from_ui('food_ready'), ready

    def _retry_as_manager(self, events):
        events.with_user(self.pos_admin).with_context(allowed_company_ids=(self.company_a | self.company_b).ids).action_retry()
        self.env.invalidate_all()
