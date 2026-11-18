from datetime import date, timedelta

from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestBudgetCard(GecMarginCommon):
    """Actual against the budget prorated to the same days: 365 000 over 2025 is 31 000 for March."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gl_income = cls.env['account.account'].create({
            'name': 'T Income', 'code': 'TST955', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
        })
        budget = cls.env['budget.analytic'].create({
            'name': 'T 2025', 'budget_type': 'both',
            'date_from': '2025-01-01', 'date_to': '2025-12-31',
            'budget_line_ids': [Command.create({
                cls.target_col: cls.bl_a.id, 'general_account_id': cls.gl_income.id,
                'budget_amount': 365000.0,
            })],
        })
        budget.action_budget_confirm()
        cls.env['account.analytic.line'].create({
            'name': 'T sale', 'date': '2025-03-15', 'amount': 27900.0,
            'company_id': cls.company.id, 'general_account_id': cls.gl_income.id,
            cls.target_col: cls.bl_a.id,
        })

    def _budget(self, date_from, date_to):
        return self.env['gec.margin.dashboard'].get_dashboard_data(
            date_from, date_to, self.target_plan.id,
        )['profitability']['budget']

    def test_budget_is_prorated_to_the_period(self):
        budget = self._budget('2025-03-01', '2025-03-31')
        self.assertAlmostEqual(budget['revenue_budget'], 31000.0, places=2)
        self.assertAlmostEqual(budget['revenue'], 27900.0, places=2)
        self.assertAlmostEqual(budget['net_budget'], 31000.0, places=2)

    def test_the_window_stops_at_today(self):
        today = date.today()
        start = today - timedelta(days=9)
        self.env['budget.analytic'].create({
            'name': 'T current', 'budget_type': 'revenue',
            'date_from': start, 'date_to': start + timedelta(days=99),
            'budget_line_ids': [Command.create({
                self.target_col: self.bl_b.id, 'general_account_id': self.gl_income.id,
                'budget_amount': 100000.0,
            })],
        }).action_budget_confirm()
        budget = self._budget(start, start + timedelta(days=99))
        self.assertEqual(budget['through'], str(today))
        self.assertAlmostEqual(budget['revenue_budget'], 10000.0, places=2,
                               msg="ten of a hundred days have passed")

    def test_no_card_without_a_budget(self):
        self.assertEqual(self._budget('2024-03-01', '2024-03-31'), {})

    def test_outlook_prorates_the_budget_by_quarter(self):
        from dateutil.relativedelta import relativedelta
        today = date.today()
        first = (today.replace(day=1) + relativedelta(months=3 - (today.month - 1) % 3)).replace(day=1)
        last = first + relativedelta(months=12) - timedelta(days=1)
        days = (last - first).days + 1
        self.env['budget.analytic'].create({
            'name': 'T next year', 'budget_type': 'revenue', 'date_from': first, 'date_to': last,
            'budget_line_ids': [Command.create({
                self.target_col: self.bl_b.id, 'general_account_id': self.gl_income.id,
                'budget_amount': float(days) * 100,
            })],
        }).action_budget_confirm()
        o = self.env['gec.margin.dashboard'].get_dashboard_data(
            '2025-03-01', '2025-03-31', self.target_plan.id)['profitability']['outlook']
        self.assertEqual(len(o['quarters']), 4)
        self.assertAlmostEqual(o['budget_total'], days * 100, places=0, msg="100 a day over the four quarters")
        self.assertEqual(o['budgeted_quarters'], 4)
        self.assertAlmostEqual(o['plan_total'], o['budget_total'], places=0)
        q1 = o['quarters'][0]
        q1_days = (date.fromisoformat(q1['end']) - date.fromisoformat(q1['start'])).days + 1
        self.assertAlmostEqual(q1['budget_revenue'], q1_days * 100, places=0)
