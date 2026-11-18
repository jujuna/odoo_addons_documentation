from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestCascade(GecMarginCommon):
    """Step-down allocation: a service department charged before it charges on."""

    def test_step_two_pool_includes_what_step_one_delivered(self):
        self._line(amount=-50000.0, quantity=1.0, service=self.it,
                   gl=self.gl_pool, name='T IT cost')
        self._pool(amount=-40000.0)
        self._drivers()

        step_one = self._rule(
            name='T IT to Development', step=1,
            source_plan_id=self.service_plan.id,
            source_account_ids=[Command.set(self.it.ids)],
            target_plan_id=self.source_plan.id,
            driver='manual',
            line_ids=[Command.create({'account_id': self.dir_a.id, 'percentage': 100.0})],
        )
        step_two = self._rule(name='T Development to lines', step=2,
                              activity=self._activity())

        run = self._run()
        run.action_compute()

        self.assertAlmostEqual(
            step_two._get_pool_amount(self.date_from, self.date_to), -90000.0, places=2,
            msg="step 2 must see what step 1 delivered, or the service cost vanishes",
        )
        charged = sum(run.line_ids.filtered(
            lambda l: l.gec_allocation_kind == 'target' and l[self.target_col]
        ).mapped('amount'))
        self.assertAlmostEqual(charged, -90000.0, places=2,
                               msg="70/30 of 90,000 should reach the business lines")
        self.assertTrue(step_one.exists())

    def test_same_step_output_is_never_re_pooled(self):
        self._pool()
        self._drivers()
        rule = self._rule(activity=self._activity(), step=1)
        self._run().action_compute()
        self.assertAlmostEqual(
            rule._get_pool_amount(self.date_from, self.date_to), -40000.0, places=2,
            msg="a rule must not eat its own output",
        )

    def test_company_total_survives_a_cascade(self):
        self._line(amount=-50000.0, quantity=1.0, service=self.it,
                   gl=self.gl_pool, name='T IT cost')
        self._pool(amount=-40000.0)
        self._drivers()
        self._rule(
            name='T IT to Development', step=1,
            source_plan_id=self.service_plan.id,
            source_account_ids=[Command.set(self.it.ids)],
            target_plan_id=self.source_plan.id,
            driver='manual',
            line_ids=[Command.create({'account_id': self.dir_a.id, 'percentage': 100.0})],
        )
        self._rule(name='T Development to lines', step=2, activity=self._activity())
        run = self._run()
        run.action_compute()
        self.assertAlmostEqual(sum(run.line_ids.mapped('amount')), 0.0, places=2,
                               msg="two steps must still net to zero")


@tagged('post_install', '-at_install')
class TestCostHierarchy(GecMarginCommon):

    def test_facility_level_cannot_be_allocatable(self):
        with self.assertRaises(ValidationError):
            self.env['gec.margin.component'].create({
                'name': 'T Rent', 'code': 't_rent', 'nature': 'cost',
                'cost_level': 'facility', 'allocatable': True,
            })

    def test_facility_level_is_accepted_when_not_allocated(self):
        rent = self.env['gec.margin.component'].create({
            'name': 'T Rent', 'code': 't_rent2', 'nature': 'cost',
            'cost_level': 'facility', 'allocatable': False,
        })
        self.assertEqual(rent.cost_level, 'facility')

    def test_default_level_leaves_existing_behaviour_alone(self):
        self.assertEqual(self.overhead.cost_level, 'product')
        self.assertTrue(self.overhead.allocatable)

    def test_facility_cost_stays_where_it_was_booked(self):
        rent_component = self.env['gec.margin.component'].create({
            'name': 'T Rent', 'code': 't_rent3', 'nature': 'cost',
            'cost_level': 'facility', 'allocatable': False,
        })
        rent_account = self.env['account.account'].create({
            'name': 'T Rent account', 'code': 'TST930', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
            'gec_margin_component_id': rent_component.id,
        })
        self._line(amount=-20000.0, quantity=1.0, source=self.dir_a,
                   gl=rent_account, name='T rent')
        self._pool()
        self._drivers()
        rule = self._rule(activity=self._activity())
        self.assertAlmostEqual(
            rule._get_pool_amount(self.date_from, self.date_to), -40000.0, places=2,
            msg="rent must not be drawn into a pool restricted to the overhead account",
        )


@tagged('post_install', '-at_install')
class TestBudgetingAndValue(GecMarginCommon):

    def test_planned_cost_is_quantity_times_rate(self):
        activity = self._activity(rate_mode='standard', standard_rate=50.0,
                                  planned_quantity=9600.0)
        self.assertAlmostEqual(activity.planned_cost, 480000.0, places=2)

    def test_capacity_gap_warns_when_the_plan_exceeds_capacity(self):
        activity = self._activity(rate_mode='standard', standard_rate=50.0,
                                  planned_quantity=9600.0, practical_capacity=8000.0)
        self.assertAlmostEqual(activity.planned_capacity_gap, 1600.0, places=2)

    def test_no_capacity_means_no_gap(self):
        activity = self._activity(planned_quantity=9600.0)
        self.assertEqual(activity.planned_capacity_gap, 0.0)

    def test_value_added_defaults_and_groups(self):
        activity = self._activity()
        self.assertEqual(activity.value_added, 'value_added')
        waste = self._activity(name='T Rework', value_added='non_value_added')
        grouped = self.env['gec.activity']._read_group(
            [('id', 'in', (activity | waste).ids)],
            groupby=['value_added'], aggregates=['__count'],
        )
        self.assertEqual(dict((g[0], g[1]) for g in grouped),
                         {'value_added': 1, 'non_value_added': 1})
