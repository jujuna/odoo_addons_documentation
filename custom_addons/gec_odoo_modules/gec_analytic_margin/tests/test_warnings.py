from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestUnallocatedPoolWarning(TransactionCase):
    """A pool nobody wrote a rule for must be told apart, in words, from one deliberately left alone."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Plan = cls.env['account.analytic.plan']
        Account = cls.env['account.analytic.account']

        cls.bl_plan = Plan.create({'name': 'W Business Line'})
        cls.cc_plan = Plan.create({'name': 'W Cost Center'})
        Plan.search([])._sync_all_plan_column()
        cls.env.transaction.will_change_registry()
        cls.BL_COL = cls.bl_plan._column_name()
        cls.CC_COL = cls.cc_plan._column_name()

        cls.line_a = Account.create({'name': 'W Line A', 'plan_id': cls.bl_plan.id})
        cls.covered = Account.create({'name': 'W Covered Centre',
                                      'plan_id': cls.cc_plan.id})
        cls.orphan = Account.create({'name': 'W Orphan Centre',
                                     'plan_id': cls.cc_plan.id})

        Component = cls.env['gec.margin.component']
        cls.overhead = Component.search([('code', '=', 'overhead')], limit=1)
        cls.overhead.allocatable = True
        cls.facility = Component.create({
            'name': 'W Facility', 'code': 'w_facility',
            'nature': 'cost', 'cost_level': 'facility', 'allocatable': False,
        })

        cls.gl_overhead = cls._gl('W Rent', 'WAR900', cls.overhead)
        cls.gl_facility = cls._gl('W HQ Building', 'WAR910', cls.facility)

        cls._line('W covered rent', -10000.0, cls.covered, cls.gl_overhead)
        cls._line('W orphan rent', -6000.0, cls.orphan, cls.gl_overhead)
        cls._line('W hours', 0.0, cls.line_a, None, column=cls.BL_COL,
                  quantity=100.0)

        cls.rule = cls.env['gec.allocation.rule'].create({
            'name': 'W covered pool',
            'company_id': cls.company.id,
            'source_plan_id': cls.cc_plan.id,
            'source_account_ids': [Command.set(cls.covered.ids)],
            'source_gl_account_ids': [Command.set(cls.gl_overhead.ids)],
            'target_plan_id': cls.bl_plan.id,
            'driver': 'equal',
        })

        cls.report = cls.env.ref(
            'gec_analytic_margin.gec_margin_statement_report'
        )
        cls.handler = cls.env['gec.margin.statement.report.handler']

    @classmethod
    def _gl(cls, name, code, component):
        return cls.env['account.account'].create({
            'name': name, 'code': code, 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': component.id,
        })

    @classmethod
    def _line(cls, name, amount, account, general, column=None, quantity=0.0):
        vals = {
            'name': name, 'date': '2026-06-15', 'amount': amount,
            'unit_amount': quantity, 'company_id': cls.company.id,
            column or cls.CC_COL: account.id,
        }
        if general:
            vals['general_account_id'] = general.id
        return cls.env['account.analytic.line'].create(vals)

    def _warnings(self):
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31',
                     'mode': 'range', 'filter': 'custom'},
        })
        warnings = {}
        self.handler._gec_add_warnings(self.report, options, warnings)
        return warnings

    KEY = 'gec_analytic_margin.warning_unallocated_pool'

    def test_a_cost_centre_no_rule_covers_is_reported(self):
        warning = self._warnings().get(self.KEY)
        self.assertTrue(warning, "the orphan pool was not reported")
        self.assertIn('6,000', warning['amount'])
        self.assertIn(self.orphan.display_name, warning['accounts'])
        self.assertNotIn(
            self.covered.display_name, warning['accounts'],
            "a pool that has a rule was reported as having none",
        )

    def test_writing_a_rule_for_it_makes_the_warning_go_away(self):
        self.rule.source_account_ids |= self.orphan
        self.assertNotIn(
            self.KEY, self._warnings(),
            "the pool is covered now and is still being reported",
        )

    def test_facility_cost_is_meant_to_stay_and_is_not_reported(self):
        """Cooper and Kaplan's fourth level is deliberately never allocated, so it must not fire the banner."""
        self._line('W hq', -25000.0, self.orphan, self.gl_facility)
        warning = self._warnings().get(self.KEY)
        self.assertTrue(warning)
        self.assertIn(
            '6,000', warning['amount'],
            "facility cost was counted as a pool waiting for a rule",
        )

    def test_cost_booked_straight_onto_a_cost_object_is_not_a_pool(self):
        """Overhead tagged directly to a business line is already on a cost object and needs no allocation."""
        self._line('W direct overhead', -9000.0, self.line_a, self.gl_overhead,
                   column=self.BL_COL)
        warning = self._warnings().get(self.KEY)
        self.assertIn(
            '6,000', warning['amount'],
            "cost already sitting on a cost object was reported as an orphan pool",
        )

    def test_a_company_with_no_rules_at_all_is_not_nagged(self):
        """No rules is a company that has not started, not a finding."""
        self.env['gec.allocation.rule'].search([]).unlink()
        self.assertNotIn(self.KEY, self._warnings())
