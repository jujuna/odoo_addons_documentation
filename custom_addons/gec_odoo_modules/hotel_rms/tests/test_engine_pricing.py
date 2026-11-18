import random

from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.hotel_rms.engine import pricing as engine

DEMAND_CURVE = [(0, -10), (40, -5), (60, 0), (75, 5), (85, 10), (92, 15)]
RANDOM_CASES = 500
RANDOM_SEED = 20261024


def make_ctx(**overrides):
    """A quiet context: occupancy 60 has no demand change, so the raw target is the base."""
    ctx = {
        'base': 200, 'min_rate': 100, 'max_rate': 400, 'current_rate': None,
        'dow_pct': 0, 'event_pct': 0, 'forecast_occ': 60, 'pace': None, 'method': 'coldstart_v1', 'lead': 30,
        'demand_curve': DEMAND_CURVE, 'pace_threshold_pct': 10, 'pace_adj_pct': 5,
        'lastmin_days': 3, 'lastmin_occ_pct': 60, 'lastmin_pct': -10,
        'protect_days': 7, 'protect_occ_pct': 85, 'max_step_pct': 15, 'min_change_pct': 3, 'price_step': 1,
    }
    return dict(ctx, **overrides)


def factor_pcts(result):
    return {factor['code']: factor['pct'] for factor in result['factors']}


def guard_codes(result):
    return [guard['code'] for guard in result['guards']]


@tagged('post_install', '-at_install')
class TestPriceFactors(BaseCase):

    def test_factors_apply_in_order_and_multiply(self):
        result = engine.price_v1(make_ctx(dow_pct=10, event_pct=20, forecast_occ=80, pace=1.3))
        self.assertEqual([f['code'] for f in result['factors']], ['weekday', 'event', 'demand', 'pace', 'last_minute'])
        self.assertEqual([f['pct'] for f in result['factors']], [10, 20, 5, 5, 0])
        self.assertEqual(result['raw_target'], 291.06)
        self.assertEqual(result['recommended'], 291)
        self.assertEqual(result['action'], 'new')

    def test_demand_follows_the_last_curve_point_reached(self):
        cases = ((0, -10), (39.9, -10), (40, -5), (59, -5), (60, 0), (84.9, 5), (85, 10), (92, 15), (100, 15))
        for occupancy, pct in cases:
            with self.subTest(occupancy=occupancy):
                result = engine.price_v1(make_ctx(forecast_occ=occupancy))
                self.assertEqual(factor_pcts(result)['demand'], pct)

    def test_demand_is_zero_before_the_first_curve_point(self):
        result = engine.price_v1(make_ctx(demand_curve=[(50, 5)], forecast_occ=10))
        self.assertEqual(factor_pcts(result)['demand'], 0)

    def test_pace_moves_the_price_by_the_adjustment(self):
        cases = ((1.3, 'coldstart_v1', 5), (0.7, 'coldstart_v1', -5), (1.05, 'coldstart_v1', 0),
                 (0.95, 'coldstart_v1', 0), (None, 'coldstart_v1', 0))
        for pace, method, pct in cases:
            with self.subTest(pace=pace, method=method):
                result = engine.price_v1(make_ctx(pace=pace, method=method))
                self.assertEqual(factor_pcts(result)['pace'], pct)

    def test_pace_is_halved_when_the_forecast_already_holds_todays_bookings(self):
        for pace, pct in ((1.3, 2.5), (0.7, -2.5)):
            with self.subTest(pace=pace):
                result = engine.price_v1(make_ctx(pace=pace, method='forecast_v1'))
                self.assertEqual(factor_pcts(result)['pace'], pct)

    def test_last_minute_applies_close_to_the_night_with_low_occupancy_and_no_positive_event(self):
        cases = ((2, 50, 0, -10), (3, 59.9, 0, -10), (2, 50, -5, -10), (4, 50, 0, 0), (2, 60, 0, 0), (2, 50, 10, 0))
        for lead, occupancy, event_pct, pct in cases:
            with self.subTest(lead=lead, occupancy=occupancy, event_pct=event_pct):
                result = engine.price_v1(make_ctx(lead=lead, forecast_occ=occupancy, event_pct=event_pct))
                self.assertEqual(factor_pcts(result)['last_minute'], pct)


