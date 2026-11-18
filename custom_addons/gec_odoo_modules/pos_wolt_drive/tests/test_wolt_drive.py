from datetime import datetime

from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import DELIVERY, LOCATION, PROMISE, WoltDriveCommon, _response

DUPLICATE_ORDER = {
    'error_code': 'DUPLICATE_ORDER',
    'reason': 'An order with this merchant_order_reference_id already exists',
    'details': '',
}
SERVER_ERROR = {'error_code': 'GENERIC_INTERNAL_ERROR', 'reason': 'Internal server error', 'details': ''}
NOT_BOOKED = {
    'wolt_drive_status': 'requested',
    'wolt_drive_ref': False,
    'wolt_drive_tracking_url': False,
    'wolt_drive_price': 0,
    'wolt_drive_pickup_eta': False,
    'wolt_drive_dropoff_eta': False,
}


@tagged('post_install', '-at_install')
class TestWoltDriveBooking(WoltDriveCommon):

    def _book(self, order=None):
        return (order or self.order).wolt_drive_book('P1', LOCATION)

    def _sent_reference(self, request):
        return request.call_args.kwargs['json']['merchant_order_reference_id']

    def test_quote_book_and_events_to_delivered(self):
        with self._wolt_answers(_response(PROMISE, 201), _response(DELIVERY, 201)) as request:
            quote = self.order.wolt_drive_quote()
            self.assertEqual(quote, {'promise_id': 'P1', 'dropoff_location': LOCATION, 'price': 8.6, 'eta_minutes': 35})
            self.assertTrue(self.order.wolt_drive_book(quote['promise_id'], quote['dropoff_location']))
        self.assertEqual(self._paths(request), [('POST', '/v1/venues/DV1/shipment-promises'), ('POST', '/v1/venues/DV1/deliveries')])
        promise_call, delivery_call = request.call_args_list
        self.assertTrue(promise_call.args[1].startswith('https://daas-public-api.development.dev.woltapi.com/'))
        self.assertEqual(promise_call.kwargs['headers'], {'Authorization': 'Bearer KEY'})
        self.assertEqual(promise_call.kwargs['json']['min_preparation_time_minutes'], 20)
        parcel = {
            'description': self.order.pos_reference,
            'identifier': self.order.tracking_number,
            'count': 1,
            'price': {'amount': 2620, 'currency': self.order.currency_id.name},
        }
        self.assertEqual(delivery_call.kwargs['json'], {
            'shipment_promise_id': 'P1',
            'dropoff': {'location': LOCATION},
            'recipient': {'name': 'Nino', 'phone_number': '+995555123456'},
            'parcels': [parcel],
            'merchant_order_reference_id': f'{self.order.pos_reference}-1',
            'order_number': self.order.tracking_number,
        })
        self.assertRecordValues(self.order, [{
            'wolt_drive_status': 'requested',
            'wolt_drive_ref': 'WOLTREF1',
            'wolt_drive_attempt': 1,
            'wolt_drive_tracking_url': 'https://track.wolt.com/T1',
            'wolt_drive_price': 8.6,
            'wolt_drive_pickup_eta': datetime(2026, 10, 27, 12, 30),
            'wolt_drive_dropoff_eta': False,
        }])
        with self.assertRaisesRegex(UserError, 'already booked'):
            self.order.wolt_drive_quote()
        events = [
            ('order.pickup_started', 'courier_assigned'),
            ('order.pickup_arrival', 'courier_at_pickup'),
            ('order.picked_up', 'picked_up'),
            ('order.dropoff_started', 'picked_up'),
            ('order.dropoff_arrival', 'picked_up'),
            ('order.dropoff_completed', 'delivered'),
            ('order.delivered', 'delivered'),
        ]
        for event_type, status in events:
            with self.subTest(event_type):
                self.assertEqual(self._post_event(event_type).status_code, 200)
                self.assertEqual(self.order.wolt_drive_status, status)

    def test_quote_sends_no_coordinates(self):
        with self._wolt_answers(_response(PROMISE, 201)) as request:
            self.order.wolt_drive_quote()
        self.assertEqual(request.call_args.kwargs['json'], {
            'street': 'Rustaveli Ave 1',
            'city': 'Tbilisi',
            'post_code': '0108',
            'min_preparation_time_minutes': 20,
            'parcels': [{
                'description': self.order.pos_reference,
                'identifier': self.order.tracking_number,
                'count': 1,
                'price': {'amount': 2620, 'currency': self.order.currency_id.name},
            }],
        })

    def test_quote_failures_are_shown_to_the_cashier(self):
        outside = {
            'error_code': 'DROPOFF_OUTSIDE_OF_DELIVERY_AREA',
            'reason': 'Dropoff location is outside of the delivery area',
            'details': 'Delivery distance is longer than maximum allowed distance',
        }
        with self._wolt_answers(_response(outside, 400)):
            with self.assertRaisesRegex(UserError, 'DROPOFF_OUTSIDE_OF_DELIVERY_AREA Dropoff location is outside of the delivery area'):
                self.order.wolt_drive_quote()
        with self._wolt_answers(_response({**PROMISE, 'is_binding': False}, 201)):
            with self.assertRaisesRegex(UserError, "Add the customer's street and city or zip"):
                self.order.wolt_drive_quote()
        with self._wolt_answers(Timeout("read timed out")):
            with self.assertRaisesRegex(UserError, 'Wolt Drive cannot be reached'):
                self.order.wolt_drive_quote()

    def test_cancel_before_pickup(self):
        with self._wolt_answers(_response(DELIVERY, 201), _response({'status': 'REJECTED'})) as request:
            self._book()
            self.assertTrue(self.order.wolt_drive_cancel())
        self.assertEqual(self._paths(request)[-1], ('PATCH', '/order/WOLTREF1/status/cancel'))
        self.assertEqual(list(request.call_args.kwargs['json']), ['reason'])
        self.assertEqual(self.order.wolt_drive_status, 'cancelled')

    def test_cancel_refused_after_pickup_started(self):
        self._set_courier('requested')
        self._post_event('order.pickup_started')
        self.assertEqual(self.order.wolt_drive_status, 'courier_assigned')
        with self._wolt_answers() as request:
            with self.assertRaisesRegex(UserError, 'Contact Wolt support to cancel'):
                self.order.wolt_drive_cancel()
        request.assert_not_called()
        self.assertEqual(self.order.wolt_drive_status, 'courier_assigned')

    def test_cancel_refused_without_wolt_reference(self):
        self._set_courier('requested', ref=False)
        with self._wolt_answers() as request:
            with self.assertRaisesRegex(UserError, 'Wolt has not confirmed this courier yet'):
                self.order.wolt_drive_cancel()
        request.assert_not_called()
        self.assertEqual(self.order.wolt_drive_status, 'requested')

    def test_cancel_refused_when_nothing_was_booked(self):
        with self._wolt_answers() as request:
            with self.assertRaises(UserError):
                self.order.wolt_drive_cancel()
        request.assert_not_called()

    def test_cancel_answer_too_late_keeps_the_status(self):
        too_late = {'error_code': 'INVALID_ORDER_STATE_TRANSITION', 'reason': 'The courier already started the pickup', 'details': ''}
        self._set_courier('requested')
        with self._wolt_answers(_response(too_late, 400)):
            with self.assertRaisesRegex(UserError, 'INVALID_ORDER_STATE_TRANSITION'):
                self.order.wolt_drive_cancel()
        self.assertEqual(self.order.wolt_drive_status, 'requested')

    def test_timeout_then_retry_sends_the_same_reference(self):
        with self._wolt_answers(Timeout("read timed out"), _response(DELIVERY, 201)) as request:
            self.assertFalse(self._book())
            first_reference = self._sent_reference(request)
            self.assertRecordValues(self.order, [{**NOT_BOOKED, 'wolt_drive_attempt': 1}])
            self.assertIn(first_reference, self.order.message_ids[0].body)
            self.assertTrue(self._book())
            self.assertEqual(self._sent_reference(request), first_reference)
        self.assertEqual(first_reference, f'{self.order.pos_reference}-1')
        self.assertRecordValues(self.order, [{'wolt_drive_status': 'requested', 'wolt_drive_ref': 'WOLTREF1', 'wolt_drive_attempt': 1}])

    def test_connection_error_waits_for_wolt(self):
        with self._wolt_answers(RequestsConnectionError("refused")):
            self.assertFalse(self._book())
        self.assertRecordValues(self.order, [{**NOT_BOOKED, 'wolt_drive_attempt': 1}])

    def test_duplicate_order_keeps_waiting_and_order_received_relinks_it(self):
        with self._wolt_answers(_response(DUPLICATE_ORDER, 400), _response(DUPLICATE_ORDER, 400)) as request:
            self.assertFalse(self._book())
            self.assertFalse(self._book())
        self.assertEqual(self._sent_reference(request), f'{self.order.pos_reference}-1')
        self.assertRecordValues(self.order, [{**NOT_BOOKED, 'wolt_drive_attempt': 1}])
        details = {
            'merchant_order_reference_id': f'{self.order.pos_reference}-1',
            'price': {'amount': 860, 'currency': 'GEL'},
            'wolt_order_reference_id': 'WOLTREF9',
        }
        self.assertEqual(self._post_event('order.received', details).status_code, 200)
        self.assertRecordValues(self.order, [{
            'wolt_drive_status': 'requested',
            'wolt_drive_ref': 'WOLTREF9',
            'wolt_drive_attempt': 1,
            'wolt_drive_price': 8.6,
        }])

    def test_server_error_then_success_retry_sends_the_same_reference(self):
        with self._wolt_answers(_response(SERVER_ERROR, 500), _response(DELIVERY, 201)) as request:
            self.assertFalse(self._book())
            first_reference = self._sent_reference(request)
            self.assertRecordValues(self.order, [{**NOT_BOOKED, 'wolt_drive_attempt': 1}])
            self.assertTrue(self._book())
            self.assertEqual(self._sent_reference(request), first_reference)
        self.assertEqual(self.order.wolt_drive_ref, 'WOLTREF1')

    def test_server_error_without_json_body_keeps_waiting(self):
        with self._wolt_answers(_response(None, 502)):
            self.assertFalse(self._book())
        self.assertRecordValues(self.order, [{**NOT_BOOKED, 'wolt_drive_attempt': 1}])

    def test_rebook_after_each_final_status(self):
        cases = [
            ('delivered', False),
            ('not_delivered', True),
            ('cancelled', True),
        ]
        for status, allowed in cases:
            with self.subTest(status):
                self._set_courier(status)
                if not allowed:
                    with self._wolt_answers() as request:
                        with self.assertRaisesRegex(UserError, 'already delivered'):
                            self.order.wolt_drive_quote()
                        with self.assertRaisesRegex(UserError, 'already delivered'):
                            self._book()
                    request.assert_not_called()
                    continue
                with self._wolt_answers(_response({**DELIVERY, 'wolt_order_reference_id': 'WOLTREF2'}, 201)) as request:
                    self.assertTrue(self._book())
                self.assertEqual(self._sent_reference(request), f'{self.order.pos_reference}-2')
                self.assertRecordValues(self.order, [{'wolt_drive_status': 'requested', 'wolt_drive_ref': 'WOLTREF2', 'wolt_drive_attempt': 2}])

    def test_booking_refused_while_a_courier_is_active(self):
        for status in ('requested', 'courier_assigned', 'courier_at_pickup', 'picked_up'):
            with self.subTest(status):
                self._set_courier(status)
                with self._wolt_answers() as request:
                    with self.assertRaisesRegex(UserError, 'already booked'):
                        self._book()
                request.assert_not_called()

    def test_booking_refused_while_status_updates_are_not_set_up(self):
        with self._wolt_answers() as request:
            with self.assertRaisesRegex(UserError, 'status updates are not set up'):
                self.order_unregistered_pos.wolt_drive_quote()
            with self.assertRaisesRegex(UserError, 'status updates are not set up'):
                self._book(self.order_unregistered_pos)
        request.assert_not_called()
        self.assertFalse(self.order_unregistered_pos.wolt_drive_status)

    def test_booking_refused_when_the_order_is_not_a_paid_sale(self):
        draft = self._create_order(self.customer, state='draft')
        refund = self._create_order(self.customer, amount=-10.0)
        with self._wolt_answers() as request:
            for order in (draft, refund):
                with self.assertRaisesRegex(UserError, 'Only a paid sale'):
                    order.wolt_drive_quote()
        request.assert_not_called()

    def test_booking_refused_without_a_venue(self):
        self.wolt_config.wolt_drive_venue_id = False
        with self._wolt_answers() as request:
            with self.assertRaisesRegex(UserError, 'not set up for this Point of Sale'):
                self.order.wolt_drive_quote()
        request.assert_not_called()

    def test_booking_refused_for_a_customer_without_address_or_phone(self):
        with self._wolt_answers() as request:
            for order in (self.order_without_address, self.order_without_phone):
                with self.subTest(order.partner_id.name):
                    with self.assertRaisesRegex(UserError, 'needs a phone number, a street and a city or zip'):
                        order.wolt_drive_quote()
                    with self.assertRaisesRegex(UserError, 'needs a phone number, a street and a city or zip'):
                        self._book(order)
        request.assert_not_called()

    def test_cashier_books_and_cancels_but_cannot_read_the_key(self):
        order = self.order.with_user(self.cashier)
        with self._wolt_answers(_response(PROMISE, 201), _response(DELIVERY, 201), _response({'status': 'REJECTED'})) as request:
            quote = order.wolt_drive_quote()
            self.assertTrue(order.wolt_drive_book(quote['promise_id'], quote['dropoff_location']))
            self.assertTrue(order.wolt_drive_cancel())
        self.assertEqual(request.call_args.kwargs['headers'], {'Authorization': 'Bearer KEY'})
        self.assertEqual(self.order.wolt_drive_status, 'cancelled')
        config = self.wolt_config.with_user(self.cashier)
        self.assertEqual(config.wolt_drive_venue_id, 'DV1')
        self.assertTrue(config.wolt_drive_webhook_ready)
        for name in ('wolt_drive_merchant_id', 'wolt_drive_api_key', 'wolt_drive_test_mode', 'wolt_drive_webhook_secret'):
            with self.subTest(name), self.assertRaises(AccessError):
                config.read([name])

    def test_tolerant_reads_of_a_success_answer(self):
        answers = {
            'no tracking and an ETA that is not a text': {
                'wolt_order_reference_id': 'WOLTREF2',
                'price': {'amount': 860, 'currency': 'GEL'},
                'pickup': {'eta': 1790000000},
                'dropoff': {'eta': None},
            },
            'only the reference': {'wolt_order_reference_id': 'WOLTREF2'},
            'sections that are null': {'wolt_order_reference_id': 'WOLTREF2', 'tracking': None, 'pickup': None, 'dropoff': None},
        }
        for case, answer in answers.items():
            with self.subTest(case):
                self.order.write({'wolt_drive_status': False, 'wolt_drive_attempt': 0})
                with self._wolt_answers(_response(answer, 201)):
                    self.assertTrue(self._book())
                self.assertRecordValues(self.order, [{
                    'wolt_drive_status': 'requested',
                    'wolt_drive_ref': 'WOLTREF2',
                    'wolt_drive_tracking_url': False,
                    'wolt_drive_pickup_eta': False,
                    'wolt_drive_dropoff_eta': False,
                }])

    def test_validation_error_shows_every_detail_message(self):
        invalid = {
            'detail': [
                {'type': 'value_error', 'loc': ['body', 'recipient', 'phone_number'], 'msg': 'Value error, Impossible phone number: 123'},
                {'type': 'missing', 'loc': ['body', 'parcels'], 'msg': 'Field required'},
            ],
        }
        with self._wolt_answers(_response(invalid, 422)):
            with self.assertRaisesRegex(UserError, 'Impossible phone number: 123; Field required'):
                self._book()
        self.assertFalse(self.order.wolt_drive_status)

    def test_expired_promise_asks_to_press_the_button_again(self):
        expired = {'error_code': 'SHIPMENT_PROMISE_NOT_FOUND', 'reason': 'Shipment promise not found', 'details': ''}
        with self._wolt_answers(_response(expired, 404)):
            with self.assertRaisesRegex(UserError, r'The price expired: press Wolt Courier again\.'):
                self._book()
        self.assertFalse(self.order.wolt_drive_status)

    def test_other_booking_error_is_shown_with_its_code(self):
        closed = {'error_code': 'VENUE_CLOSED', 'reason': 'Venue is closed', 'details': ''}
        with self._wolt_answers(_response(closed, 400)):
            with self.assertRaisesRegex(UserError, 'VENUE_CLOSED Venue is closed'):
                self._book()
        self.assertFalse(self.order.wolt_drive_status)

    def test_pos_ui_booking(self):
        self.env['pos.printer'].search([]).unlink()
        with self._wolt_answers(_response(PROMISE, 201), _response(DELIVERY, 201)):
            self.start_pos_tour('test_wolt_drive_booking')
        self.assertEqual(self.order.wolt_drive_status, 'requested')
