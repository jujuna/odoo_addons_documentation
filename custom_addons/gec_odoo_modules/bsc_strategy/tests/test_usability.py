# -*- coding: utf-8 -*-
"""Usability: scores for any period, rows for every started period, KPI own target,
all activation problems at once, demo load and removal, dashboard payload.
"""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestUsability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.user
        cls.financial = cls.env.ref('bsc_strategy.perspective_financial')
        cls.learning = cls.env.ref('bsc_strategy.perspective_learning')
        today = fields.Date.context_today(cls.env['bsc.scorecard'])
        quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        # A cycle whose current quarter is the fourth, so three have started before.
        cls.start = quarter_start - relativedelta(months=9)
        cls.scorecard = cls.env['bsc.scorecard'].create({
            'name': 'Usability Strategy',
            'date_from': cls.start,
            'date_to': cls.start + relativedelta(years=1, days=-1),
            'frequency': 'quarterly',
            'responsible_id': cls.user.id,
        })
        cls.objective = cls.env['bsc.objective'].create({
            'name': 'Grow revenue',
            'code': 'F1',
            'scorecard_id': cls.scorecard.id,
            'perspective_id': cls.financial.id,
            'owner_id': cls.user.id,
        })
        cls.kpi = cls.env['bsc.kpi'].create({
            'name': 'Revenue',
            'objective_id': cls.objective.id,
            'owner_id': cls.user.id,
            'direction': 'higher_better',
            'default_target': 100.0,
        })

    def _periods(self):
        return self.scorecard.period_ids.sorted('date_from')

    def _row(self, period, kpi=None):
        return period.measurement_ids.filtered(lambda m: m.kpi_id == (kpi or self.kpi))

    def test_activation_prepares_every_started_period(self):
        self.scorecard.action_activate()
        periods = self._periods()
        self.assertEqual(len(periods), 4)
        for period in periods:
            self.assertTrue(self._row(period), "%s has no row" % period.name)

    def test_kpi_target_reaches_the_first_row(self):
        self.scorecard.action_activate()
        self.assertEqual(self._row(self._periods()[0]).target_value, 100.0)

    def test_target_set_later_reaches_open_rows(self):
        kpi = self.env['bsc.kpi'].create({
            'name': 'Margin', 'objective_id': self.objective.id,
            'owner_id': self.user.id, 'direction': 'higher_better',
        })
        self.scorecard.action_activate()
        row = self._row(self._periods()[0], kpi)
        self.assertEqual(row.target_value, 0.0)
        kpi.default_target = 12.0
        self.assertEqual(row.target_value, 12.0)

    def test_scores_can_be_read_for_any_period(self):
        self.scorecard.action_activate()
        first, *middle, last = self._periods()
        self._row(first).write({'actual_value': 50.0, 'comment': 'Bad quarter'})
        self._row(last).actual_value = 100.0
        latest = self.scorecard.with_context(bsc_period_id=last.id)
        self.assertAlmostEqual(latest.score, 100.0)
        pinned = self.scorecard.with_context(bsc_period_id=first.id)
        self.assertAlmostEqual(pinned.score, 50.0)
        self.assertEqual(pinned.status, 'red')
        self.assertEqual(latest.status, 'green')
        # Unpinned: the latest ended period still open is current, not the one containing today.
        self.assertEqual(self.scorecard.current_period_id, middle[-1])

    def test_review_snapshot_is_for_its_own_period(self):
        """A Q1 review prepared in Q2 freezes Q1's score."""
        self.scorecard.action_activate()
        first = self._periods()[0]
        self._row(first).write({'actual_value': 50.0, 'comment': 'Bad quarter'})
        self.env['bsc.measurement'].search([
            ('period_id', '=', first.id), ('actual_value_set', '=', False)]).write(
            {'actual_value': 1.0, 'comment': 'filler'})
        first.action_close()
        review = self.scorecard.review_ids.filtered(lambda r: r.period_id == first)
        self.assertTrue(review)
        self.assertAlmostEqual(review.score_snapshot, 50.0)
        self.assertIn(self.objective, review.red_objective_ids)

    def test_activation_lists_every_problem(self):
        self.env['bsc.objective'].create({
            'name': 'Empty one', 'scorecard_id': self.scorecard.id,
            'perspective_id': self.learning.id, 'owner_id': self.user.id,
        })
        self.env['bsc.objective'].create({
            'name': 'Empty two', 'scorecard_id': self.scorecard.id,
            'perspective_id': self.learning.id, 'owner_id': self.user.id,
        })
        with self.assertRaises(UserError) as caught:
            self.scorecard.action_activate()
        message = str(caught.exception)
        self.assertIn('Empty one', message)
        self.assertIn('Empty two', message)

    def test_setup_checklist(self):
        self.assertFalse(self.scorecard.setup_done)
        self.assertIn('Usability', self.scorecard.name)
        self.assertTrue(self.scorecard.setup_checklist)
        self.scorecard.action_activate()
        self.scorecard.invalidate_recordset(['setup_done', 'setup_checklist'])
        self.assertTrue(self.scorecard.setup_done)

    def test_calendar_period_names(self):
        self.scorecard.action_activate()
        first = self._periods()[0]
        quarter = (self.start.month - 1) // 3 + 1
        self.assertEqual(first.name, '%s-Q%s' % (self.start.year, quarter))

    def test_early_review_is_prepared_again_on_close(self):
        self.scorecard.action_activate()
        first = self._periods()[0]
        first.action_open_review()
        review = self.scorecard.review_ids.filtered(lambda r: r.period_id == first)
        self.assertEqual(review.completion_snapshot, 0.0)
        self._row(first).write({'actual_value': 100.0})
        first.action_close()
        self.assertEqual(review.completion_snapshot, 100.0)
        self.assertAlmostEqual(review.score_snapshot, 100.0)

    def test_read_only_places_link_to_the_editable_record(self):
        self.scorecard.action_activate()
        action = self.kpi.action_open_current_measurement()
        self.assertEqual(action['res_model'], 'bsc.measurement')
        row = self.env['bsc.measurement'].browse(action['res_id'])
        self.assertEqual(row.period_id, self.scorecard.current_period_id)
        self.assertEqual(row.action_open_form()['res_id'], row.id)
        self.assertEqual(self.objective.action_open_form()['res_id'], self.objective.id)
        self.assertEqual(self.kpi.action_open_form()['res_model'], 'bsc.kpi')

    def test_dashboard_payload(self):
        self.scorecard.action_activate()
        data = self.env['bsc.scorecard'].get_dashboard_data(
            scorecard_id=self.scorecard.id, period_id=self._periods()[0].id)
        self.assertEqual(data['scorecard']['id'], self.scorecard.id)
        self.assertEqual(data['period']['id'], self._periods()[0].id)
        self.assertEqual(len(data['trend']), 1)
        self.assertEqual(data['attention']['missing_total'], 1)
        self.assertEqual(len(data['kpis']), 1)
        action = self._periods()[0].action_open_review()
        self.assertEqual(action['res_model'], 'bsc.review')


