from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestMarginStatement(GecMarginCommon):
    """The transposed report must be the same money, arranged differently.
    Risks from the explosion: an amount counted twice on component lines, one falling off the ladder
    (unclassified account), two rows sharing a synthetic id."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.level = cls.env['gec.margin.level'].create({
            'name': 'T Operating Margin',
            'code': 't_operating',
            'sequence': 5,
            'component_ids': [Command.set((cls.direct | cls.overhead).ids)],
        })
        cls.gl_direct = cls.env['account.account'].create({
            'name': 'T Direct Cost', 'code': 'TST901', 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': cls.direct.id,
        })
        cls._line(amount=-1000.0, target=cls.bl_a, gl=cls.gl_direct, name='T direct')
        cls._line(amount=-400.0, target=cls.bl_a, gl=cls.gl_pool, name='T overhead')

        cls.statement = cls.env['gec.margin.statement.report']
        cls.report = cls.env['gec.margin.report']

    def test_ladder_rows_are_ordered_under_their_components(self):
        """A subtotal belongs directly below the last component it contains, without sequencing rungs by hand."""
        rows = self.env['gec.margin.row'].search([])
        by_code = {row.code: row for row in rows}
        self.assertIn('t_operating', by_code, "the new level did not become a rung")
        self.assertIn('t_overhead', by_code)

        level_row = by_code['t_operating']
        members = (by_code['t_direct'], by_code['t_overhead'])
        self.assertGreater(
            level_row.sequence, max(member.sequence for member in members),
            "the subtotal sorts above a component it contains",
        )
        self.assertEqual(level_row.row_type, 'level')
        self.assertEqual(by_code['t_direct'].row_type, 'component')

    def test_component_lines_reconcile_with_the_margin_report(self):
        """Summing the component lines must give exactly what the untransposed report gives."""
        original = sum(self.report.search([]).mapped('amount'))
        transposed = sum(
            self.statement.search([('is_component_row', '=', True)]).mapped('amount')
        )
        self.assertAlmostEqual(original, transposed, places=2)

    def test_subtotal_line_equals_its_measure_column(self):
        """The rung and the level column are two readings of one definition."""
        column = self.level._column_name()
        self.assertIn(column, self.report._fields)
        from_columns = sum(self.report.search([]).mapped(column))
        from_rows = sum(
            self.statement
            .search([('margin_row_id.level_id', '=', self.level.id)])
            .mapped('amount')
        )
        self.assertAlmostEqual(from_columns, from_rows, places=2)
        self.assertAlmostEqual(from_rows, -1400.0, places=2)

    def test_an_amount_appears_once_per_rung_it_belongs_to(self):
        """-1000 of Direct Cost is on its component line and on the subtotal; that repetition is what a P&L is."""
        direct_rows = self.statement.search([
            ('component_id', '=', self.direct.id),
            ('analytic_account_id', '=', self.bl_a.id),
        ])
        rungs = direct_rows.mapped('margin_row_id.code')
        self.assertEqual(sorted(rungs), ['t_direct', 't_operating'])
        self.assertEqual(
            len(direct_rows.filtered('is_component_row')), 1,
            "the amount is counted more than once among the component lines",
        )

    def test_an_unclassified_amount_still_shows_up_once(self):
        """An amount on no rung must not fall out of the report (driver lines have no GL account)."""
        self._drivers()
        self.statement.invalidate_model()
        orphan = self.statement.search([('margin_row_id', '=', False)])
        self.assertTrue(orphan, "rows with no component were dropped from the report")
        self.assertTrue(
            all(orphan.mapped('is_component_row')),
            "an unclassified amount must still be counted by the totals filter",
        )

    def test_synthetic_ids_do_not_collide(self):
        """Three explosions share one id space: plan, ladder rung, budget/actual."""
        ids = self.statement.search([]).ids
        self.assertTrue(ids, "the statement produced no rows at all")
        self.assertEqual(len(ids), len(set(ids)), "two statement rows share an id")

    def test_the_pivot_shape_the_report_exists_for(self):
        """Ladder down the side, plans across the top."""
        groups = self.statement._read_group(
            [('analytic_account_id', '=', self.bl_a.id)],
            groupby=['margin_row_id', 'plan_id'],
            aggregates=['amount:sum'],
        )
        cells = {
            (row.code, plan.name): amount
            for row, plan, amount in groups
        }
        self.assertAlmostEqual(cells[('t_direct', 'T Business Line')], -1000.0, places=2)
        self.assertAlmostEqual(cells[('t_overhead', 'T Business Line')], -400.0, places=2)
        self.assertAlmostEqual(cells[('t_operating', 'T Business Line')], -1400.0, places=2)

    def test_the_untransposed_report_is_unchanged(self):
        """The old report must not inherit the explosion, or every figure on it would be multiplied."""
        rows = self.report.search([('analytic_account_id', '=', self.bl_a.id)])
        self.assertEqual(
            len(rows.filtered(lambda row: row.component_id == self.direct)), 1,
            "the margin report now returns one row per ladder rung",
        )
