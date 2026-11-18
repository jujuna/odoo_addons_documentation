from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestDryRun(GecMarginCommon):
    """A preview that writes anything is not a preview: it runs for real and rewinds, so step 2 sees step 1."""

    def _run_for(self, rules):
        """A run pinned to its own rules, since ``_get_effective_rules`` falls back to every active rule."""
        return self.env['gec.allocation.run'].create({
            'name': 'T run', 'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
            'rule_ids': [Command.set(rules.ids)],
        })

    def test_a_dry_run_leaves_no_trace(self):
        self._pool()
        self._drivers()
        run = self._run_for(self._rule(activity=self._activity()))

        run.action_dry_run()

        self.assertEqual(run.state, 'draft', "the run was marked generated")
        self.assertFalse(run.line_ids, "the dry run wrote analytic lines")
        self.assertFalse(run.rate_ids, "the dry run wrote a rate record")
        self.assertFalse(run.log, "the dry run overwrote the real log")
        self.assertFalse(self.env['account.analytic.line'].search([
            ('gec_allocation_run_id', '=', run.id),
        ]), "lines survived the rewind")

    def test_the_preview_says_what_the_run_would_do(self):
        self._pool()
        self._drivers()
        run = self._run_for(self._rule(activity=self._activity()))

        action = run.action_dry_run()
        preview = self.env['gec.allocation.preview'].browse(action['res_id'])

        self.assertTrue(preview.log, "the preview has no explanation")
        self.assertAlmostEqual(preview.allocated_amount, -40000.0, places=2)
        self.assertEqual(preview.line_count, 3)
        self.assertEqual(len(preview.line_ids), 3)
        targets = preview.line_ids.filtered(lambda line: line.kind == 'target')
        self.assertEqual(
            sorted(round(line.amount, 2) for line in targets),
            [-28000.0, -12000.0],
        )
        self.assertTrue(
            all(line.analytic_label for line in preview.line_ids),
            "a preview line does not say which cost object it would hit",
        )

    def test_the_preview_and_the_run_agree(self):
        """The point of the whole exercise: what you saw is what you get."""
        self._pool()
        self._drivers()
        run = self._run_for(
            self._rule(activity=self._activity(practical_capacity=200.0))
        )

        preview = self.env['gec.allocation.preview'].browse(
            run.action_dry_run()['res_id']
        )
        promised = sorted(round(line.amount, 2) for line in preview.line_ids)
        promised_log = preview.log

        run.action_compute()
        delivered = sorted(round(line.amount, 2) for line in run.line_ids)

        self.assertEqual(promised, delivered)
        self.assertEqual(promised_log, run.log)

    def test_a_cascade_previews_end_to_end(self):
        """Step 2 must see what step 1 delivered, inside the rewind as well."""
        self._line(amount=-90000.0, quantity=1.0, service=self.it,
                   gl=self.gl_pool, name='T IT cost')
        self._drivers()

        step_one = self._rule(
            name='T IT to directions', step=1,
            source_plan_id=self.service_plan.id,
            source_account_ids=[Command.set(self.it.ids)],
            target_plan_id=self.source_plan.id,
            driver='manual',
            line_ids=[Command.create({'account_id': self.dir_a.id,
                                      'percentage': 100.0})],
        )
        step_two = self._rule(
            name='T directions to lines', step=2,
            activity=self._activity(),
        )

        run = self.env['gec.allocation.run'].create({
            'name': 'T cascade', 'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
            'rule_ids': [Command.set((step_one | step_two).ids)],
        })
        preview = self.env['gec.allocation.preview'].browse(
            run.action_dry_run()['res_id']
        )

        self.assertIn(step_one.name, preview.log)
        self.assertIn(step_two.name, preview.log)
        self.assertFalse(run.line_ids, "the cascade preview wrote lines")

    def test_confirming_from_the_preview_runs_it(self):
        self._pool()
        self._drivers()
        run = self._run_for(self._rule(activity=self._activity()))

        preview = self.env['gec.allocation.preview'].browse(
            run.action_dry_run()['res_id']
        )
        preview.action_confirm()

        self.assertEqual(run.state, 'done')
        self.assertEqual(len(run.line_ids), 3)
