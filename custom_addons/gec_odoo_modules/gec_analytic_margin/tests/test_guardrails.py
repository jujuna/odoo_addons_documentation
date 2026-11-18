from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestGuardrails(GecMarginCommon):

    def test_source_and_target_plan_must_differ(self):
        with self.assertRaises(ValidationError):
            self._rule(target_plan_id=self.source_plan.id)

    def test_non_allocatable_source_is_flagged_before_the_run(self):
        gl = self.env['account.account'].create({
            'name': 'T Direct cost', 'code': 'TST910', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
            'gec_margin_component_id': self.direct.id,
        })
        rule = self._rule(source_gl_account_ids=[Command.set(gl.ids)])
        self.assertTrue(rule.gec_source_warning)
        self.assertIn('TST910', rule.gec_source_warning)

    def test_allocatable_source_is_silent(self):
        self.assertFalse(self._rule().gec_source_warning)

    def test_unclassified_source_is_flagged(self):
        gl = self.env['account.account'].create({
            'name': 'T Unclassified', 'code': 'TST920', 'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        rule = self._rule(source_gl_account_ids=[Command.set(gl.ids)])
        self.assertTrue(rule.gec_source_warning)

    def test_a_rule_classified_source_is_not_flagged(self):
        gl = self.env['account.account'].create({
            'name': 'T Ruled', 'code': 'TST921', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        rule = self._rule(source_gl_account_ids=[Command.set(gl.ids)])
        self.assertFalse(rule.gec_source_warning)

    def test_activities_are_isolated_per_company(self):
        other = self.env['res.company'].create({'name': 'T Other Co'})
        mine = self._activity()
        theirs = self._activity(name='T Theirs', company_id=other.id)

        user = self.env['res.users'].create({
            'name': 'T User', 'login': 't_user',
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('analytic.group_analytic_accounting').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
        })
        visible = self.env['gec.activity'].with_user(user).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible,
                         "one company must not see another's costing activities")

    def test_rules_are_isolated_per_company(self):
        other = self.env['res.company'].create({'name': 'T Other Co 2'})
        user = self.env['res.users'].create({
            'name': 'T User 2', 'login': 't_user_2',
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('analytic.group_analytic_accounting').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
        })
        mine = self._rule()
        theirs = self._rule(name='T theirs', company_id=other.id,
                            source_account_ids=False, source_gl_account_ids=False)
        visible = self.env['gec.allocation.rule'].with_user(user).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)

    def test_abc_switch_hides_the_costing_configuration(self):
        """One gate on the configuration section; menu groups are OR'ed, so a leftover group would keep it visible."""
        group = self.env.ref('gec_analytic_margin.group_gec_abc')
        config = self.env.ref('gec_analytic_margin.menu_gec_abc_config')
        self.assertEqual(
            config.group_ids, group,
            "the costing configuration is not gated by the ABC switch",
        )
        self.assertTrue(config.child_id, "the section has no menus under it")
        for child in config.child_id:
            self.assertFalse(
                child.group_ids - group,
                f"{child.name} carries a group of its own that defeats the gate",
            )
        self.assertEqual(
            self.env.ref('gec_analytic_margin.menu_gec_abc_runs').group_ids, group,
            "running an allocation is a costing job and must follow the switch",
        )

    def test_the_reports_are_visible_to_anyone_who_can_read_them(self):
        """The reports are gated by analytic accounting (implied by the ABC switch), not by the ABC switch itself.

        An accountant without analytic access could open the menu and the report would raise."""
        reports = self.env.ref('gec_analytic_margin.menu_gec_abc_reports')
        analytic = self.env.ref('analytic.group_analytic_accounting')
        self.assertEqual(reports.group_ids, analytic)
        self.assertNotIn(
            self.env.ref('gec_analytic_margin.group_gec_abc'), reports.group_ids,
            "the reports are gated behind the costing switch",
        )
        self.assertIn(analytic, self.env.ref(
            'gec_analytic_margin.group_gec_abc').implied_ids,
            "the ABC switch no longer grants the analytic access the reports need",
        )
        self.assertIn('Margin Analysis', reports.child_id.mapped('name'))

    def test_an_accountant_without_analytic_access_is_not_offered_the_reports(self):
        """The failure the gate exists to prevent: a menu that only errors."""
        reader = self.env['res.users'].create({
            'name': 'T Bare Accountant', 'login': 'tbare',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
        })
        if reader.has_group('analytic.group_analytic_accounting'):
            # Some databases give analytic accounting to every internal user, so this scenario cannot exist there.
            self.skipTest(
                "this database grants analytic accounting to all users"
            )
        visible = self.env['ir.ui.menu'].with_user(reader)._visible_menu_ids()
        self.assertNotIn(
            self.env.ref('gec_analytic_margin.menu_gec_abc_reports').id, visible,
            "an accountant with no analytic access is offered a report that "
            "can only raise",
        )

    def test_distribution_model_carries_its_activity_to_analytic_lines(self):
        """A matched model names the activity, and the analytic line a posted bill creates carries it."""
        activity = self._activity()
        self.env['account.analytic.distribution.model'].create({
            'account_prefix': self.gl_pool.code,
            'gec_activity_id': activity.id,
            'company_id': self.company.id,
            'analytic_distribution': {str(self.dir_a.id): 100},
        })
        move_line = self.env['account.move.line'].new({
            'account_id': self.gl_pool.id,
            'company_id': self.company.id,
        })
        self.assertEqual(move_line._gec_activity_from_distribution_models(), activity.id)

    def test_lowest_sequence_wins_when_two_models_match(self):
        first = self._activity(name='T First')
        second = self._activity(name='T Second')
        Distribution = self.env['account.analytic.distribution.model']
        distribution = {str(self.dir_a.id): 100}
        Distribution.create({'account_prefix': self.gl_pool.code, 'sequence': 5,
                             'gec_activity_id': first.id, 'company_id': self.company.id,
                             'analytic_distribution': distribution})
        Distribution.create({'account_prefix': self.gl_pool.code, 'sequence': 50,
                             'gec_activity_id': second.id, 'company_id': self.company.id,
                             'analytic_distribution': distribution})
        move_line = self.env['account.move.line'].new({
            'account_id': self.gl_pool.id,
            'company_id': self.company.id,
        })
        self.assertEqual(move_line._gec_activity_from_distribution_models(), first.id)

    def test_the_pickers_build_the_path(self):
        """Two dropdowns compose the path, so nobody types 'project_id.account_id' from memory."""
        Field = self.env['ir.model.fields']
        line = self.env['ir.model']._get('account.analytic.line')
        activity = self._activity()
        activity.source_analytic_path = False

        direct = Field.search([
            ('model', '=', 'account.analytic.line'), ('name', '=', 'account_id'),
        ], limit=1)
        activity.source_analytic_field_id = direct
        activity._onchange_source_analytic_pickers()
        self.assertEqual(activity.source_analytic_path, 'account_id')

        via = Field.search([('model_id', '=', line.id), ('name', '=', 'move_line_id')], limit=1)
        if via:
            activity.source_analytic_via_id = via
            self.assertEqual(
                activity.source_analytic_model, via.relation,
                "the second picker is not following the hop",
            )

    def test_a_broken_activity_says_so(self):
        """A wrong path measures nothing and moves no money without complaining.

        Checks run in order: is anything matched at all, then does the path lead anywhere."""
        activity = self._activity()
        activity.source_domain = "[('name', '=', 'nothing matches this at all')]"
        self.assertIn('would measure nothing', activity.setup_warning or '')

        self._line(quantity=5.0, target=self.bl_a, name='T hours')
        activity.source_domain = "[]"
        activity.source_analytic_path = 'nonsense_id'
        self.assertIn('not a valid path', activity.setup_warning or '')

    def test_a_sound_activity_is_silent(self):
        self._line(quantity=5.0, target=self.bl_a, name='T hours')
        activity = self._activity()
        self.assertFalse(activity.setup_warning)
