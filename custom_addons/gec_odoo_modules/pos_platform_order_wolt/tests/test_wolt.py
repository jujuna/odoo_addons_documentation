import datetime
from unittest.mock import patch

import psycopg2

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.pos_platform_order_wolt.tests.common import REQUESTS, WoltCommon, _response


@tagged('post_install', '-at_install')
class TestWolt(WoltCommon):

    def test_bad_signature_refused(self):
        response = self._post(self._notification('CREATED'), secret='wrong')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self._wolt_order())

    def test_order_flow(self):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs.get('json')))
            if method == 'GET':
                return _response(self._order())
            return _response(status=202)

        with patch(f'{REQUESTS}.request', side_effect=fake_request):
            self.assertEqual(self._post(self._notification('CREATED')).status_code, 200)
            self.assertEqual(self._post(self._notification('CREATED')).status_code, 200)  # duplicate
            order = self._wolt_order()
            self.assertEqual(len(order), 1)
            self.assertEqual(order.platform_order_status, 'new')
            self.assertEqual(order.floating_order_name, 'Wolt #042')
            # Cola's Odoo tax is price-excluded, so its price is converted and can drift by a cent
            self.assertAlmostEqual(order.amount_total, 25.0, delta=0.011)
            burger_line = order.lines.filtered(lambda l: l.product_id.product_tmpl_id == self.burger)
            self.assertAlmostEqual(burger_line.price_unit, 12.0)
            self.assertAlmostEqual(burger_line.discount, 100 * 200 / 2400)
            self.assertEqual(burger_line.attribute_value_ids, self.cheese)
            cola_line = order.lines.filtered(lambda l: l.product_id.product_tmpl_id == self.cola)
            self.assertAlmostEqual(cola_line.price_subtotal_incl, 3.0)

            self.assertTrue(order.platform_order_status_update_from_ui('accept')['success'])
            self.assertEqual(order.platform_order_status, 'accepted')
            self.assertTrue(order.platform_order_status_update_from_ui('food_ready')['success'])
            self.assertTrue(order.platform_order_food_ready)
            # Wolt courier delivers: the venue cannot mark it delivered
            self.assertFalse(order.platform_order_status_update_from_ui('delivered')['success'])

            self._post(self._notification('PRODUCTION'))  # late notification, ignored
            self._post(self._notification(None, notification_type='pickup_completed.notification'))
            self.assertEqual(order.platform_order_status, 'collected')
            self._post(self._notification('DELIVERED'))
            self.assertEqual(order.platform_order_status, 'delivered')
            self.assertEqual(order.state, 'paid')
            self.assertEqual(order.payment_ids.payment_method_id, self.provider.default_payment_method_id)
            self.assertAlmostEqual(order.amount_paid, order.amount_total, places=2)

        put_paths = [url.split('woltapi.com')[1] for method, url, _json in calls if method == 'PUT']
        self.assertEqual(put_paths, ['/orders/W1/accept', '/orders/W1/ready'])
        self.assertEqual(sum(1 for method, *_ in calls if method == 'GET'), 1)  # duplicate found locally

    def test_reject(self):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs.get('json')))
            if method == 'GET':
                return _response(self._order())
            return _response(status=202)

        with patch(f'{REQUESTS}.request', side_effect=fake_request):
            self._post(self._notification('CREATED'))
            order = self._wolt_order()
            self.assertTrue(order.platform_order_status_update_from_ui('reject', reason='ITEMS_UNAVAILABLE')['success'])
            self.assertEqual(order.platform_order_status, 'cancelled')
            self._post(self._notification('CANCELED'))
            self.assertEqual(order.platform_order_status, 'cancelled')
        reject = [c for c in calls if c[1].endswith('/reject')][0]
        self.assertEqual(reject[2]['code'], 'ITEMS_UNAVAILABLE')
        self.assertTrue(reject[2]['reason'])

    def test_takeaway_auto_accepted(self):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url))
            if method == 'GET':
                return _response(self._order('W2', 'takeaway', 'auto_accepted_by_wolt'))
            return _response(status=202)

        with patch(f'{REQUESTS}.request', side_effect=fake_request):
            self._post(self._notification('PRODUCTION', 'W2'))  # CREATED missed: imported from PRODUCTION
            order = self._wolt_order('W2')
            self.assertEqual(order.platform_order_status, 'accepted')
            self.assertEqual(order.platform_order_type, 'pickup')
            self.assertFalse(order.platform_order_status_update_from_ui('delivered')['success'])  # not ready yet
            order.platform_order_status_update_from_ui('food_ready')
            self.assertTrue(order.platform_order_status_update_from_ui('delivered')['success'])
            self.assertEqual(order.platform_order_status, 'delivered')
            self.assertEqual(order.state, 'paid')
        self.assertIn(('PUT', 'https://pos-integration-service.development.dev.woltapi.com/orders/W2/delivered'), calls)
        self.assertFalse(any(url.endswith('/accept') for _m, url in calls))

    def test_preorder_confirm(self):
        preorder = self._order(
            'W3', type='preorder', pre_order={'preorder_time': '2026-10-28T12:00:00Z', 'pre_order_status': 'waiting'})
        preorder['type'] = 'preorder'
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url))
            return _response(preorder) if method == 'GET' else _response(status=204)

        with patch(f'{REQUESTS}.request', side_effect=fake_request):
            self._post(self._notification('CREATED', 'W3'))
            order = self._wolt_order('W3')
            self.assertEqual(order.wolt_order_type, 'preorder')
            self.assertEqual(order.platform_order_status, 'new')
            order.platform_order_status_update_from_ui('accept')
            self.assertEqual(order.platform_order_status, 'accepted')
        self.assertTrue(calls[-1][1].endswith('/orders/W3/confirm-preorder'))

    def test_token_refresh(self):
        self.token.expiry = fields.Datetime.now() - datetime.timedelta(minutes=5)
        token_calls = []

        def fake_post(url, data=None, **kwargs):
            token_calls.append(data)
            return _response({'access_token': 'x.eyJhIjoxfQ.y', 'refresh_token': 'RT2', 'expires_in': 3600})

        status = _response({'status': {'is_online': True, 'is_open': False}})
        with (
            patch(f'{REQUESTS}.post', side_effect=fake_post),
            patch(f'{REQUESTS}.request', return_value=status) as request,
        ):
            self.store.action_wolt_refresh_status()
            self.store.action_wolt_refresh_status()
        self.assertEqual(token_calls, [{'grant_type': 'refresh_token', 'refresh_token': 'RT1'}])
        self.assertEqual(self.token.refresh_token, 'RT2')
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer x.eyJhIjoxfQ.y')
        self.assertTrue(self.store.wolt_venue_online)

    def test_oauth_callback(self):
        claims = 'eyJpbnRlZ3JhdGlvbiI6eyJ2ZW51ZV9pZCI6IlZFTlVFOSJ9fQ'  # {"integration":{"venue_id":"VENUE9"}}
        action = self.store.action_wolt_connect()
        self.assertIn('client_id=cid', action['url'])
        state = self.store.sudo().wolt_oauth_state
        token_response = _response({'access_token': f'h.{claims}.s', 'refresh_token': 'R', 'expires_in': 3600})
        with patch(f'{REQUESTS}.post', return_value=token_response) as post:
            admin = self.env.ref('base.user_admin')
            admin.write({'group_ids': [Command.link(self.env.ref('point_of_sale.group_pos_manager').id)],
                         'company_ids': [Command.link(self.store.company_id.id)]})
            self.authenticate('admin', 'admin')
            response = self.url_open(f'/wolt/oauth/callback?code=CODE&state={state}', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(post.call_args.kwargs['data']['code'], 'CODE')
        self.assertEqual(self.store.external_id, 'VENUE9')
        self.assertEqual(self.token.refresh_token, 'R')
        self.assertTrue(self.store.wolt_connected)

    def test_menu_and_item_push(self):
        menu = self.store._wolt_prepare_menu()
        items = {i['external_data']: i for c in menu['categories'] for i in c['items']}
        burger = items[f'product_template_{self.burger.id}']
        self.assertAlmostEqual(burger['price'], 10.0, places=2)
        self.assertEqual(burger['sales_tax_percentage'], 18.0)
        self.assertAlmostEqual(items[f'product_template_{self.cola.id}']['price'], 3.54, places=2)
        option = burger['options'][0]
        self.assertEqual(option['type'], 'MultiChoice')
        option_prices = {v['external_data']: v['price'] for v in option['values']}
        self.assertAlmostEqual(option_prices[f'product_template_attribute_value_{self.cheese.id}'], 2.0, places=2)

        with patch(f'{REQUESTS}.request', return_value=_response(status=202)) as request:
            self.store.action_sync_menu()
            menu_url = 'https://pos-integration-service.development.dev.woltapi.com/v1/restaurants/VENUE1/menu'
            self.assertEqual(request.call_args.args[:2], ('POST', menu_url))
            self.assertEqual(self.store.menu_sync_state, 'done')

            self.cola.list_price = 4.0
            self.assertEqual(self.store.wolt_pending_product_tmpl_ids, self.cola)
            self.env['platform.order.entity']._cron_wolt_sync()
            pushed = {
                'external_id': f'product_template_{self.cola.id}',
                'price': 472,
                'enabled': True,
                'vat_percentage': 18.0,
            }
            self.assertEqual(request.call_args.kwargs['json'], {'data': [pushed]})
            self.assertFalse(self.store.wolt_pending_product_tmpl_ids)

            self.cola.list_price = 5.0
            request.reset_mock()
            self.env['platform.order.entity']._cron_wolt_sync()  # within 15 minutes: kept for later
            request.assert_not_called()
            self.assertEqual(self.store.wolt_pending_product_tmpl_ids, self.cola)

    def test_opening_hours(self):
        calendar = self.env['resource.calendar'].create({'name': 'Hours', 'attendance_ids': [
            Command.create({'dayofweek': '0', 'hour_from': 10, 'hour_to': 22.5}),
            Command.create({'dayofweek': '6', 'hour_from': 0, 'hour_to': 24}),
        ]})
        self.store.sudo().service_hours_id = calendar
        self.assertEqual(self.store._wolt_prepare_opening_times(), [
            {'opening_day': 'MONDAY', 'opening_time': '10:00', 'closing_day': 'MONDAY', 'closing_time': '22:30'},
            {'opening_day': 'SUNDAY', 'opening_time': '00:00', 'closing_day': 'SUNDAY', 'closing_time': '24:00'},
        ])

    def test_concurrent_import_refused(self):
        with patch(f'{REQUESTS}.request', return_value=_response(status=202)):
            self.store._create_order_from_data(self._order('W5'))
            with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
                self.store._create_order_from_data(self._order('W5'))

    def test_self_delivery(self):
        data = self._order('W6', acceptance='to_be_accepted_by_venue', consumer_phone_number='+995555123456')
        data['delivery'] = {'type': 'homedelivery', 'self_delivery': True, 'location': {
            'street_address': 'Rustaveli 1', 'city': 'Tbilisi', 'zip_code': '0108',
            'formatted_address': 'Rustaveli 1, entrance B',
        }}
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(url)
            return _response(status=202)

        with patch(f'{REQUESTS}.request', side_effect=fake_request):
            order = self.store._create_order_from_data(data)
            self.assertEqual(order.partner_id.phone, '+995555123456')
            self.assertEqual(order.partner_id.city, 'Tbilisi')
            self.assertIn('entrance B', order.general_customer_note)
            order.platform_order_status_update_from_ui('accept')
            order.platform_order_status_update_from_ui('food_ready')
            self.assertTrue(order.platform_order_status_update_from_ui('delivered')['success'])
        self.assertTrue(calls[0].endswith('/orders/W6/self-delivery/accept'))
        self.assertTrue(calls[-1].endswith('/orders/W6/delivered'))

    def test_closed_pos_queue(self):
        self.config.current_session_id.state = 'closed'
        preorder = self._order(
            'W7', type='preorder', pre_order={'preorder_time': '2026-10-28T12:00:00Z', 'pre_order_status': 'waiting'})
        manual = self._order('W8')
        responses = [_response(preorder), _response(status=204), _response(manual), _response(status=202)]
        with patch(f'{REQUESTS}.request', side_effect=responses) as request:
            self._post(self._notification('CREATED', 'W7'))
            self._post(self._notification('CREATED', 'W8'))
        self.assertFalse(self._wolt_order('W7') | self._wolt_order('W8'))
        self.assertEqual(self.store.wolt_pending_order_refs, ['W7'])  # preorder waits, manual instant order is rejected
        self.assertTrue(request.call_args_list[1].args[1].endswith('/orders/W7/confirm-preorder'))
        self.assertTrue(request.call_args.args[1].endswith('/orders/W8/reject'))

        self.config.open_ui()
        confirmed = {**preorder, 'pre_order': {**preorder['pre_order'], 'pre_order_status': 'confirmed'}}
        with patch(f'{REQUESTS}.request', return_value=_response(confirmed)):
            self.env['platform.order.entity']._cron_wolt_sync()
        self.assertEqual(self._wolt_order('W7').platform_order_status, 'accepted')
        self.assertFalse(self.store.wolt_pending_order_refs)

    def test_unknown_item_fallback(self):
        data = self._order('W10')
        data['items'][1]['pos_id'] = None
        data['items'][1]['name'] = 'Wolt-only drink'
        with patch(f'{REQUESTS}.request', return_value=_response(data)):
            with self.assertRaises(ValidationError):
                self.store._create_order_from_data(data)
            self.store.wolt_fallback_product_id = self.cola.product_variant_id
            order = self.store._create_order_from_data(data)
        self.assertIn('Wolt-only drink', order.lines.mapped('full_product_name'))

    def test_accepted_order_not_rejected(self):
        with patch(f'{REQUESTS}.request', return_value=_response(status=202)) as request:
            order = self.store._create_order_from_data(self._order('W11', acceptance='auto_accepted_by_wolt'))
            result = order.platform_order_status_update_from_ui('reject', reason='GENERIC')
        self.assertFalse(result['success'])
        self.assertEqual(order.platform_order_status, 'accepted')
        request.assert_not_called()

    def test_pos_user_cannot_drive_venue(self):
        pos_user = self.env['res.users'].create({
            'name': 'Cashier', 'login': 'cashier_wolt', 'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('point_of_sale.group_pos_user').id])],
        })
        with patch(f'{REQUESTS}.request', return_value=_response(status=204)) as request:
            with self.assertRaises(AccessError):
                self.store.with_user(pos_user).action_wolt_go_offline()
            with self.assertRaises(AccessError):
                self.store.with_user(pos_user).action_wolt_push_opening_hours()
        request.assert_not_called()