@tagged('post_install', '-at_install')
class TestPriceGuards(BaseCase):

    def test_season_limits_clamp_the_target(self):
        high = engine.price_v1(make_ctx(base=300, dow_pct=50, max_rate=350))
        self.assertEqual((high['raw_target'], high['recommended']), (450, 350))
        self.assertEqual(guard_codes(high), ['season_limit'])
        low = engine.price_v1(make_ctx(base=120, dow_pct=-50))
        self.assertEqual((low['raw_target'], low['recommended']), (60, 100))
        self.assertEqual(guard_codes(low), ['season_limit'])

    def test_raw_target_is_kept_when_the_max_step_limits_the_price(self):
        result = engine.price_v1(make_ctx(base=250, current_rate=187, price_step=5))
        self.assertEqual(result['raw_target'], 250)
        self.assertEqual(result['recommended'], 215)
        self.assertEqual(result['action'], 'up')
        self.assertEqual(guard_codes(result), ['max_step', 'rounding'])

    def test_near_the_night_a_full_hotel_never_lowers_the_current_price(self):
        result = engine.price_v1(make_ctx(forecast_occ=90, current_rate=300, lead=5))
        self.assertEqual(result['raw_target'], 220)
        self.assertEqual(result['recommended'], 300)
        self.assertEqual(guard_codes(result), ['protect'])

    def test_protect_needs_a_close_night_and_high_occupancy(self):
        far = engine.price_v1(make_ctx(forecast_occ=90, current_rate=300, lead=8))
        self.assertEqual((far['recommended'], guard_codes(far)), (255, ['max_step']))
        quiet = engine.price_v1(make_ctx(forecast_occ=80, current_rate=300, lead=5))
        self.assertNotIn('protect', guard_codes(quiet))

    def test_season_wins_over_the_max_step(self):
        result = engine.price_v1(make_ctx(base=150, min_rate=120, max_rate=200, current_rate=300))
        self.assertEqual(result['recommended'], 200)
        self.assertEqual(result['action'], 'down')
        self.assertEqual(guard_codes(result), ['max_step', 'season_limit'])

    def test_rounding_stays_inside_the_max_step_band(self):
        result = engine.price_v1(make_ctx(base=140, min_rate=50, max_rate=200, current_rate=100, price_step=10))
        self.assertEqual(result['recommended'], 110)
        self.assertEqual(guard_codes(result), ['max_step', 'rounding'])

    def test_rounding_uses_the_season_range_when_the_band_has_no_step_value(self):
        result = engine.price_v1(make_ctx(base=130, min_rate=50, max_rate=200, current_rate=120,
                                          max_step_pct=5, price_step=50))
        self.assertEqual(result['recommended'], 150)

    def test_price_is_not_rounded_when_the_season_has_no_step_value(self):
        result = engine.price_v1(make_ctx(base=130, min_rate=101, max_rate=140, price_step=50))
        self.assertEqual(result['recommended'], 130)
        self.assertNotIn('rounding', guard_codes(result))

    def test_rounding_is_half_up(self):
        for base, step, expected in ((100.5, 1, 101), (100.4, 1, 100), (102.5, 5, 105), (102.4, 5, 100)):
            with self.subTest(base=base, step=step):
                self.assertEqual(engine.price_v1(make_ctx(base=base, price_step=step))['recommended'], expected)

    def test_a_small_change_keeps_the_current_price(self):
        result = engine.price_v1(make_ctx(base=101, min_rate=50, max_rate=200, current_rate=100))
        self.assertEqual(result['recommended'], 100)
        self.assertEqual(result['action'], 'hold')
        self.assertEqual(guard_codes(result), ['hold'])

    def test_hold_needs_the_current_price_inside_the_season_range(self):
        result = engine.price_v1(make_ctx(base=110, min_rate=110, max_rate=300, current_rate=108))
        self.assertEqual(result['recommended'], 110)
        self.assertEqual(result['action'], 'up')
        self.assertNotIn('hold', guard_codes(result))

    def test_action_compares_the_recommendation_with_the_current_price(self):
        self.assertEqual(engine.price_v1(make_ctx())['action'], 'new')
        self.assertEqual(engine.price_v1(make_ctx(current_rate=190))['action'], 'up')
        self.assertEqual(engine.price_v1(make_ctx(current_rate=210))['action'], 'down')
        self.assertEqual(engine.price_v1(make_ctx(current_rate=200))['action'], 'hold')

    def test_zero_price_step_skips_rounding(self):
        result = engine.price_v1(make_ctx(base=100.37, price_step=0))
        self.assertEqual(result['recommended'], 100.37)
        self.assertNotIn('rounding', guard_codes(result))


