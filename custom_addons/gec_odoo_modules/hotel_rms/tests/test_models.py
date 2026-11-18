import psycopg2
from dateutil.relativedelta import relativedelta

from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger

from odoo.addons.hotel_rms.engine import forecast as forecast_engine
from odoo.addons.hotel_rms.models.hotel_rms_property import BOOKING_CURVE_DEFAULT, DEMAND_CURVE_DEFAULT

from .common import DAY, HotelRmsCommon


@tagged('post_install', '-at_install')
class TestModels(HotelRmsCommon):

    def test_new_hotel_gets_the_default_curves(self):
        demand = self.hotel.demand_point_ids.sorted('x')
        booking = self.hotel.booking_point_ids.sorted('x')
        self.assertEqual([(p.x, p.value) for p in demand], [(0, -10), (40, -5), (60, 0), (75, 5), (85, 10), (92, 15)])
        self.assertEqual([(p.x, p.value) for p in booking],
                         [(0, 100), (3, 92), (7, 82), (14, 68), (30, 48), (60, 28), (90, 15), (180, 5)])
        self.assertEqual(set((demand + booking).mapped('source')), {'default'})

    def test_a_hotel_created_with_empty_curve_lists_gets_the_default_curves(self):
        hotel = self.env['hotel.rms.property'].create({
            'name': "Web Hotel", 'company_id': self.company.id, 'tz': 'UTC', 'demand_point_ids': [], 'booking_point_ids': []})
        self.assertEqual(len(hotel.demand_point_ids), len(DEMAND_CURVE_DEFAULT))
        self.assertEqual(len(hotel.booking_point_ids), len(BOOKING_CURVE_DEFAULT))
        self.assertEqual(set((hotel.demand_point_ids + hotel.booking_point_ids).mapped('source')), {'default'})

    def test_a_curve_line_added_in_the_hotel_form_is_saved_with_its_kind(self):
        form = Form(self.hotel)
        with form.demand_point_ids.new() as line:
            line.x = 50
            line.value = 3
        with form.booking_point_ids.new() as line:
            line.x = 45
            line.value = 40
        form.save()
        self.assertEqual(self.hotel.demand_point_ids.filtered(lambda p: p.x == 50).kind, 'demand')
        self.assertEqual(self.hotel.booking_point_ids.filtered(lambda p: p.x == 45).kind, 'booking')

    def test_a_hotel_has_one_reference_room_type(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rms.room.type'].create({
                'property_id': self.hotel.id, 'name': "Second reference", 'derivation': 'reference'})

    def test_seasons_of_a_hotel_cannot_overlap(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rms.season'].create({
                'property_id': self.hotel.id, 'name': "Overlap", 'date_from': self.today,
                'date_to': self.today + 5 * DAY, 'base_rate': 150, 'min_rate': 100, 'max_rate': 200})

    def test_season_base_price_must_be_inside_its_range(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.season.base_rate = 50

    def test_season_copies_to_the_next_year(self):
        self.season.write({'date_from': self.today, 'date_to': self.today + 59 * DAY})
        self.season.action_copy_next_year()
        copy = self.hotel.season_ids - self.season
        self.assertEqual(copy.date_from, self.season.date_from + relativedelta(years=1))
        self.assertEqual(copy.date_to, self.season.date_to + relativedelta(years=1))
        self.assertEqual((copy.base_rate, copy.min_rate, copy.max_rate), (200, 100, 400))

    def test_reservation_reference_is_unique_per_hotel(self):
        reservation = self._add_reservation(self.today)
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self._add_reservation(self.today, source_ref=reservation.source_ref)

    def test_reservation_nights_follow_the_dates(self):
        self.assertEqual(self._add_reservation(self.today, nights=3).nights, 3)

    def test_night_index_counts_no_show_and_follows_cancellation_dates(self):
        """A cancellation without a date never counts: it is treated as cancelled the day it was booked."""
        night = self.today + 5 * DAY
        booked = self.today - 10 * DAY
        self._add_reservation(night, booked=booked, status='no_show')
        self._add_reservation(night, booked=booked, status='cancelled', cancel_date=self.today - 5 * DAY)
        self._add_reservation(night, booked=booked, status='cancelled')
        index = self.hotel._load_night_index(self.today, self.today + 10 * DAY)
        otb = forecast_engine.otb
        self.assertEqual(otb(index, night, booked - DAY)[0], 0)
        self.assertEqual(otb(index, night, booked)[0], 2)
        self.assertEqual(otb(index, night, self.today - 6 * DAY)[0], 2)
        self.assertEqual(otb(index, night, self.today)[0], 1)

    def test_learning_the_booking_curve_replaces_the_points(self):
        self.hotel.curve_min_nights = 2
        for back in (1, 2):
            night = self.today - back * DAY
            self._add_reservation(night, rooms=4, booked=night - 100 * DAY)
            self._add_reservation(night, rooms=1, booked=night)
        self.hotel.action_learn_booking_curve()
        points = {point.x: point.value for point in self.hotel.booking_point_ids}
        self.assertEqual(set(self.hotel.booking_point_ids.mapped('source')), {'learned'})
        self.assertEqual(points, {0: 100, 3: 80, 7: 80, 14: 80, 30: 80, 60: 80, 90: 80, 180: 0})

    def test_learning_the_booking_curve_needs_enough_history(self):
        result = self.hotel.action_learn_booking_curve()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(set(self.hotel.booking_point_ids.mapped('source')), {'default'})
