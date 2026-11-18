from odoo import Command
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestMarginStatementUI(HttpCase):
    """Walk the filter bar in a real browser: no server-side test sees the OWL component failing to render."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Plan = cls.env['account.analytic.plan']
        Account = cls.env['account.analytic.account']

        cls.project_plan, _others = Plan._get_all_plans()
        cls.account, cls.other = [
            Account.create({'name': name, 'plan_id': cls.project_plan.id})
            for name in ('UI Project', 'UI Other')
        ]
        for name, account in (('UI Project', cls.account), ('UI Other', cls.other)):
            cls.env['project.project'].create({
                'name': name, 'company_id': cls.company.id,
                'account_id': account.id,
            })

        component = cls.env['gec.margin.component'].search(
            [('code', '=', 'revenue')], limit=1)
        cls.gl = cls.env['account.account'].create({
            'name': 'UI Revenue', 'code': 'UIT400', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': component.id,
        })
        direct = cls.env['gec.margin.component'].search(
            [('code', '=', 'direct_cost')], limit=1)
        cls.gl_cost = cls.env['account.account'].create({
            'name': 'UI Cost', 'code': 'UIT600',
            'account_type': 'expense_direct_cost',
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': direct.id,
        })
        today = cls.env.cr.now().date()
        column = cls.project_plan._column_name()
        for account in (cls.account, cls.other):
            for amount, general in ((120000.0, cls.gl), (-45000.0, cls.gl_cost)):
                cls.env['account.analytic.line'].create({
                    'name': 'UI line', 'date': today.replace(month=6, day=15),
                    'amount': amount, 'company_id': cls.company.id,
                    'general_account_id': general.id, column: account.id,
                })

    def test_the_filter_bar_works_in_a_browser(self):
        self.start_tour(
            "/odoo/action-gec_analytic_margin."
            "action_gec_margin_statement_report",
            "gec_margin_statement_tour",
            login="admin",
        )

    def test_the_dashboard_draws_in_a_browser(self):
        self.start_tour(
            "/odoo/action-gec_analytic_margin.action_gec_margin_dashboard",
            "gec_abc_dashboard_tour",
            login="admin",
        )
