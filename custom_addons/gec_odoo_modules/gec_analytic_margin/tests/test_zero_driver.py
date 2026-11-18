from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestZeroDriverWarning(GecMarginCommon):
    """A cost object that measured nothing receives nothing and says nothing, like a dormant one."""

    def _run_for(self, rules):
        """A run pinned to its own rules, since ``_get_effective_rules`` falls back to every active rule."""
        return self.env['gec.allocation.run'].create({
            'name': 'T run', 'company_id': self.company.id,
            'date_from': self.date_from, 'date_to': self.date_to,
            'rule_ids': [Command.set(rules.ids)],
        })

    def _busy_but_unmeasured(self):
        """BL-B earns money and logs no hours — the case that must be caught."""
        self._pool()
        self._line(quantity=70.0, target=self.bl_a, name='T hours A')
        revenue = self.env['account.account'].create({
            'name': 'T Revenue', 'code': 'TST400', 'account_type': 'income',
            'company_ids': [Command.set(self.company.ids)],
        })
        self._line(amount=25000.0, target=self.bl_b, gl=revenue, name='T sale B')

    def test_a_busy_target_that_measured_nothing_is_named(self):
        self._busy_but_unmeasured()
        run = self._run_for(self._rule(activity=self._activity()))
        run.action_compute()

        self.assertTrue(run.driver_warning, "the silent target was not reported")
        self.assertIn(self.bl_b.display_name, run.driver_warning)
        self.assertNotIn(self.bl_a.display_name, run.driver_warning,
                         "a target that was measured must not be reported")
        self.assertIn('hour', run.driver_warning,
                      "the warning does not say what was not measured")

    def test_a_dormant_target_is_not_reported(self):
        """Not every empty account is a problem. Most are just empty."""
        self._pool()
        self._drivers()
        self.env['account.analytic.account'].create({
            'name': 'T BL-C dormant', 'plan_id': self.target_plan.id,
        })
        run = self._run_for(self._rule(activity=self._activity()))
        run.action_compute()

        self.assertFalse(
            run.driver_warning,
            f"a dormant account was reported as a finding: {run.driver_warning}",
        )

    def test_allocation_output_does_not_make_a_target_look_busy(self):
        """A target charged only by a run is not evidence the business used it."""
        self._pool()
        self._drivers()
        rule = self._rule(activity=self._activity())
        run = self._run_for(rule)

        dormant = self.env['account.analytic.account'].create({
            'name': 'T BL-C charged only by a run',
            'plan_id': self.target_plan.id,
        })
        charged = self._line(amount=-5000.0, target=dormant, gl=self.gl_pool,
                             name='T allocated to C')
        charged.gec_allocation_run_id = run.id

        self.assertFalse(
            run._accounts_with_activity(rule, dormant),
            "allocation output was mistaken for activity of the target's own",
        )
        charged.gec_allocation_run_id = False
        self.assertTrue(
            run._accounts_with_activity(rule, dormant),
            "cost the business actually put there is being ignored",
        )

    def test_the_warning_is_cleared_when_the_run_is_reset(self):
        self._busy_but_unmeasured()
        run = self._run_for(self._rule(activity=self._activity()))
        run.action_compute()
        self.assertTrue(run.driver_warning)

        run.action_reset()
        self.assertFalse(run.driver_warning,
                         "a deleted allocation kept its findings")
