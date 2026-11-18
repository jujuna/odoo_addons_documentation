# -*- coding: utf-8 -*-
"""The end-to-end cycle: design, activate, report, close, review."""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestBscWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.user = cls.env.user
        cls.perspective_financial = cls.env.ref('bsc_strategy.perspective_financial')
        cls.perspective_learning = cls.env.ref('bsc_strategy.perspective_learning')
        today = fields.Date.context_today(cls.env['bsc.scorecard'])
        cls.scorecard = cls.env['bsc.scorecard'].create({
            'name': 'Test Strategy',
            'company_id': cls.company.id,
            'date_from': today.replace(month=1, day=1),
            'date_to': today.replace(month=12, day=31),
            'frequency': 'quarterly',
            'responsible_id': cls.user.id,
        })
        cls.objective = cls.env['bsc.objective'].create({
            'name': 'Grow revenue',
            'code': 'F1',
            'scorecard_id': cls.scorecard.id,
            'perspective_id': cls.perspective_financial.id,
            'owner_id': cls.user.id,
            'weight': 100.0,
        })
        cls.kpi = cls.env['bsc.kpi'].create({
            'name': 'Revenue',
            'objective_id': cls.objective.id,
            'owner_id': cls.user.id,
            'uom_name': 'GEL',
            'direction': 'higher_better',
            'weight': 100.0,
        })

    def test_activation_requires_a_measure(self):
        objective = self.env['bsc.objective'].create({
            'name': 'Naked objective',
            'scorecard_id': self.scorecard.id,
            'perspective_id': self.perspective_learning.id,
            'owner_id': self.user.id,
        })
        with self.assertRaises(UserError):
            self.scorecard.action_activate()
        objective.assessment_mode = 'qualitative'
        self.scorecard.action_activate()
        self.assertEqual(self.scorecard.state, 'active')

    def test_activation_generates_periods_and_rows(self):
        self.scorecard.action_activate()
        self.assertEqual(len(self.scorecard.period_ids), 4,
                         "A calendar year reviewed quarterly gives four periods")
        period = self.scorecard.current_period_id
        self.assertTrue(period, "There must be a current period")
        self.assertEqual(len(period.measurement_ids), 1)
        measurement = period.measurement_ids
        self.assertFalse(measurement.actual_value_set)
        self.assertEqual(measurement.status, 'no_data')
        self.assertEqual(period.completion_rate, 0.0)

    def test_reporting_a_figure(self):
        self.scorecard.action_activate()
        measurement = self.scorecard.current_period_id.measurement_ids
        measurement.write({'target_value': 100.0, 'actual_value': 96.0})
        self.assertTrue(measurement.actual_value_set)
        self.assertEqual(measurement.entered_by_id, self.user)
        self.assertAlmostEqual(measurement.achievement, 96.0)
        self.assertEqual(measurement.status, 'green')
        self.assertAlmostEqual(self.objective.score, 96.0)
        self.assertEqual(self.objective.status, 'green')
        self.assertAlmostEqual(self.scorecard.score, 96.0)
        self.assertEqual(self.scorecard.current_period_id.completion_rate, 100.0)

    def test_zero_is_a_real_figure(self):
        """Reporting zero must count as reported."""
        self.scorecard.action_activate()
        measurement = self.scorecard.current_period_id.measurement_ids
        measurement.write({'target_value': 100.0, 'actual_value': 0.0,
                           'comment': 'Nothing sold this quarter.'})
        self.assertTrue(measurement.actual_value_set)
        self.assertEqual(measurement.status, 'red')
        self.assertEqual(self.scorecard.current_period_id.completion_rate, 100.0)

    def test_red_figure_needs_a_reason(self):
        self.scorecard.action_activate()
        measurement = self.scorecard.current_period_id.measurement_ids
        with self.assertRaises(ValidationError):
            measurement.write({'target_value': 100.0, 'actual_value': 10.0})
        measurement.write({'target_value': 100.0, 'actual_value': 10.0,
                           'comment': 'Two contracts slipped to next quarter.'})
        self.assertEqual(measurement.status, 'red')

    def test_incomplete_period_does_not_close_silently(self):
        self.scorecard.action_activate()
        period = self.scorecard.current_period_id
        with self.assertRaises(UserError):
            period.action_close()
        period.action_force_close()
        self.assertEqual(period.state, 'closed')

    def test_closed_period_rejects_writes(self):
        self.scorecard.action_activate()
        period = self.scorecard.current_period_id
        measurement = period.measurement_ids
        measurement.write({'target_value': 100.0, 'actual_value': 99.0})
        period.action_close()
        self.assertEqual(period.state, 'closed')
        with self.assertRaises(UserError):
            measurement.write({'actual_value': 120.0})
        measurement.with_context(bsc_bypass_period_lock=True).write({'actual_value': 120.0})
        self.assertAlmostEqual(measurement.actual_value, 120.0)

    def test_qualitative_objective_scores_without_kpi(self):
        objective = self.env['bsc.objective'].create({
            'name': 'Strengthen the culture',
            'scorecard_id': self.scorecard.id,
            'perspective_id': self.perspective_learning.id,
            'owner_id': self.user.id,
            'assessment_mode': 'qualitative',
            'weight': 100.0,
        })
        self.scorecard.action_activate()
        objective.qualitative_status = 'amber'
        self.assertEqual(objective.status, 'amber')
        self.assertAlmostEqual(objective.score, 85.0)
        with self.assertRaises(ValidationError):
            objective.qualitative_status = 'red'

    def test_cause_effect_link_rules(self):
        driver = self.env['bsc.objective'].create({
            'name': 'Train the team',
            'scorecard_id': self.scorecard.id,
            'perspective_id': self.perspective_learning.id,
            'owner_id': self.user.id,
            'assessment_mode': 'qualitative',
        })
        link = self.env['bsc.objective.link'].create({
            'source_id': driver.id,
            'target_id': self.objective.id,
            'hypothesis': 'A better trained team closes more deals.',
            'strength': 'medium',
        })
        self.assertIn(link, self.objective.link_in_ids)
        self.assertIn(link, driver.link_out_ids)
        self.assertFalse(link.validated)
        with self.assertRaises(ValidationError):
            self.env['bsc.objective.link'].create({
                'source_id': driver.id,
                'target_id': driver.id,
                'hypothesis': 'Nonsense.',
            })

    def test_initiative_gates(self):
        self.scorecard.action_activate()
        initiative = self.env['bsc.initiative'].create({
            'name': 'Launch the new service line',
            'scorecard_id': self.scorecard.id,
            'objective_ids': [(6, 0, self.objective.ids)],
            'owner_id': self.user.id,
        })
        self.assertEqual(initiative.state, 'proposed')
        approved = self.env.ref('bsc_strategy.initiative_stage_approved')
        with self.assertRaises(UserError):
            initiative.stage_id = approved
        initiative.budget_planned = 15000.0
        initiative.stage_id = approved
        self.assertEqual(initiative.state, 'approved')
        self.assertTrue(initiative.approval_date)
        self.assertEqual(initiative.approved_by_id, self.user)
        done = self.env.ref('bsc_strategy.initiative_stage_done')
        with self.assertRaises(UserError):
            initiative.stage_id = done
        initiative.result_summary = 'Service line launched, first three clients signed.'
        initiative.stage_id = done
        self.assertAlmostEqual(initiative.progress, 100.0)

    def test_review_closes_the_loop(self):
        self.scorecard.action_activate()
        period = self.scorecard.current_period_id
        period.measurement_ids.write({
            'target_value': 100.0,
            'actual_value': 40.0,
            'comment': 'Pipeline dried up.',
        })
        review = self.env['bsc.review'].create({
            'scorecard_id': self.scorecard.id,
            'period_id': period.id,
        })
        review.action_prepare()
        self.assertIn(self.objective, review.red_objective_ids)
        self.assertAlmostEqual(review.completion_snapshot, 100.0)
        with self.assertRaises(UserError):
            review.action_done()
        review.decisions = '<p>Reassign two people to sales for the next quarter.</p>'
        review.action_done()
        self.assertEqual(review.state, 'done')

    def test_computed_status_is_searchable(self):
        """Filtering off-track objectives works on the computed status, whose search value may be an OrderedSet."""
        self.scorecard.action_activate()
        self.scorecard.current_period_id.measurement_ids.write({
            'target_value': 100.0, 'actual_value': 20.0, 'comment': 'Missed badly.'})
        Objective = self.env['bsc.objective']
        self.assertEqual(self.objective.status, 'red')
        self.assertIn(self.objective, Objective.search([('status', '=', 'red')]))
        self.assertIn(self.objective, Objective.search([('status', 'in', ['red', 'amber'])]))
        self.assertNotIn(self.objective, Objective.search([('status', '!=', 'red')]))
        self.assertNotIn(self.objective, Objective.search([('status', '=', 'green')]))
        Kpi = self.env['bsc.kpi']
        self.assertIn(self.kpi, Kpi.search([('current_status', '=', 'red')]))
        self.assertIn(self.scorecard,
                      self.env['bsc.scorecard'].search([('status', '=', 'red')]))

    def test_copy_to_new_cycle_carries_the_design_only(self):
        driver = self.env['bsc.objective'].create({
            'name': 'Train the team',
            'scorecard_id': self.scorecard.id,
            'perspective_id': self.perspective_learning.id,
            'owner_id': self.user.id,
            'assessment_mode': 'qualitative',
        })
        self.env['bsc.objective.link'].create({
            'source_id': driver.id,
            'target_id': self.objective.id,
            'hypothesis': 'A better trained team closes more deals.',
        })
        self.scorecard.action_activate()
        self.scorecard.current_period_id.measurement_ids.write({
            'target_value': 100.0, 'actual_value': 99.0})
        action = self.scorecard.action_duplicate_to_new_cycle()
        new_card = self.env['bsc.scorecard'].browse(action['res_id'])
        self.assertEqual(new_card.state, 'draft')
        self.assertEqual(len(new_card.objective_ids), len(self.scorecard.objective_ids))
        self.assertEqual(len(new_card.objective_ids.kpi_ids),
                         len(self.scorecard.objective_ids.kpi_ids),
                         "KPIs travel with their objective")
        new_links = new_card.objective_ids.link_out_ids
        self.assertEqual(len(new_links), 1, "The strategy map is rebuilt")
        self.assertIn(new_links.source_id, new_card.objective_ids)
        self.assertIn(new_links.target_id, new_card.objective_ids,
                      "A copied link must not point at the old scorecard")
        self.assertFalse(new_card.period_ids, "Periods stay with their cycle")
        self.assertFalse(new_card.objective_ids.kpi_ids.measurement_ids,
                         "Figures stay with their cycle")