@tagged('post_install', '-at_install')
class TestWaterfall(BaseCase):

    def _assert_sums_to_the_change(self, result, base, label):
        cents = sum(round(step['amount'] * 100) for step in result['waterfall'])
        self.assertEqual(cents, round((result['recommended'] - base) * 100), label)

    def _random_ctx(self, rng):
        base = round(rng.uniform(40, 600), 2)
        min_rate = round(base * rng.uniform(0.4, 1), 2)
        max_rate = round(base * rng.uniform(1, 2.5), 2)
        current = rng.choice((None, round(rng.uniform(min_rate * 0.8, max_rate * 1.2), 2)))
        return make_ctx(
            base=base, min_rate=min_rate, max_rate=max_rate, current_rate=current,
            dow_pct=round(rng.uniform(-15, 25), 1), event_pct=rng.choice((0, 0, 10, 25, -10)),
            forecast_occ=rng.uniform(0, 100), pace=rng.choice((None, round(rng.uniform(0.3, 2.5), 2))),
            method=rng.choice(('coldstart_v1', 'forecast_v1')), lead=rng.randint(0, 120),
            price_step=rng.choice((0, 0.5, 1, 5, 10)), max_step_pct=rng.choice((5, 15, 30)),
            min_change_pct=rng.choice((0, 3, 5)),
        )

    def test_waterfall_sums_exactly_and_zero_percent_steps_stay_zero(self):
        rng = random.Random(RANDOM_SEED)
        for case in range(RANDOM_CASES):
            ctx = self._random_ctx(rng)
            label = f"case {case}: {ctx}"
            result = engine.price_v1(ctx)
            self._assert_sums_to_the_change(result, ctx['base'], label)
            for factor, step in zip(result['factors'], result['waterfall']):
                if not factor['pct']:
                    self.assertEqual(step['amount'], 0, f"{factor['code']} is 0% but has an amount; {label}")

    def test_derived_waterfall_sums_exactly(self):
        rng = random.Random(RANDOM_SEED)
        for case in range(RANDOM_CASES):
            ctx = self._random_ctx(rng)
            reference = engine.price_v1(ctx)
            derivation = rng.choice(('amount', 'percent'))
            current = rng.choice((None, round(reference['recommended'] * rng.uniform(0.9, 1.4), 2)))
            derived = engine.derive(reference, derivation, round(rng.uniform(-30, 80), 1), current,
                                    ctx['price_step'], ctx['min_change_pct'])
            self._assert_sums_to_the_change(derived, ctx['base'], f"case {case}: {derivation} {ctx}")

    def test_waterfall_lists_factors_then_guards(self):
        result = engine.price_v1(make_ctx(base=250, current_rate=187, price_step=5))
        self.assertEqual([step['code'] for step in result['waterfall']],
                         ['weekday', 'event', 'demand', 'pace', 'last_minute', 'max_step', 'rounding'])
        self.assertEqual([step['amount'] for step in result['waterfall']], [0, 0, 0, 0, 0, -34.95, -0.05])


@tagged('post_install', '-at_install')
class TestDerive(BaseCase):

    def setUp(self):
        super().setUp()
        self.reference = engine.price_v1(make_ctx(base=213, price_step=5))

    def test_amount_is_added_to_target_and_recommendation(self):
        derived = engine.derive(self.reference, 'amount', 2.5, None, 5, 3)
        self.assertEqual(derived['raw_target'], 215.5)
        self.assertEqual(derived['recommended'], 220)
        self.assertEqual(derived['action'], 'new')

    def test_percent_is_applied_to_target_and_recommendation(self):
        derived = engine.derive(self.reference, 'percent', 10, None, 5, 3)
        self.assertEqual(derived['raw_target'], 234.3)
        self.assertEqual(derived['recommended'], 235)

    def test_recommendation_is_rounded_half_up_to_the_step(self):
        reference = engine.price_v1(make_ctx(base=100, price_step=5))
        self.assertEqual(engine.derive(reference, 'amount', 2.5, None, 5, 3)['recommended'], 105)

    def test_no_rounding_without_a_price_step(self):
        reference = engine.price_v1(make_ctx(base=100, price_step=0))
        self.assertEqual(engine.derive(reference, 'percent', 12.5, None, 0, 3)['recommended'], 112.5)

    def test_own_hold_rule_keeps_the_current_price_of_the_room(self):
        derived = engine.derive(self.reference, 'percent', 10, 233, 5, 3)
        self.assertEqual(derived['recommended'], 233)
        self.assertEqual(derived['action'], 'hold')
        self.assertEqual(guard_codes(derived)[-1], 'hold')
        self.assertEqual([step['code'] for step in derived['waterfall']][-2:], ['derived', 'hold'])

    def test_a_big_difference_is_not_held(self):
        derived = engine.derive(self.reference, 'percent', 10, 200, 5, 3)
        self.assertEqual((derived['recommended'], derived['action']), (235, 'up'))
        self.assertNotIn('hold', guard_codes(derived))

    def test_waterfall_ends_on_the_recommendation(self):
        derived = engine.derive(self.reference, 'percent', 10, None, 5, 3)
        self.assertEqual(sum(round(step['amount'] * 100) for step in derived['waterfall']),
                         round((derived['recommended'] - 213) * 100))
