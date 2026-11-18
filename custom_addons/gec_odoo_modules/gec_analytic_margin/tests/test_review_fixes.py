from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestReviewFixes(GecMarginCommon):
    """Two readings of the same thing must agree.
    A search and the compute it mirrors, the report's SQL and the Apply button,
    batched and line-by-line Margin %, the uncovered-pool warning and the report classification."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.direct_component = cls.env.ref('gec_analytic_margin.component_direct_cost')
        cls.overhead_component = cls.env.ref('gec_analytic_margin.component_overhead')
        cls.gl_ruled_direct = cls.env['account.account'].create({
            'name': 'T Ruled Direct', 'code': 'TST970', 'account_type': 'expense_direct_cost',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.gl_ruled_overhead = cls.env['account.account'].create({
            'name': 'T Ruled Overhead', 'code': 'TST971', 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.gl_unclassified = cls.env['account.account'].create({
            'name': 'T Nothing', 'code': 'TST972', 'account_type': 'asset_current',
            'company_ids': [Command.set(cls.company.ids)],
        })

    def test_effective_component_search_accepts_what_odoo_20_passes(self):
        """'=' reaches the search method as 'in' with an OrderedSet."""
        Account = self.env['account.account']
        field = 'gec_margin_component_effective_id'
        self.assertEqual(self.gl_ruled_direct[field], self.direct_component)

        found = Account.search([(field, '=', self.direct_component.id)])
        self.assertIn(self.gl_ruled_direct, found)
        self.assertNotIn(self.gl_ruled_overhead, found)

        excluded = Account.search([(field, '!=', self.direct_component.id),
                                   ('id', 'in', (self.gl_ruled_direct | self.gl_ruled_overhead).ids)])
        self.assertEqual(excluded, self.gl_ruled_overhead)

        none = Account.search([(field, '=', False),
                               ('id', 'in', (self.gl_ruled_direct | self.gl_unclassified).ids)])
        self.assertEqual(none, self.gl_unclassified, "False must mean 'resolves to no component'")

    def test_a_company_scoped_rule_does_not_classify_other_companies(self):
        """The report's SQL and the Apply button honour the same company limit."""
        other = self.env['res.company'].create({'name': 'T Other Co'})
        self.env['gec.margin.classification.rule'].create({
            'sequence': 1,
            'code_prefix': 'TST97',
            'component_id': self.env.ref('gec_analytic_margin.component_personnel').id,
            'company_ids': [Command.set(other.ids)],
        })
        self.gl_ruled_direct.invalidate_recordset()
        self.assertEqual(
            self.gl_ruled_direct.gec_margin_component_effective_id, self.direct_component,
            "a rule limited to another company reclassified this company's account",
        )

    def test_uncovered_pool_counts_rule_classified_accounts(self):
        """Allocatable cost on an account classified only by a rule still counts."""
        self._rule()
        self._line(amount=-300.0, source=self.dir_a, gl=self.gl_ruled_overhead,
                   name='T uncovered')
        total, by_account = self.env['gec.allocation.rule']._uncovered_pool(
            self.date_from, self.date_to, self.company,
        )
        self.assertAlmostEqual(total, -300.0, places=2)
        self.assertAlmostEqual(by_account.get(self.dir_a), -300.0, places=2)

    def test_ladder_first_margin_base_is_the_same_batched_or_not(self):
        """Unfold All must not change a Margin % under Ladder First."""
        column = self.target_col
        for amount, gl in ((1000.0, self.gl_income()), (-400.0, self.gl_ruled_direct)):
            self.env['account.analytic.line'].create({
                'name': 'T ladder', 'date': self.date, 'amount': amount,
                'company_id': self.company.id, 'general_account_id': gl.id,
                column: self.bl_a.id,
            })
        report = self.env.ref('gec_analytic_margin.gec_margin_statement_report')
        handler = self.env['gec.margin.statement.report.handler']
        options = report.get_options({'gec_ladder_first': True})
        options['date'] = {**options['date'], 'date_from': self.date_from,
                           'date_to': self.date_to, 'mode': 'range', 'filter': 'custom'}
        axis = handler._gec_axis(options)
        self.assertEqual(axis[0], 'margin_row_id')

        direct_row = self.env['gec.margin.row'].search(
            [('component_id', '=', self.direct_component.id)], limit=1)
        chain = {
            'account.analytic.plan': self.target_plan.id,
            'gec.margin.row': direct_row.id,
            'account.analytic.account': self.bl_a.id,
        }
        batch = handler._custom_unfold_all_batch_data_generator(report, options, {})
        batched = handler._gec_object_revenue(report, options, chain, axis, batch)
        direct = handler._gec_object_revenue(report, options, chain, axis, None)
        self.assertEqual(batched, direct)
        self.assertAlmostEqual(next(iter(direct.values())), 1000.0, places=2,
                               msg="a cost rung is measured against the cost object's revenue")

    @classmethod
    def gl_income(cls):
        if not hasattr(cls, '_gl_income'):
            cls._gl_income = cls.env['account.account'].create({
                'name': 'T Income', 'code': 'TST973', 'account_type': 'income',
                'company_ids': [Command.set(cls.company.ids)],
            })
        return cls._gl_income
