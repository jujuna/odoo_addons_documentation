from datetime import date, timedelta

from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.hotel_rms.engine import forecast as engine

TODAY = date(2026, 6, 10)
DAY = timedelta(days=1)
CURVE = [(0, 1.0), (10, 0.5), (30, 0.2)]


def booking(booked, arrival, nights=1, rooms=1, revenue=100.0, cancelled=None):
    return {
        'booking_date': booked, 'arrival': arrival, 'departure': arrival + nights * DAY,
        'rooms': rooms, 'revenue': revenue, 'cancel_date': cancelled,
    }


@tagged('post_install', '-at_install')
class TestOnTheBooks(BaseCase):

    def test_index_spreads_the_revenue_over_the_nights(self):
        arrival = date(2026, 7, 1)
        index = engine.night_index([booking(TODAY, arrival, nights=3, rooms=2, revenue=300.0)])
        self.assertEqual(sorted(index), [arrival, arrival + DAY, arrival + 2 * DAY])
        self.assertEqual(index[arrival], [(TODAY, None, 2, 100.0)])

    def test_index_skips_stays_without_a_night(self):
        arrival = date(2026, 7, 1)
        zero = booking(TODAY, arrival, nights=0)
        negative = booking(TODAY, arrival, nights=-2)
        self.assertEqual(engine.night_index([zero, negative]), {})

    def test_booking_counts_from_its_booking_date(self):
        night = date(2026, 7, 1)
        index = engine.night_index([booking(TODAY, night)])
        self.assertEqual(engine.otb(index, night, TODAY), (1, 100.0))
        self.assertEqual(engine.otb(index, night, TODAY - DAY), (0, 0))

    def test_cancellation_after_the_as_of_date_still_counts(self):
        night = date(2026, 7, 1)
        index = engine.night_index([booking(TODAY - 5 * DAY, night, cancelled=TODAY + DAY)])
        self.assertEqual(engine.otb(index, night, TODAY)[0], 1)

    def test_cancellation_on_or_before_the_as_of_date_does_not_count(self):
        night = date(2026, 7, 1)
        index = engine.night_index([booking(TODAY - 5 * DAY, night, cancelled=TODAY)])
        self.assertEqual(engine.otb(index, night, TODAY)[0], 0)
        self.assertEqual(engine.otb(index, night, TODAY + DAY)[0], 0)

    def test_cancellation_is_known_only_from_its_own_day(self):
        night = date(2026, 7, 1)
        index = engine.night_index([booking(TODAY - 5 * DAY, night, cancelled=TODAY)])
        self.assertEqual(engine.otb(index, night, TODAY - DAY)[0], 1)

    def test_rooms_and_revenue_are_summed(self):
        night = date(2026, 7, 1)
        index = engine.night_index([
            booking(TODAY, night, rooms=2, revenue=250.0),
            booking(TODAY, night, rooms=1, revenue=90.0),
            booking(TODAY, night + DAY, rooms=5),
        ])
        self.assertEqual(engine.otb(index, night, TODAY), (3, 340.0))

    def test_night_without_bookings_is_empty(self):
        self.assertEqual(engine.otb({}, date(2026, 7, 1), TODAY), (0, 0))


@tagged('post_install', '-at_install')
class TestComparableDates(BaseCase):

    def test_recent_weeks_are_the_latest_same_weekday_nights(self):
        night = TODAY + 7 * DAY
        found = engine.comparable_dates(night, TODAY, window_days=0, years=0, recent_weeks=3)
        self.assertEqual(found, [TODAY - 21 * DAY, TODAY - 14 * DAY, TODAY - 7 * DAY])

    def test_previous_year_window_keeps_the_weekday(self):
        night = TODAY + 7 * DAY
        centre = night - 364 * DAY
        found = engine.comparable_dates(night, TODAY, window_days=7, years=1, recent_weeks=0)
        self.assertEqual(found, [centre - 7 * DAY, centre, centre + 7 * DAY])

    def test_only_past_nights_unique_and_sorted(self):
        night = TODAY + 3 * DAY
        found = engine.comparable_dates(night, TODAY, window_days=21, years=2, recent_weeks=8)
        self.assertEqual(found, sorted(set(found)))
        self.assertTrue(all(day < TODAY and day.weekday() == night.weekday() for day in found))


