import datetime
from unittest.mock import patch

from requests.exceptions import ConnectionError as RequestsConnectionError

from odoo import fields
from odoo.tests import tagged

from odoo.addons.pos_platform_order_wolt.tests.common import REQUESTS, WoltCommon, _response

DELIVERY_REFUSAL = "Only an accepted order that is not delivered or cancelled can be marked as delivered."


@tagged('post_install', '-at_install')
class TestWoltScenarios(WoltCommon):

    def _cron(self):
        self.env['platform.order.entity']._cron_wolt_sync()

    def _queue_while_closed(self, order):
        self._close_pos_session()
        with self._mock_wolt({order['id']: order}):
            self.assertEqual(self._post(self._notification('CREATED', order['id'])).status_code, 200)
        self.assertFalse(self._wolt_order(order['id']))
        self.assertEqual(self.store.wolt_pending_order_refs, [order['id']])

    def _draft(self, order_id, **extra):
        return self.store._create_order_from_data(self._order(order_id, **extra))

    def test_instant_order_accepted_and_delivered_is_paid_once(self):
        with self._mock_wolt({'W1': self._order()}) as calls:
            self.assertEqual(self._post(self._notification('CREATED')).status_code, 200)
            order = self._wolt_order()
            self.assertEqual(order.session_id, self.config.current_session_id)
            self.assertTrue(order.platform_order_status_update_from_ui('accept')['success'])
            self._post(self._notification('PRODUCTION'))
            self._post(self._notification(None, notification_type='courier.notification'))
            self.assertEqual((order.platform_order_status, order.state), ('driver_allocated', 'draft'))
            self._post(self._notification(None, notification_type='pickup_completed.notification'))
            self.assertEqual((order.platform_order_status, order.state), ('collected', 'paid'))
            self._post(self._notification('DELIVERED'))
        self.assertEqual((order.platform_order_status, order.state), ('delivered', 'paid'))
        self.assertEqual(order.payment_ids.mapped('amount'), [order.amount_total])
        self.assertEqual(calls, ['GET /v2/orders/W1', 'PUT /orders/W1/accept'])

    def test_preorder_waiting_arrives_new_and_accept_confirms_it(self):
        with self._mock_wolt({'W3': self._preorder('W3')}) as calls:
            self._post(self._notification('CREATED', 'W3'))
            order = self._wolt_order('W3')
            self.assertEqual((order.wolt_order_type, order.platform_order_status), ('preorder', 'new'))
            self.assertEqual(order.preset_time, datetime.datetime(2026, 10, 28, 12, 0))
            self.assertTrue(order.platform_order_status_update_from_ui('accept')['success'])
        self.assertEqual(order.platform_order_status, 'accepted')
        self.assertEqual(calls, ['GET /v2/orders/W3', 'PUT /orders/W3/confirm-preorder'])

    def test_preorder_already_confirmed_at_wolt_imports_accepted(self):
        with self._mock_wolt({'W4': self._preorder('W4', 'confirmed')}) as calls:
            self._post(self._notification('CREATED', 'W4'))
        order = self._wolt_order('W4')
        self.assertEqual((order.wolt_order_type, order.platform_order_status), ('preorder', 'accepted'))
        self.assertEqual(calls, ['GET /v2/orders/W4'])

    def test_takeaway_ready_and_delivered_calls_wolt_and_pays(self):
        with self._mock_wolt({'W2': self._order('W2', 'takeaway', 'auto_accepted_by_wolt')}) as calls:
            self._post(self._notification('CREATED', 'W2'))
            order = self._wolt_order('W2')
            self.assertEqual((order.platform_order_status, order.platform_order_type), ('accepted', 'pickup'))
            self.assertTrue(order.platform_order_status_update_from_ui('food_ready')['success'])
            self.assertTrue(order.platform_order_status_update_from_ui('delivered')['success'])
        self.assertEqual((order.platform_order_status, order.state), ('delivered', 'paid'))
        self.assertEqual(calls, ['GET /v2/orders/W2', 'PUT /orders/W2/ready', 'PUT /orders/W2/delivered'])

    def test_mark_delivered_refused_on_new_or_cancelled_order(self):
        orders = {'W12': self._order('W12', 'takeaway'), 'W13': self._order('W13', 'takeaway', 'auto_accepted_by_wolt')}
        with self._mock_wolt(orders) as calls:
            for order_id in orders:
                self._post(self._notification('CREATED', order_id))
            new, cancelled = self._wolt_order('W12'), self._wolt_order('W13')
            new.platform_order_food_ready = True
            cancelled.platform_order_status_update_from_ui('food_ready')
            self._post(self._notification('CANCELED', 'W13'))
            self.assertEqual((new.platform_order_status, cancelled.platform_order_status), ('new', 'cancelled'))
            calls_before = list(calls)
            for order in new | cancelled:
                self.assertEqual(order.platform_order_status_update_from_ui('delivered'), {'success': False, 'message': DELIVERY_REFUSAL})
        self.assertEqual(calls, calls_before)

    def test_cancel_before_payment_cancels_the_order(self):
        with self._mock_wolt({'W1': self._order()}):
            self._post(self._notification('CREATED'))
            order = self._wolt_order()
            order.platform_order_status_update_from_ui('accept')
            self._post(self._notification('CANCELED'))
        self.assertEqual((order.platform_order_status, order.state), ('cancelled', 'cancel'))
        self.assertFalse(order.payment_ids)

    def test_cancel_after_payment_keeps_the_order_paid_and_leaves_a_note(self):
        with self._mock_wolt({'W1': self._order()}):
            self._post(self._notification('CREATED'))
            order = self._wolt_order()
            order.platform_order_status_update_from_ui('accept')
            self._post(self._notification(None, notification_type='courier.notification'))
            self._post(self._notification(None, notification_type='pickup_completed.notification'))
            self._post(self._notification('CANCELED'))
        self.assertEqual((order.platform_order_status, order.state), ('collected', 'paid'))
        self.assertIn("Wolt cancelled this order after it was paid", self._messages(order))

    def test_closed_pos_rejects_instant_order_at_wolt(self):
        self._close_pos_session()
        with self._mock_wolt({'W8': self._order('W8')}) as calls:
            self.assertEqual(self._post(self._notification('CREATED', 'W8')).status_code, 200)
        self.assertEqual(calls, ['GET /v2/orders/W8', 'PUT /orders/W8/reject'])
        self.assertFalse(self._wolt_order('W8'))
        self.assertFalse(self.store.wolt_pending_order_refs)

    def test_closed_pos_confirms_waiting_preorder_and_queues_it(self):
        self._close_pos_session()
        with self._mock_wolt({'W7': self._preorder('W7')}) as calls:
            self.assertEqual(self._post(self._notification('CREATED', 'W7')).status_code, 200)
        self.assertEqual(calls, ['GET /v2/orders/W7', 'PUT /orders/W7/confirm-preorder'])
        self.assertFalse(self._wolt_order('W7'))
        self.assertEqual(self.store.wolt_pending_order_refs, ['W7'])

    def test_queued_order_delivered_at_wolt_is_paid_when_pos_opens(self):
        self._queue_while_closed(self._order('W9', acceptance='auto_accepted_by_wolt'))
        self.config.open_ui()
        with self._mock_wolt({'W9': self._order('W9', acceptance='auto_accepted_by_wolt', order_status='delivered')}):
            self._cron()
        order = self._wolt_order('W9')
        self.assertEqual((order.platform_order_status, order.state), ('delivered', 'paid'))
        self.assertEqual(order.session_id, self.config.current_session_id)
        self.assertEqual(len(order.payment_ids), 1)
        self.assertFalse(self.store.wolt_pending_order_refs)

    def test_queued_order_rejected_at_wolt_is_dropped(self):
        self._queue_while_closed(self._order('W9', acceptance='auto_accepted_by_wolt'))
        self.config.open_ui()
        with self._mock_wolt({'W9': self._order('W9', acceptance='auto_accepted_by_wolt', order_status='rejected')}):
            self._cron()
        self.assertFalse(self._wolt_order('W9'))
        self.assertFalse(self.store.wolt_pending_order_refs)

    def test_queued_order_unknown_to_wolt_is_dropped(self):
        self._queue_while_closed(self._order('W9', acceptance='auto_accepted_by_wolt'))
        self.config.open_ui()
        with self._mock_wolt({'W9': _response(status=404)}):
            self._cron()
        self.assertFalse(self._wolt_order('W9'))
        self.assertFalse(self.store.wolt_pending_order_refs)

    def test_closed_pos_cron_confirms_queued_waiting_preorder_and_keeps_it(self):
        self._queue_while_closed(self._preorder('W7'))
        with self._mock_wolt({'W7': self._preorder('W7')}) as calls:
            self._cron()
        self.assertEqual(calls, ['GET /v2/orders/W7', 'PUT /orders/W7/confirm-preorder'])
        self.assertEqual(self.store.wolt_pending_order_refs, ['W7'])
        with self._mock_wolt({'W7': self._preorder('W7', 'confirmed')}) as calls:
            self._cron()
        self.assertEqual(calls, ['GET /v2/orders/W7'])
        self.assertEqual(self.store.wolt_pending_order_refs, ['W7'])
        self.assertFalse(self._wolt_order('W7'))

    def test_failed_import_is_queued_and_imported_by_the_next_cron_run(self):
        orders = {'W1': RequestsConnectionError('Wolt is unreachable')}
        with self._mock_wolt(orders):
            self.assertEqual(self._post(self._notification('CREATED')).status_code, 503)
        self.assertFalse(self._wolt_order())
        self.assertEqual(self.store.wolt_pending_order_refs, ['W1'])
        orders['W1'] = self._order()
        with self._mock_wolt(orders):
            self._cron()
        self.assertEqual(self._wolt_order().platform_order_status, 'new')
        self.assertFalse(self.store.wolt_pending_order_refs)

    def test_refused_token_refresh_disconnects_the_store(self):
        self.token.expiry = fields.Datetime.now() - datetime.timedelta(minutes=5)
        refused = _response({'error': 'invalid_grant', 'error_description': 'The refresh token expired.'}, status=400)
        with patch(f'{REQUESTS}.post', return_value=refused), self._user_error() as caught:
            self.store._wolt_get_access_token()
        self.assertEqual(str(caught.exception), f"Wolt disconnected store {self.store.display_name}: press Connect to Wolt on the store.")
        self.assertFalse(self.env['platform.order.wolt.token'].search([('store_id', '=', self.store.id)]))

    def test_network_error_during_token_refresh_keeps_the_token(self):
        self.token.expiry = fields.Datetime.now() - datetime.timedelta(minutes=5)
        with patch(f'{REQUESTS}.post', side_effect=RequestsConnectionError('Wolt is unreachable')), self._user_error() as caught:
            self.store._wolt_get_access_token()
        self.assertIn(f"Wolt token refresh failed for {self.store.display_name}", str(caught.exception))
        self.assertTrue(self.token.exists())
        self.assertEqual(self.token.refresh_token, 'RT1')

    def test_same_venue_in_two_companies_goes_to_the_store_of_the_signing_provider(self):
        order_b = self._order('WB1', items=[self._item(self.soup, 500)], **self._self_delivery())
        with self._mock_wolt({'WB1': order_b}):
            response = self._post(self._notification('CREATED', 'WB1'), secret=self.provider_b.sudo().wolt_webhook_secret)
        self.assertEqual(response.status_code, 200)
        order = self._wolt_order('WB1')
        self.assertEqual(order.platform_order_store_id, self.store_b)
        self.assertEqual((order.company_id, order.session_id), (self.company_b, self.config_b.current_session_id))
        self.assertEqual(order.partner_id.company_id, self.company_b)
        self.assertEqual(order.lines.tax_ids, self.vat18_b)

    def test_order_of_one_store_notified_to_another_store_is_ignored(self):
        secret_b = self.provider_b.sudo().wolt_webhook_secret
        with self._mock_wolt({'W1': self._order()}):
            self._post(self._notification('CREATED'))
            order = self._wolt_order()
            self.assertEqual(order.platform_order_store_id, self.store)
            self.assertEqual(self._post(self._notification('PRODUCTION'), secret=secret_b).status_code, 200)
            self.assertEqual(order.platform_order_status, 'new')
            self._post(self._notification('PRODUCTION', venue_id='VENUE2'))
            self.assertEqual(order.platform_order_status, 'new')
            self._post(self._notification('PRODUCTION'))
            self.assertEqual(order.platform_order_status, 'accepted')

    def test_branch_store_receives_the_orders_of_its_own_venue(self):
        with self._mock_wolt({'W20': self._order('W20', venue={'id': 'VENUE2'})}):
            self._post(self._notification('CREATED', 'W20', venue_id='VENUE2'))
        order = self._wolt_order('W20')
        self.assertEqual(order.platform_order_store_id, self.store_branch)
        self.assertEqual(order.session_id, self.config_branch.current_session_id)

    def test_menu_sync_refused_by_wolt_keeps_state_and_queue(self):
        self.store._set_menu_sync_state_done()
        self.cola.list_price = 4.0
        self.assertEqual(self.store.wolt_pending_product_tmpl_ids, self.cola)
        with patch(f'{REQUESTS}.request', return_value=_response(status=429)), patch.object(self.registry['res.users'], '_bus_send') as bus:
            self.store.action_sync_menu()
        self.assertEqual(self.store.menu_sync_state, 'done')
        self.assertEqual(self.store.wolt_pending_product_tmpl_ids, self.cola)
        bus.assert_called_once_with('simple_notification', {
            'type': 'warning',
            'message': "Wolt accepts one menu sync every 15 minutes; try again later.",
        })

    def test_single_value_attribute_is_part_of_the_variant_lookup(self):
        option = {'value_pos_id': f'product_template_attribute_value_{self.large.id}', 'count': 1}
        order = self.store._create_order_from_data(self._order('W30', items=[self._item(self.pizza, 1200, options=[option])]))
        self.assertEqual(order.lines.product_id.product_template_attribute_value_ids, self.thin | self.large)
        self.assertEqual(order.lines.attribute_value_ids, self.thin | self.large)

    def test_option_without_attribute_value_goes_to_the_line_note(self):
        cheese = {'value_pos_id': f'product_template_attribute_value_{self.cheese.id}', 'count': 1}
        options = [cheese, {'value': 'Ketchup', 'count': 2}, {'name': 'Mayo', 'count': 1}]
        order = self.store._create_order_from_data(self._order('W31', items=[self._item(self.burger, 2200, count=2, options=options)]))
        self.assertEqual(order.lines.attribute_value_ids, self.cheese)
        self.assertEqual(order.lines.customer_note, '2 x Ketchup, Mayo')

    def test_line_taxes_are_only_those_of_the_pos_company(self):
        self.assertEqual(self.soup.taxes_id, self.vat18_incl | self.vat18_b)
        order = self.store._create_order_from_data(self._order('W32', items=[self._item(self.soup, 500), self._item(self.water, 200)]))
        lines = {line.product_id.product_tmpl_id: line for line in order.lines}
        self.assertEqual(lines[self.soup].tax_ids, self.vat18_incl)
        self.assertFalse(lines[self.water].tax_ids)
        self.assertEqual((lines[self.water].price_subtotal, lines[self.water].price_subtotal_incl), (2.0, 2.0))

    def test_found_contact_address_is_updated_from_the_order(self):
        partner = self.env['res.partner'].create({
            'name': 'Nino',
            'phone': '+995555123456',
            'street': 'Old street 5',
            'city': 'Kutaisi',
        })
        order = self.store._create_order_from_data(self._order('W33', **self._self_delivery()))
        self.assertEqual(order.partner_id, partner)
        self.assertEqual((partner.street, partner.city, partner.zip), ('Rustaveli 1', 'Tbilisi', '0108'))
        self.assertEqual(self.env['res.partner'].search_count([('phone', '=', '+995555123456')]), 1)

    def test_session_close_pays_collected_and_delivered_orders_without_asking_wolt(self):
        collected, delivered = self._draft('W1'), self._draft('W2')
        collected.platform_order_status = 'collected'
        delivered.platform_order_status = 'delivered'
        with self._mock_wolt() as calls:
            (collected | delivered).cancel_order_from_pos()
        self.assertEqual((collected.state, delivered.state), ('paid', 'paid'))
        self.assertEqual((len(collected.payment_ids), len(delivered.payment_ids)), (1, 1))
        self.assertFalse(calls)

    def test_session_close_pays_order_delivered_at_wolt(self):
        order = self._draft('W1')
        with self._mock_wolt({'W1': self._order(order_status='delivered')}) as calls:
            order.cancel_order_from_pos()
        self.assertEqual((order.platform_order_status, order.state), ('delivered', 'paid'))
        self.assertEqual(calls, ['GET /v2/orders/W1'])

    def test_session_close_cancels_order_rejected_at_wolt_without_a_note(self):
        order = self._draft('W1')
        with self._mock_wolt({'W1': self._order(order_status='rejected')}) as calls:
            order.cancel_order_from_pos()
        self.assertEqual((order.platform_order_status, order.state), ('cancelled', 'cancel'))
        self.assertNotIn("Wolt reports this order as", self._messages(order))
        self.assertEqual(calls, ['GET /v2/orders/W1'])

    def test_session_close_cancels_refunded_and_other_orders_without_payment(self):
        refunded, other = self._draft('W1', acceptance='auto_accepted_by_wolt'), self._draft('W2', acceptance='auto_accepted_by_wolt')
        orders = {
            'W1': self._order('W1', acceptance='auto_accepted_by_wolt', order_status='refunded'),
            'W2': self._order('W2', acceptance='auto_accepted_by_wolt', order_status='other'),
        }
        with self._mock_wolt(orders) as calls:
            (refunded | other).cancel_order_from_pos()
        for order, status in ((refunded, 'refunded'), (other, 'other')):
            self.assertEqual((order.platform_order_status, order.state), ('cancelled', 'cancel'))
            self.assertFalse(order.payment_ids)
            expected = f"Wolt reports this order as {status}: Odoo cancelled it without payment when the session was closed."
            self.assertIn(expected, self._messages(order))
        self.assertCountEqual(calls, ['GET /v2/orders/W1', 'GET /v2/orders/W2'])

    def test_session_close_rejects_instant_order_not_yet_accepted_at_wolt(self):
        order = self._draft('W1')
        with self._mock_wolt({'W1': self._order()}) as calls:
            order.cancel_order_from_pos()
        self.assertEqual(calls, ['GET /v2/orders/W1', 'PUT /orders/W1/reject'])
        self.assertEqual((order.platform_order_status, order.state), ('cancelled', 'cancel'))

    def test_session_close_refuses_order_accepted_at_wolt_and_does_not_reject_it(self):
        order = self._draft('W1')
        accepted = self._order(acceptance='accepted_by_venue')
        with self._mock_wolt({'W1': accepted}) as calls, self._user_error() as caught:
            order.cancel_order_from_pos()
        self.assertIn("Wolt order Wolt #042 is still in progress at Wolt", str(caught.exception))
        self.assertEqual(calls, ['GET /v2/orders/W1'])
        self.assertEqual((order.platform_order_status, order.state), ('new', 'draft'))

    def test_session_close_with_an_order_in_production_changes_no_order(self):
        rejectable, in_production, delivered = self._draft('W1'), self._draft('W2', order_number='043'), self._draft('W3', order_number='044')
        orders = {
            'W1': self._order('W1'),
            'W2': self._order('W2', acceptance='accepted_by_venue', order_status='production', order_number='043'),
            'W3': self._order('W3', order_status='delivered', order_number='044'),
        }
        with self._mock_wolt(orders) as calls, self._user_error() as caught:
            (rejectable | in_production | delivered).cancel_order_from_pos()
        self.assertIn("Wolt order Wolt #043 is still in progress at Wolt", str(caught.exception))
        self.assertNotIn("#044", str(caught.exception))
        self.assertFalse([call for call in calls if not call.startswith('GET')])
        for order in rejectable | in_production | delivered:
            self.assertEqual((order.platform_order_status, order.state), ('new', 'draft'))

    def test_session_close_with_wolt_unreachable_changes_no_order(self):
        order = self._draft('W1')
        unreachable = {'W1': RequestsConnectionError('Wolt is unreachable')}
        with self._mock_wolt(unreachable), self._user_error() as caught:
            order.cancel_order_from_pos()
        self.assertIn("Odoo cannot check Wolt order Wolt #042", str(caught.exception))
        self.assertEqual((order.platform_order_status, order.state), ('new', 'draft'))

    def test_session_close_returns_core_result_and_cancels_other_drafts_as_core_does(self):
        wolt_order = self._draft('W1')
        line = {'product_id': self.cola.product_variant_id.id}
        plain, _refund = self.create_backend_pos_order({'pos_config': self.config, 'line_data': [line]})
        with self._mock_wolt({'W1': self._order()}):
            result = (wolt_order | plain).cancel_order_from_pos()
        self.assertEqual((wolt_order.state, plain.state), ('cancel', 'cancel'))
        self.assertEqual(list(result), ['pos.order'])
        self.assertEqual([record['id'] for record in result['pos.order']], plain.ids)

    def test_webhook_status_change_is_authored_by_odoobot(self):
        with self._mock_wolt({'W1': self._order()}):
            self._post(self._notification('CREATED'))
            self._post(self._notification('PRODUCTION'))
        changes = self._wolt_order().message_ids.filtered(lambda message: 'Platform status updated to accepted' in message.body)
        self.assertEqual(changes.author_id, self.env.ref('base.partner_root'))
