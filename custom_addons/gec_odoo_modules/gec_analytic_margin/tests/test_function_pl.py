from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestFunctionPL(GecMarginCommon):
    """The P&L by function: the same money regrouped by what it was for.
    A 40 000 pool on a delivery cost centre (Cost of Sales), charged out by an R&D activity,
    becomes R&D after the run, on projects and in the total."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.cogs = ref('gec_analytic_margin.component_function_cogs')
        cls.rnd = ref('gec_analytic_margin.component_function_rnd')
        cls.dir_a.gec_function_component_id = cls.cogs
        cls.overhead.function_reclassify = True

        cls.gl_income = cls.env['account.account'].create({
            'name': 'T Income', 'code': 'TST980', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.gl_depreciation = cls.env['account.account'].create({
            'name': 'T Depreciation', 'code': 'TST981', 'account_type': 'expense_depreciation',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls._pool()
        cls._drivers()
        cls._line(amount=50000.0, target=cls.bl_a, gl=cls.gl_income, name='T sale')
        cls._line(amount=-1000.0, source=cls.dir_a, gl=cls.gl_depreciation, name='T dep')
        cls.activity = cls._activity(gec_function_component_id=cls.rnd.id)
        cls._rule(activity=cls.activity)

    def _by_component(self, extra=()):
        groups = self.env['gec.margin.report']._read_group([
            ('line_type', '=', 'actual'),
            ('date', '>=', self.date_from), ('date', '<=', self.date_to),
            ('company_id', '=', self.company.id),
            *extra,
        ], ['component_id'], ['amount:sum'])
        return {component.code: amount for component, amount in groups if amount}

    def _company_total(self):
        return self._by_component([('is_primary_plan', '=', True)])

    def test_nature_mode_is_unchanged(self):
        self.assertEqual(self.company.gec_pl_mode, 'nature')
        total = self._company_total()
        self.assertAlmostEqual(total['t_overhead'], -40000.0, places=2)
        self.assertNotIn('function_cogs', total)

    def test_function_mode_reads_the_cost_centre_before_a_run(self):
        self.company.gec_pl_mode = 'function'
        total = self._company_total()
        self.assertAlmostEqual(total['function_cogs'], -40000.0, places=2)
        self.assertNotIn('t_overhead', total, "pooled cost stayed under its nature line")
        self.assertAlmostEqual(total['revenue'], 50000.0, places=2)
        self.assertAlmostEqual(total['depreciation'], -1000.0, places=2)

    def test_the_activity_moves_the_cost_to_its_function(self):
        self.company.gec_pl_mode = 'function'
        self._run().action_compute()
        total = self._company_total()
        self.assertAlmostEqual(total.get('function_cogs', 0.0), 0.0, places=2)
        self.assertAlmostEqual(total['function_rnd'], -40000.0, places=2)

        on_a = self._by_component([('analytic_account_id', '=', self.bl_a.id)])
        self.assertAlmostEqual(on_a['function_rnd'], -28000.0, places=2)
        self.assertAlmostEqual(on_a['revenue'], 50000.0, places=2)

    def test_without_an_activity_function_the_cost_centre_decides(self):
        self.company.gec_pl_mode = 'function'
        self.activity.gec_function_component_id = False
        self._run().action_compute()
        on_a = self._by_component([('analytic_account_id', '=', self.bl_a.id)])
        self.assertAlmostEqual(on_a['function_cogs'], -28000.0, places=2)

    def test_levels_place_the_functions(self):
        """Cost of Sales closes at Gross Margin; R&D only reaches EBITDA."""
        self.company.gec_pl_mode = 'function'
        self._run().action_compute()
        gross = self.env.ref('gec_analytic_margin.level_gross')._column_name()
        ebitda = self.env.ref('gec_analytic_margin.level_ebitda')._column_name()
        [(gross_sum, ebitda_sum)] = self.env['gec.margin.report']._read_group([
            ('line_type', '=', 'actual'), ('analytic_account_id', '=', self.bl_a.id),
            ('date', '>=', self.date_from), ('date', '<=', self.date_to),
        ], [], [f'{gross}:sum', f'{ebitda}:sum'])
        self.assertAlmostEqual(gross_sum, 50000.0, places=2, msg="R&D is not cost of sales")
        self.assertAlmostEqual(ebitda_sum, 22000.0, places=2)

    def test_health_check_names_cost_without_a_function(self):
        self.company.gec_pl_mode = 'function'
        self.dir_a.gec_function_component_id = False
        health = self.env['gec.abc.health'].create({
            'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
        })
        findings = [vals['name'] for vals in health._check_functions()]
        self.assertTrue(any('no function' in name for name in findings), findings)

        self.dir_a.gec_function_component_id = self.cogs
        self.assertFalse(health._check_functions())

    def test_dashboard_shows_each_function_as_a_share_of_revenue(self):
        self.company.gec_pl_mode = 'function'
        self._run().action_compute()
        data = self.env['gec.margin.dashboard'].get_dashboard_data(
            self.date_from, self.date_to, self.target_plan.id,
        )
        kpis = {kpi['key']: kpi for kpi in data['profitability']['kpis']}
        rnd = kpis[f'function_{self.rnd.id}']
        self.assertAlmostEqual(rnd['value'], -40000.0, places=2)
        self.assertAlmostEqual(rnd['pct'], 0.8, places=4, msg="40 000 of R&D on 50 000 revenue")
        self.assertTrue(rnd['is_cost'])

        self.company.gec_pl_mode = 'nature'
        data = self.env['gec.margin.dashboard'].get_dashboard_data(
            self.date_from, self.date_to, self.target_plan.id,
        )
        self.assertFalse([k for k in data['profitability']['kpis'] if k['key'].startswith('function_')])

    def test_an_internal_product_project_makes_its_hours_rnd(self):
        """The project decides first: product work is R&D whatever activity carried it."""
        self.company.gec_pl_mode = 'function'
        Account = self.env['account.analytic.account']
        project_plan, _others = self.env['account.analytic.plan']._get_all_plans()
        project_col = project_plan._column_name()
        platform = Account.create({'name': 'T Core Platform', 'plan_id': project_plan.id,
                                   'gec_function_component_id': self.rnd.id})
        customer = Account.create({'name': 'T Bank Rollout', 'plan_id': project_plan.id})
        team = Account.create({'name': 'T Delivery Team', 'plan_id': self.source_plan.id,
                               'gec_function_component_id': self.cogs.id})

        self._line(amount=-10000.0, source=team, gl=self.gl_pool, name='T team pool')
        for account, hours in ((platform, 40.0), (customer, 60.0)):
            self.env['account.analytic.line'].create({
                'name': 'T hours', 'date': self.date, 'unit_amount': hours,
                'company_id': self.company.id, project_col: account.id,
            })
        hours_activity = self._activity(
            name='T Delivery hours', source_analytic_path=project_col,
            gec_function_component_id=self.cogs.id,
        )
        rule = self._rule(activity=hours_activity, name='T team rule',
                          source_account_ids=[Command.set(team.ids)],
                          target_plan_id=project_plan.id)
        self._run(rules=rule).action_compute()

        on_platform = self._by_component([('analytic_account_id', '=', platform.id)])
        on_customer = self._by_component([('analytic_account_id', '=', customer.id)])
        self.assertAlmostEqual(on_platform['function_rnd'], -4000.0, places=2)
        self.assertNotIn('function_cogs', on_platform)
        self.assertAlmostEqual(on_customer['function_cogs'], -6000.0, places=2)

        objects = self.env['gec.margin.dashboard'].get_dashboard_data(
            self.date_from, self.date_to, project_plan.id,
        )['profitability']['objects']
        self.assertEqual([o['id'] for o in objects['internal']], [platform.id])
        self.assertNotIn(platform.id, [o['id'] for o in objects['chart'] + objects['bottom']])

        project = self.env['project.project'].create({'name': 'T Platform', 'account_id': customer.id})
        project.gec_function_component_id = self.rnd
        self.assertEqual(customer.gec_function_component_id, self.rnd)
