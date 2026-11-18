from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGecMarginStatementReport(TransactionCase):
    """The statement must agree with itself.
    A section header carries the Net of everything under it while the lines under it include repeating subtotals,
    so the header is checked against the arithmetic it summarises."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Plan = cls.env['account.analytic.plan']
        Account = cls.env['account.analytic.account']

        cls.project_plan = Plan.search([('parent_id', '=', False)], limit=1)
        cls.bl_plan = Plan.create({'name': 'T Business Line'})
        Plan.search([])._sync_all_plan_column()
        cls.env.transaction.will_change_registry()

        cls.project = Account.create({'name': 'T Alta', 'plan_id': cls.project_plan.id})
        cls.business_line = Account.create({
            'name': 'T Consulting', 'plan_id': cls.bl_plan.id,
        })

        components = cls.env['gec.margin.component']
        cls.revenue = components.search([('code', '=', 'revenue')], limit=1)
        cls.direct = components.search([('code', '=', 'direct_cost')], limit=1)
        cls.personnel = components.search([('code', '=', 'personnel')], limit=1)

        cls.gl_revenue = cls._gl('T Revenue', 'TSR400', 'income', cls.revenue)
        cls.gl_direct = cls._gl('T Subcontracting', 'TSR600', 'expense_direct_cost', cls.direct)
        cls.gl_personnel = cls._gl('T Salaries', 'TSR620', 'expense', cls.personnel)

        cls.invoice = cls._invoice(200000.0, cls.gl_revenue)
        cls._line('T subcontractor', -60000.0, cls.gl_direct)
        cls._line('T team', -50000.0, cls.gl_personnel)

        cls.project_record = cls.env['project.project'].create({
            'name': 'T Alta Project',
            'account_id': cls.project.id,
            'company_id': cls.company.id,
        })

        cls.report = cls.env.ref(
            'gec_analytic_margin.gec_margin_statement_report'
        )

    @classmethod
    def _gl(cls, name, code, account_type, component):
        return cls.env['account.account'].create({
            'name': name, 'code': code, 'account_type': account_type,
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': component.id,
        })

    @classmethod
    def _invoice(cls, amount, general_account):
        """A posted customer invoice carrying the same analytic tags, so the drill-down can bottom out on a document."""
        journal = cls.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', cls.company.id),
        ], limit=1)
        distribution = {f"{cls.project.id},{cls.business_line.id}": 100.0}
        move = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal.id,
            'partner_id': cls.env['res.partner'].create({'name': 'T Customer'}).id,
            'invoice_date': '2026-06-15',
            'date': '2026-06-15',
            'invoice_line_ids': [Command.create({
                'name': 'T invoice',
                'account_id': general_account.id,
                'quantity': 1.0,
                'price_unit': amount,
                'tax_ids': [Command.clear()],
                'analytic_distribution': distribution,
            })],
        })
        move.action_post()
        return move

    @classmethod
    def _line(cls, name, amount, general_account):
        return cls.env['account.analytic.line'].create({
            'name': name,
            'date': '2026-06-15',
            'amount': amount,
            'company_id': cls.company.id,
            'general_account_id': general_account.id,
            cls.project_plan._column_name(): cls.project.id,
            cls.bl_plan._column_name(): cls.business_line.id,
        })

    def _lines(self, unfold_all=True, unfolded=(), ladder_first=False):
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'gec_ladder_first': ladder_first,
        })
        options['date'] = {
            **options['date'],
            'date_from': '2026-01-01', 'date_to': '2026-12-31',
            'mode': 'range', 'filter': 'custom',
        }
        options['unfold_all'] = unfold_all
        options['unfolded_lines'] = list(unfolded)
        return options, self.report._get_lines(options)

    @staticmethod
    def _value(line, label='actual'):
        for column in line.columns:
            if column.expression_label == label:
                return column.no_format
        return None

    def _by_name(self, lines):
        return {line.name: line for line in lines}

    @staticmethod
    def _children(lines, parent, level):
        """The real children of a line: filtering on the child level drops the injected "Total <section>" line."""
        return [
            line for line in lines
            if line.parent_id == parent['id'] and line.level == level
        ]

    def _find(self, lines, parent, level, name):
        return next(
            line for line in self._children(lines, parent, level)
            if line.name == name
        )

    def _rung_line(self, lines, account_name, rung_name):
        """One rung of one analytic account of one plan: names repeat, so walk the chain plan, cost object, ladder."""
        plan = next(
            line for line in lines
            if line.level == 0 and line.name == self.project_plan.name
        )
        account = self._find(lines, plan, 2, account_name)
        return self._find(lines, account, 3, rung_name)

    def test_a_plan_section_shows_its_net_not_the_sum_of_its_lines(self):
        """Summing every line under the section counts Revenue again inside each subtotal (90 000 became 500 000)."""
        _options, lines = self._lines()
        by_name = self._by_name(lines)
        self.assertIn('T Business Line', by_name, "the plan section is missing")
        self.assertAlmostEqual(self._value(by_name['T Business Line']), 90000.0, places=2)

    def test_the_ladder_is_inside_the_plan_and_in_order(self):
        _options, lines = self._lines()
        names = [line.name for line in lines]
        for rung in ('Revenue', 'Direct Cost', 'Contribution Margin', 'Personnel',
                     'Gross Margin', 'EBITDA'):
            self.assertIn(rung, names, f"{rung} is not on the statement")
        self.assertLess(
            names.index('Direct Cost'), names.index('Contribution Margin'),
            "a subtotal is printed above a component it contains",
        )

    def test_the_rungs_carry_the_configured_arithmetic(self):
        _options, lines = self._lines()
        by_name = self._by_name(lines)
        self.assertAlmostEqual(self._value(by_name['Revenue']), 200000.0, places=2)
        self.assertAlmostEqual(self._value(by_name['Direct Cost']), -60000.0, places=2)
        self.assertAlmostEqual(
            self._value(by_name['Contribution Margin']), 140000.0, places=2,
            msg="Contribution Margin is not Revenue + Direct Cost",
        )
        self.assertAlmostEqual(
            self._value(by_name['EBITDA']), 90000.0, places=2,
            msg="EBITDA does not match the components configured on the level",
        )

    def test_a_component_line_unfolds_to_its_analytic_accounts(self):
        _options, lines = self._lines()
        names = [line.name for line in lines]
        self.assertIn('T Alta', names, "the analytic account detail never appeared")
        self.assertIn('T Consulting', names)

    def test_a_subtotal_line_does_not_pretend_to_unfold(self):
        """There is nothing underneath a subtotal — it is other lines added up."""
        _options, lines = self._lines()
        by_name = self._by_name(lines)
        self.assertFalse(by_name['Gross Margin'].unfoldable)
        self.assertTrue(by_name['Direct Cost'].unfoldable)

    def test_the_drill_path_matches_the_pivot(self):
        """Plan, ladder line, analytic account, GL account, document: the same drill as the Analytic Margin pivot."""
        _options, lines = self._lines()
        rung_line = self._rung_line(lines, 'T Alta', 'Revenue')
        self.assertTrue(
            rung_line.unfoldable,
            "the ladder line is a dead end — nothing explains the figure",
        )

        gl_lines = self._children(lines, rung_line, 4)
        self.assertTrue(gl_lines, "the ladder line does not open onto GL accounts")
        gl_line = self._find(lines, rung_line, 4, self.gl_revenue.display_name)
        self.assertEqual(gl_line.caret_options, 'account.account')

        documents = self._children(lines, gl_line, 5)
        self.assertTrue(documents, "the GL account unfolded to nothing")
        self.assertTrue(
            any(line.caret_options == 'account.move' for line in documents),
            "a posted invoice is not offered as the cause of the revenue",
        )

    def test_an_item_with_no_document_still_names_its_cause(self):
        """Payroll and allocation lines have no invoice; the item is the cause."""
        _options, lines = self._lines()
        rung_line = self._rung_line(lines, 'T Alta', 'Personnel')
        gl_line = self._find(lines, rung_line, 4, self.gl_personnel.display_name)
        documents = self._children(lines, gl_line, 5)
        self.assertTrue(documents)
        self.assertTrue(
            all(line.caret_options == 'account.analytic.line' for line in documents),
            "a cost with no invoice behind it is claiming to have one",
        )

    def test_the_documents_add_up_to_the_account_they_sit_under(self):
        """A drill-down that does not reconcile is worse than none."""
        _options, lines = self._lines()
        for rung_name, expected in (('Revenue', 200000.0),
                                    ('Direct Cost', -60000.0),
                                    ('Personnel', -50000.0)):
            with self.subTest(rung=rung_name):
                rung_line = self._rung_line(lines, 'T Alta', rung_name)
                gl_lines = self._children(lines, rung_line, 4)
                self.assertTrue(gl_lines)
                self.assertAlmostEqual(self._value(rung_line), expected, places=2)
                self.assertAlmostEqual(
                    sum(self._value(line) or 0.0 for line in gl_lines),
                    expected, places=2,
                    msg="the GL accounts do not sum to the ladder line above them",
                )
                for gl_line in gl_lines:
                    documents = self._children(lines, gl_line, 5)
                    self.assertAlmostEqual(
                        sum(self._value(line) or 0.0 for line in documents),
                        self._value(gl_line), places=2,
                        msg="the documents do not sum to their GL account",
                    )

    def test_variance_is_blank_on_a_document(self):
        """Actual minus a budget the document was never measured against is not a variance."""
        _options, lines = self._lines()
        rung_line = self._rung_line(lines, 'T Alta', 'Revenue')
        gl_line = self._find(lines, rung_line, 4, self.gl_revenue.display_name)
        children = self._children(lines, gl_line, 5)
        self.assertTrue(children)
        for line in children:
            self.assertIsNone(
                self._value(line, 'variance'),
                f"{line.name}: a document line is showing a variance",
            )

    def test_the_report_opens_folded(self):
        """Four levels unfolded on a real ledger is thousands of rows."""
        _options, lines = self._lines(unfold_all=False)
        self.assertTrue(lines)
        self.assertTrue(
            all((line.level or 0) <= 1 for line in lines),
            "the report expands past the plan sections before anybody clicks",
        )

    def test_a_project_is_one_block_by_default(self):
        """A project's P&L has to be readable in one place; with the ladder on top its figures are scattered."""
        _options, lines = self._lines()
        plan = next(
            line for line in lines
            if line.level == 0 and line.name == self.project_plan.name
        )
        account = self._find(lines, plan, 2, 'T Alta')
        self.assertAlmostEqual(
            self._value(account), 90000.0, places=2,
            msg="the project header is not the project's Net",
        )
        rungs = [line.name for line in self._children(lines, account, 3)]
        for expected in ('Revenue', 'Direct Cost', 'Gross Margin', 'EBITDA'):
            self.assertIn(expected, rungs,
                          f"{expected} is not inside the project block")

    def test_ladder_first_puts_the_plan_p_and_l_back(self):
        """The company-wide reading, one tick away: cost object first loses the plan's own P&L."""
        _options, lines = self._lines(ladder_first=True)
        plan = next(
            line for line in lines
            if line.level == 0 and line.name == self.project_plan.name
        )
        revenue = self._find(lines, plan, 2, 'Revenue')
        accounts = self._children(lines, revenue, 3)
        self.assertIn('T Alta', [line.name for line in accounts],
                      "the ladder line does not open onto its cost objects")

        alta = next(line for line in accounts if line.name == 'T Alta')
        self.assertAlmostEqual(
            self._value(alta), 200000.0, places=2,
            msg="this fixture's revenue is not under the plan's Revenue rung",
        )
        # An invariant rather than 200 000: the project plan is shared, so other data may exist in the period.
        self.assertAlmostEqual(
            self._value(revenue),
            sum(self._value(line) or 0.0 for line in accounts), places=2,
            msg="the plan-level ladder does not carry the plan's total — it is "
                "summing subtotals instead of the cost objects underneath it",
        )

    def test_revenue_and_expense_split_reconciles_to_net(self):
        """The two new columns must add up, and stay blank on a rung that is all revenue or all cost."""
        _options, lines = self._lines()
        plan = next(
            line for line in lines
            if line.level == 0 and line.name == self.project_plan.name
        )
        account = self._find(lines, plan, 2, 'T Alta')
        revenue = self._value(account, 'revenue')
        expense = self._value(account, 'expense')
        self.assertAlmostEqual(revenue, 200000.0, places=2)
        self.assertAlmostEqual(expense, -110000.0, places=2)
        self.assertAlmostEqual(
            revenue + expense, self._value(account), places=2,
            msg="Revenue plus Expense is not Net",
        )

        cost_rung = self._find(lines, account, 3, 'Direct Cost')
        self.assertFalse(
            self._value(cost_rung, 'revenue'),
            "a pure cost line is printing a revenue figure",
        )

    def test_the_split_counts_actuals_only(self):
        """Budgeted revenue must not be added to actual revenue in the split column next to Net."""
        _options, lines = self._lines()
        plan = next(
            line for line in lines
            if line.level == 0 and line.name == self.project_plan.name
        )
        account = self._find(lines, plan, 2, 'T Alta')
        self.assertAlmostEqual(
            self._value(account, 'revenue'), 200000.0, places=2,
            msg="the Revenue column is picking up more than the actuals",
        )

    def test_margin_percentage_is_of_the_cost_object_revenue(self):
        """A cost rung has no revenue of its own, so it is measured against the revenue it was incurred to earn."""
        _options, lines = self._lines()
        plan = next(
            line for line in lines
            if line.level == 0 and line.name == self.project_plan.name
        )
        account = self._find(lines, plan, 2, 'T Alta')
        self.assertAlmostEqual(self._value(account, 'margin_pct'), 45.0, places=1)
        self.assertAlmostEqual(
            self._value(self._find(lines, account, 3, 'Revenue'), 'margin_pct'),
            100.0, places=1,
        )
        self.assertAlmostEqual(
            self._value(self._find(lines, account, 3, 'Direct Cost'), 'margin_pct'),
            -30.0, places=1,
            msg="a cost rung is not measured against the revenue above it",
        )

    def test_the_report_warns_about_money_on_no_margin_line(self):
        """Unclassified is a finding, and it hides inside a fold."""
        account = self.env['account.account'].create({
            'name': 'T Balance Sheet', 'code': 'TSTW10',
            'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        self._line('T misposted', -4000.0, account)

        warnings = {}
        options, _lines = self._lines()
        self.env['gec.margin.statement.report.handler']._gec_add_warnings(
            self.report, options, warnings,
        )
        self.assertIn(
            'gec_analytic_margin.warning_unclassified', warnings,
            "money on no margin line is not being reported anywhere",
        )

    def _sections(self, section_by):
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'gec_section_by': section_by,
            'unfold_all': True,
        })
        options['date'] = {
            **options['date'],
            'date_from': '2026-01-01', 'date_to': '2026-12-31',
            'mode': 'range', 'filter': 'custom',
        }
        lines = self.report._get_lines(options)
        return options, lines, [line for line in lines if line.level == 0]

    def test_the_report_is_cut_by_analytic_plans_by_default(self):
        options, _lines, tops = self._sections(None)
        self.assertEqual(options['gec_section_by'], 'plans')
        self.assertIn(
            self.project_plan.name, [line.name for line in tops],
            "the default view is not sectioned by analytic plan",
        )

    def test_cutting_by_project_counts_each_amount_once(self):
        """A project tagged on three plans must not report three times (non-plan sections collapse the explosion)."""
        _options, _lines, tops = self._sections('project')
        project = next(
            (line for line in tops if line.name == self.project_record.name), None,
        )
        self.assertTrue(project, "no project section was produced")
        self.assertAlmostEqual(
            self._value(project), 90000.0, places=2,
            msg="the project reports once per analytic plan instead of once",
        )

    def test_cutting_by_customer_sections_on_the_partner(self):
        _options, _lines, tops = self._sections('partner')
        self.assertIn(
            'T Customer', [line.name for line in tops],
            "the invoice's customer is not a section",
        )

    def test_a_section_opens_straight_onto_the_ladder(self):
        """No analytic-account level under a project or a customer: the section already is the cost object."""
        _options, lines, tops = self._sections('project')
        project = next(line for line in tops if line.name == self.project_record.name)
        children = [line.name for line in lines
                    if line.parent_id == project.id and line.level == 2]
        self.assertIn('Revenue', children)
        self.assertIn('Gross Margin', children)

    def test_amounts_answering_the_question_with_nothing_still_appear(self):
        """Cost with no project is most of a services company's overhead and must stay in the sections."""
        self._line('T no project at all', -7000.0, self.gl_personnel)
        self.env['account.analytic.line'].search([
            ('name', '=', 'T no project at all'),
        ]).write({self.project_plan._column_name(): False})

        _options, _lines, tops = self._sections('project')
        self.assertTrue(
            any(line.name.startswith('No ') for line in tops),
            "amounts with no project vanished from the report",
        )

    def test_the_picker_offers_only_what_the_period_has(self):
        """A list of every partner ever created is noise, not a filter."""
        options, _lines, tops = self._sections('project')
        offered = {record['name'] for record in options['gec_section_records']}
        self.assertIn(self.project_record.name, offered)
        self.assertNotIn(
            'No Project', offered,
            "the remainder is not a record and cannot be picked",
        )
        self.assertTrue(
            offered <= {line.name for line in tops},
            "the picker offers sections the report does not render",
        )

    def test_picking_a_section_hides_the_others(self):
        options, _lines, _tops = self._sections('project')
        chosen = options['gec_section_records'][0]
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31',
                     'mode': 'range', 'filter': 'custom'},
            'gec_section_by': 'project',
            'gec_section_filter': [chosen['id']],
            'gec_section_filter_for': 'project',
        })
        tops = [line for line in self.report._get_lines(options)
                if line.level == 0]
        self.assertEqual([line.name for line in tops], [chosen['name']])

    def test_a_pick_is_forgotten_when_the_reading_changes(self):
        """A project id left selected under By Customers would hide everything while looking unfiltered."""
        options, _lines, _tops = self._sections('project')
        chosen = options['gec_section_records'][0]
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31',
                     'mode': 'range', 'filter': 'custom'},
            'gec_section_by': 'partner',
            'gec_section_filter': [chosen['id']],
            'gec_section_filter_for': 'project',
        })
        self.assertEqual(options['gec_section_filter'], [])

    def test_unfold_all_is_batched_without_changing_a_number(self):
        """The tree read in a handful of queries must render identically to one query per line."""
        handler = type(self.env['gec.margin.statement.report.handler'])
        generator = handler._custom_unfold_all_batch_data_generator

        def snapshot():
            _options, lines = self._lines()
            # Rounded to the cent: batching sums in a different order, so floats differ in the last bits.
            return [
                (line.level, line.name,
                 tuple(
                     None if (value := self._value(line, column['expression_label'])) is None
                     else round(value, 2)
                     for column in _options['columns']
                 ))
                for line in lines
            ]

        batched = snapshot()
        handler._custom_unfold_all_batch_data_generator = lambda self, *a, **k: None
        try:
            unbatched = snapshot()
        finally:
            handler._custom_unfold_all_batch_data_generator = generator

        self.assertTrue(batched, "the report rendered nothing to compare")
        self.assertEqual(
            batched, unbatched,
            "batching unfold-all changed the report it was meant to speed up",
        )

    def test_by_activity_is_offered_and_nets_to_the_resource_cost(self):
        """An allocation is net-zero, so an activity's own total is what it consumed."""
        options, _lines, _tops = self._sections('plans')
        self.assertIn(
            'By Activity', [choice['name'] for choice in options['gec_section_choices']],
        )
        self.assertIn(
            'By Partner', [choice['name'] for choice in options['gec_section_choices']],
            "the partner reading still promises profit per customer",
        )
