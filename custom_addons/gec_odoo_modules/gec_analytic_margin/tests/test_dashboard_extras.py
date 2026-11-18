from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestRetention(GecMarginCommon):
    """NRR and GRR, March 2025 against March 2024, on maintenance revenue; E's project fee stays out."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        maintenance = cls.env.ref('gec_analytic_margin.revenue_stream_maintenance')
        gl = cls.env['account.account'].create({
            'name': 'T Maintenance', 'code': 'TST940', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)], 'gec_revenue_stream_id': maintenance.id,
        })
        fees = cls.env['account.account'].create({
            'name': 'T Fees', 'code': 'TST941', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
        })
        Partner = cls.env['res.partner']
        a, b, c, d, e = (Partner.create({'name': f'T Bank {x}', 'is_company': True}) for x in 'ABCDE')
        for partner, amount, when, account in (
            (a, 100, '2024-03-10', gl), (b, 100, '2024-03-10', gl), (c, 100, '2024-03-10', gl),
            (a, 150, '2025-03-10', gl), (b, 60, '2025-03-10', gl), (d, 80, '2025-03-10', gl),
            (e, 999, '2025-03-10', fees),
        ):
            cls.env['account.analytic.line'].create({
                'name': 'T fee', 'date': when, 'amount': amount, 'partner_id': partner.id,
                'company_id': cls.company.id, 'general_account_id': account.id,
                cls.target_col: cls.bl_a.id,
            })

    def test_nrr_grr_and_the_bridge(self):
        r = self.env['gec.margin.dashboard'].get_dashboard_data(
            '2025-03-01', '2025-03-31', self.target_plan.id)['profitability']['retention']
        self.assertEqual(r['basis'], 'recurring')
        self.assertAlmostEqual(r['start'], 300.0, places=2)
        self.assertAlmostEqual(r['expansion'], 50.0, places=2)
        self.assertAlmostEqual(r['contraction'], 40.0, places=2)
        self.assertAlmostEqual(r['churn'], 100.0, places=2)
        self.assertAlmostEqual(r['new'], 80.0, places=2, msg="new customers sit beside NRR, not in it")
        self.assertAlmostEqual(r['nrr'], 0.7, places=4)
        self.assertAlmostEqual(r['grr'], 160 / 300, places=4)
        self.assertEqual((r['customers'], r['lost'], r['won']), (3, 1, 1))
        self.assertAlmostEqual(r['start'] + r['expansion'] - r['contraction'] - r['churn'],
                               r['retained'], places=2)


@tagged('post_install', '-at_install')
class TestBacklogAndCash(GecMarginCommon):
    """Backlog, cost-to-cost progress, unbilled work, cash collected."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_plan, _others = cls.env['account.analytic.plan']._get_all_plans()
        cls.project = cls.env['project.project'].create({
            'name': 'T Rollout', 'allocated_hours': 0.0, 'gec_contract_value': 100000.0,
            'gec_remaining_other_cost': 20000.0,
        })
        column = cls.project_plan._column_name()
        for amount, kind in ((40000.0, 'income'), (-30000.0, 'expense_direct_cost')):
            gl = cls.env['account.account'].create({
                'name': f'T {kind}', 'code': f'TST9{50 if kind == "income" else 51}X',
                'account_type': kind, 'company_ids': [Command.set(cls.company.ids)],
            })
            cls.env['account.analytic.line'].create({
                'name': 'T doc', 'date': cls.date, 'amount': amount, 'company_id': cls.company.id,
                'general_account_id': gl.id, column: cls.project.account_id.id,
            })

    def test_backlog_progress_and_unbilled(self):
        p = self.project
        self.assertAlmostEqual(p.gec_backlog, 60000.0, places=2)
        self.assertAlmostEqual(p.gec_percent_complete, 0.6, places=4, msg="30 000 of 50 000 forecast cost")
        self.assertAlmostEqual(p.gec_earned_revenue, 60000.0, places=2)
        self.assertAlmostEqual(p.gec_unbilled, 20000.0, places=2, msg="earned 60 000, invoiced 40 000")
        self.assertAlmostEqual(p.gec_cash_margin, -30000.0, places=2, msg="nothing collected yet")

    def test_collected_counts_the_paid_part_of_an_invoice(self):
        journal = self.env['account.journal'].search([('type', '=', 'sale'), ('company_id', '=', self.company.id)], limit=1)
        income = self.env['account.account'].search([('account_type', '=', 'income'), ('company_ids', 'in', self.company.ids)], limit=1)
        if not journal or not income:
            self.skipTest("no chart of accounts in this database")
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.env['res.partner'].create({'name': 'T Payer'}).id,
            'journal_id': journal.id, 'invoice_date': self.date,
            'invoice_line_ids': [Command.create({
                'name': 'T milestone', 'quantity': 1, 'price_unit': 1000.0, 'account_id': income.id,
                'tax_ids': [Command.clear()],
                'analytic_distribution': {str(self.project.account_id.id): 100},
            })],
        })
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'amount': 250.0})._create_payments()
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.gec_collected, 250.0, places=2)


@tagged('post_install', '-at_install')
class TestDashboardScope(GecMarginCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        income = cls.env['account.account'].create({
            'name': 'T Income', 'code': 'TST945', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.env['account.analytic.line'].create({
            'name': 'T sale', 'date': cls.date, 'amount': 5000.0, 'company_id': cls.company.id,
            'general_account_id': income.id, cls.target_col: cls.bl_a.id, cls.source_col: cls.dir_a.id,
        })

    def test_company_wide_counts_each_amount_once(self):
        D = self.env['gec.margin.dashboard']
        data = D.get_dashboard_data(self.date_from, self.date_to, D.COMPANY_WIDE)
        self.assertEqual(data['plan_id'], D.COMPANY_WIDE)
        revenue = next(k for k in data['profitability']['kpis'] if k['key'] == 'revenue')
        self.assertAlmostEqual(revenue['value'], 5000.0, places=2)

    def test_trend_carries_the_sparkline_series(self):
        trend = self.env['gec.margin.dashboard'].get_dashboard_data(
            self.date_from, self.date_to, self.target_plan.id)['profitability']['trend']
        june = next(m for m in trend if m['month'] == '2026-06-01')
        self.assertIn('gross_pct', june)
        self.assertIn('recurring_pct', june)
