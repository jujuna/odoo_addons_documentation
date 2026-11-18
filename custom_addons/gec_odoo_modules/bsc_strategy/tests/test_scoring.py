# -*- coding: utf-8 -*-
"""The arithmetic of the scorecard, run against the pure helpers.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.bsc_strategy.models.bsc_common import (
    achievement,
    rag_status,
    trend,
    weighted_average,
)

GREEN = 95.0
AMBER = 80.0


@tagged('post_install', '-at_install')
class TestScoring(TransactionCase):

    def _status(self, direction, target, actual, **kwargs):
        value = achievement(direction, target, actual, **kwargs)
        return value, rag_status(value, GREEN, AMBER)

    def test_t1_higher_better_on_target(self):
        value, status = self._status('higher_better', 100.0, 95.0)
        self.assertAlmostEqual(value, 95.0)
        self.assertEqual(status, 'green')

    def test_t2_higher_better_amber(self):
        value, status = self._status('higher_better', 100.0, 85.0)
        self.assertAlmostEqual(value, 85.0)
        self.assertEqual(status, 'amber')

    def test_t3_higher_better_red(self):
        value, status = self._status('higher_better', 100.0, 50.0)
        self.assertAlmostEqual(value, 50.0)
        self.assertEqual(status, 'red')

    def test_t4_lower_better_capped(self):
        value, status = self._status('lower_better', 10.0, 5.0, cap=150.0)
        self.assertAlmostEqual(value, 150.0, msg="200% must be capped at 150%")
        self.assertEqual(status, 'green')

    def test_t5_lower_better_zero_actual(self):
        """Zero complaints is the perfect outcome, not a division by zero."""
        value, status = self._status('lower_better', 10.0, 0.0)
        self.assertAlmostEqual(value, 100.0)
        self.assertEqual(status, 'green')

    def test_t5b_lower_better_zero_target(self):
        """A target of zero is legitimate for a lower-is-better measure."""
        self.assertAlmostEqual(achievement('lower_better', 0.0, 0.0), 100.0)
        self.assertAlmostEqual(achievement('lower_better', 0.0, 5.0), 0.0)

    def test_t6_range_inside(self):
        value, status = self._status('target_range', 0.0, 25.0,
                                     target_min=20.0, target_max=30.0)
        self.assertAlmostEqual(value, 100.0)
        self.assertEqual(status, 'green')

    def test_t7_range_below(self):
        value, status = self._status('target_range', 0.0, 15.0,
                                     target_min=20.0, target_max=30.0)
        self.assertAlmostEqual(value, 75.0)
        self.assertEqual(status, 'red')

    def test_t7b_range_above(self):
        value, _status = self._status('target_range', 0.0, 40.0,
                                      target_min=20.0, target_max=30.0)
        self.assertAlmostEqual(value, 75.0)

    def test_t8_zero_target(self):
        value, status = self._status('higher_better', 0.0, 12.0)
        self.assertIsNone(value)
        self.assertEqual(status, 'no_data')

    def test_t9_no_actual(self):
        self.assertEqual(rag_status(None, GREEN, AMBER), 'no_data')

    def test_t10_missing_kpi_is_not_zero(self):
        """A KPI with no data leaves the average alone; it does not drag it down."""
        value = weighted_average([(50.0, 100.0), (50.0, 80.0), (50.0, None)])
        self.assertAlmostEqual(value, 90.0)

    def test_t11_all_weights_zero(self):
        value = weighted_average([(0.0, 100.0), (0.0, 50.0)])
        self.assertAlmostEqual(value, 75.0, msg="Unweighted means equal weights")

    def test_t11b_nothing_measurable(self):
        self.assertIsNone(weighted_average([(10.0, None), (5.0, None)]))
        self.assertIsNone(weighted_average([]))

    def test_t12_two_red_objectives(self):
        objective_a = weighted_average([(1.0, 40.0), (1.0, 50.0)])
        objective_b = weighted_average([(1.0, 60.0)])
        scorecard = weighted_average([(25.0, objective_a), (25.0, objective_b)])
        self.assertLess(scorecard, AMBER)
        self.assertEqual(rag_status(scorecard, GREEN, AMBER), 'red')

    def test_trend_flat_within_tolerance(self):
        self.assertEqual(trend(100.5, 100.0), 'flat')

    def test_trend_up_and_down(self):
        self.assertEqual(trend(120.0, 100.0), 'up')
        self.assertEqual(trend(80.0, 100.0), 'down')

    def test_trend_without_history(self):
        self.assertEqual(trend(50.0, None), 'flat')

    def test_negative_achievement_floors_at_zero(self):
        self.assertAlmostEqual(achievement('higher_better', 100.0, -20.0), 0.0)
