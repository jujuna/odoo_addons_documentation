from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestMarginAtCompletion(GecMarginCommon):
    """Forecast margin = contract - (cost to date + estimate to complete).
    A 100 000 contract; 60 of 100 allocated hours spent (166.67 an hour from a 10 000 pool)
    plus 20 000 subcontracting: cost 30 000, 40 hours to go."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_plan, _others = cls.env['account.analytic.plan']._get_all_plans()
        cls.project_col = cls.project_plan._column_name()
        cls.project = cls.env['project.project'].create({
            'name': 'T Rollout', 'allocated_hours': 100.0, 'allow_timesheets': True,
            'gec_contract_value': 100000.0,
        })
        cls.account = cls.project.account_id or cls.env['account.analytic.account'].create({
            'name': 'T Rollout', 'plan_id': cls.project_plan.id,
        })
        cls.project.account_id = cls.account
        employee = cls.env['hr.employee'].create({'name': 'T Engineer'})
        cls.env['account.analytic.line'].create({
            'name': 'T work', 'date': cls.date, 'unit_amount': 60.0,
            'project_id': cls.project.id, 'employee_id': employee.id,
        })
        team = cls.env['account.analytic.account'].create({
            'name': 'T Team', 'plan_id': cls.source_plan.id,
        })
        cls._line(amount=-10000.0, source=team, gl=cls.gl_pool, name='T team pool')
        cls.gl_income = cls.env['account.account'].create({
            'name': 'T Income', 'code': 'TST960', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.gl_direct = cls.env['account.account'].create({
            'name': 'T Subcontract', 'code': 'TST961', 'account_type': 'expense_direct_cost',
            'company_ids': [Command.set(cls.company.ids)],
        })
        for amount, gl in ((40000.0, cls.gl_income), (-20000.0, cls.gl_direct)):
            cls.env['account.analytic.line'].create({
                'name': 'T doc', 'date': cls.date, 'amount': amount, 'company_id': cls.company.id,
                'general_account_id': gl.id, cls.project_col: cls.account.id,
            })
        hours = cls._activity(name='T Hours', source_analytic_path=cls.project_col,
                              source_domain="[('project_id', '!=', False)]")
        rule = cls._rule(activity=hours, name='T hours rule',
                         source_account_ids=[Command.set(team.ids)],
                         target_plan_id=cls.project_plan.id)
        cls._run(rules=rule).action_compute()

    def _refresh(self):
        self.project.invalidate_recordset()
        return self.project

    def test_the_forecast_adds_the_hours_still_to_come(self):
        p = self._refresh()
        self.assertAlmostEqual(p.gec_actual_cost, 30000.0, places=2)
        self.assertAlmostEqual(p.gec_actual_revenue, 40000.0, places=2)
        self.assertAlmostEqual(p.gec_remaining_hours, 40.0, places=2)
        self.assertAlmostEqual(p.gec_cost_rate, 10000.0 / 60, places=2,
                               msg="the latest rate of the hours activity that charged it")
        self.assertAlmostEqual(p.gec_estimate_to_complete, 40 * 10000.0 / 60, places=2)
        self.assertAlmostEqual(p.gec_forecast_margin, 100000.0 - 30000.0 - 40 * 10000.0 / 60, places=2)
        self.assertEqual(p.gec_forecast_status, 'on_track')

    def test_overrides_and_other_cost(self):
        self.project.write({'gec_hourly_cost': 250.0, 'gec_remaining_other_cost': 5000.0})
        p = self._refresh()
        self.assertAlmostEqual(p.gec_estimate_to_complete, 40 * 250.0 + 5000.0, places=2)
        self.assertAlmostEqual(p.gec_forecast_margin_pct, 0.55, places=4)

    def test_status_against_the_budget(self):
        budget = self.env['budget.analytic'].create({
            'name': 'T Budget', 'budget_type': 'both',
            'date_from': '2026-01-01', 'date_to': '2026-12-31',
            'budget_line_ids': [
                Command.create({'account_id': self.account.id, 'general_account_id': self.gl_income.id,
                                'budget_amount': 100000.0}),
                Command.create({'account_id': self.account.id, 'general_account_id': self.gl_direct.id,
                                'budget_amount': 40000.0}),
            ],
        })
        budget.action_budget_confirm()
        self.project.gec_hourly_cost = 250.0
        p = self._refresh()
        self.assertAlmostEqual(p.gec_budget_margin_pct, 0.6, places=4)
        self.assertEqual(p.gec_forecast_status, 'on_track', "60% forecast against 60% budgeted")

        self.project.gec_remaining_other_cost = 10000.0
        self.assertEqual(self._refresh().gec_forecast_status, 'eroding')

        self.project.gec_contract_value = 35000.0
        self.assertEqual(self._refresh().gec_forecast_status, 'loss')

        self.project.gec_contract_value = False
        self.assertAlmostEqual(self._refresh().gec_contract_value_effective, 100000.0, places=2)

    def test_no_contract_no_forecast(self):
        self.project.gec_contract_value = False
        self.assertEqual(self._refresh().gec_forecast_status, 'none')

    def test_dashboard_lists_it_and_skips_internal_projects(self):
        internal = self.env['project.project'].create({'name': 'T Platform', 'gec_contract_value': 1.0})
        internal.account_id.gec_function_component_id = self.env.ref(
            'gec_analytic_margin.component_function_rnd')
        forecast = self.env['gec.margin.dashboard'].get_dashboard_data(
            self.date_from, self.date_to, self.project_plan.id,
        )['profitability']['forecast']
        ids = [row['id'] for row in forecast['projects']]
        self.assertIn(self.project.id, ids)
        self.assertNotIn(internal.id, ids)
        action = self.env['gec.margin.dashboard'].action_drilldown(
            'project', self.date_from, self.date_to, False, self.project.id)
        self.assertEqual((action['res_model'], action['res_id']), ('project.project', self.project.id))

    def test_overhead_still_to_come_follows_the_project_history(self):
        """A revenue-share rule charged 4 000 on 40 000 of revenue: 10% of the 60 000 still to invoice is 6 000 more."""
        pool_account = self.env['account.analytic.account'].create({
            'name': 'T Office', 'plan_id': self.source_plan.id})
        self._line(amount=-4000.0, source=pool_account, gl=self.gl_pool, name='T rent')
        rule = self._rule(name='T rent rule', driver='revenue_share',
                          source_account_ids=[Command.set(pool_account.ids)],
                          target_plan_id=self.project_plan.id)
        self._run(rules=rule).action_compute()
        p = self._refresh()
        self.assertAlmostEqual(p.gec_remaining_overhead, 60000.0 * 4000.0 / 40000.0, places=0)
        hours_part = 40 * 10000.0 / 60
        self.assertAlmostEqual(p.gec_estimate_to_complete, hours_part + p.gec_remaining_overhead, places=0)
