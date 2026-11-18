from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAbcOnTheStatement(TransactionCase):
    """The statement has to explain an ABC charge: the rate, the driver units and the figure before allocation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Plan = cls.env['account.analytic.plan']
        Account = cls.env['account.analytic.account']

        cls.bl_plan = Plan.create({'name': 'A Business Line'})
        cls.cc_plan = Plan.create({'name': 'A Cost Center'})
        Plan.search([])._sync_all_plan_column()
        cls.env.transaction.will_change_registry()
        cls.BL_COL = cls.bl_plan._column_name()
        cls.CC_COL = cls.cc_plan._column_name()

        cls.busy = Account.create({'name': 'A Busy Line', 'plan_id': cls.bl_plan.id})
        cls.quiet = Account.create({'name': 'A Quiet Line', 'plan_id': cls.bl_plan.id})
        cls.centre = Account.create({'name': 'A Admin', 'plan_id': cls.cc_plan.id})

        overhead = cls.env['gec.margin.component'].search([('code', '=', 'overhead')], limit=1)
        cls.gl_overhead = cls.env['account.account'].create({
            'name': 'A Rent', 'code': 'ABC900', 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': overhead.id,
        })

        cls._line('A rent', -10000.0, {cls.CC_COL: cls.centre.id}, general=cls.gl_overhead)
        cls._line('A hours busy', 0.0, {cls.BL_COL: cls.busy.id}, quantity=750.0)
        cls._line('A hours quiet', 0.0, {cls.BL_COL: cls.quiet.id}, quantity=250.0)

        cls.activity = cls.env['gec.activity'].create({
            'name': 'A Delivery',
            'code': 'a_delivery',
            'company_id': cls.company.id,
            'driver_label': 'hour',
            'source_model_id': cls.env['ir.model']._get_id('account.analytic.line'),
            'source_date_field': 'date',
            'source_analytic_path': cls.BL_COL,
            'source_domain': (
                "[('general_account_id', '=', False), "
                "('gec_is_allocation', '=', False), ('unit_amount', '>', 0)]"
            ),
            'measure': 'field',
            'measure_field': 'unit_amount',
            'rate_mode': 'actual',
            'practical_capacity': 1250.0,
        })
        cls.rule = cls.env['gec.allocation.rule'].create({
            'name': 'A overhead by activity',
            'company_id': cls.company.id,
            'source_plan_id': cls.cc_plan.id,
            'source_account_ids': [Command.set(cls.centre.ids)],
            'source_gl_account_ids': [Command.set(cls.gl_overhead.ids)],
            'target_plan_id': cls.bl_plan.id,
            'driver': 'activity',
            'activity_id': cls.activity.id,
            'share_mode': 'declared',
            'resource_share': 100.0,
        })
        cls.allocation_run = cls.env['gec.allocation.run'].create({
            'name': 'A run',
            'company_id': cls.company.id,
            'date_from': '2026-01-01',
            'date_to': '2026-12-31',
            'rule_ids': [Command.set(cls.rule.ids)],
        })
        cls.allocation_run.action_compute()

        cls.report = cls.env.ref(
            'gec_analytic_margin.gec_margin_statement_report'
        )

    @classmethod
    def _line(cls, name, amount, tags, general=None, quantity=0.0):
        vals = {
            'name': name, 'date': '2026-06-15', 'amount': amount,
            'unit_amount': quantity, 'company_id': cls.company.id,
        }
        if general:
            vals['general_account_id'] = general.id
        vals.update(tags)
        return cls.env['account.analytic.line'].create(vals)

    def _lines(self, before_allocation=False, ladder_first=False):
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31',
                     'mode': 'range', 'filter': 'custom'},
            'gec_before_allocation': before_allocation,
            'gec_ladder_first': ladder_first,
            'unfold_all': True,
        })
        return options, self.report._get_lines(options)

    @staticmethod
    def _value(line, label='actual'):
        for column in line.columns:
            if column.expression_label == label:
                return column.no_format
        return None

    def _activity_lines(self, lines):
        """This fixture's own activity lines, not the database's."""
        return [
            line for line in lines
            if line.caret_options == 'gec.activity'
            and line.name.startswith(self.activity.name)
        ]

    def _overhead_of(self, lines, plan_name):
        """The plan's own Overhead line, read with Ladder First (cost object first has no plan-level ladder)."""
        plan = next(line for line in lines
                    if line.level == 0 and line.name == plan_name)
        return next(
            (line for line in lines
             if line.parent_id == plan.id and line.level == 2
             and 'Overhead' in line.name),
            None,
        )

    def test_practical_capacity_keeps_idle_cost_off_the_business_lines(self):
        """1 000 hours of 1 250 available: three quarters of the pool moves."""
        _options, lines = self._lines(ladder_first=True)
        charged = self._value(self._overhead_of(lines, 'A Business Line'))
        self.assertAlmostEqual(charged, -8000.0, places=2)
        self.assertAlmostEqual(
            self._value(self._overhead_of(lines, 'A Cost Center')), -10000.0, places=2,
            msg="the cost centre stopped showing what it actually spent",
        )

    def test_the_activity_is_the_cause_not_the_allocation_items(self):
        """One activity, not one row per generated line."""
        _options, lines = self._lines()
        activity_lines = self._activity_lines(lines)
        self.assertTrue(activity_lines, "the ABC charge does not name its activity")
        self.assertEqual(
            len(activity_lines), 2,
            "expected one activity line per business line, got "
            f"{len(activity_lines)}",
        )
        self.assertIn('per hour', activity_lines[0].name,
                      "the line does not say what one driver unit cost")

    def test_the_activity_line_prints_the_arithmetic(self):
        """An allocated figure has to be checkable where it lands: driver units times the rate per unit."""
        _options, lines = self._lines()
        rate = self.env['gec.activity.rate'].search([
            ('activity_id', '=', self.activity.id),
        ], limit=1)
        self.assertAlmostEqual(rate.rate, 8.0, places=2,
                               msg="rate is not pool / practical capacity")

        handler = self.env['gec.margin.statement.report.handler']
        options, lines = self._lines()
        column_options = next(
            iter(self.report._split_options_per_column_group(options).values())
        )
        for line in self._activity_lines(lines):
            charged = self._value(line)
            quantity = handler._gec_charged_quantity(
                self.activity, column_options, charged,
            )
            self.assertTrue(quantity, f"{line.name}: no driver quantity")
            self.assertAlmostEqual(
                quantity * rate.rate, abs(charged), places=2,
                msg="quantity x rate does not come back to the charge",
            )
            self.assertIn(f"{quantity:,.1f}", line.name,
                          "the driver units are not printed on the line")
            self.assertIn("per hour", line.name,
                          "the rate is not printed on the line")

    def test_there_is_no_quantity_column(self):
        """No quantity column: adding hours to invoice quantities (or subscriptions to one service) is not a number."""
        options, _lines = self._lines()
        self.assertNotIn(
            'quantity', [column['expression_label'] for column in options['columns']],
        )

    def test_before_allocation_puts_the_cost_back_where_it_was_spent(self):
        _options, after = self._lines(before_allocation=False, ladder_first=True)
        _options, before = self._lines(before_allocation=True, ladder_first=True)

        self.assertAlmostEqual(
            self._value(self._overhead_of(after, 'A Business Line')), -8000.0, places=2,
        )
        self.assertIsNone(
            self._overhead_of(before, 'A Business Line'),
            "the business lines still carry overhead with Before Allocation on",
        )
        self.assertAlmostEqual(
            self._value(self._overhead_of(before, 'A Cost Center')), -10000.0, places=2,
            msg="the cost centre's own spend changed when allocation was hidden",
        )

    def test_the_rates_are_one_click_from_the_charge(self):
        """Pool, charged and unused capacity live on the rate, not the report."""
        options, lines = self._lines()
        activity_line = self._activity_lines(lines)[0]
        action = self.env['gec.margin.statement.report.handler'] \
            .caret_option_open_gec_activity_rates(options, {'line_id': activity_line.id})
        self.assertEqual(action['res_model'], 'gec.activity.rate')

        rate = self.env['gec.activity.rate'].search(action['domain'], limit=1)
        self.assertAlmostEqual(rate.pool_amount, -10000.0, places=2)
        self.assertAlmostEqual(rate.charged_amount, -8000.0, places=2)
        self.assertAlmostEqual(
            rate.variance_amount, -2000.0, places=2,
            msg="the cost of unused capacity is not recorded anywhere",
        )

    def test_a_project_carries_its_own_allocated_overhead(self):
        """Did this cost object make money: the charge must sit inside the cost object's own block."""
        _options, lines = self._lines()
        plan = next(line for line in lines
                    if line.level == 0 and line.name == 'A Business Line')
        busy = next(line for line in lines
                    if line.parent_id == plan.id and line.level == 2
                    and line.name == 'A Busy Line')
        rungs = {
            line.name: line for line in lines
            if line.parent_id == busy.id and line.level == 3
        }
        self.assertIn('Overhead / G&A', rungs,
                      "the cost object block has no overhead of its own")
        self.assertAlmostEqual(
            self._value(rungs['Overhead / G&A']), -6000.0, places=2,
        )
        self.assertAlmostEqual(
            self._value(busy), -6000.0, places=2,
            msg="the cost object's Net is not what it absorbed",
        )

    def test_no_rate_is_printed_when_the_period_spans_two_runs(self):
        """Two runs mean two rates, so the line keeps its name and the rates go back to the caret."""
        self._line('A rent H2', -6000.0, {self.CC_COL: self.centre.id},
                   general=self.gl_overhead)
        self._line('A hours busy H2', 0.0, {self.BL_COL: self.busy.id}, quantity=400.0)
        for line in self.env['account.analytic.line'].search([
            ('name', 'in', ('A rent H2', 'A hours busy H2')),
        ]):
            line.date = '2026-09-20'

        self.allocation_run.action_reset()
        self.allocation_run.write({'date_from': '2026-01-01', 'date_to': '2026-06-30'})
        self.allocation_run.action_compute()

        second = self.env['gec.allocation.run'].create({
            'name': 'A second half',
            'company_id': self.company.id,
            'date_from': '2026-07-01',
            'date_to': '2026-12-31',
            'rule_ids': [Command.set(self.rule.ids)],
        })
        second.action_compute()

        rates = self.env['gec.activity.rate'].search([
            ('activity_id', '=', self.activity.id),
        ])
        self.assertEqual(len(rates), 2, "the fixture did not produce two rates")
        self.assertNotEqual(
            rates[0].rate, rates[1].rate,
            "the two periods happen to share a rate, so this proves nothing",
        )

        handler = self.env['gec.margin.statement.report.handler']
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31',
                     'mode': 'range', 'filter': 'custom'},
        })
        column_options = next(
            iter(self.report._split_options_per_column_group(options).values())
        )
        self.assertFalse(
            handler._gec_activity_rate(self.activity, column_options),
            "a single rate is being claimed for a period charged at two",
        )
        self.assertEqual(
            handler._gec_activity_name(self.activity, column_options, 100.0),
            self.activity.name,
            "the line is still printing arithmetic that does not hold",
        )
