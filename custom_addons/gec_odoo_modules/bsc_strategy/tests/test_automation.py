# -*- coding: utf-8 -*-
"""Every automation guard, exercised against a real source: a count of res.partner records created in the period.
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestAutomation(TransactionCase):

    @classmethod
    def _field_id(cls, model_name, field_name):
        """The ir.model.fields id of a field, as a source points at it."""
        return cls.env['ir.model.fields']._get(model_name, field_name).id

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = date.today()
        cls.source = cls.env['bsc.kpi.source'].create({
            'name': 'Partners created (test)',
            'model_id': cls.env['ir.model']._get_id('res.partner'),
            'domain': "[('ref', '=', 'BSC-TEST')]",
            'aggregate': 'count',
            'date_field_id': cls._field_id('res.partner', 'create_date'),
            'company_field_id': False,
            'uom_hint': 'partners',
        })
        cls.scorecard = cls.env['bsc.scorecard'].create({
            'name': 'Automation test card',
            'date_from': date(cls.today.year, 1, 1),
            'date_to': date(cls.today.year, 12, 31),
            # Quarterly: the deviation guard needs a previous period.
            'frequency': 'quarterly',
        })
        cls.objective = cls.env['bsc.objective'].create({
            'name': 'Grow the partner base',
            'scorecard_id': cls.scorecard.id,
            'perspective_id': cls.env.ref('bsc_strategy.perspective_customer').id,
        })
        cls.kpi = cls.env['bsc.kpi'].create({
            'name': 'New partners',
            'objective_id': cls.objective.id,
            'data_source': 'odoo',
            'source_id': cls.source.id,
            'direction': 'higher_better',
            'auto_deviation_limit': 50.0,
        })

    def _make_partners(self, count):
        self.env['res.partner'].create(
            [{'name': 'BSC test %s' % i, 'ref': 'BSC-TEST'} for i in range(count)])

    def _activate(self):
        """Activate and return the period containing today (where the test partners are created)."""
        self.scorecard.action_activate()
        return self.scorecard.period_ids.filtered(
            lambda p: p.date_from <= self.today <= p.date_to)

    def _measurement(self, period):
        return self.env['bsc.measurement'].search([
            ('kpi_id', '=', self.kpi.id), ('period_id', '=', period.id)])

    def _previous_period(self, period):
        return self.env['bsc.period'].search([
            ('scorecard_id', '=', self.scorecard.id),
            ('date_from', '<', period.date_from),
        ], order='date_from desc', limit=1)

    def test_rows_are_created_for_automated_kpis(self):
        """Core only prepares manual KPIs; the override must cover computed ones."""
        period = self._activate()
        self.assertTrue(self._measurement(period),
                        "An automated KPI got no measurement row.")

    def test_value_is_published_with_an_audit_trail(self):
        self._make_partners(4)
        period = self._activate()
        measurement = self._measurement(period)
        measurement._refresh_automated()
        self.assertTrue(measurement.actual_value_set)
        self.assertEqual(measurement.actual_value, 4.0)
        self.assertEqual(measurement.auto_state, 'ok')
        self.assertTrue(measurement.is_automated)
        self.assertIn('Partners created (test)', measurement.source_note)
        self.assertEqual(measurement.auto_record_count, 4)

    def test_empty_result_is_not_reported_as_zero(self):
        """The guard that matters most: a broken filter must not publish a zero."""
        source = self.source.copy({
            'name': 'Matches nothing',
            'domain': "[('ref', '=', 'NO-SUCH-REF')]",
            'aggregate': 'sum',
            'value_field_id': self._field_id('res.partner', 'color'),
        })
        self.kpi.source_id = source
        period = self._activate()
        measurement = self._measurement(period)
        measurement._refresh_automated()
        self.assertFalse(measurement.actual_value_set,
                         "An empty result set was published as a figure.")
        self.assertEqual(measurement.auto_state, 'no_data')
        self.assertTrue(measurement.auto_needs_attention)

    def test_a_plain_count_of_zero_is_a_real_figure(self):
        """Zero records is a legitimate answer for a count, unlike for a sum."""
        period = self._activate()
        measurement = self._measurement(period)
        measurement._refresh_automated()
        self.assertTrue(measurement.actual_value_set)
        self.assertEqual(measurement.actual_value, 0.0)
        self.assertEqual(measurement.auto_state, 'ok')

    def _history(self):
        """A two-year quarterly scorecard with a KPI on the partner source.
        Returns ``(kpi, previous, ended, running)``: the running period, and the two ended before it."""
        card = self.env['bsc.scorecard'].create({
            'name': 'Deviation history card',
            'date_from': date(self.today.year - 1, 1, 1),
            'date_to': date(self.today.year, 12, 31),
            'frequency': 'quarterly',
        })
        objective = self.env['bsc.objective'].create({
            'name': 'Grow the partner base',
            'scorecard_id': card.id,
            'perspective_id': self.env.ref('bsc_strategy.perspective_customer').id,
        })
        kpi = self.env['bsc.kpi'].create({
            'name': 'New partners', 'objective_id': objective.id,
            'data_source': 'odoo', 'source_id': self.source.id,
            'direction': 'higher_better', 'auto_deviation_limit': 50.0,
        })
        card.action_activate()
        periods = card.period_ids.sorted('date_from')
        running = periods.filtered(lambda p: p.date_from <= self.today <= p.date_to)
        index = list(periods).index(running)
        return kpi, periods[index - 2], periods[index - 1], running

    def _row(self, kpi, period):
        return self.env['bsc.measurement'].search([
            ('kpi_id', '=', kpi.id), ('period_id', '=', period.id)])

    def _make_partners_on(self, count, day):
        """Partners backdated to ``day``."""
        partners = self.env['res.partner'].create(
            [{'name': 'BSC test %s' % i, 'ref': 'BSC-TEST'} for i in range(count)])
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id IN %s",
            (datetime(day.year, day.month, day.day, 12), tuple(partners.ids)))
        self.env['res.partner'].invalidate_model(['create_date'])

    def test_large_deviation_is_held_back_then_confirmed(self):
        """A jump is held only once its period has ended, and withdraws the earlier figure.
        Ended period publishes 2, the source jumps to 12: figure taken back, new one waits."""
        kpi, previous, ended, __ = self._history()
        self._row(kpi, previous)._publish(2.0, 2)
        middle = ended.date_from + timedelta(days=45)
        self._make_partners_on(2, middle)
        measurement = self._row(kpi, ended)
        measurement._refresh_automated()
        self.assertEqual(measurement.auto_state, 'ok')
        self.assertEqual(measurement.actual_value, 2.0)
        self._make_partners_on(10, middle)
        measurement._refresh_automated()
        self.assertEqual(measurement.auto_state, 'deviation')
        self.assertFalse(measurement.actual_value_set,
                         "A held figure was published instead of being held back.")
        self.assertEqual(measurement.auto_pending_value, 12.0)
        measurement.action_accept_pending()
        self.assertEqual(measurement.actual_value, 12.0)
        self.assertEqual(measurement.auto_state, 'ok')

    def test_a_running_period_is_never_held(self):
        """Its figure is partial by nature, so it is compared to nothing."""
        kpi, __, ended, running = self._history()
        self._row(kpi, ended)._publish(2.0, 2)
        self._make_partners(10)
        measurement = self._row(kpi, running)
        measurement._refresh_automated()
        self.assertEqual(measurement.auto_state, 'ok')
        self.assertEqual(measurement.actual_value, 10.0)

    def test_deviation_check_is_skipped_without_history(self):
        self._make_partners(9)
        period = self._activate()
        measurement = self._measurement(period)
        measurement._refresh_automated()
        self.assertEqual(measurement.auto_state, 'ok',
                         "A first figure was treated as suspicious.")

    def test_a_human_edit_wins_permanently(self):
        self._make_partners(3)
        period = self._activate()
        measurement = self._measurement(period)
        measurement._refresh_automated()
        measurement.write({'actual_value': 99.0})
        self.assertEqual(measurement.auto_state, 'manual')
        self._make_partners(5)
        measurement._refresh_automated()
        self.assertEqual(measurement.actual_value, 99.0,
                         "The source overwrote a figure a person had corrected.")

    def test_validated_figures_are_never_overwritten(self):
        self._make_partners(3)
        period = self._activate()
        measurement = self._measurement(period)
        measurement._refresh_automated()
        measurement.action_submit()
        measurement.action_validate()
        self._make_partners(5)
        measurement._refresh_automated()
        self.assertEqual(measurement.actual_value, 3.0)

    def test_a_closed_period_is_never_written_to(self):
        self._make_partners(3)
        period = self._activate()
        measurement = self._measurement(period)
        measurement._refresh_automated()
        period.action_close(force=True)
        self._make_partners(5)
        measurement._refresh_automated()
        self.assertEqual(measurement.actual_value, 3.0,
                         "The automation wrote into a closed period.")

    def test_a_red_automated_figure_does_not_raise_on_write(self):
        """The core rule would make the cron fail; it must be deferred instead."""
        period = self._activate()
        measurement = self._measurement(period)
        measurement.target_value = 100.0
        self._make_partners(1)
        measurement.invalidate_recordset()
        # Would raise ValidationError without the deferred rule.
        measurement._refresh_automated()
        self.assertEqual(measurement.status, 'red')
        self.assertFalse(measurement.comment)

    def test_an_unexplained_red_automated_figure_blocks_the_close(self):
        period = self._activate()
        measurement = self._measurement(period)
        measurement.target_value = 100.0
        self._make_partners(1)
        measurement.invalidate_recordset()
        measurement._refresh_automated()
        with self.assertRaises(UserError):
            period.action_close()
        measurement.comment = 'Campaign started late.'
        period.action_close()
        self.assertEqual(period.state, 'closed')

    def test_a_broken_source_is_recorded_not_raised(self):
        period = self._activate()
        measurement = self._measurement(period)
        # Bypass the constrains to simulate a model removed by an uninstall.
        self.env.cr.execute(
            "UPDATE bsc_kpi_source SET model_name = 'no.such.model' WHERE id = %s",
            (self.source.id,))
        self.source.invalidate_recordset()
        measurement._refresh_automated()
        self.assertEqual(measurement.auto_state, 'error')
        self.assertFalse(measurement.actual_value_set)

    def test_a_source_cannot_use_a_field_from_another_model(self):
        """Writing a field of another model past the dropdown must still be refused."""
        with self.assertRaises(ValidationError):
            self.env['bsc.kpi.source'].create({
                'name': 'Field from elsewhere',
                'model_id': self.env['ir.model']._get_id('res.partner'),
                'date_field_id': self._field_id('res.users', 'login_date'),
            })

    def test_a_source_needs_a_date_field(self):
        with self.assertRaises(ValidationError):
            self.env['bsc.kpi.source'].create({
                'name': 'No date',
                'model_id': self.env['ir.model']._get_id('res.partner'),
            })

    def test_a_source_needs_a_model(self):
        with self.assertRaises(ValidationError):
            self.env['bsc.kpi.source'].create({'name': 'No model'})

    def test_a_source_cannot_aggregate_a_non_numeric_field(self):
        with self.assertRaises(ValidationError):
            self.env['bsc.kpi.source'].create({
                'name': 'Bad aggregate',
                'model_id': self.env['ir.model']._get_id('res.partner'),
                'date_field_id': self._field_id('res.partner', 'create_date'),
                'aggregate': 'sum',
                'value_field_id': self._field_id('res.partner', 'name'),
            })

    def test_a_domain_is_data_never_code(self):
        with self.assertRaises(ValidationError):
            self.env['bsc.kpi.source'].create({
                'name': 'Executable domain',
                'model_id': self.env['ir.model']._get_id('res.partner'),
                'date_field_id': self._field_id('res.partner', 'create_date'),
                'domain': "[('id', '=', __import__('os').getpid())]",
            })

    def test_a_computed_kpi_must_have_a_source(self):
        with self.assertRaises(ValidationError):
            self.env['bsc.kpi'].create({
                'name': 'Sourceless',
                'objective_id': self.objective.id,
                'data_source': 'odoo',
            })


class TestTargetsAndReview(TransactionCase):
    """The two smaller automations: proposed targets, and the review that opens itself."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = date.today()
        cls.env.user.group_ids = [
            (4, cls.env.ref('bsc_strategy.group_bsc_admin').id)]
        cls.scorecard = cls.env['bsc.scorecard'].create({
            'name': 'Targets test card',
            'date_from': date(today.year, 1, 1),
            # Runs into next year so the current period always has a successor.
            'date_to': date(today.year + 1, 12, 31),
            'frequency': 'quarterly',
        })
        cls.objective = cls.env['bsc.objective'].create({
            'name': 'Grow revenue',
            'scorecard_id': cls.scorecard.id,
            'perspective_id': cls.env.ref('bsc_strategy.perspective_financial').id,
        })

    def _kpi(self, **values):
        return self.env['bsc.kpi'].create(dict({
            'name': 'Revenue',
            'objective_id': self.objective.id,
        }, **values))

    def _two_periods(self):
        """The prepared period (containing today) and the one after it."""
        periods = self.scorecard.period_ids.sorted('date_from')
        today = date.today()
        first = periods.filtered(lambda p: p.date_from <= today <= p.date_to)
        index = list(periods).index(first)
        self.assertLess(index + 1, len(periods),
                        "No period follows the current one.")
        return first, periods[index + 1]

    def test_baseline_growth_proposes_the_target(self):
        self._kpi(baseline_value=1000.0, target_rule='baseline_growth', target_growth=10.0)
        self.scorecard.action_activate()
        measurement = self.scorecard.current_period_id.measurement_ids
        self.assertEqual(measurement.target_value, 1100.0)

    def test_growth_on_last_actual_uses_history_when_there_is_any(self):
        kpi = self._kpi(target_rule='previous_growth', target_growth=20.0)
        self.scorecard.action_activate()
        first, second = self._two_periods()
        first.measurement_ids.write({'target_value': 100.0, 'actual_value': 200.0})
        first.action_close(force=True)
        second.action_prepare_measurements()
        measurement = second.measurement_ids.filtered(lambda m: m.kpi_id == kpi)
        self.assertEqual(measurement.target_value, 240.0)

    def test_carry_forward_is_still_the_default(self):
        kpi = self._kpi()
        self.assertEqual(kpi.target_rule, 'carry')
        self.scorecard.action_activate()
        first, second = self._two_periods()
        first.measurement_ids.write({'target_value': 500.0, 'actual_value': 900.0})
        first.action_close(force=True)
        second.action_prepare_measurements()
        measurement = second.measurement_ids.filtered(lambda m: m.kpi_id == kpi)
        self.assertEqual(measurement.target_value, 500.0,
                         "The carried target changed - the core default was altered.")

    def test_closing_a_period_opens_a_prepared_review(self):
        self._kpi()
        self.scorecard.action_activate()
        period = self.scorecard.current_period_id
        period.measurement_ids.write({'target_value': 100.0, 'actual_value': 100.0})
        period.action_close()
        review = self.env['bsc.review'].search([('period_id', '=', period.id)])
        self.assertEqual(len(review), 1)
        self.assertEqual(review.state, 'draft')
        self.assertTrue(review.completion_snapshot,
                        "The review was created but not prepared.")

    def test_the_review_is_not_created_twice(self):
        self._kpi()
        self.scorecard.action_activate()
        period = self.scorecard.current_period_id
        period.action_close(force=True)
        period.action_reopen()
        period.action_close(force=True)
        self.assertEqual(
            self.env['bsc.review'].search_count([('period_id', '=', period.id)]), 1)

    def test_auto_review_can_be_switched_off(self):
        self._kpi()
        self.scorecard.auto_create_review = False
        self.scorecard.action_activate()
        period = self.scorecard.current_period_id
        period.action_close(force=True)
        self.assertFalse(self.env['bsc.review'].search([('period_id', '=', period.id)]))
