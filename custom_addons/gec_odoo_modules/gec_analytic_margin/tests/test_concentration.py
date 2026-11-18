from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestCustomerConcentration(GecMarginCommon):
    """How much of the revenue a few customers carry, company-wide, in March 2031 (a period nothing else writes to)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.bank_a = Partner.create({'name': 'T Bank A', 'is_company': True})
        cls.contact_a = Partner.create({'name': 'T Contact A', 'parent_id': cls.bank_a.id})
        cls.bank_b = Partner.create({'name': 'T Bank B', 'is_company': True})
        cls.bank_c = Partner.create({'name': 'T Bank C', 'is_company': True})
        cls.gl_income = cls.env['account.account'].create({
            'name': 'T Income', 'code': 'TST995', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
        })

        def sale(amount, partner, when='2031-03-15', **plans):
            cls.env['account.analytic.line'].create({
                'name': 'T sale', 'date': when, 'amount': amount,
                'company_id': cls.company.id, 'general_account_id': cls.gl_income.id,
                'partner_id': partner.id if partner else False,
                **{plan: account.id for plan, account in plans.items()},
            })

        sale(30000.0, cls.bank_a, **{cls.target_col: cls.bl_a})
        sale(20000.0, cls.contact_a, **{cls.target_col: cls.bl_b, cls.source_col: cls.dir_a})
        sale(30000.0, cls.bank_b, **{cls.source_col: cls.dir_a})
        sale(15000.0, cls.bank_c, **{cls.target_col: cls.bl_b})
        sale(5000.0, None, **{cls.target_col: cls.bl_a})
        sale(10000.0, cls.bank_a, when='2031-02-10', **{cls.target_col: cls.bl_a})
        sale(40000.0, cls.bank_b, when='2031-02-10', **{cls.target_col: cls.bl_a})

    def _concentration(self, plan=None):
        return self.env['gec.margin.dashboard'].get_dashboard_data(
            '2031-03-01', '2031-03-31', (plan or self.target_plan).id,
        )['profitability']['concentration']

    def test_shares_are_company_wide_and_count_each_amount_once(self):
        conc = self._concentration()
        self.assertAlmostEqual(conc['total'], 100000.0, places=2)
        self.assertEqual(conc['customer_count'], 3)
        self.assertEqual([c['id'] for c in conc['customers']],
                         [self.bank_a.id, self.bank_b.id, self.bank_c.id])
        self.assertAlmostEqual(conc['top_pct'], 0.5, places=4)
        self.assertAlmostEqual(conc['top_n_pct'], 0.95, places=4)
        self.assertEqual(conc['top_n'], 3)
        self.assertAlmostEqual(conc['customers'][1]['cumulative_pct'], 0.8, places=4)
        self.assertAlmostEqual(conc['no_customer'], 5000.0, places=2)

    def test_the_selected_plan_does_not_change_it(self):
        self.assertEqual(self._concentration(self.source_plan), self._concentration(self.target_plan))

    def test_previous_period_is_compared(self):
        conc = self._concentration()
        self.assertAlmostEqual(conc['prev_top_pct'], 0.8, places=4, msg="Bank B's 40 000 of 50 000")

    def test_drilldown_opens_the_whole_customer(self):
        action = self.env['gec.margin.dashboard'].action_drilldown(
            'customer', '2031-03-01', '2031-03-31', self.target_plan.id, self.bank_a.id,
        )
        rows = self.env['gec.margin.report'].search(action['domain'])
        self.assertAlmostEqual(sum(rows.mapped('revenue_amount')), 50000.0, places=2,
                               msg="the contact's invoice belongs to the bank")

    def test_nothing_to_show_without_revenue(self):
        data = self.env['gec.margin.dashboard'].get_dashboard_data(
            '2031-06-01', '2031-06-30', self.target_plan.id,
        )
        self.assertEqual(data['profitability']['concentration'], {})
