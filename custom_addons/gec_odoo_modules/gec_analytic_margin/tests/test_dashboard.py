from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestDashboard(GecMarginCommon):
    """Nothing on the dashboard may disagree with the statement, apart from the sign change so costs read as costs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.level = cls.env['gec.margin.level'].create({
            'name': 'T Operating Margin',
            'code': 't_dash_operating',
            'sequence': 5,
            'component_ids': [Command.set((cls.direct | cls.overhead).ids)],
        })
        cls.revenue = cls.env['gec.margin.component'].create({
            'name': 'T Revenue', 'code': 't_dash_revenue', 'nature': 'revenue',
        })
        cls.gl_income = cls.env['account.account'].create({
            'name': 'T Income', 'code': 'TST950', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': cls.revenue.id,
        })

        cls._pool()
        cls._drivers()
        cls.activity = cls._activity(practical_capacity=200.0)
        cls._rule(activity=cls.activity)
        cls._run().action_compute()

        cls._line(amount=50000.0, target=cls.bl_a, gl=cls.gl_income, name='T sale')
        cls._line(amount=-500.0, target=cls.bl_b, name='T stray')

        cls.dashboard = cls.env['gec.margin.dashboard']

    def _data(self):
        return self.dashboard.get_dashboard_data(
            self.date_from, self.date_to, self.target_plan.id,
        )

    def test_cards_are_the_ladder_for_the_chosen_plan(self):
        data = self._data()
        self.assertEqual(data['plan_id'], self.target_plan.id)
        kpis = {kpi['key']: kpi for kpi in data['profitability']['kpis']}

        self.assertAlmostEqual(kpis['revenue']['value'], 50000.0, places=2)
        self.assertAlmostEqual(kpis['expense']['value'], -20500.0, places=2)
        self.assertAlmostEqual(kpis['net']['value'], 29500.0, places=2)
        self.assertAlmostEqual(kpis['net']['pct'], 0.59, places=4)
        self.assertFalse(kpis['revenue']['pct'], "revenue is not a share of itself")

        level = kpis[f'level_{self.level.id}']
        self.assertAlmostEqual(level['value'], -20000.0, places=2)
        self.assertAlmostEqual(level['pct'], -0.4, places=4)

        self.assertAlmostEqual(data['profitability']['unclassified'], -500.0, places=2)

    def test_cards_match_the_statement(self):
        """Same plan, same period, same Net as the report the statement reads."""
        net = sum(self.env['gec.margin.report'].search([
            ('line_type', '=', 'actual'),
            ('plan_id', '=', self.target_plan.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]).mapped('amount'))
        kpis = {kpi['key']: kpi for kpi in self._data()['profitability']['kpis']}
        self.assertAlmostEqual(kpis['net']['value'], net, places=2)

    def test_cost_objects_rank_by_net_and_costs_read_positive(self):
        objects = self._data()['profitability']['objects']
        self.assertEqual(objects['count'], 2)
        self.assertEqual([o['id'] for o in objects['chart']], [self.bl_a.id, self.bl_b.id])
        self.assertEqual([o['id'] for o in objects['top']], [self.bl_a.id])
        self.assertEqual([o['id'] for o in objects['bottom']], [self.bl_b.id])
        bl_a, bl_b = objects['chart']
        self.assertAlmostEqual(bl_a['net'], 36000.0, places=2)
        self.assertAlmostEqual(bl_a['expense'], 14000.0, places=2)
        self.assertAlmostEqual(bl_a['pct'], 0.72, places=4)
        self.assertAlmostEqual(bl_b['net'], -6500.0, places=2)
        self.assertFalse(bl_b['pct'], "no revenue, no margin percentage")

    def test_trend_covers_twelve_months_and_lands_the_amounts(self):
        trend = self._data()['profitability']['trend']
        self.assertEqual(len(trend), 12)
        self.assertEqual(trend[-1]['month'], '2026-06-01')
        self.assertAlmostEqual(trend[-1]['net'], 29500.0, places=2)
        self.assertAlmostEqual(trend[-1]['expense'], 20500.0, places=2)
        self.assertFalse(any(month['net'] for month in trend[:-1]))

    def test_activity_figures_are_the_rate_history_as_positive_cost(self):
        activity = self._data()['activity']
        entry = next(a for a in activity['activities'] if a['id'] == self.activity.id)
        self.assertAlmostEqual(entry['pool'], 40000.0, places=2)
        self.assertAlmostEqual(entry['charged'], 20000.0, places=2)
        self.assertAlmostEqual(entry['not_charged'], 20000.0, places=2)
        self.assertAlmostEqual(entry['idle'], 20000.0, places=2)
        self.assertAlmostEqual(entry['rate_variance'], 0.0, places=2)
        self.assertAlmostEqual(entry['capacity_used'], 0.5, places=4)
        self.assertAlmostEqual(entry['rate'], 200.0, places=4)
        self.assertEqual(entry['unit'], 'hour')

        totals = activity['totals']
        self.assertAlmostEqual(
            totals['pool'], totals['charged'] + totals['not_charged'], places=2,
            msg="what was charged and what was not must add back to the pool",
        )
        self.assertTrue(activity['value_split'])

    def test_previous_period_keeps_the_shape(self):
        from datetime import date
        previous = self.dashboard._gec_previous_period
        self.assertEqual(previous(date(2026, 3, 1), date(2026, 3, 31)),
                         (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(previous(date(2026, 4, 1), date(2026, 6, 30)),
                         (date(2026, 1, 1), date(2026, 3, 31)))
        self.assertEqual(previous(date(2026, 3, 10), date(2026, 3, 19)),
                         (date(2026, 2, 28), date(2026, 3, 9)))

    def test_drilldown_opens_the_rows_behind_the_figure(self):
        action = self.dashboard.action_drilldown(
            'object', self.date_from, self.date_to, self.target_plan.id, self.bl_a.id,
        )
        self.assertEqual(action['res_model'], 'gec.margin.report')
        rows = self.env['gec.margin.report'].search(action['domain'])
        self.assertAlmostEqual(sum(rows.mapped('amount')), 36000.0, places=2)

        action = self.dashboard.action_drilldown(
            'activity', self.date_from, self.date_to, self.target_plan.id, self.activity.id,
        )
        self.assertEqual(action['res_model'], 'gec.activity.rate')
        self.assertEqual(
            self.env['gec.activity.rate'].search(action['domain']).activity_id, self.activity,
        )

    def test_the_ladder_reads_in_statement_order_and_closes_on_net(self):
        ladder = self._data()['profitability']['ladder']
        labels = [row['label'] for row in ladder]
        self.assertEqual(labels[-1], 'Net')
        self.assertAlmostEqual(ladder[-1]['amount'], 29500.0, places=2)
        level = next(row for row in ladder if row['label'] == 'T Operating Margin')
        self.assertEqual(level['kind'], 'level')
        self.assertAlmostEqual(level['amount'], -20000.0, places=2)
        overhead = next(row for row in ladder if row['label'] == 'T Overhead')
        self.assertLess(labels.index('T Overhead'), labels.index('T Operating Margin'))
        self.assertEqual(overhead['kind'], 'cost')
        self.assertAlmostEqual(overhead['amount'], -20000.0, places=2)

    def test_a_proof_reproduces_its_card_and_opens_its_rows(self):
        D = self.dashboard
        proof = D.get_proof('gross', self.date_from, self.date_to, self.target_plan.id)
        self.assertEqual(proof['title'], 'Gross margin')
        self.assertTrue(proof['computation'].endswith(proof['value']))
        for part in proof['parts']:
            rows = self.env[part['action']['res_model']].search(part['action']['domain'])
            self.assertEqual(len(rows), part['count'])
            self.assertAlmostEqual(sum(rows.mapped('amount')), part['raw'], places=2)

    def test_every_card_has_a_proof(self):
        D = self.dashboard
        keys = ['revenue', 'gross', 'ebitda', 'recurring', 'nrr', 'grr', 'churn', 'revenue_fte', 'backlog',
                'projects', 'budget_revenue', 'budget_net', 'standard', 'top', 'top_n', 'fte', 'growth',
                'utilization', 'coverage', 'product_share', 'delivery', 'bespoke', 'rnd_customer', 'gross_fte',
                'recurring_fte', 'unbilled', 'ahead', 'cash', 'pool', 'charged', 'not_charged', 'idle',
                'rate_variance', 'capacity', 'outlook', 'rework',
                'milestones', 'golive', 'completion', 'templates', 'dso', 'conversion', 'cash_forecast', 'accuracy']
        for key in keys:
            proof = D.get_proof(key, self.date_from, self.date_to, self.target_plan.id)
            self.assertTrue(proof.get('title'), f"no proof for {key}")
            self.assertIn('computation', proof)
