from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestSetupHealthCheck(GecMarginCommon):
    """An ABC model fails quietly; each finding here is a question you would otherwise have to know to ask."""

    def _unclassified_total(self):
        """The gross figure the chart finding headlines; the case checks the movement, not the absolute total."""
        found = self._findings(self._health(), 'no margin component')
        if not found:
            return 0.0
        return float(found[0].name.split(' of movement')[0].replace(',', ''))

    def _health(self):
        health = self.env['gec.abc.health'].create({
            'company_id': self.company.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
        })
        health.action_check()
        return health

    def _findings(self, health, contains, record=None):
        """Findings about this test's own records, not the live database's activities and rules."""
        return [
            check for check in health.check_ids
            if contains in check.name
            and (record is None
                 or (check.res_model == record._name and check.res_id == record.id))
        ]

    def test_a_clean_setup_reports_nothing(self):
        """The check has to be quiet when things are right, or nobody reads it."""
        self._pool()
        self._drivers()
        activity = self._activity(practical_capacity=200.0)
        self._rule(activity=activity)

        health = self._health()
        mine = [
            check for check in health.check_ids
            if activity.name in check.name or 'T rule' in check.name
        ]
        self.assertFalse(
            mine, f"a correct setup was reported: {[c.name for c in mine]}",
        )

    def test_an_activity_that_counts_everything_is_an_error(self):
        """An empty filter on analytic items sums hours, invoice quantities and allocation output into one number."""
        self._pool()
        self._drivers()
        activity = self._activity(source_domain='[]')
        self._rule(activity=activity)

        found = self._findings(self._health(), 'counts every analytic item', activity)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'error')
        self.assertEqual(found[0].res_id, activity.id)
        self.assertEqual(found[0].res_model, 'gec.activity')

    def test_an_activity_that_measures_nothing_is_reported(self):
        self._pool()
        activity = self._activity()
        self._rule(activity=activity)

        found = self._findings(self._health(), 'measured no hour', activity)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'warning')

    def test_an_activity_with_a_broken_path_is_an_error_not_a_crash(self):
        """A wrong path is reported as a finding, not raised in the middle of a run."""
        self._pool()
        self._drivers()
        activity = self._activity(source_analytic_path='nonsense_field_id')
        self._rule(activity=activity)

        found = self._findings(self._health(), 'cannot count at all', activity)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'error')
        self.assertIn('nonsense_field_id', found[0].detail)

    def test_an_activity_no_rule_uses_is_reported(self):
        self._pool()
        self._drivers()
        activity = self._activity()

        found = self._findings(
            self._health(), 'is not used by any rule', activity,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'info')

    def test_a_standard_rate_without_a_capacity_is_reported(self):
        self._pool()
        self._drivers()
        activity = self._activity(rate_mode='standard', standard_rate=100.0)
        self._rule(activity=activity)

        found = self._findings(self._health(), 'no practical capacity', activity)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'info')

    def test_a_rule_with_cost_and_no_base_is_an_error(self):
        """Cost to spread and nothing to spread it over: the whole amount silently stays on the source."""
        self._pool()
        rule = self._rule(activity=self._activity())

        found = self._findings(
            self._health(), 'nothing to spread it over', rule,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'error')
        self.assertIn('40,000', found[0].detail)

    def test_an_empty_pool_is_only_a_warning(self):
        """No cost this period is usually a quiet month, not a mistake."""
        self._drivers()
        rule = self._rule(activity=self._activity())

        found = self._findings(self._health(), 'has an empty pool', rule)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'warning')

    def test_two_rules_claiming_one_pool_twice_is_an_error(self):
        # A live database may already have an over-claimed pool; silence its rules.
        self.preexisting_rules.active = False
        self._pool()
        self._drivers()
        self._rule(activity=self._activity(), name='T rule one')
        self._rule(activity=self._activity(name='T second activity'),
                   name='T rule two')

        found = self._findings(self._health(), 'of one cost pool')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'error')
        self.assertIn('200.0', found[0].name)

    def test_unclassified_money_is_reported_gross_not_net(self):
        """Gross, not net: -7,500, -4,425 and +13,000 net to 1,074 and would hide 25 thousand of misplaced money."""
        before = self._unclassified_total()
        income = self.env['account.account'].create({
            'name': 'T Unclassified Income', 'code': 'TSH400',
            'account_type': 'income',
            'company_ids': [Command.set(self.company.ids)],
        })
        expense = self.env['account.account'].create({
            'name': 'T Unclassified Expense', 'code': 'TSH600',
            'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        self._line(amount=10000.0, target=self.bl_a, gl=income, name='T in')
        self._line(amount=-9000.0, target=self.bl_a, gl=expense, name='T out')

        found = self._findings(self._health(), 'no margin component')
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(
            self._unclassified_total() - before, 19000.0, places=2,
            msg="the headline nets offsetting amounts into nothing",
        )
        self.assertIn('TSH400', found[0].detail)
        self.assertIn('TSH600', found[0].detail)

    def test_an_uncovered_pool_is_reported(self):
        """The same arithmetic the statement's banner uses, asked before a run."""
        orphan = self.env['account.analytic.account'].create({
            'name': 'T Orphan Centre', 'plan_id': self.source_plan.id,
        })
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        self._line(amount=-6000.0, source=orphan, gl=self.gl_pool,
                   name='T uncovered')

        found = self._findings(self._health(), 'covered by no rule')
        self.assertEqual(len(found), 1)
        self.assertIn('6,000', found[0].name)
        self.assertIn(orphan.display_name, found[0].detail)

    def test_the_statement_banner_and_the_health_check_cannot_disagree(self):
        """Both read one method, so there is nothing to keep in sync."""
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        orphan = self.env['account.analytic.account'].create({
            'name': 'T Orphan Two', 'plan_id': self.source_plan.id,
        })
        self._line(amount=-6000.0, source=orphan, gl=self.gl_pool, name='T u2')

        total, by_account = self.env['gec.allocation.rule']._uncovered_pool(
            self.date_from, self.date_to, self.company,
        )
        self.assertAlmostEqual(total, -6000.0, places=2)
        self.assertEqual(list(by_account), [orphan])

    def test_opening_the_screen_runs_the_checks(self):
        """An empty list and a button is a screen people close again."""
        self._pool()
        self._rule(activity=self._activity())
        health = self.env['gec.abc.health'].with_context(
            gec_check_on_open=True,
        ).create(self.env['gec.abc.health'].with_context(
            gec_check_on_open=True,
        ).default_get(['company_id', 'date_from', 'date_to', 'check_ids']))
        self.assertTrue(health.check_ids, "the screen opened with nothing on it")
