from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import DAY, HotelRmsCommon

PROPERTY_MODEL_LOGGER = 'odoo.addons.hotel_rms.models.hotel_rms_property'


@tagged('post_install', '-at_install')
class TestRun(HotelRmsCommon):

    def test_run_forecasts_every_night_of_the_horizon(self):
        run = self._run()
        forecasts = self._forecasts()
        self.assertEqual(forecasts.mapped('stay_date'), [self.today + i * DAY for i in range(10)])
        self.assertEqual(set(forecasts.mapped('run_date')), {self.today})
        self.assertEqual(set(forecasts.mapped('capacity')), {10})
        self.assertEqual((run.run_date, run.nights), (self.today, 10))

    def test_run_prices_every_room_type_of_a_night_with_a_season(self):
        self._run()
        prices = self._prices()
        self.assertEqual(len(prices), 20)
        self.assertEqual(set(prices.mapped('state')), {'pending'})
        self.assertTrue(all(prices.mapped('recommended_rate')))

    def test_derived_room_follows_the_reference_room(self):
        self._run()
        for offset in range(10):
            self.assertEqual(self._price(offset, self.suite).recommended_rate,
                             self._price(offset, self.double).recommended_rate + 50)

    def test_nights_without_a_season_get_no_price_rows(self):
        self.season.date_to = self.today + 3 * DAY
        self._run()
        self.assertEqual(set(self._prices().mapped('stay_date')), {self.today + i * DAY for i in range(4)})
        self.assertEqual(len(self._prices()), 8)

    def test_nights_that_lose_their_season_are_cleared_to_hold(self):
        self._run()
        self.season.date_to = self.today + 3 * DAY
        run = self._run()
        cleared = self._price(5)
        self.assertEqual((cleared.recommended_rate, cleared.raw_target_rate), (0, 0))
        self.assertFalse(cleared.action)
        self.assertFalse(cleared.reason_json)
        self.assertEqual((cleared.state, cleared.run_id), ('hold', run))
        self.assertEqual(self._price(5, self.suite).state, 'hold')
        self.assertEqual(self._price(2).state, 'pending')

    def test_a_cleared_night_cannot_be_accepted(self):
        self._run()
        self.season.date_to = self.today + 3 * DAY
        self._run()
        cleared = self._price(5)
        cleared.action_accept()
        self.assertEqual((cleared.state, cleared.published_rate), ('hold', 0))

    def test_hotel_without_rooms_skips_every_night(self):
        self.hotel.room_type_ids.write({'rooms': 0})
        run = self._run()
        self.assertEqual((run.nights, run.prices_changed), (0, 0))
        self.assertTrue(run.message)
        self.assertFalse(self._forecasts())
        self.assertFalse(self._prices())

    def test_stale_data_changes_nothing(self):
        self._run()
        before = self._snapshot()
        forecasts = self._forecasts()
        self.hotel.last_data_at = fields.Datetime.now() - timedelta(days=5)
        self.season.base_rate = 300
        run = self.hotel._run_engine()
        self.assertEqual(run.state, 'stale')
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self._forecasts(), forecasts)
        self.assertEqual(set(forecasts.mapped('is_current')), {True})

    def test_a_hotel_that_never_got_data_is_stale(self):
        hotel = self.hotel.copy({'name': "No data"})
        self.assertFalse(hotel.last_data_at)
        self.assertEqual(hotel._run_engine().state, 'stale')
        self.assertFalse(self._prices(hotel))

    def test_rerun_on_the_same_day_overwrites_the_forecast_rows(self):
        self._run()
        first = self._forecasts()
        run = self._run()
        self.assertEqual(self._forecasts(), first)
        self.assertEqual(set(first.mapped('run_id')), {run})

    def test_only_the_last_done_run_is_current(self):
        past_run = self.env['hotel.rms.run'].create({
            'property_id': self.hotel.id, 'run_date': self.today - DAY, 'state': 'done'})
        old = self.env['hotel.rms.forecast'].create({
            'property_id': self.hotel.id, 'run_date': self.today - DAY, 'stay_date': self.today + DAY,
            'capacity': 10, 'run_id': past_run.id, 'is_current': True})
        run = self._run()
        self.assertFalse(old.is_current)
        current = self._forecasts().filtered('is_current')
        self.assertEqual(set(current.mapped('run_id')), {run})
        self.assertEqual(len(current), 10)

    def test_short_history_falls_back_to_cold_start(self):
        for offset in range(-3, 10):
            self._add_reservation(self.today + offset * DAY, rooms=2, booked=self.today - 3 * DAY)
        self._run()
        self.assertEqual(set(self._forecasts().mapped('method')), {'coldstart_v1'})

    def test_enough_history_uses_the_forecast_from_comparable_nights(self):
        for offset in range(-70, 10):
            self._add_reservation(self.today + offset * DAY, rooms=2, booked=self.today - 100 * DAY)
        self._run()
        forecasts = self._forecasts()
        self.assertEqual(set(forecasts.mapped('method')), {'forecast_v1'})
        self.assertEqual(set(forecasts.mapped('refs')), {8})
        self.assertEqual(set(forecasts.mapped('otb_rooms')), {2})

    def test_nights_without_a_season_are_forecast_from_history(self):
        for offset in range(-70, 10):
            self._add_reservation(self.today + offset * DAY, rooms=2, booked=self.today - 100 * DAY)
        self.season.date_to = self.today + 3 * DAY
        self._run()
        self.assertEqual(len(self._forecasts()), 10)
        self.assertEqual(len(self._prices()), 8)

    def test_same_inputs_give_the_same_recommendations(self):
        self._run()
        first = self._snapshot()
        self._run()
        self.assertEqual(self._snapshot(), first)

    def test_a_changed_strategy_keeps_the_old_prices_on_the_old_settings_hash(self):
        first_run = self._run()
        old_hash = first_run.params_hash
        self.assertTrue(old_hash)
        locked = self._price(2)
        locked.action_lock()
        self.hotel.max_step_pct = 20
        self.assertEqual(set(self._prices().mapped('run_id.params_hash')), {old_hash})
        second_run = self._run()
        self.assertNotEqual(second_run.params_hash, old_hash)
        self.assertEqual(first_run.params['max_step_pct'], 15)
        self.assertEqual(second_run.params['max_step_pct'], 20)
        self.assertEqual(locked.run_id.params_hash, old_hash)
        self.assertEqual(self._price(3).run_id.params_hash, second_run.params_hash)

    def test_identical_settings_give_the_same_hash(self):
        self.assertEqual(self._run().params_hash, self._run().params_hash)

    def test_an_engine_failure_leaves_a_failed_run_and_no_partial_rows(self):
        with (patch.object(type(self.hotel), '_compute_actuals', side_effect=RuntimeError("boom")),
              mute_logger(PROPERTY_MODEL_LOGGER)):
            run = self.hotel._run_engine()
        self.assertEqual(run.state, 'failed')
        self.assertIn('RuntimeError', run.message)
        self.assertFalse(self._forecasts())
        self.assertFalse(self._prices())

    def test_each_hotel_runs_on_its_own_local_day(self):
        far_east = self.hotel.copy({'name': "Far east", 'tz': 'Pacific/Kiritimati'})
        far_west = self.hotel.copy({'name': "Far west", 'tz': 'Pacific/Pago_Pago'})
        (far_east + far_west).last_data_at = fields.Datetime.now()
        runs = [hotel._run_engine() for hotel in (far_east, far_west)]
        self.assertEqual(runs[0].run_date, far_east._get_local_today())
        self.assertEqual(runs[1].run_date, far_west._get_local_today())
        self.assertGreater(runs[0].run_date, runs[1].run_date)

    def test_forecasts_of_passed_nights_get_the_real_rooms(self):
        night = self.today - 3 * DAY
        self._add_reservation(night, rooms=3, booked=night - 10 * DAY)
        forecast = self.env['hotel.rms.forecast'].create({
            'property_id': self.hotel.id, 'run_date': night - 5 * DAY, 'stay_date': night, 'capacity': 10,
            'forecast_rooms': 5})
        self._run()
        self.assertTrue(forecast.has_actual)
        self.assertEqual(forecast.actual_rooms, 3)
        self.assertEqual(forecast.error_pts, 20)

    def test_the_daily_cron_runs_every_hotel(self):
        with patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=float('inf')):
            self.env['hotel.rms.property']._cron_run_engine()
        self.assertEqual(self.env['hotel.rms.run'].search([('property_id', '=', self.hotel.id)]).state, 'done')

    def test_a_revenue_manager_runs_the_engine_with_normal_rights(self):
        self.hotel.with_user(self.manager).action_run_engine()
        self.assertEqual(self.env['hotel.rms.run'].search([('property_id', '=', self.hotel.id)]).state, 'done')
        self.assertEqual(len(self._prices()), 20)

    def test_a_viewer_cannot_run_the_engine(self):
        with self.assertRaises(AccessError):
            self.hotel.with_user(self.viewer).action_run_engine()

    def test_calendar_shows_nights_cells_and_kpis(self):
        self._run()
        calendar = self.hotel.with_user(self.manager).get_calendar(self.today, 5)
        self.assertEqual(len(calendar['nights']), 5)
        self.assertEqual(len(calendar['cells']), 10)
        self.assertEqual([room['code'] for room in calendar['room_types']], ['DBL', 'STE'])
        self.assertTrue(calendar['can_decide'])
        self.assertFalse(calendar['is_stale'])
        self.assertEqual(calendar['publish']['method'], 'action_publish_approved')
        self.assertEqual(calendar['to_export_count'], 0)
        self.assertEqual(len(calendar['kpis']['forecast_series']), 10)
        self.assertEqual(calendar['last_run']['state'], 'done')

    def test_a_viewer_sees_the_calendar_but_cannot_decide(self):
        self._run()
        calendar = self.hotel.with_user(self.viewer).get_calendar(self.today, 3)
        self.assertFalse(calendar['can_decide'])
        self.assertEqual(len(calendar['cells']), 6)

    def test_the_explanation_names_the_forecast_and_ends_on_the_recommendation(self):
        self._run()
        price = self._price(5)
        self.assertIn("Forecast occupancy 50%", price.explanation_html)
        self.assertIn("5 days left.", price.explanation_html)
        self.assertIn("Recommended", price.explanation_html)

    def test_a_night_without_a_recommendation_says_so(self):
        self._run()
        self.season.date_to = self.today + 3 * DAY
        self._run()
        self.assertIn("No recommendation for this night", self._price(5).explanation_html)

    def test_the_hotel_dashboard_shows_the_forecast_of_the_next_nights(self):
        self._run()
        self.assertEqual(self.hotel.forecast_occ, 50)
        self.assertEqual(self.hotel.otb_occ, 0)
        self.assertEqual(self.hotel.forecast_series, [50.0] * 10)

    def test_calendar_marks_nights_without_a_season(self):
        self.season.date_to = self.today + DAY
        self._run()
        calendar = self.hotel.get_calendar(self.today, 4)
        self.assertEqual([night['has_season'] for night in calendar['nights']], [True, True, False, False])
