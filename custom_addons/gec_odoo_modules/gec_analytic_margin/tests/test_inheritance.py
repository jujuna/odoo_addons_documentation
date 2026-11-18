from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestProjectTagsReachTheHours(GecMarginCommon):
    """Hours logged on a project carry that project's other analytic tags.
    hr_timesheet copies the plan columns itself;
    Odoo does not fix items posted before the project was filled in: covered here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.has_timesheets = 'project_id' in cls.env['account.analytic.line']._fields
        cls.project = cls.env['project.project'].create({
            'name': 'T Tagged Project', 'company_id': cls.company.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'T Timesheet Employee', 'company_id': cls.company.id,
        }) if cls.has_timesheets else None

    def setUp(self):
        super().setUp()
        if not self.has_timesheets:
            self.skipTest("analytic items carry no project without Timesheets")

    def _timesheet(self, **overrides):
        vals = {
            'name': 'T hours', 'date': self.date, 'unit_amount': 8.0,
            'company_id': self.company.id, 'project_id': self.project.id,
            'employee_id': self.employee.id,
        }
        vals.update(overrides)
        return self.env['account.analytic.line'].create(vals)

    def test_an_hour_carries_the_tag_its_project_names(self):
        """The mechanism the whole product story rests on, pinned down."""
        self.project[self.target_col] = self.bl_a.id
        self.assertEqual(self._timesheet()[self.target_col], self.bl_a)

    def test_an_hour_carries_nothing_when_the_project_names_nothing(self):
        """Why the demo showed no labour on any product: an empty field, not a missing mechanism."""
        self.project[self.target_col] = False
        self.assertFalse(self._timesheet()[self.target_col])

    def test_an_activity_can_measure_effort_per_cost_object(self):
        """With the project tagged, an activity pathed at that plan measures real hours."""
        self.project[self.target_col] = self.bl_a.id
        self._timesheet(unit_amount=12.0)

        quantities = self._activity().get_quantities(self.date_from, self.date_to)
        self.assertEqual(
            quantities.get(self.bl_a.id), 12.0,
            "hours logged on the project did not reach the cost object",
        )

    def test_items_posted_before_the_project_was_filled_in_stay_behind(self):
        """The gap Odoo leaves, and the reason the button exists."""
        self.project[self.target_col] = False
        old = self._timesheet()
        self.project[self.target_col] = self.bl_a.id

        self.assertFalse(
            old[self.target_col],
            "filling the project in rewrote history by itself",
        )
        self.assertEqual(
            self.env['account.analytic.line']._gec_items_behind_project_tag(
                self.target_plan,
            ),
            1,
        )

    def test_filling_from_projects_catches_them_up(self):
        self.project[self.target_col] = False
        old = self._timesheet()
        self.project[self.target_col] = self.bl_a.id

        self.target_plan.action_gec_fill_from_projects()
        self.assertEqual(old[self.target_col], self.bl_a)

    def test_filling_never_overwrites_a_tag_the_item_already_states(self):
        """An item naming a cost object is more precise than its project."""
        self.project[self.target_col] = self.bl_a.id
        stated = self._timesheet(**{self.target_col: self.bl_b.id})

        self.target_plan.action_gec_fill_from_projects()
        self.assertEqual(stated[self.target_col], self.bl_b)

    def test_the_count_is_zero_once_they_are_caught_up(self):
        self.project[self.target_col] = False
        self._timesheet()
        self.project[self.target_col] = self.bl_a.id
        self.target_plan.action_gec_fill_from_projects()

        self.assertEqual(
            self.env['account.analytic.line']._gec_items_behind_project_tag(
                self.target_plan,
            ),
            0,
        )

    def test_the_health_check_reports_a_reading_no_project_names(self):
        self._claim_reading('department')
        self.project[self.target_col] = False

        found = self._findings('No project names')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'warning')

    def test_the_health_check_reports_items_that_predate_the_tag(self):
        self._claim_reading('department')
        self.project[self.target_col] = False
        self._timesheet()
        self.project[self.target_col] = self.bl_a.id

        found = self._findings('predate')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, 'info')

    def test_the_health_check_ignores_plans_that_are_not_a_reading(self):
        """A Cost Center on a project means nothing, so it must not raise a warning."""
        self.target_plan.gec_section_key = False
        self.project[self.target_col] = False

        self.assertFalse(self._findings('No project names'))

    def _claim_reading(self, key):
        """Make this test's plan the named reading, releasing any plan the live database already uses."""
        Plan = self.env['account.analytic.plan']
        Plan.search([('gec_section_key', '=', key)]).gec_section_key = False
        self.target_plan.gec_section_key = key

    def _findings(self, contains):
        health = self.env['gec.abc.health'].create({
            'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
        })
        health.action_check()
        return [
            check for check in health.check_ids
            if contains in check.name and check.res_id == self.target_plan.id
        ]
