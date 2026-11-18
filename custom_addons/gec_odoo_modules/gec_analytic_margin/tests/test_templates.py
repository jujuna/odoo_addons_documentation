from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestActivityTemplates(GecMarginCommon):
    """Every offered template is exercised against its database: model, date field and path exist, the measure runs."""

    def _new(self, template_key):
        activity = self.env['gec.activity'].new({
            'name': 'T templated',
            'company_id': self.company.id,
            'template_key': template_key,
        })
        activity._onchange_template_key()
        return activity

    def _created(self, template_key):
        """A saved activity built by the template: its values must be enough to create() a record directly."""
        Activity = self.env['gec.activity']
        return Activity.create({
            'name': f"T {template_key}",
            'company_id': self.company.id,
            **Activity._template_values(Activity.TEMPLATES[template_key]),
        })

    def test_only_installed_models_are_offered(self):
        Activity = self.env['gec.activity']
        offered = dict(Activity._selection_template_key())
        self.assertTrue(offered, "no template is offered at all")
        for key in offered:
            self.assertIn(
                Activity.TEMPLATES[key]['model'], self.env,
                f"{key} is offered but its model is not installed",
            )

    def test_every_offered_template_fills_every_required_field(self):
        Activity = self.env['gec.activity']
        for key, label in Activity._selection_template_key():
            with self.subTest(template=label):
                activity = self._new(key)
                self.assertTrue(activity.source_model_id)
                self.assertTrue(activity.source_date_field)
                self.assertTrue(activity.source_analytic_path)
                self.assertTrue(activity.driver_label)
                if activity.measure == 'field':
                    self.assertTrue(activity.measure_field)

    def test_every_offered_template_actually_runs(self):
        """The template counts without raising: ``get_quantities`` is where a wrong date field, domain or path fails."""
        Activity = self.env['gec.activity']
        for key, label in Activity._selection_template_key():
            with self.subTest(template=label):
                self.assertIsInstance(
                    self._created(key).get_quantities(
                        self.date_from, self.date_to,
                    ),
                    dict,
                )

    def test_the_pickers_agree_with_the_path_they_wrote(self):
        """The form must not show one thing and the engine read another."""
        Activity = self.env['gec.activity']
        for key, label in Activity._selection_template_key():
            with self.subTest(template=label):
                activity = self._new(key)
                rebuilt = '.'.join(filter(None, (
                    activity.source_analytic_via_id.name,
                    activity.source_analytic_field_id.name,
                )))
                self.assertEqual(
                    rebuilt, activity.source_analytic_path,
                    "the pickers and the technical path disagree",
                )
                self.assertEqual(
                    activity.source_date_field_id.name,
                    activity.source_date_field,
                )

    def test_choosing_a_template_does_not_clear_what_it_just_wrote(self):
        """Applying a template sets the model; the model's onchange must not clear the pickers just filled."""
        activity = self._new('timesheet_project')
        activity._onchange_source_model_clears_the_pickers()
        self.assertTrue(activity.source_analytic_path)
        self.assertTrue(activity.source_analytic_field_id)
        self.assertTrue(activity.source_date_field_id)

    def test_switching_model_by_hand_still_clears_a_stale_path(self):
        """The behaviour the unconditional clear was there for."""
        activity = self._new('task_done')
        self.assertEqual(activity.source_analytic_path, 'project_id.account_id')

        activity.source_model_id = self.env['ir.model']._get_id('res.partner')
        activity.source_model_name = 'res.partner'
        activity._onchange_source_model_clears_the_pickers()

        self.assertFalse(activity.source_analytic_via_id)
        self.assertFalse(activity.source_analytic_field_id)
        self.assertFalse(activity.source_analytic_path)
