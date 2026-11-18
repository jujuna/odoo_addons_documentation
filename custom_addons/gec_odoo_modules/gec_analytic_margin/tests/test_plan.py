from odoo.exceptions import UserError
from odoo.tests.common import tagged
from psycopg2 import IntegrityError

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestPlannedVsActual(GecMarginCommon):
    """Costing says what things cost; only a plan says whether that was fair.

    Actuals are never stored: they are measured from the same activity that drives the allocation."""

    def _plan(self, activity, account, quantity, **overrides):
        vals = {
            'activity_id': activity.id,
            'analytic_account_id': account.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'planned_quantity': quantity,
        }
        vals.update(overrides)
        return self.env['gec.activity.plan'].create(vals)

    def test_the_variance_is_measured_not_typed(self):
        """70 hours logged against a plan of 50 is 20 over, in units."""
        self._drivers()
        activity = self._activity()
        plan = self._plan(activity, self.bl_a, 50.0)

        self.assertAlmostEqual(plan.actual_quantity, 70.0, places=2)
        self.assertAlmostEqual(plan.variance_quantity, 20.0, places=2)
        self.assertAlmostEqual(plan.variance_percent, 0.4, places=4)

    def test_the_actual_follows_the_data_not_the_record(self):
        """A plan written in January must still be right in March: nothing is stored."""
        self._drivers()
        activity = self._activity()
        plan = self._plan(activity, self.bl_a, 50.0)
        self.assertAlmostEqual(plan.actual_quantity, 70.0, places=2)

        self._line(quantity=30.0, target=self.bl_a, name='T more hours')
        plan.invalidate_recordset()
        self.assertAlmostEqual(plan.actual_quantity, 100.0, places=2)
        self.assertAlmostEqual(plan.variance_quantity, 50.0, places=2)

    def test_a_standard_rate_values_the_variance(self):
        """20 hours over at 150 is 3,000 nobody sold."""
        self._drivers()
        activity = self._activity(rate_mode='standard', standard_rate=150.0)
        plan = self._plan(activity, self.bl_a, 50.0)

        self.assertTrue(plan.has_rate)
        self.assertAlmostEqual(plan.rate, 150.0, places=4)
        self.assertAlmostEqual(plan.variance_amount, 3000.0, places=2)

    def test_an_actual_rate_comes_from_the_run_that_recorded_it(self):
        self._pool()
        self._drivers()
        activity = self._activity()
        self._run(self._rule(activity=activity)).action_compute()

        plan = self._plan(activity, self.bl_a, 50.0)
        self.assertTrue(plan.has_rate)
        self.assertAlmostEqual(plan.rate, 400.0, places=4)
        self.assertAlmostEqual(plan.variance_amount, 20.0 * 400.0, places=2)

    def test_no_run_means_no_value_rather_than_a_confident_zero(self):
        """A zero there would read as "nothing at stake", which is not "not known"."""
        self._drivers()
        plan = self._plan(self._activity(), self.bl_a, 50.0)

        self.assertFalse(plan.has_rate)
        self.assertAlmostEqual(plan.variance_amount, 0.0, places=2)
        self.assertAlmostEqual(plan.variance_quantity, 20.0, places=2,
                               msg="the unit variance is real either way")

    def test_a_cost_object_that_consumed_nothing_is_under_plan(self):
        self._drivers()
        activity = self._activity()
        plan = self._plan(activity, self.it, 40.0)

        self.assertAlmostEqual(plan.actual_quantity, 0.0, places=2)
        self.assertAlmostEqual(plan.variance_quantity, -40.0, places=2)

    def test_one_period_is_measured_once_for_every_cost_object_on_it(self):
        """A plan with forty rows must not re-count the company forty times."""
        self._drivers()
        activity = self._activity()
        plans = self._plan(activity, self.bl_a, 50.0) | self._plan(
            activity, self.bl_b, 50.0,
        )
        plans.invalidate_recordset()

        calls = []
        original = type(activity).get_quantities

        def counting(self, date_from, date_to):
            calls.append((self.id, date_from, date_to))
            return original(self, date_from, date_to)

        self.patch(type(activity), 'get_quantities', counting)
        plans.mapped('actual_quantity')
        self.assertEqual(len(calls), 1,
                         f"measured {len(calls)} times for one activity period")

    def test_the_same_cost_object_cannot_be_planned_twice(self):
        self._drivers()
        activity = self._activity()
        self._plan(activity, self.bl_a, 50.0)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self._plan(activity, self.bl_a, 80.0)

    def _wizard(self, activity, **overrides):
        vals = {
            'activity_id': activity.id,
            'source_date_from': self.date_from,
            'source_date_to': self.date_to,
            'target_date_from': '2026-07-01',
            'target_date_to': '2026-07-31',
        }
        vals.update(overrides)
        return self.env['gec.activity.plan.wizard'].create(vals)

    def test_planning_from_actuals_carries_the_measured_quantities(self):
        self._drivers()
        activity = self._activity()
        self._wizard(activity).action_generate()

        plans = self.env['gec.activity.plan'].search([
            ('activity_id', '=', activity.id), ('date_from', '=', '2026-07-01'),
        ])
        self.assertEqual(len(plans), 2)
        self.assertEqual(
            sorted(round(plan.planned_quantity, 1) for plan in plans),
            [30.0, 70.0],
        )

    def test_a_factor_scales_the_plan(self):
        """"The same as last year plus ten percent" is what a plan usually is."""
        self._drivers()
        activity = self._activity()
        self._wizard(activity, factor=110.0).action_generate()

        plans = self.env['gec.activity.plan'].search([
            ('activity_id', '=', activity.id), ('date_from', '=', '2026-07-01'),
        ])
        self.assertEqual(
            sorted(round(plan.planned_quantity, 1) for plan in plans),
            [33.0, 77.0],
        )

    def test_regenerating_updates_rather_than_failing_on_the_constraint(self):
        self._drivers()
        activity = self._activity()
        self._wizard(activity).action_generate()
        self._wizard(activity, factor=200.0).action_generate()

        plans = self.env['gec.activity.plan'].search([
            ('activity_id', '=', activity.id), ('date_from', '=', '2026-07-01'),
        ])
        self.assertEqual(len(plans), 2, "regenerating duplicated the plan")
        self.assertEqual(
            sorted(round(plan.planned_quantity, 1) for plan in plans),
            [60.0, 140.0],
        )

    def test_hand_edited_plans_can_be_protected(self):
        self._drivers()
        activity = self._activity()
        self._wizard(activity).action_generate()
        plan = self.env['gec.activity.plan'].search([
            ('activity_id', '=', activity.id), ('date_from', '=', '2026-07-01'),
            ('analytic_account_id', '=', self.bl_a.id),
        ])
        plan.planned_quantity = 12.0

        self._wizard(activity, factor=200.0, overwrite=False).action_generate()
        self.assertAlmostEqual(plan.planned_quantity, 12.0, places=2)

    def test_planning_from_a_period_with_no_data_is_refused(self):
        """Generating nothing and saying nothing is how a plan ends up empty."""
        activity = self._activity()
        with self.assertRaises(UserError):
            self._wizard(activity).action_generate()

    def test_the_health_check_reports_a_cost_object_left_out_of_the_plan(self):
        """A plan covering some cost objects and not others is not a plan."""
        self._drivers()
        activity = self._activity()
        self._plan(activity, self.bl_a, 50.0)

        health = self.env['gec.abc.health'].create({
            'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
        })
        health.action_check()
        found = [
            check for check in health.check_ids
            if 'with no plan' in check.name and check.res_id == activity.id
        ]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'warning')
        self.assertIn(self.bl_b.display_name, found[0].detail)

    def test_another_companys_plan_is_hidden(self):
        """A user working in company B must not read company A's plans."""
        plan = self._plan(self._activity(), self.bl_a, 50.0)
        other = self.env['res.company'].create({'name': 'Other Co'})
        user = self.env['res.users'].create({
            'name': 'Other Accountant', 'login': 'gec_other_accountant',
            'company_id': other.id, 'company_ids': [(6, 0, other.ids)],
            'group_ids': [(6, 0, self.env.ref('account.group_account_readonly').ids)],
        })
        Plan = self.env['gec.activity.plan'].with_user(user).with_context(allowed_company_ids=other.ids)
        self.assertFalse(Plan.search([('id', '=', plan.id)]))

    def test_the_health_check_is_quiet_when_the_plan_is_complete(self):
        self._drivers()
        activity = self._activity()
        self._plan(activity, self.bl_a, 50.0)
        self._plan(activity, self.bl_b, 50.0)

        health = self.env['gec.abc.health'].create({
            'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
        })
        health.action_check()
        self.assertFalse([
            check for check in health.check_ids
            if 'with no plan' in check.name and check.res_id == activity.id
        ])