@tagged('post_install', '-at_install')
class TestDemoData(TransactionCase):

    def test_load_and_remove(self):
        real = self.env['bsc.scorecard'].create({
            'name': 'Real one',
            'date_from': date(2030, 1, 1),
            'date_to': date(2030, 12, 31),
            'responsible_id': self.env.user.id,
        })
        wizard = self.env['bsc.demo.data'].create({})
        wizard.action_load()
        card = self.env['bsc.scorecard'].search([('is_demo', '=', True)])
        self.assertEqual(len(card), 1)
        self.assertEqual(card.state, 'active')
        self.assertEqual(len(card.objective_ids), 8)
        self.assertEqual(len(card.link_ids), 9)
        periods = card.period_ids.sorted('date_from')
        self.assertEqual(periods.mapped('state'), ['closed', 'closed', 'closed', 'open'])
        self.assertEqual(len(card.review_ids), 3)
        self.assertEqual(card.review_ids.filtered(lambda r: r.state == 'done').mapped(
            'period_id'), periods[:2])
        for period in periods:
            data = self.env['bsc.scorecard'].get_dashboard_data(card.id, period.id)
            self.assertTrue(data['kpis'])
        with self.assertRaises(UserError):
            self.env['bsc.demo.data'].create({}).action_load()

        self.env['bsc.demo.data'].create({}).action_remove()
        self.assertFalse(card.exists())
        self.assertFalse(self.env['bsc.measurement'].search([('scorecard_id', '=', card.id)]))
        self.assertTrue(real.exists())

    def test_georgian_texts(self):
        self.env['res.lang']._activate_lang('ka_GE')
        wizard = self.env['bsc.demo.data'].with_context(lang='ka_GE').create({})
        wizard.action_load()
        card = self.env['bsc.scorecard'].search([('is_demo', '=', True)])
        self.assertIn('დემო', card.with_context(lang='ka_GE').name)


@tagged('post_install', '-at_install')
class TestZeroFigure(TransactionCase):

    def test_reporting_zero_with_the_switch(self):
        today = fields.Date.context_today(self.env['bsc.scorecard'])
        card = self.env['bsc.scorecard'].create({
            'name': 'Zero', 'date_from': today.replace(month=1, day=1),
            'date_to': today.replace(month=12, day=31), 'responsible_id': self.env.user.id,
        })
        objective = self.env['bsc.objective'].create({
            'name': 'Safety', 'scorecard_id': card.id,
            'perspective_id': self.env.ref('bsc_strategy.perspective_process').id,
            'owner_id': self.env.user.id,
        })
        self.env['bsc.kpi'].create({
            'name': 'Accidents', 'objective_id': objective.id, 'owner_id': self.env.user.id,
            'direction': 'lower_better', 'default_target': 2.0,
        })
        card.action_activate()
        row = card.current_period_id.measurement_ids
        self.assertFalse(row.actual_value_set)
        row.write({'actual_value_set': True})
        self.assertTrue(row.actual_value_set)
        self.assertEqual(row.entered_by_id, self.env.user)
        self.assertEqual(row.status, 'green')

    def test_unticking_reported_withdraws_the_figure(self):
        today = fields.Date.context_today(self.env['bsc.scorecard'])
        card = self.env['bsc.scorecard'].create({
            'name': 'Untick', 'date_from': today.replace(month=1, day=1),
            'date_to': today.replace(month=12, day=31), 'responsible_id': self.env.user.id,
        })
        objective = self.env['bsc.objective'].create({
            'name': 'Sales', 'scorecard_id': card.id,
            'perspective_id': self.env.ref('bsc_strategy.perspective_financial').id,
            'owner_id': self.env.user.id,
        })
        self.env['bsc.kpi'].create({
            'name': 'Orders', 'objective_id': objective.id, 'owner_id': self.env.user.id,
            'default_target': 10.0,
        })
        card.action_activate()
        row = card.current_period_id.measurement_ids
        row.write({'actual_value': 12.0})
        row.action_submit()
        row.action_validate()
        row.write({'actual_value_set': False})
        self.assertFalse(row.actual_value_set)
        self.assertEqual(row.state, 'draft')
        self.assertEqual(row.actual_value, 0.0)
        self.assertEqual(row.status, 'no_data')
