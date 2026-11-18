from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestRevenueMix(GecMarginCommon):
    """Revenue by stream, and the share of it that renews.
    BL-A: 30 000 licenses, 20 000 maintenance; BL-B: 10 000 services via an untagged income account.
    Recurring = maintenance: 20 000 of 60 000."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.license = ref('gec_analytic_margin.revenue_stream_license')
        cls.maintenance = ref('gec_analytic_margin.revenue_stream_maintenance')
        cls.services = ref('gec_analytic_margin.revenue_stream_services')

        def income(code, name, stream=None):
            return cls.env['account.account'].create({
                'name': name, 'code': code, 'account_type': 'income',
                'company_ids': [Command.set(cls.company.ids)],
                'gec_revenue_stream_id': stream.id if stream else False,
            })

        cls.gl_license = income('TST990', 'T Licenses', cls.license)
        cls.gl_maintenance = income('TST991', 'T Maintenance', cls.maintenance)
        cls.gl_services = income('TST992', 'T Services')
        cls._line(amount=30000.0, target=cls.bl_a, gl=cls.gl_license, name='T lic')
        cls._line(amount=20000.0, target=cls.bl_a, gl=cls.gl_maintenance, name='T mnt')
        cls._line(amount=10000.0, target=cls.bl_b, gl=cls.gl_services, name='T svc')
        cls.dashboard = cls.env['gec.margin.dashboard']

    def _mix(self):
        data = self.dashboard.get_dashboard_data(self.date_from, self.date_to, self.target_plan.id)
        kpis = {kpi['key']: kpi for kpi in data['profitability']['kpis']}
        return data['profitability']['mix'], kpis

    def test_recurring_share_and_mix_add_up_to_revenue(self):
        mix, kpis = self._mix()
        self.assertAlmostEqual(kpis['recurring']['value'], 20000.0, places=2)
        self.assertAlmostEqual(kpis['recurring']['pct'], 1 / 3, places=4)
        by_stream = {s['id']: s['amount'] for s in mix['streams']}
        self.assertEqual(by_stream, {self.license.id: 30000.0, self.maintenance.id: 20000.0})
        self.assertAlmostEqual(mix['unassigned'], 10000.0, places=2)
        self.assertAlmostEqual(
            sum(by_stream.values()) + mix['unassigned'], kpis['revenue']['value'], places=2,
            msg="the mix must add up to the Revenue card",
        )

    def test_the_analytic_account_stream_takes_precedence(self):
        self.bl_b.gec_revenue_stream_id = self.services
        self.bl_a.gec_revenue_stream_id = self.maintenance
        mix, kpis = self._mix()
        by_stream = {s['id']: s['amount'] for s in mix['streams']}
        self.assertEqual(by_stream, {self.maintenance.id: 50000.0, self.services.id: 10000.0})
        self.assertFalse(mix['unassigned'])

    def test_cost_takes_the_analytic_stream_never_the_gl_one(self):
        self.gl_pool.gec_revenue_stream_id = self.services
        self._line(amount=-5000.0, target=self.bl_a, gl=self.gl_pool, name='T cost')
        Report = self.env['gec.margin.report']
        domain = [('analytic_account_id', '=', self.bl_a.id), ('direction', '=', 'expense'),
                  ('plan_id', '=', self.target_plan.id)]
        self.assertFalse(Report.search(domain).revenue_stream_id)
        self.bl_a.gec_revenue_stream_id = self.maintenance
        Report.invalidate_model()
        self.assertEqual(Report.search(domain).revenue_stream_id, self.maintenance)

    def test_gross_margin_by_stream(self):
        self.bl_a.gec_revenue_stream_id = self.maintenance
        self._line(amount=-5000.0, target=self.bl_a, gl=self.gl_ruled_direct(), name='T cost')
        mix, _kpis = self._mix()
        maintenance = next(s for s in mix['streams'] if s['id'] == self.maintenance.id)
        self.assertAlmostEqual(maintenance['amount'], 50000.0, places=2)
        self.assertAlmostEqual(maintenance['gross'], 45000.0, places=2)
        self.assertAlmostEqual(maintenance['gross_pct'], 0.9, places=4)

    @classmethod
    def gl_ruled_direct(cls):
        return cls.env['account.account'].create({
            'name': 'T Direct', 'code': 'TST993', 'account_type': 'expense_direct_cost',
            'company_ids': [Command.set(cls.company.ids)],
        })

    def test_no_card_until_a_stream_is_in_use(self):
        (self.gl_license | self.gl_maintenance).gec_revenue_stream_id = False
        mix, kpis = self._mix()
        self.assertFalse(mix)
        self.assertNotIn('recurring', kpis)

    def test_health_check_names_revenue_without_a_stream(self):
        health = self.env['gec.abc.health'].create({
            'company_id': self.company.id, 'date_from': self.date_from, 'date_to': self.date_to,
        })
        findings = health._check_revenue_streams()
        self.assertEqual(len(findings), 1)
        self.assertIn('T Services', findings[0]['detail'])
        self.gl_services.gec_revenue_stream_id = self.services
        self.assertFalse(health._check_revenue_streams())

    def test_drilldown_opens_the_stream(self):
        action = self.dashboard.action_drilldown(
            'stream', self.date_from, self.date_to, self.target_plan.id, self.maintenance.id,
        )
        rows = self.env['gec.margin.report'].search(action['domain'])
        self.assertAlmostEqual(sum(rows.mapped('revenue_amount')), 20000.0, places=2)
        unassigned = self.dashboard.action_drilldown(
            'stream', self.date_from, self.date_to, self.target_plan.id, False,
        )
        rows = self.env['gec.margin.report'].search(unassigned['domain'])
        self.assertAlmostEqual(sum(rows.mapped('revenue_amount')), 10000.0, places=2)

    def test_standard_product_share(self):
        mix, _kpis = self._mix()
        self.assertAlmostEqual(mix['standard'], 50000.0, places=2)
        self.assertAlmostEqual(mix['standard_pct'], 50000.0 / 60000.0, places=4)
