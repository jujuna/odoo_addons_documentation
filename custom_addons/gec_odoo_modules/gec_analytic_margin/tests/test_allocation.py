from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestAllocation(GecMarginCommon):

    def _totals(self, run):
        """(contra, charged) split by kind, not by sign: the contra is positive, the target lines negative."""
        contra = sum(run.line_ids.filtered(
            lambda l: l.gec_allocation_kind == 'contra').mapped('amount'))
        charged = sum(run.line_ids.filtered(
            lambda l: l.gec_allocation_kind != 'contra').mapped('amount'))
        return contra, charged

    def test_pool_is_split_by_measured_hours(self):
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        run = self._run()
        run.action_compute()

        by_account = {}
        for line in run.line_ids:
            if line.gec_allocation_kind == 'contra':
                key = self.dir_a
            else:
                key = line[self.target_col]
            by_account.setdefault(key, 0.0)
            by_account[key] += line.amount

        self.assertAlmostEqual(by_account[self.bl_a], -28000.0, places=2)
        self.assertAlmostEqual(by_account[self.bl_b], -12000.0, places=2)
        self.assertAlmostEqual(by_account[self.dir_a], 40000.0, places=2)

    def test_allocation_never_changes_the_company_total(self):
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        run = self._run()
        run.action_compute()
        contra, target = self._totals(run)
        self.assertAlmostEqual(contra + target, 0.0, places=2,
                               msg="allocation must move cost, never create it")

    def test_partial_share_leaves_the_remainder_on_the_source(self):
        """75% charged out means 25% stays put — and the contra matches what left."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(), resource_share=75.0)
        run = self._run()
        run.action_compute()
        contra, charged = self._totals(run)
        self.assertAlmostEqual(charged, -30000.0, places=2)
        self.assertAlmostEqual(contra, 30000.0, places=2,
                               msg="the contra must equal what was charged, not the pool")

    def test_capacity_holds_idle_cost_on_the_source(self):
        """100 hours used of 200 available charges out half the pool."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(practical_capacity=200.0))
        run = self._run()
        run.action_compute()
        contra, charged = self._totals(run)
        self.assertAlmostEqual(charged, -20000.0, places=2)
        self.assertAlmostEqual(contra, 20000.0, places=2)

    def test_allocated_cost_is_never_allocated_again(self):
        """The output of a run must never become the input of another; checked on the pool itself."""
        self._pool()
        self._drivers()
        rule = self._rule(activity=self._activity())
        self._run().action_compute()
        self.assertAlmostEqual(
            rule._get_pool_amount(self.date_from, self.date_to), -40000.0, places=2,
            msg="the pool grew — allocation output is being treated as new cost",
        )

    def test_running_the_same_rule_twice_is_refused(self):
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        self._run().action_compute()
        with self.assertRaises(UserError):
            self._run().action_compute()

    def test_recompute_does_not_stack(self):
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        run = self._run()
        run.action_compute()
        before = len(run.line_ids), len(run.rate_ids)
        run.action_compute()
        self.assertEqual((len(run.line_ids), len(run.rate_ids)), before,
                         "recomputing must replace lines and rates, not add to them")

    def test_run_writes_no_journal_entries(self):
        moves_before = self.env['account.move'].search_count([])
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        self._run().action_compute()
        self.assertEqual(self.env['account.move'].search_count([]), moves_before,
                         "allocation must touch analytic lines only")

    def test_rate_is_recorded_per_run(self):
        self._pool()
        self._drivers()
        activity = self._activity()
        self._rule(activity=activity)
        run = self._run()
        run.action_compute()
        rate = run.rate_ids.filtered(lambda r: r.activity_id == activity)
        self.assertTrue(rate, "the run should record the rate it used")
        self.assertAlmostEqual(rate[0].rate, 400.0, places=2,
                               msg="40,000 over 100 measured hours is 400/hour")


@tagged('post_install', '-at_install')
class TestOnePoolOneHundredPercent(GecMarginCommon):
    """A pool split between two plans must still be one pool, or it is charged out twice."""

    def _revenue_rule(self, name, target_plan, **overrides):
        vals = {
            'name': name,
            'company_id': self.company.id,
            'source_plan_id': self.source_plan.id,
            'source_account_ids': [Command.set(self.dir_a.ids)],
            'source_gl_account_ids': [Command.set(self.gl_pool.ids)],
            'target_plan_id': target_plan.id,
            'driver': 'equal',
        }
        vals.update(overrides)
        return self.env['gec.allocation.rule'].create(vals)

    def test_two_ordinary_rules_on_one_pool_are_refused(self):
        self._pool()
        self._drivers()
        rules = (self._revenue_rule('T to lines', self.target_plan)
                 | self._revenue_rule('T to services', self.service_plan))

        with self.assertRaises(UserError) as caught:
            self._run(rules).action_compute()
        self.assertIn('200.0', str(caught.exception))

    def test_splitting_the_pool_with_shares_is_allowed(self):
        """The fix the refusal is meant to produce."""
        self._pool()
        self._drivers()
        rules = (
            self._revenue_rule('T to lines', self.target_plan, resource_share=60.0)
            | self._revenue_rule('T to services', self.service_plan,
                                 resource_share=40.0)
        )
        run = self._run(rules)
        run.action_compute()

        charged = sum(run.line_ids.filtered(
            lambda line: line.gec_allocation_kind == 'target'
        ).mapped('amount'))
        self.assertAlmostEqual(
            charged, -40000.0, places=2,
            msg="60 + 40 of one pool must charge out the pool exactly once",
        )

    def test_one_rule_on_a_pool_is_untouched(self):
        """The guard must not get in the way of the ordinary case."""
        self._pool()
        self._drivers()
        run = self._run(self._revenue_rule('T alone', self.target_plan))
        run.action_compute()
        self.assertEqual(run.state, 'done')

    def test_the_health_check_sees_it_before_the_run_does(self):
        self._pool()
        self._drivers()
        self._revenue_rule('T to lines', self.target_plan)
        self._revenue_rule('T to services', self.service_plan)

        health = self.env['gec.abc.health'].create({
            'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
        })
        health.action_check()
        found = [c for c in health.check_ids if 'of one cost pool' in c.name]
        self.assertTrue(found, "the health check missed a pool charged out twice")
        self.assertEqual(found[0].severity, 'error')