@tagged('post_install', '-at_install')
class TestForecastV1(BaseCase):

    def setUp(self):
        super().setUp()
        self.night = TODAY + 10 * DAY
        self.lead = 10
        self.refs = [date(2026, 5, 6), date(2026, 5, 13), date(2026, 5, 20)]
        self.history_start = self.refs[0] - 20 * DAY

    def _index(self, early, pickup, cancel_early=False):
        """Each ref has `early` rooms booked before the lead window and `pickup` rooms after it."""
        reservations = [booking(TODAY - DAY, self.night, rooms=4)]
        for ref, rooms_early, rooms_pickup in zip(self.refs, early, pickup):
            if rooms_early:
                reservations.append(booking(ref - 20 * DAY, ref, rooms=rooms_early,
                                            cancelled=ref - 3 * DAY if cancel_early else None))
            if rooms_pickup:
                reservations.append(booking(ref - 5 * DAY, ref, rooms=rooms_pickup))
        return engine.night_index(reservations)

    def _forecast(self, index, refs=None, capacity=10, min_refs=3, history_start=None):
        return engine.forecast_v1(
            index, self.night, TODAY, capacity, self.refs if refs is None else refs, min_refs,
            history_start or self.history_start)

    def test_forecast_adds_the_median_pickup_to_the_booked_rooms(self):
        result = self._forecast(self._index(early=(2, 2, 2), pickup=(1, 3, 2)))
        self.assertEqual(result['method'], 'forecast_v1')
        self.assertEqual(result['otb'], 4)
        self.assertEqual(result['otb_revenue'], 100.0)
        self.assertEqual(result['forecast_rooms'], 6)
        self.assertEqual(result['expected_otb'], 2)
        self.assertEqual(result['pace'], 2.0)
        self.assertEqual(result['refs'], 3)

    def test_forecast_is_capped_by_the_capacity(self):
        result = self._forecast(self._index(early=(2, 2, 2), pickup=(1, 3, 2)), capacity=5)
        self.assertEqual(result['forecast_rooms'], 5)

    def test_negative_pickup_is_treated_as_zero(self):
        index = self._index(early=(4, 4, 4), pickup=(0, 0, 0), cancel_early=True)
        result = self._forecast(index)
        self.assertEqual(result['forecast_rooms'], 4)
        self.assertEqual(result['expected_otb'], 4)

    def test_pace_is_none_when_fewer_than_one_room_is_expected(self):
        result = self._forecast(self._index(early=(0, 0, 0), pickup=(2, 2, 2)))
        self.assertEqual(result['expected_otb'], 0)
        self.assertIsNone(result['pace'])
        self.assertEqual(result['forecast_rooms'], 6)

    def test_pace_exists_from_one_expected_room(self):
        result = self._forecast(self._index(early=(1, 1, 1), pickup=(2, 2, 2)))
        self.assertEqual(result['pace'], 4.0)

    def test_too_few_comparable_nights_gives_none(self):
        index = self._index(early=(2, 2, 2), pickup=(1, 3, 2))
        self.assertIsNone(self._forecast(index, min_refs=4))

    def test_no_booking_history_gives_none(self):
        index = self._index(early=(2, 2, 2), pickup=(1, 3, 2))
        self.assertIsNone(engine.forecast_v1(index, self.night, TODAY, 10, self.refs, 3, None))

    def test_refs_without_history_at_their_lead_are_dropped(self):
        index = self._index(early=(2, 2, 2), pickup=(1, 3, 2))
        refs = [date(2025, 1, 1), *self.refs]
        result = self._forecast(index, refs=refs)
        self.assertEqual(result['refs'], 3)
        self.assertIsNone(self._forecast(index, refs=refs, min_refs=4))

    def test_history_start_is_inclusive_at_the_lead(self):
        index = self._index(early=(2, 2, 2), pickup=(1, 3, 2))
        on_the_day = self.refs[0] - self.lead * DAY
        self.assertEqual(self._forecast(index, history_start=on_the_day)['refs'], 3)
        self.assertIsNone(self._forecast(index, history_start=on_the_day + DAY))


