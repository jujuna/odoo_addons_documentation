from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestReportingCurrency(GecMarginCommon):
    """Two companies in two currencies, read together: 100 booked in the second is 200 here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        main = cls.company.currency_id
        other = cls.env['res.currency'].with_context(active_test=False).search([('id', '!=', main.id), ('name', 'in', ('EUR', 'GBP', 'GEL'))], limit=1)
        other.active = True
        cls.other_currency = other
        cls.env['res.currency.rate'].create({
            'currency_id': other.id, 'company_id': cls.company.id, 'name': '2026-01-01', 'rate': 0.5,
        })
        cls.co2 = cls.env['res.company'].create({'name': 'T Foreign Co', 'currency_id': other.id})
        cls.env.user.company_ids |= cls.co2
        for company, amount, code in ((cls.company, 1000.0, 'TST930'), (cls.co2, 100.0, 'TST931')):
            gl = cls.env['account.account'].with_company(company).create({
                'name': 'T Income', 'code': code, 'account_type': 'income',
                'company_ids': [Command.set(company.ids)],
            })
            cls.env['account.analytic.line'].create({
                'name': 'T sale', 'date': cls.date, 'amount': amount, 'company_id': company.id,
                'general_account_id': gl.id, cls.target_col: cls.bl_a.id,
            })

    def _revenue(self, companies):
        D = self.env['gec.margin.dashboard'].with_company(self.company).with_context(allowed_company_ids=companies.ids)
        data = D.get_dashboard_data(self.date_from, self.date_to, self.target_plan.id)
        return data, next(k for k in data['profitability']['kpis'] if k['key'] == 'revenue')['value']

    def test_one_currency_is_untouched(self):
        data, revenue = self._revenue(self.company)
        self.assertFalse(data['mixed_currency'])
        self.assertAlmostEqual(revenue, 1000.0, places=2)

    def test_two_currencies_convert_at_the_rate_of_the_date(self):
        data, revenue = self._revenue(self.company | self.co2)
        self.assertTrue(data['mixed_currency'])
        self.assertAlmostEqual(revenue, 1000.0 + 100.0 / 0.5, places=2)

    def test_the_statement_model_is_untouched_without_the_switch(self):
        rows = self.env['gec.margin.report'].with_context(allowed_company_ids=(self.company | self.co2).ids).search([
            ('company_id', '=', self.co2.id), ('line_type', '=', 'actual')])
        self.assertAlmostEqual(sum(rows.mapped('amount')), 100.0 * len(rows.mapped('plan_id')), places=2)
        self.assertEqual(rows.currency_id, self.other_currency)
