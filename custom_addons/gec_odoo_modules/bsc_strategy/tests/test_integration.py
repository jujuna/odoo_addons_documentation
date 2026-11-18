# -*- coding: utf-8 -*-
"""The links to the rest of Odoo: project execution and KPIs filled from data."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestProjectExecution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang='en_US'))
        today = fields.Date.context_today(cls.env['bsc.scorecard'])
        cls.card = cls.env['bsc.scorecard'].create({
            'name': 'Execution', 'date_from': today.replace(month=1, day=1),
            'date_to': today.replace(month=12, day=31), 'responsible_id': cls.env.user.id,
        })
        cls.objective = cls.env['bsc.objective'].create({
            'name': 'Faster delivery', 'scorecard_id': cls.card.id,
            'perspective_id': cls.env.ref('bsc_strategy.perspective_process').id,
            'owner_id': cls.env.user.id,
        })
        approved = cls.env['bsc.initiative.stage'].search([('state', '=', 'approved')], limit=1)
        cls.initiative = cls.env['bsc.initiative'].create({
            'name': 'New warehouse layout', 'scorecard_id': cls.card.id,
            'objective_ids': [(6, 0, cls.objective.ids)], 'owner_id': cls.env.user.id,
            'stage_id': approved.id, 'progress': 40.0, 'budget_planned': 10000.0,
        })

    def _stage(self, name):
        return self.initiative.project_id.type_ids.filtered(lambda s: s.name == name)

    def test_progress_follows_the_board(self):
        self.initiative.action_create_project()
        self.assertTrue(self.initiative.use_project_progress)
        self.assertEqual(self.initiative.progress, 40.0)
        Task = self.env['project.task']
        project = self.initiative.project_id
        a, b, parent = (Task.create({'name': n, 'project_id': project.id}) for n in 'abc')
        sub1, sub2 = (Task.create({'name': n, 'project_id': project.id, 'parent_id': parent.id})
                      for n in ('c1', 'c2'))
        # Work units: a, b, c1, c2 - the parent counts through its subtasks.
        self.assertEqual(self.initiative.task_count, 4)
        self.assertEqual(self.initiative.progress, 0.0)

        a.stage_id = self._stage('Done')
        self.assertEqual(a.state, '1_done')
        self.assertEqual(self.initiative.progress, 25.0)

        b.stage_id = self._stage('Cancelled')
        self.assertEqual(b.state, '1_canceled')
        self.assertEqual(self.initiative.task_count, 3)
        self.assertAlmostEqual(self.initiative.progress, 33.3)

        a.stage_id = self._stage('In Progress')
        self.assertEqual(a.state, '01_in_progress')
        self.assertEqual(self.initiative.progress, 0.0)

        (a | sub1 | sub2).write({'state': '1_done'})
        self.assertEqual(self.initiative.progress, 100.0)
        self.assertTrue(any('Every task' in (m.preview or '')
                            for m in self.initiative.message_ids))

    def test_other_projects_keep_their_own_rules(self):
        self.initiative.action_create_project()
        board = self.initiative.project_id.type_ids
        done = self.env['project.task.type'].create({'name': 'Done', 'fold': False})
        other = self.env['project.project'].create({'name': 'Unrelated', 'type_ids': [(6, 0, done.ids)]})
        self.assertNotIn(done, board)
        task = self.env['project.task'].create({'name': 'x', 'project_id': other.id})
        task.stage_id = done
        self.assertNotEqual(task.state, '1_done')

    def test_folded_cancel_column_is_not_progress(self):
        self.initiative.action_create_project()
        project = self.initiative.project_id
        parked = self.env['project.task.type'].create({'name': 'Cancelled by client', 'fold': True})
        project.type_ids |= parked
        Task = self.env['project.task']
        a = Task.create({'name': 'a', 'project_id': project.id})
        Task.create({'name': 'b', 'project_id': project.id})
        a.stage_id = parked
        self.assertEqual(self.initiative.task_count, 1)
        self.assertEqual(self.initiative.progress, 0.0)

    def test_task_write_cost_does_not_grow_with_the_project(self):
        self.initiative.action_create_project()
        project = self.initiative.project_id
        Task = self.env['project.task']
        Task.create([{'name': str(i), 'project_id': project.id} for i in range(30)])
        task = Task.create({'name': 'probe', 'project_id': project.id})
        done = self.env.ref('bsc_strategy.task_stage_done')
        progress = self.env.ref('bsc_strategy.task_stage_in_progress')
        task.stage_id = done
        self.env.invalidate_all()
        with self.assertQueryCount(__system__=60):
            task.stage_id = progress
            task.stage_id = done
            self.env.flush_all()

    def test_single_task_with_subtasks(self):
        self.initiative.action_create_task()
        task = self.initiative.task_id
        Task = self.env['project.task']
        s1 = Task.create({'name': 's1', 'project_id': task.project_id.id, 'parent_id': task.id})
        Task.create({'name': 's2', 'project_id': task.project_id.id, 'parent_id': task.id})
        self.assertEqual(self.initiative.task_count, 2)
        s1.state = '1_done'
        self.assertEqual(self.initiative.progress, 50.0)

    def test_manual_progress_is_left_alone(self):
        self.initiative.action_create_project()
        self.initiative.use_project_progress = False
        self.env['project.task'].create({'name': 'x', 'project_id': self.initiative.project_id.id,
                                         'state': '1_done'})
        self.assertEqual(self.initiative.progress, 40.0)
        self.assertEqual(self.initiative.project_progress, 100.0)


@tagged('post_install', '-at_install')
class TestKpiFromOdooData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = 'Asia/Tbilisi'
        today = fields.Date.context_today(cls.env['bsc.scorecard'])
        cls.card = cls.env['bsc.scorecard'].create({
            'name': 'Data', 'date_from': today.replace(day=1),
            'date_to': today.replace(month=12, day=31), 'responsible_id': cls.env.user.id,
            'frequency': 'monthly',
        })
        cls.objective = cls.env['bsc.objective'].create({
            'name': 'Deliver', 'scorecard_id': cls.card.id,
            'perspective_id': cls.env.ref('bsc_strategy.perspective_process').id,
            'owner_id': cls.env.user.id,
        })
        cls.kpi = cls.env['bsc.kpi'].create({
            'name': 'Tasks closed', 'objective_id': cls.objective.id,
            'owner_id': cls.env.user.id, 'default_target': 2.0,
        })
        cls.project = cls.env['project.project'].create({'name': 'Delivery'})
        cls.other = cls.env['project.project'].create({'name': 'Other'})
        cls.card.action_activate()

    def _wizard(self, **values):
        return self.env['bsc.kpi.connect'].create(dict({'kpi_id': self.kpi.id}, **values))

    def test_catalogue_lists_installed_apps_only(self):
        keys = dict(self.env['bsc.kpi.connect']._recipe_selection())
        self.assertIn('tasks_done', keys)
        installed = set(self.env['ir.module.module'].search(
            [('state', '=', 'installed')]).mapped('name'))
        if 'crm' not in installed:
            self.assertNotIn('crm_win_rate', keys)

    def test_connect_fills_the_open_period_and_respects_the_filter(self):
        Task = self.env['project.task']
        for name, project in (('a', self.project), ('b', self.project), ('c', self.other)):
            Task.create({'name': name, 'project_id': project.id}).state = '1_done'
        wizard = self._wizard(recipe='tasks_done',
                              extra_domain="[('project_id', '=', %d)]" % self.project.id)
        self.assertIn('<b>2.00</b>', wizard.preview)
        wizard.action_connect()
        self.assertEqual(self.kpi.data_source, 'odoo')
        self.assertEqual(self.kpi.source_id.recipe_key, 'tasks_done')
        row = self.kpi.measurement_ids.filtered(
            lambda m: m.period_id == self.card.current_period_id)
        self.assertEqual(row.actual_value, 2.0)
        self.assertEqual(row.auto_state, 'ok')
        kpi2 = self.kpi.copy({'name': 'Tasks closed 2'})
        self.env['bsc.kpi.connect'].create({'kpi_id': kpi2.id, 'recipe': 'tasks_done'}).action_connect()
        self.assertEqual(kpi2.source_id, self.kpi.source_id)

    def test_typed_figure_is_kept_and_clearing_hands_it_back(self):
        row = self.kpi.measurement_ids.filtered(
            lambda m: m.period_id == self.card.current_period_id)
        row.actual_value = 7.0
        self._wizard(recipe='tasks_done',
                     extra_domain="[('project_id', '=', %d)]" % self.project.id).action_connect()
        self.assertEqual(row.actual_value, 7.0)
        self.assertEqual(row.auto_state, 'manual')
        row.action_reset()
        self.assertFalse(row.auto_state)
        self.kpi.action_refresh_now()
        self.assertEqual(row.auto_state, 'ok')
        self.assertEqual(row.actual_value, 0.0)

    def test_scale_for_a_kpi_kept_in_thousands(self):
        self.kpi.uom_name = 'thousand tasks'
        Task = self.env['project.task']
        for name in 'ab':
            Task.create({'name': name, 'project_id': self.project.id}).state = '1_done'
        wizard = self.env['bsc.kpi.connect'].with_context(default_kpi_id=self.kpi.id).create(
            {'recipe': 'tasks_done',
             'extra_domain': "[('project_id', '=', %d)]" % self.project.id})
        self.assertEqual(wizard.scale, '0.001')
        wizard.action_connect()
        row = self.kpi.measurement_ids.filtered(
            lambda m: m.period_id == self.card.current_period_id)
        self.assertAlmostEqual(row.actual_value, 0.002)

    def test_disconnect(self):
        self._wizard(recipe='tasks_done').action_connect()
        self.kpi.action_disconnect_source()
        self.assertEqual(self.kpi.data_source, 'manual')
        self.assertFalse(self.kpi.source_id)

    def test_share_of_records(self):
        Task = self.env['project.task']
        tasks = Task.create([{'name': str(i), 'project_id': self.project.id} for i in range(4)])
        tasks[0].state = '1_done'
        source = self.env['bsc.kpi.source'].create({
            'name': 'Share of tasks done',
            'model_id': self.env['ir.model']._get('project.task').id,
            'domain': "[('project_id', '=', %d)]" % self.project.id,
            'aggregate': 'ratio', 'ratio_domain': "[('state', '=', '1_done')]",
            'date_field_id': self.env['ir.model.fields']._get('project.task', 'create_date').id,
        })
        today = fields.Date.context_today(source)
        value, count = source._fetch_value(today, today)
        self.assertEqual(count, 4)
        self.assertEqual(value, 25.0)

    def test_period_bounds_use_the_scorecard_time_zone(self):
        source = self.env['bsc.kpi.source'].new({
            'model_id': self.env['ir.model']._get('project.task').id,
            'date_field_id': self.env['ir.model.fields']._get('project.task', 'create_date').id,
        })
        day = fields.Date.context_today(source)
        bounds = source._period_bounds(self.env['project.task'], day, day, tz_name='Asia/Tbilisi')
        start = datetime.combine(day, time.min, tzinfo=ZoneInfo('Asia/Tbilisi'))
        self.assertEqual(bounds[0][2], start.astimezone(timezone.utc).replace(tzinfo=None))
