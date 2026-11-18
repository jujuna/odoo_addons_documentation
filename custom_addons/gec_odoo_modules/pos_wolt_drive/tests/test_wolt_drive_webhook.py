import json
from datetime import datetime

from requests.exceptions import ConnectionError as RequestsConnectionError

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import SECRET, WoltDriveCommon, _response, _webhook_config

CONFIG_LOGGER = 'odoo.addons.pos_wolt_drive.models.pos_config'
FINAL_EVENTS = {
    'delivered': 'order.delivered',
    'not_delivered': 'order.not_delivered',
    'cancelled': 'order.rejected',
}
SECRET_FIELDS = ('wolt_drive_merchant_id', 'wolt_drive_api_key', 'wolt_drive_test_mode', 'wolt_drive_webhook_secret')


@tagged('post_install', '-at_install')
class TestWoltDriveWebhook(WoltDriveCommon):

    def _relink_details(self, order, attempt, **details):
        return {'merchant_order_reference_id': f'{order.pos_reference}-{attempt}', 'wolt_order_reference_id': 'WOLTREF9', **details}

    def test_event_signed_with_a_wrong_secret_is_refused(self):
        self._set_courier('requested')
        self.assertEqual(self._post_event('order.picked_up', secret='wrong').status_code, 403)
        self.assertEqual(self.order.wolt_drive_status, 'requested')

    def test_event_is_refused_when_no_status_updates_are_registered(self):
        self._set_courier('requested', order=self.order_unregistered_pos)
        response = self._post_event('order.picked_up', {'venue_id': 'DV2'}, config=self.unregistered_config)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.order_unregistered_pos.wolt_drive_status, 'requested')

    def test_event_signed_for_another_point_of_sale_is_refused(self):
        self.unregistered_config.sudo().wolt_drive_webhook_secret = 'O' * 64
        self._set_courier('requested')
        self.assertEqual(self._post_event('order.picked_up', secret='O' * 64).status_code, 403)
        self.assertEqual(self.order.wolt_drive_status, 'requested')

    def test_event_with_a_token_that_is_not_signed_with_hs256_is_refused(self):
        self._set_courier('requested')
        self.assertEqual(self._post_event('order.picked_up', alg='none').status_code, 403)
        self.assertEqual(self.order.wolt_drive_status, 'requested')

    def test_malformed_requests_are_refused(self):
        self.assertEqual(self._post_raw('not json').status_code, 400)
        self.assertEqual(self._post_raw(json.dumps({'token': None})).status_code, 403)
        self.assertEqual(self._post_raw(json.dumps({'token': 'a.b.c'})).status_code, 403)
        self.assertEqual(self._post_raw(json.dumps({})).status_code, 403)
        unknown_config = self.url_open('/wolt_drive/webhook/0', data=json.dumps({'token': 'x'}), headers={'Content-Type': 'application/json'})
        self.assertEqual(unknown_config.status_code, 403)

    def test_event_chatter_note_is_posted_by_odoobot(self):
        self._set_courier('requested')
        self._post_event('order.pickup_started')
        message = self.order.message_ids[0]
        self.assertEqual(message.author_id, self.env.ref('base.partner_root'))
        self.assertIn('Courier on the Way', message.body)

    def test_late_event_does_not_move_the_status_backwards(self):
        self._set_courier('picked_up')
        self.assertEqual(self._post_event('order.pickup_started').status_code, 200)
        self.assertEqual(self.order.wolt_drive_status, 'picked_up')
        self._post_event('order.pickup_arrival')
        self.assertEqual(self.order.wolt_drive_status, 'picked_up')

    def test_events_that_end_the_delivery(self):
        events = [('order.not_delivered', 'not_delivered'), ('order.customer_no_show', 'not_delivered'), ('order.rejected', 'cancelled')]
        for event_type, status in events:
            with self.subTest(event_type):
                self._set_courier('picked_up')
                self._post_event(event_type)
                self.assertEqual(self.order.wolt_drive_status, status)

    def test_estimate_events_update_the_times_without_moving_the_status(self):
        self._set_courier('courier_assigned')
        details = {'pickup': {'eta': '2026-10-27T12:40:00Z'}, 'dropoff': {'eta': {'min': '2026-10-27T12:55:00Z', 'max': '2026-10-27T13:05:00Z'}}}
        self._post_event('order.dropoff_eta_updated', details)
        self.assertRecordValues(self.order, [{
            'wolt_drive_status': 'courier_assigned',
            'wolt_drive_pickup_eta': datetime(2026, 10, 27, 12, 40),
            'wolt_drive_dropoff_eta': datetime(2026, 10, 27, 13, 5),
        }])

    def test_nothing_is_written_after_a_final_status(self):
        times = {'wolt_drive_pickup_eta': datetime(2026, 10, 27, 12, 30), 'wolt_drive_dropoff_eta': datetime(2026, 10, 27, 13, 0)}
        details = {'pickup': {'eta': '2026-10-27T15:00:00Z'}, 'dropoff': {'eta': {'max': '2026-10-27T16:00:00Z'}}}
        for final_status in FINAL_EVENTS:
            for event_type in ('order.pickup_eta_updated', 'order.picked_up', *FINAL_EVENTS.values()):
                with self.subTest(f'{event_type} after {final_status}'):
                    self._set_courier(final_status)
                    self.order.write(times)
                    messages = len(self.order.message_ids)
                    self._post_event(event_type, details)
                    self.assertRecordValues(self.order, [{'wolt_drive_status': final_status, **times}])
                    self.assertEqual(len(self.order.message_ids), messages)

    def test_relink_by_webhook_when_the_booking_was_rolled_back(self):
        details = self._relink_details(self.order, 1, price={'amount': 860, 'currency': 'GEL'}, pickup={'eta': '2026-10-27T12:30:00Z'})
        self.assertEqual(self._post_event('order.received', details).status_code, 200)
        self.assertRecordValues(self.order, [{
            'wolt_drive_status': 'requested',
            'wolt_drive_ref': 'WOLTREF9',
            'wolt_drive_attempt': 1,
            'wolt_drive_price': 8.6,
            'wolt_drive_tracking_url': False,
            'wolt_drive_pickup_eta': datetime(2026, 10, 27, 12, 30),
        }])
        self._post_event('order.picked_up', {'wolt_order_reference_id': 'WOLTREF9'})
        self.assertEqual(self.order.wolt_drive_status, 'picked_up')

    def test_relink_by_webhook_of_a_rebooking_that_was_rolled_back(self):
        self._set_courier('cancelled', ref='OLDREF')
        self._post_event('order.received', self._relink_details(self.order, 2))
        self.assertRecordValues(self.order, [{'wolt_drive_status': 'requested', 'wolt_drive_ref': 'WOLTREF9', 'wolt_drive_attempt': 2}])

    def test_relink_ignores_events_that_do_not_belong_to_the_order(self):
        self._set_courier('cancelled', ref='OLDREF')
        cases = {
            'same attempt that already has a Wolt reference': self._relink_details(self.order, 1),
            'older attempt': self._relink_details(self.order, 0),
            'another venue': self._relink_details(self.order, 2, venue_id='DV2'),
            'no venue': self._relink_details(self.order, 2, venue_id=None),
            'unknown receipt number': {**self._relink_details(self.order, 2), 'merchant_order_reference_id': 'Order 99999-999-9999-2'},
            'reference without attempt number': {**self._relink_details(self.order, 2), 'merchant_order_reference_id': self.order.pos_reference},
            'no merchant reference': {**self._relink_details(self.order, 2), 'merchant_order_reference_id': None},
        }
        for case, details in cases.items():
            with self.subTest(case):
                self.assertEqual(self._post_event('order.received', details).status_code, 200)
                self.assertRecordValues(self.order, [{'wolt_drive_status': 'cancelled', 'wolt_drive_ref': 'OLDREF', 'wolt_drive_attempt': 1}])
        self.assertEqual(self._post_event('order.picked_up', {'wolt_order_reference_id': None}).status_code, 200)

    def test_register_webhook_generates_the_secret_once_and_deletes_old_duplicates(self):
        config = self.unregistered_config
        url = config._wolt_drive_webhook_url()
        self.assertTrue(url.endswith(f'/wolt_drive/webhook/{config.id}'))
        old, new, other = _webhook_config('W-old', url), _webhook_config('W-new', url), _webhook_config('W-other', 'https://other.example/hook')
        with self._wolt_answers(_response(new, 201), _response([old, new, other]), _response(None, 204)) as request:
            action = config.action_wolt_drive_register_webhook()
        self.assertEqual(action['tag'], 'display_notification')
        secret = config.sudo().wolt_drive_webhook_secret
        self.assertRegex(secret, '^[0-9a-f]{64}$')
        self.assertEqual(self._paths(request), [
            ('POST', '/v1/merchants/M2/webhooks'),
            ('GET', '/v1/merchants/M2/webhooks'),
            ('DELETE', '/v1/merchants/M2/webhooks/W-old'),
        ])
        body = request.call_args_list[0].kwargs['json']
        self.assertEqual((body['callback_url'], body['client_secret']), (url, secret))
        self.assertTrue(config.wolt_drive_webhook_ready)
        newer = _webhook_config('W-newer', url)
        with self._wolt_answers(_response(newer, 201), _response([new, newer]), _response(None, 204)) as request:
            config.action_wolt_drive_register_webhook()
        self.assertEqual(request.call_args_list[0].kwargs['json']['client_secret'], secret)
        self.assertEqual(config.sudo().wolt_drive_webhook_secret, secret)
        self.assertEqual(self._paths(request)[-1], ('DELETE', '/v1/merchants/M2/webhooks/W-new'))

    def test_register_webhook_cleanup_failure_is_logged_not_raised(self):
        config = self.unregistered_config
        url = config._wolt_drive_webhook_url()
        new = _webhook_config('W-new', url)
        failures = {
            'listing fails': (RequestsConnectionError("refused"),),
            'deleting fails': (_response([_webhook_config('W-old', url), new]), RequestsConnectionError("refused")),
        }
        for case, cleanup in failures.items():
            with self.subTest(case):
                config.sudo().wolt_drive_webhook_secret = False
                with self._wolt_answers(_response(new, 201), *cleanup), self.assertLogs(CONFIG_LOGGER, 'ERROR'):
                    action = config.action_wolt_drive_register_webhook()
                self.assertEqual(action['tag'], 'display_notification')
                self.assertTrue(config.wolt_drive_webhook_ready)

    def test_register_webhook_that_fails_leaves_no_secret(self):
        config = self.unregistered_config
        refused = {'detail': [{'type': 'missing', 'loc': ['body', 'callback_url'], 'msg': 'Field required'}]}
        answers = {
            'Wolt Drive cannot be reached': RequestsConnectionError("refused"),
            'Wolt Drive refused the webhook': _response(refused, 422),
        }
        for message, answer in answers.items():
            with self.subTest(message), self._wolt_answers(answer):
                with self.assertRaisesRegex(UserError, message):
                    config.action_wolt_drive_register_webhook()
                self.assertFalse(config.wolt_drive_webhook_ready)

    def test_register_webhook_needs_the_merchant_and_an_administrator(self):
        config = self.unregistered_config
        with self._wolt_answers() as request:
            with self.assertRaisesRegex(AccessError, 'Only administrators'):
                config.with_user(self.cashier).action_wolt_drive_register_webhook()
            config.wolt_drive_merchant_id = False
            with self.assertRaisesRegex(UserError, 'merchant ID and API key'):
                config.action_wolt_drive_register_webhook()
        request.assert_not_called()

    def test_switching_test_mode_clears_the_secret_and_stops_bookings(self):
        self.wolt_config.wolt_drive_test_mode = False
        self.assertFalse(self.wolt_config.sudo().wolt_drive_webhook_secret)
        self.assertFalse(self.wolt_config.wolt_drive_webhook_ready)
        with self._wolt_answers() as request:
            with self.assertRaisesRegex(UserError, 'status updates are not set up'):
                self.order.wolt_drive_quote()
        request.assert_not_called()

    def test_changing_merchant_or_key_clears_the_secret(self):
        for values in ({'wolt_drive_merchant_id': 'M9'}, {'wolt_drive_api_key': 'KEY9'}):
            with self.subTest(values):
                self.wolt_config.sudo().wolt_drive_webhook_secret = SECRET
                self.wolt_config.write(values)
                self.assertFalse(self.wolt_config.sudo().wolt_drive_webhook_secret)

    def test_saving_unchanged_values_keeps_the_secret(self):
        self.wolt_config.write({
            'wolt_drive_merchant_id': 'M1',
            'wolt_drive_api_key': 'KEY',
            'wolt_drive_test_mode': True,
            'wolt_drive_preparation_minutes': 40,
        })
        self.assertEqual(self.wolt_config.sudo().wolt_drive_webhook_secret, SECRET)
        self.assertTrue(self.wolt_config.wolt_drive_webhook_ready)

    def test_only_the_point_of_sale_whose_key_changed_loses_its_secret(self):
        self.unregistered_config.sudo().wolt_drive_webhook_secret = SECRET
        (self.wolt_config | self.unregistered_config).write({'wolt_drive_api_key': 'KEY'})
        self.assertEqual(self.wolt_config.sudo().wolt_drive_webhook_secret, SECRET)
        self.assertFalse(self.unregistered_config.sudo().wolt_drive_webhook_secret)

    def test_pos_data_load_has_no_merchant_key_test_mode_or_secret(self):
        for user in (self.env.user, self.cashier):
            with self.subTest(user.login):
                config = self.wolt_config.with_user(user)
                record = self.env['pos.config'].with_user(user)._load_pos_data_read(config, config)[0]
                self.assertEqual(record['wolt_drive_venue_id'], 'DV1')
                self.assertEqual(record['wolt_drive_preparation_minutes'], 20)
                for name in SECRET_FIELDS:
                    self.assertNotIn(name, record)