@tagged('post_install', '-at_install')
class TestColdStart(BaseCase):

    def test_curve_share_interpolates_between_points(self):
        for lead, share in ((5, 0.75), (10, 0.5), (20, 0.35), (30, 0.2)):
            with self.subTest(lead=lead):
                self.assertAlmostEqual(engine.curve_share(CURVE, lead), share)

    def test_curve_share_is_flat_outside_the_ends(self):
        self.assertEqual(engine.curve_share(CURVE, 0), 1.0)
        self.assertEqual(engine.curve_share(CURVE, -5), 1.0)
        self.assertEqual(engine.curve_share(CURVE, 90), 0.2)

    def test_expected_occupancy_is_spread_over_the_curve(self):
        result = engine.coldstart_v1(3, 300.0, 10, 0.7, 5, CURVE)
        self.assertEqual(result['method'], 'coldstart_v1')
        self.assertEqual(result['refs'], 0)
        self.assertEqual(result['otb'], 3)
        self.assertEqual(result['otb_revenue'], 300.0)
        self.assertAlmostEqual(result['expected_otb'], 5.25)
        self.assertAlmostEqual(result['pace'], 3 / 5.25)
        self.assertAlmostEqual(result['forecast_rooms'], 7)

    def test_booked_rooms_above_the_expectation_win(self):
        self.assertEqual(engine.coldstart_v1(9, 0, 10, 0.7, 5, CURVE)['forecast_rooms'], 9)

    def test_forecast_is_capped_by_the_capacity(self):
        self.assertEqual(engine.coldstart_v1(2, 0, 10, 1.5, 5, CURVE)['forecast_rooms'], 10)

    def test_pace_is_none_when_fewer_than_one_room_is_expected(self):
        result = engine.coldstart_v1(0, 0, 2, 0.4, 30, CURVE)
        self.assertLess(result['expected_otb'], 1)
        self.assertIsNone(result['pace'])


@tagged('post_install', '-at_install')
class TestLearnCurve(BaseCase):

    def _nights(self, count):
        return [TODAY - (i + 1) * DAY for i in range(count)]

    def _steady_index(self, count):
        reservations = []
        for night in self._nights(count):
            reservations += [
                booking(night - 40 * DAY, night, rooms=4), booking(night - 20 * DAY, night, rooms=3),
                booking(night - 5 * DAY, night, rooms=2), booking(night, night, rooms=1),
            ]
        return engine.night_index(reservations)

    def test_curve_is_the_median_share_booked_at_each_lead(self):
        curve = engine.learn_curve(self._steady_index(3), TODAY, [30, 0, 10, 3], min_nights=3)
        self.assertEqual(curve, [(0, 1.0), (3, 0.9), (10, 0.7), (30, 0.4)])

    def test_too_few_nights_gives_none(self):
        self.assertIsNone(engine.learn_curve(self._steady_index(2), TODAY, [0, 7], min_nights=3))

    def test_a_curve_never_rises_with_the_lead(self):
        reservations = []
        for night in self._nights(2):
            reservations += [booking(night - 40 * DAY, night, rooms=5, cancelled=night - 15 * DAY),
                             booking(night - 5 * DAY, night, rooms=5)]
        curve = engine.learn_curve(engine.night_index(reservations), TODAY, [0, 3, 10, 30], min_nights=2)
        self.assertEqual(curve, [(0, 1.0), (3, 1.0), (10, 0.0), (30, 0.0)])

    def test_nights_older_than_a_year_and_today_are_ignored(self):
        old = TODAY - (engine.CURVE_HISTORY_DAYS + 1) * DAY
        index = engine.night_index([booking(old - DAY, old, rooms=2), booking(TODAY - DAY, TODAY, rooms=2)])
        self.assertIsNone(engine.learn_curve(index, TODAY, [0, 7], min_nights=1))


@tagged('post_install', '-at_install')
class TestConfidence(BaseCase):

    def test_history_score_grows_with_the_comparable_nights(self):
        self.assertEqual(engine.confidence('forecast_v1', 3, 0), (69, 'medium'))
        self.assertEqual(engine.confidence('forecast_v1', 4, 0), (72, 'high'))
        self.assertEqual(engine.confidence('forecast_v1', 10, 0), (90, 'high'))

    def test_history_score_stops_growing_after_ten_nights(self):
        self.assertEqual(engine.confidence('forecast_v1', 25, 0), (90, 'high'))

    def test_cold_start_is_low(self):
        self.assertEqual(engine.confidence('coldstart_v1', 0, 0), (30, 'low'))

    def test_first_day_of_data_age_is_free_then_ten_points_a_day(self):
        self.assertEqual(engine.confidence('forecast_v1', 4, 1), (72, 'high'))
        self.assertEqual(engine.confidence('forecast_v1', 4, 2), (62, 'medium'))
        self.assertEqual(engine.confidence('forecast_v1', 4, 5), (32, 'low'))

    def test_score_is_clamped_at_zero(self):
        self.assertEqual(engine.confidence('coldstart_v1', 0, 9), (0, 'low'))
