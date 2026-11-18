from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestVarianceSplit(GecMarginCommon):
    """Not Charged is two problems: idle capacity (a sales problem) and rate variance (a cost problem)."""

    def _rate_record(self, run):
        self.assertEqual(len(run.rate_ids), 1, "expected one rate per run")
        return run.rate_ids

    def test_idle_capacity_carries_the_whole_variance_on_an_actual_rate(self):
        """100 hours used of 200: half the pool stays, and none of it is a rate problem."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(practical_capacity=200.0))
        run = self._run()
        run.action_compute()

        rate = self._rate_record(run)
        self.assertAlmostEqual(rate.rate, 200.0, places=4)
        self.assertAlmostEqual(rate.variance_amount, -20000.0, places=2)
        self.assertAlmostEqual(rate.volume_variance, -20000.0, places=2)
        self.assertAlmostEqual(rate.spending_variance, 0.0, places=2)
        self.assertAlmostEqual(rate.unused_quantity, 100.0, places=2)

    def test_a_standard_rate_below_the_pool_shows_as_a_rate_variance(self):
        """Sized for 200 hours at 150 (30 000 budget) but the pool came to 40 000: overspending plus idle volume."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(
            practical_capacity=200.0, rate_mode='standard', standard_rate=150.0,
        ))
        run = self._run()
        run.action_compute()

        rate = self._rate_record(run)
        self.assertAlmostEqual(rate.charged_amount, -15000.0, places=2)
        self.assertAlmostEqual(rate.variance_amount, -25000.0, places=2)
        self.assertAlmostEqual(rate.volume_variance, -15000.0, places=2)
        self.assertAlmostEqual(rate.spending_variance, -10000.0, places=2)

    def test_a_standard_rate_above_the_pool_over_absorbs(self):
        """Charging more per hour than the pool holds is a positive variance."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(
            practical_capacity=100.0, rate_mode='standard', standard_rate=500.0,
        ))
        run = self._run()
        run.action_compute()

        rate = self._rate_record(run)
        self.assertAlmostEqual(rate.volume_variance, 0.0, places=2)
        self.assertAlmostEqual(rate.spending_variance, 10000.0, places=2,
                               msg="over-absorption must show as a rate variance")
        self.assertAlmostEqual(rate.variance_amount, 10000.0, places=2)

    def test_without_a_capacity_the_whole_variance_is_a_rate_variance(self):
        """No capacity means no volume to fall short of."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(
            rate_mode='standard', standard_rate=300.0,
        ))
        run = self._run()
        run.action_compute()

        rate = self._rate_record(run)
        self.assertAlmostEqual(rate.volume_variance, 0.0, places=2)
        self.assertAlmostEqual(rate.spending_variance, rate.variance_amount, places=2)

    def test_the_two_halves_always_add_back(self):
        """The split is an identity, checked on the arithmetic across every shape a period can take."""
        Rate = self.env['gec.activity.rate']
        for pool, charged, rate, capacity in (
            (-40000.0, -20000.0, 200.0, 200.0),
            (-40000.0, -15000.0, 150.0, 200.0),
            (-40000.0, -50000.0, 500.0, 100.0),
            (-40000.0, -30000.0, 300.0, 0.0),
            (-40000.0, -40000.0, 400.0, 100.0),
            (0.0, 0.0, 0.0, 100.0),
        ):
            with self.subTest(pool=pool, charged=charged, capacity=capacity):
                volume, spending = Rate._split_variance(
                    pool, charged, rate, capacity,
                )
                self.assertAlmostEqual(
                    volume + spending, pool - charged, places=6,
                    msg="the split does not reconcile to Not Charged",
                )

    def test_a_partial_share_is_rated_against_its_own_slice_of_the_pool(self):
        """A cost centre split between two activities holds two pools, so each rate uses its own pool."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(), resource_share=75.0)
        run = self._run()
        run.action_compute()

        rate = self._rate_record(run)
        self.assertAlmostEqual(rate.pool_amount, -30000.0, places=2,
                               msg="the pool recorded is the whole cost centre, "
                                   "not this activity's share of it")
        self.assertAlmostEqual(rate.rate, 300.0, places=4)
        self.assertAlmostEqual(rate.charged_amount, -30000.0, places=2)
        self.assertAlmostEqual(
            rate.variance_amount, 0.0, places=2,
            msg="a 75% share that charges out its whole slice leaves nothing "
                "behind — the remaining 25% belongs to another activity's rule",
        )
