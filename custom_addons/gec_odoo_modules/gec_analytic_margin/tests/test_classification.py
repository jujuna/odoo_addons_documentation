from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestClassificationGuardrails(GecMarginCommon):
    """Two ways the model was wrong without saying so."""

    def test_an_unclassified_expense_is_overhead_not_cost_of_revenue(self):
        """Odoo's generic Expenses type is operating cost, not cost of sales (which has its own account type)."""
        account = self.env['account.account'].create({
            'name': 'T Unclassified Expense',
            'code': 'TSTC10',
            'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.assertFalse(
            account.gec_margin_component_id,
            "the account under test is supposed to be unclassified",
        )
        self._line(amount=-5000.0, target=self.bl_a, gl=account, name='T unclassified')

        rows = self.env['gec.margin.report'].search([
            ('general_account_id', '=', account.id),
        ])
        self.assertTrue(rows, "the amount did not reach the report at all")
        self.assertEqual(
            set(rows.mapped('component_id.code')), {'overhead'},
            "a generic expense account is still being read as cost of revenue",
        )

    def test_an_explicit_component_still_wins(self):
        """The fallback is a fallback — it must not override a decision."""
        account = self.env['account.account'].create({
            'name': 'T Explicit Direct Cost',
            'code': 'TSTC11',
            'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
            'gec_margin_component_id': self.direct.id,
        })
        self._line(amount=-3000.0, target=self.bl_a, gl=account, name='T explicit')

        rows = self.env['gec.margin.report'].search([
            ('general_account_id', '=', account.id),
        ])
        self.assertEqual(set(rows.mapped('component_id')), {self.direct})

    def test_two_projects_cannot_share_one_analytic_account(self):
        """Two projects behind one analytic account are one cost object, so they must be told apart."""
        Project = self.env['project.project']
        account = self.env['account.analytic.account'].create({
            'name': 'T Shared Account', 'plan_id': self.source_plan.id,
        })
        Project.create({'name': 'T First Project', 'account_id': account.id})

        with self.assertRaises(ValidationError):
            Project.create({'name': 'T Second Project', 'account_id': account.id})

    def test_two_ordinary_projects_each_get_their_own_account(self):
        """Creating two projects back to back must not collide on the analytic account."""
        projects = self.env['project.project'].create([
            {'name': 'T Ordinary A'},
            {'name': 'T Ordinary B'},
        ])
        self.assertEqual(len(projects), 2)
        accounts = projects.mapped('account_id')
        if accounts:
            self.assertEqual(
                len(accounts), 2,
                "two projects ended up sharing one analytic account",
            )
