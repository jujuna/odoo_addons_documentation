from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestViews(TransactionCase):
    """Every view must render, and the report measures must be selectable."""

    def test_all_views_render(self):
        views = self.env['ir.ui.view'].search([
            ('model', '!=', False),
            ('id', 'in', self.env['ir.model.data'].search([
                ('module', '=', 'gec_analytic_margin'),
                ('model', '=', 'ir.ui.view'),
            ]).mapped('res_id')),
        ])
        self.assertTrue(views, "the module ships no views — check the manifest")
        for view in views:
            with self.subTest(view=view.xml_id or view.name):
                self.env[view.model].get_view(view.id, view.type)

    def test_inherited_views_do_not_break_other_models(self):
        """A view inherited in primary mode is copied onto another model (hr_timesheet: Timesheets Analysis)."""
        for model in ('account.analytic.line', 'account.move.line',
                      'account.analytic.distribution.model', 'account.account'):
            for view_type in ('list', 'form', 'search'):
                with self.subTest(model=model, view_type=view_type):
                    self.env[model].get_view(view_type=view_type)
        analysis = self.env.get('timesheets.analysis.report')
        if analysis is not None:
            for view_type in ('pivot', 'search'):
                with self.subTest(model='timesheets.analysis.report', view_type=view_type):
                    analysis.get_view(view_type=view_type)

    def test_margin_levels_are_selectable_measures(self):
        report = self.env['gec.margin.report']
        levels = self.env['gec.margin.level'].search([])
        self.assertTrue(levels, "no margin levels are installed")

        arch = report.get_view(view_type='pivot')['arch']
        for level in levels:
            column = level._column_name()
            self.assertIn(column, report._fields,
                          f"{level.name}: column {column} was never created")
            field = report._fields[column]
            self.assertTrue(
                field.aggregator,
                f"{level.name}: without an aggregator it cannot be a measure",
            )
            # `invisible="1"` in the arch removes the measure from the menu; leaving it out offers it.
            self.assertNotIn(
                f'name="{column}" type="measure" invisible',
                arch.replace("'", '"'),
                f"{level.name} is hidden from the measures menu",
            )

    def test_distribution_model_form_exposes_everything_configurable(self):
        """Activities and rules have no menu: a field not surfaced on this form is unreachable."""
        # The page is gated by the ABC switch and get_view strips what the user cannot see, so grant it first.
        self.env.user.group_ids |= self.env.ref('gec_analytic_margin.group_gec_abc')
        arch = self.env['account.analytic.distribution.model'].get_view(
            view_type='form')['arch']
        for field in ('gec_activity_id', 'gec_driver_label', 'gec_source_model_id',
                      'gec_source_domain', 'gec_source_analytic_path', 'gec_measure',
                      'gec_practical_capacity', 'gec_rate_mode',
                      'gec_planned_quantity', 'gec_value_added', 'gec_rule_ids'):
            self.assertIn(field, arch, f"{field} is unreachable from the ABC page")

        rules_arch = self.env['gec.allocation.rule'].get_view(view_type='form')['arch']
        for field in ('step', 'source_plan_id', 'target_plan_id', 'driver',
                      'share_mode', 'resource_share', 'line_ids'):
            self.assertIn(field, rules_arch, f"{field} missing from the rule form")

    def test_component_and_rule_lists_can_be_opened(self):
        """Inline-editable lists need open_form_view or the form is unreachable."""
        for xml_id in ('gec_analytic_margin.view_gec_margin_component_list',):
            view = self.env.ref(xml_id)
            arch = self.env[view.model].get_view(view.id, 'list')['arch']
            self.assertIn('editable', arch)
            self.assertIn('open_form_view', arch,
                          f"{xml_id}: editable list with no way to reach the form")
