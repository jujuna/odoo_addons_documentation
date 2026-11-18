from datetime import time

import psycopg2

from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import DAY, HOTEL_TZ, UTC, HotelRmsSaleCommon

WRITES = (('hotel.rms.reservation', 'create'), ('hotel.rms.reservation', 'write'),
          ('hotel.rms.price', 'create'), ('hotel.rms.price', 'write'))


@tagged('post_install', '-at_install')
class TestReservationSync(HotelRmsSaleCommon):

    def _cancel_and_sync(self, order):
        order._action_cancel()
        self._sync()
        return self._reservations()

    def test_a_confirmed_rental_order_becomes_a_reservation(self):
        order = self._order(arrival_offset=3, nights=3, rooms=2, total=600)
        self._sync()
        reservation = self._reservations()
        self.assertEqual(reservation.source_ref, f"sale.order.line,{order.order_line.id}")
        self.assertEqual((reservation.arrival, reservation.departure, reservation.nights),
                         (self.today + 3 * DAY, self.today + 6 * DAY, 3))
        self.assertEqual((reservation.rooms, reservation.revenue, reservation.status), (2, 600, 'confirmed'))
        self.assertEqual((reservation.room_type_id, reservation.cancel_date), (self.room, False))
        self.assertTrue(self.hotel.last_data_at)
        self.assertFalse(self.hotel.is_stale)

    def test_revenue_is_the_line_subtotal(self):
        order = self._order(rooms=2, total=500)
        self._sync()
        self.assertEqual(self._reservations().revenue, order.order_line.price_subtotal)
        self.assertEqual(self._reservations().revenue, 500)

    def test_arrival_is_the_local_date_of_the_pickup(self):
        order = self._order(arrival_offset=4, nights=2, pickup=time(1), checkout=time(1))
        self.assertEqual(order.rental_start_date.date(), self.today + 3 * DAY)
        self._sync()
        reservation = self._reservations()
        self.assertEqual((reservation.arrival, reservation.departure), (self.today + 4 * DAY, self.today + 6 * DAY))

    def test_a_late_checkout_adds_no_night(self):
        self._order(arrival_offset=3, nights=2, checkout=time(19))
        self._sync()
        self.assertEqual(self._reservations().nights, 2)

    def test_booking_date_is_the_order_day(self):
        order = self._order(arrival_offset=3)
        self._sync()
        created = order.create_date.replace(tzinfo=UTC).astimezone(HOTEL_TZ).date()
        self.assertEqual(self._reservations().booking_date, created)

    def test_booking_date_never_falls_after_the_arrival(self):
        self._order(arrival_offset=-5, nights=2)
        self._sync()
        self.assertEqual(self._reservations().booking_date, self.today - 5 * DAY)

    def test_a_quotation_is_not_read(self):
        self._order(confirm=False)
        self._sync()
        self.assertFalse(self._reservations())

    def test_a_product_that_is_no_room_type_is_not_read(self):
        other = self._create_room_product("Parking")
        self._order(product=other)
        self._sync()
        self.assertFalse(self._reservations())

    def test_cancelling_the_order_cancels_the_reservation_today(self):
        order = self._order()
        self._sync()
        self.assertEqual(self._reservations().status, 'confirmed')
        reservation = self._cancel_and_sync(order)
        self.assertEqual((reservation.status, reservation.cancel_date), ('cancelled', self.today))

    def test_a_draft_after_the_cancellation_stays_cancelled_with_its_date(self):
        order = self._order()
        self._sync()
        reservation = self._cancel_and_sync(order)
        reservation.cancel_date = self.today - 2 * DAY
        order.action_draft()
        self._sync()
        self.assertEqual((reservation.status, reservation.cancel_date), ('cancelled', self.today - 2 * DAY))

    def test_a_draft_order_cancels_a_known_reservation(self):
        order = self._order()
        self._sync()
        order.write({'state': 'draft'})
        self._sync()
        reservation = self._reservations()
        self.assertEqual((reservation.status, reservation.cancel_date), ('cancelled', self.today))

    def test_reconfirming_clears_the_cancellation_date(self):
        order = self._order()
        self._sync()
        reservation = self._cancel_and_sync(order)
        order.action_draft()
        order.action_confirm()
        self._sync()
        self.assertEqual((reservation.status, reservation.cancel_date), ('confirmed', False))

    def test_a_line_that_no_longer_exists_cancels_the_reservation(self):
        order = self._order()
        self._sync()
        order.write({'state': 'draft'})
        order.order_line.unlink()
        self._sync()
        reservation = self._reservations()
        self.assertEqual((reservation.status, reservation.cancel_date), ('cancelled', self.today))

    def test_a_cancelled_reservation_of_a_deleted_line_keeps_its_date(self):
        order = self._order()
        self._sync()
        reservation = self._cancel_and_sync(order)
        reservation.cancel_date = self.today - 2 * DAY
        order.action_draft()
        order.order_line.unlink()
        self._sync()
        self.assertEqual((reservation.status, reservation.cancel_date), ('cancelled', self.today - 2 * DAY))

    def test_a_hand_edited_reference_is_ignored(self):
        Reservation = self.env['hotel.rms.reservation']
        values = {'property_id': self.hotel.id, 'room_type_id': self.room.id,
                  'arrival': self.today, 'departure': self.today + DAY}
        manual = Reservation.create([dict(values, source_ref=ref)
                                     for ref in ('MANUAL-1', 'sale.order.line,abc', 'sale.order.line.')])
        self._order()
        self._sync()
        self.assertEqual(manual.mapped('status'), ['confirmed'] * 3)

    def test_a_reference_of_a_line_that_never_existed_is_cancelled(self):
        ghost = self.env['hotel.rms.reservation'].create({
            'property_id': self.hotel.id, 'room_type_id': self.room.id, 'source_ref': 'sale.order.line,999999999',
            'arrival': self.today, 'departure': self.today + DAY})
        self._order()
        self._sync()
        self.assertEqual((ghost.status, ghost.cancel_date), ('cancelled', self.today))

    def test_a_line_moved_to_a_product_that_is_no_room_type_does_not_break_the_run(self):
        order = self._order()
        self._sync()
        order._action_cancel()
        order.action_draft()
        order.order_line.product_id = self._create_room_product("Parking").product_variant_id
        run = self.hotel._run_engine()
        self.assertEqual(run.state, 'done', f"The run of a hotel with an edited order line failed: {run.message}")

    def test_revenue_is_converted_to_the_company_currency_at_the_order_date(self):
        foreign = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', self.currency.id)], limit=1)
        foreign.active = True
        self.env['res.currency.rate'].create([
            {'currency_id': foreign.id, 'name': self.today - 60 * DAY, 'rate': 2.0, 'company_id': self.company.id},
            {'currency_id': self.currency.id, 'name': self.today - 60 * DAY, 'rate': 1.0,
             'company_id': self.company.id}])
        pricelist = self.env['product.pricelist'].create({
            'name': "Foreign pricelist", 'currency_id': foreign.id, 'company_id': self.company.id})
        order = self._order(confirm=False, total=300)
        order.pricelist_id = pricelist
        order.order_line.price_unit = 300
        order.action_confirm()
        self.assertEqual(order.currency_id, foreign)
        self._sync()
        self.assertEqual(self._reservations().revenue, self.currency.round(300 / 2.0))

    def test_a_second_sync_writes_nothing(self):
        order = self._order()
        self._set_night_price(2, 180)
        with self._count_calls(*WRITES) as first_calls:
            self._sync()
        self.assertEqual(len(self._reservations()), 1)
        self.assertIn(('hotel.rms.reservation', 'create'), first_calls)
        self.assertIn(('hotel.rms.price', 'create'), first_calls)
        with self._count_calls(*WRITES) as calls:
            self._sync()
        self.assertEqual(calls, [])
        order._action_cancel()
        self._sync()
        with self._count_calls(*WRITES) as calls:
            self._sync()
        self.assertEqual(calls, [])

    def test_a_revenue_manager_without_sales_rights_still_reads_the_orders(self):
        self._order()
        self.hotel.with_user(self.manager)._sync_sources()
        self.assertEqual(len(self._reservations()), 1)

    def test_the_engine_run_reads_the_orders_first(self):
        self._order(arrival_offset=1)
        run = self.hotel._run_engine()
        self.assertEqual(run.state, 'done', run.message)
        self.assertEqual(self._reservations().mapped('status'), ['confirmed'])
        forecast = self.env['hotel.rms.forecast'].search([
            ('property_id', '=', self.hotel.id), ('stay_date', '=', self.today + DAY)])
        self.assertEqual(forecast.otb_rooms, 1)

    def test_an_order_of_another_company_is_not_read(self):
        company_b = self.env['res.company'].create({'name': "Other company"})
        self._order(company=company_b)
        self._sync()
        self.assertFalse(self._reservations())

    def test_a_product_can_be_the_room_product_of_one_room_type_only(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.env['hotel.rms.room.type'].create({
                'property_id': self.hotel.id, 'name': "Duplicate", 'derivation': 'amount', 'derive_value': 10,
                'product_tmpl_id': self.room_product.id})
