from datetime import date

from odoo import Command, fields
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestMonthlyAllocationCron(GecMarginCommon):
    """The scheduled action must never allocate a period that is still moving: the trigger is the lock date."""

    def setUp(self):
        super().setUp()
        # Finished runs in a live database would make generate cases measure the guard; reset to draft.
        self.preexisting_runs.filtered(
            lambda run: run.state == 'done'
        ).state = 'draft'
        # The cron applies every active rule, so park the existing ones.
        self.preexisting_allocation_rules.active = False
        self.company.gec_allocation_cron_mode = 'draft'
        self.company.gec_allocation_cron_basis = 'lock'
        self.company.fiscalyear_lock_date = False
        self.company.hard_lock_date = False

    def _cron(self):
        return self.env['gec.allocation.run']._cron_generate_closed_periods()

    def _runs(self):
        return self.env['gec.allocation.run'].search([
            ('company_id', '=', self.company.id),
        ]) - self.preexisting_runs

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.preexisting_runs = cls.env['gec.allocation.run'].search([])
        cls.preexisting_allocation_rules = cls.env['gec.allocation.rule'].search([])

    def test_it_does_nothing_when_switched_off(self):
        self.company.gec_allocation_cron_mode = 'off'
        self.company.fiscalyear_lock_date = date(2026, 6, 30)
        self._cron()
        self.assertFalse(self._runs())

    def test_it_does_nothing_without_a_lock_date(self):
        """No lock date means nothing has been declared settled."""
        self._cron()
        self.assertFalse(self._runs())

    def test_a_lock_date_on_a_month_end_allocates_that_month(self):
        self.company.fiscalyear_lock_date = date(2026, 6, 30)
        self._cron()

        run = self._runs()
        self.assertEqual(len(run), 1)
        self.assertEqual(run.date_from, date(2026, 6, 1))
        self.assertEqual(run.date_to, date(2026, 6, 30))

    def test_a_lock_date_mid_month_falls_back_to_the_month_before(self):
        """Locked to the 15th means that month is still moving."""
        self.company.fiscalyear_lock_date = date(2026, 6, 15)
        self._cron()

        run = self._runs()
        self.assertEqual(run.date_from, date(2026, 5, 1))
        self.assertEqual(run.date_to, date(2026, 5, 31))

    def test_the_hard_lock_counts_too_and_the_later_one_wins(self):
        self.company.fiscalyear_lock_date = date(2026, 3, 31)
        self.company.hard_lock_date = date(2026, 6, 30)
        self._cron()
        self.assertEqual(self._runs().date_to, date(2026, 6, 30))

    def test_draft_mode_prepares_and_stops(self):
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        self.company.fiscalyear_lock_date = date(2026, 6, 30)
        self._cron()

        run = self._runs()
        self.assertEqual(run.state, 'draft')
        self.assertFalse(run.line_ids, "a draft run wrote allocation lines")
        self.assertIn('Preview', run.log)

    def test_generate_mode_computes_it(self):
        self._pool()
        self._drivers()
        self._rule(activity=self._activity())
        self.company.gec_allocation_cron_mode = 'generate'
        self.company.fiscalyear_lock_date = date(2026, 6, 30)
        self._cron()

        run = self._runs()
        self.assertEqual(run.state, 'done')
        self.assertTrue(run.line_ids)

    def test_a_refusal_leaves_a_draft_carrying_the_reason(self):
        """The cron must survive a rule it cannot apply, without losing the prepared run or other companies."""
        self._pool()
        self._drivers()
        for name in ('T one', 'T two'):
            self.env['gec.allocation.rule'].create({
                'name': name, 'company_id': self.company.id,
                'source_plan_id': self.source_plan.id,
                'source_account_ids': [Command.set(self.dir_a.ids)],
                'source_gl_account_ids': [Command.set(self.gl_pool.ids)],
                'target_plan_id': self.target_plan.id, 'driver': 'equal',
            })
        self.company.gec_allocation_cron_mode = 'generate'
        self.company.fiscalyear_lock_date = date(2026, 6, 30)
        self._cron()

        run = self._runs()
        self.assertEqual(len(run), 1, "the cron lost the run it had prepared")
        self.assertEqual(run.state, 'draft')
        self.assertIn('200.0', run.log)
        self.assertFalse(run.line_ids)

    def test_running_twice_does_not_duplicate_the_period(self):
        self.company.fiscalyear_lock_date = date(2026, 6, 30)
        self._cron()
        self._cron()
        self.assertEqual(len(self._runs()), 1)

    def test_elapsed_days_is_an_explicit_guess(self):
        """For companies that never lock. Still not the bare calendar."""
        self.company.gec_allocation_cron_basis = 'delay'
        self.company.gec_allocation_cron_delay_days = 10
        today = fields.Date.context_today(self.company)
        # The cron skips a period that already has a run; clear the way first.
        start, end = self.company._gec_last_closed_month()
        self.env['gec.allocation.run'].search([
            ('company_id', '=', self.company.id),
            ('date_from', '=', start), ('date_to', '=', end),
        ]).unlink()
        self._cron()

        run = self._runs()
        self.assertTrue(run, "elapsed-days mode prepared nothing")
        self.assertLess(
            run.date_to, today.replace(day=1),
            "a month that has not finished was prepared for allocation",
        )
