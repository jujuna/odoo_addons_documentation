from lxml.builder import E

from odoo import models, fields, _
from odoo.tools import SQL


class GecMarginReport(models.Model):
    _name = 'gec.margin.report'
    _inherit = ['analytic.plan.fields.mixin', 'gec.margin.level.mixin']
    _description = 'Analytic Margin Report'
    _auto = False
    _order = 'plan_sequence, date desc, id desc'

    # Tree dimensions: one source amount gives one row per plan it is tagged with.
    plan_id = fields.Many2one(
        'account.analytic.plan', string='Analytic Plan', readonly=True,
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account', readonly=True,
    )
    auto_account_id = fields.Many2one(string='Analytic Account (any plan)')
    plan_sequence = fields.Integer(string='Plan Order', readonly=True)
    is_primary_plan = fields.Boolean(
        string='Primary Plan', readonly=True,
        help="True on one row per source amount — the first plan it is tagged "
             "with. Filter on it when you need a grand total that counts every "
             "amount exactly once.",
    )

    general_account_id = fields.Many2one(
        'account.account', string='GL Account', readonly=True,
    )
    move_id = fields.Many2one('account.move', string='Invoice / Bill', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)
    activity_id = fields.Many2one(
        'gec.activity', string='Activity', readonly=True,
        help="For allocated lines, which activity produced the cost — the bill "
             "of activities behind a cost object.",
    )
    project_id = fields.Many2one(
        'project.project', string='Project', readonly=True,
        help="The Project-module project behind this amount, resolved from the "
             "analytic account on the project plan.",
    )

    date = fields.Date(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    line_type = fields.Selection(
        [('budget', 'Budget'), ('actual', 'Actual')],
        string='Type', readonly=True,
    )
    direction = fields.Selection(
        [('revenue', 'Revenue'), ('expense', 'Expense')],
        string='Revenue / Expense', readonly=True,
    )
    component_id = fields.Many2one(
        'gec.margin.component', string='Margin Component', readonly=True,
        help="Resolved from the GL account — the explicit component if one is "
             "set, otherwise whatever the classification rules make of it.",
    )
    revenue_stream_id = fields.Many2one(
        'gec.revenue.stream', string='Revenue Stream', readonly=True,
        help="The stream of the first analytic account on the row that names "
             "one. On revenue rows, otherwise that of the GL account.",
    )
    is_allocation = fields.Boolean(
        string='From Allocation', readonly=True,
        help="Row produced by a cost allocation run rather than by a document. "
             "These have no invoice behind them.",
    )
    budget_analytic_id = fields.Many2one('budget.analytic', string='Budget', readonly=True)
    budget_line_id = fields.Many2one('budget.line', string='Budget Line', readonly=True)
    analytic_line_id = fields.Many2one(
        'account.analytic.line', string='Analytic Item', readonly=True,
    )

    # Measures are signed (revenue positive, cost negative); gec.margin.level.mixin adds one column per level.
    amount = fields.Monetary(string='Net', readonly=True)
    revenue_amount = fields.Monetary(string='Revenue', readonly=True)
    expense_amount = fields.Monetary(string='Expense', readonly=True)
    budget_amount = fields.Monetary(string='Budgeted', readonly=True)
    actual_amount = fields.Monetary(string='Actual', readonly=True)
    unit_amount = fields.Float(
        string='Quantity', readonly=True, aggregator='sum',
        help="Quantity from the analytic item — hours for timesheets, units "
             "otherwise. Zero on budget rows: budget lines hold amounts only.",
    )

    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return self._patch_level_view(arch, view, view_type)

    def _patch_level_view(self, arch, view, view_type):
        """Add one column per margin level to the list view; pivot and graph already offer them as measures.

        Naming them in a pivot/graph arch would activate them by default, or hide them with `invisible`."""
        if self.env.context.get('studio') or view_type != 'list':
            return arch, view
        levels = self.env['gec.margin.level'].sudo().search([])
        anchor = arch.find('.//field[@name="amount"]')
        if anchor is None:
            return arch, view
        for level in reversed(levels):
            fname = level._column_name()
            if fname not in self._fields:
                continue
            anchor.addnext(E.field(name=fname, sum=level.name, optional='hide'))
        return arch, view

    def _get_report_plans(self):
        """The plans the report explodes over, in display order."""
        project_plan, other_plans = self.env['account.analytic.plan']._get_all_plans()
        return [
            plan for plan in project_plan | other_plans
            if plan._column_name() in self
        ]

    @property
    def _table_sql(self):
        self.env['budget.line'].flush_model()
        self.env['account.analytic.line'].flush_model()
        self.env['account.move.line'].flush_model()
        self.env['account.account'].flush_model()
        self.env['gec.margin.component'].flush_model()
        self.env['gec.margin.level'].flush_model()
        self.env['gec.activity'].flush_model(['gec_function_component_id'])
        self.env['account.analytic.account'].flush_model(['gec_function_component_id'])
        self.env['res.company'].flush_model(['gec_pl_mode'])
        self.env['account.analytic.account'].flush_model(['gec_revenue_stream_id'])
        self.env['account.account'].flush_model(['gec_revenue_stream_id'])

        plans = self._get_report_plans()
        plan_fnames = [plan._column_name() for plan in plans]
        # _table_sql is used as-is in FROM, so it carries its own parentheses.
        return SQL(
            "(%s UNION ALL %s)",
            self._get_budget_query(plans, plan_fnames),
            self._get_actual_query(plans, plan_fnames),
        )

    @staticmethod
    def _plan_source_model(alias):
        return 'budget.line' if alias == 'bl' else 'account.analytic.line'

    def _plan_lateral(self, alias, plans):
        """``VALUES`` list turning the per-plan columns into rows."""
        model = self._plan_source_model(alias)
        return SQL(', ').join(
            SQL(
                "(%(plan_id)s::integer, %(column)s, %(seq)s::integer)",
                plan_id=plan.id,
                column=self.env[model]._field_to_sql(alias, plan._column_name()),
                seq=index,
            )
            for index, plan in enumerate(plans)
        )

    def _primary_seq_case(self, alias, plans):
        """Sequence of the first plan the source row carries."""
        model = self._plan_source_model(alias)
        branches = SQL(' ').join(
            SQL(
                "WHEN %(column)s IS NOT NULL THEN %(seq)s",
                column=self.env[model]._field_to_sql(alias, plan._column_name()),
                seq=index,
            )
            for index, plan in enumerate(plans)
        )
        return SQL("CASE %(branches)s ELSE -1 END", branches=branches)

    def _id_multiplier(self, plans):
        # Two ids per (source row, plan, slot): even for budget, odd for actual.
        return 2 * (len(plans) + 1) * self._id_slots()

    # Subclasses that explode a (source row, plan) pair further reserve their id slots here.
    def _id_slots(self):
        return 1

    def _id_slot_sql(self):
        return SQL("0")

    def _row_id_sql(self, source_id, plans, branch):
        """The synthetic primary key, computed as bigint: an int4 product overflows at ~14M analytic items."""
        return SQL(
            "%(source)s::bigint * %(mult)s + (pl.plan_seq * %(slots)s + %(slot)s) * 2 + %(branch)s",
            source=source_id,
            mult=self._id_multiplier(plans),
            slots=self._id_slots(),
            slot=self._id_slot_sql(),
            branch=branch,
        )

    # SELECT-list / FROM fragments for each union branch; the columns one carries its own leading comma.
    def _extra_columns(self, alias):
        return SQL("")

    def _extra_joins(self, alias):
        return SQL("")

    def _has_project(self):
        return 'project.project' in self.env

    def _project_column(self):
        return SQL("pp.id AS project_id") if self._has_project() \
            else SQL("NULL::integer AS project_id")

    def _project_join(self, alias):
        """Resolve the project from the project-plan account; LATERAL LIMIT 1 so a shared account adds no rows."""
        if not self._has_project():
            return SQL("")
        return SQL(
            """
       LEFT JOIN LATERAL (
                 SELECT p.id FROM project_project p
                  WHERE p.account_id = %(account_col)s
                  ORDER BY p.id LIMIT 1
                 ) pp ON TRUE
            """,
            account_col=self.env[self._plan_source_model(alias)]._field_to_sql(
                alias, 'account_id',
            ),
        )

    def _component_join(self, account_alias, source_alias, plans):
        """Resolve the row's margin component once, for nature and levels.
        ``gmc_gl``: the GL account's component; ``gmc``: the reported one, but a pooled cost in a by-function company
        reads under its activity's or cost centre's function."""
        return SQL(
            """
       LEFT JOIN gec_margin_component gmc_gl ON gmc_gl.id = (%(component)s)
       LEFT JOIN gec_margin_component gmc ON gmc.id = (
                 CASE WHEN rc.gec_pl_mode = 'function' AND gmc_gl.function_reclassify
                      THEN COALESCE(%(function)s, gmc_gl.id)
                      ELSE gmc_gl.id
                 END)
            """,
            component=self.env['account.account']._gec_component_sql(account_alias),
            function=self._function_sql(source_alias, plans),
        )

    def _function_sql(self, source_alias, plans):
        """Function a row's cost was for, or NULL; first hit wins:
        1. project: account on the project plan; 2. activity, unless an allocation's contra line (cost centre's);
        3. cost centre: first other plan account naming one."""
        model = self._plan_source_model(source_alias)
        project_plan, _other_plans = self.env['account.analytic.plan']._get_all_plans()
        account_function = (
            "(SELECT cc.gec_function_component_id FROM account_analytic_account cc"
            "  WHERE cc.id = %s)"
        )
        candidates = [
            SQL(account_function, self.env[model]._field_to_sql(source_alias, plan._column_name()))
            for plan in plans if plan == project_plan
        ]
        if source_alias == 'aal':
            candidates.append(SQL(
                "(SELECT act.gec_function_component_id FROM gec_activity act"
                "  WHERE act.id = aal.gec_activity_id"
                "    AND aal.gec_allocation_kind IS DISTINCT FROM 'contra')"
            ))
        for plan in plans:
            if plan != project_plan:
                candidates.append(SQL(
                    account_function,
                    self.env[model]._field_to_sql(source_alias, plan._column_name()),
                ))
        if not candidates:
            return SQL("NULL::integer")
        return SQL("COALESCE(%s)", SQL(", ").join(candidates))

    def _revenue_stream_sql(self, source_alias, plans, signed_amount):
        """Which revenue stream a row belongs to.
        Revenue: analytic accounts first, then the GL account, so streams add up to the Revenue column.
        Cost: analytic accounts only; a salary account says nothing about a stream."""
        model = self._plan_source_model(source_alias)
        candidates = [
            SQL(
                "(SELECT a.gec_revenue_stream_id FROM account_analytic_account a WHERE a.id = %s)",
                self.env[model]._field_to_sql(source_alias, plan._column_name()),
            )
            for plan in plans
        ]
        analytic = SQL(", ").join(candidates) if candidates else SQL("NULL::integer")
        return SQL(
            "CASE WHEN %(direction)s = 'revenue'"
            "     THEN COALESCE(%(analytic)s, aa.gec_revenue_stream_id)"
            "     ELSE COALESCE(%(analytic)s) END",
            direction=self._direction_sql(signed_amount),
            analytic=analytic,
        )

    # Amounts are in each company currency; a reporting currency in the context converts them at their date rate.
    def _reporting_currency(self):
        currency_id = self.env.context.get('gec_reporting_currency_id')
        return self.env['res.currency'].browse(currency_id) if currency_id else None

    def _currency_column(self):
        currency = self._reporting_currency()
        return SQL("%s::integer", currency.id) if currency else SQL("rc.currency_id")

    def _converted(self, amount, date):
        currency = self._reporting_currency()
        if not currency:
            return amount
        company = self.env['res.company'].browse(
            self.env.context.get('gec_reporting_company_id') or self.env.company.id)
        self.env['res.currency.rate'].flush_model()

        def rate(currency_sql):
            # Units of the currency per one unit of the rate table's company currency; no rate counts as 1.
            return SQL(
                """COALESCE((SELECT r.rate FROM res_currency_rate r
                              WHERE r.currency_id = %(cur)s
                                AND (r.company_id = %(company)s OR r.company_id IS NULL)
                                AND r.name <= %(date)s
                           ORDER BY r.name DESC, r.company_id NULLS LAST LIMIT 1), 1.0)""",
                cur=currency_sql, company=company.id, date=date)
        return SQL(
            "(%(amount)s) * CASE WHEN rc.currency_id = %(target)s THEN 1.0"
            " ELSE %(to)s / NULLIF(%(from)s, 0) END",
            amount=amount, target=currency.id,
            to=rate(SQL("%s", currency.id)), **{'from': rate(SQL("rc.currency_id"))})

    def _direction_sql(self, signed_amount):
        """Revenue or Expense; falls back to the amount sign so the columns add up to Net."""
        return SQL(
            """
            CASE WHEN gmc.nature = 'revenue' THEN 'revenue'
                 WHEN gmc.nature = 'cost' THEN 'expense'
                 WHEN %(amount)s > 0 THEN 'revenue'
                 WHEN %(amount)s < 0 THEN 'expense'
                 ELSE NULL
            END
            """,
            amount=signed_amount,
        )

    def _measure_columns(self, signed_amount):
        """Revenue/expense split plus one column per level; ``revenue_amount + expense_amount = amount`` per row."""
        direction = self._direction_sql(signed_amount)
        columns = [
            SQL("%s AS direction", direction),
            SQL(
                "CASE WHEN %(d)s = 'revenue' THEN %(a)s ELSE 0.0 END AS revenue_amount",
                d=direction, a=signed_amount,
            ),
            SQL(
                "CASE WHEN %(d)s = 'expense' THEN %(a)s ELSE 0.0 END AS expense_amount",
                d=direction, a=signed_amount,
            ),
        ]
        for level in self.env['gec.margin.level'].sudo().search([]):
            fname = level._column_name()
            if fname not in self._fields:
                continue
            columns.append(SQL(
                "CASE WHEN gmc.id IN %(members)s THEN %(a)s ELSE 0.0 END AS %(name)s",
                members=tuple(level.component_ids.ids) or (0,),
                a=signed_amount,
                name=SQL.identifier(fname),
            ))
        return SQL(', ').join(columns)

    def _level_fnames_sql(self):
        """Placeholder so both union branches agree on the order of the level columns."""
        return [
            fname
            for level in self.env['gec.margin.level'].sudo().search([])
            if (fname := level._column_name()) in self._fields
        ]

    def _get_budget_query(self, plans, plan_fnames):
        signed_amount = self._converted(SQL(
            """
            CASE WHEN gmc.id IS NOT NULL
                     THEN bl.budget_amount * CASE WHEN gmc.nature = 'revenue' THEN 1 ELSE -1 END
                 WHEN ba.budget_type = 'revenue' THEN bl.budget_amount
                 ELSE -bl.budget_amount
            END
            """
        ), SQL("bl.date_from"))
        return SQL(
            """
            SELECT %(row_id)s AS id,
                   pl.plan_id AS plan_id,
                   pl.analytic_account_id AS analytic_account_id,
                   pl.plan_seq AS plan_sequence,
                   (pl.plan_seq = %(primary_seq)s) AS is_primary_plan,
                   bl.date_from AS date,
                   bl.company_id AS company_id,
                   %(currency)s AS currency_id,
                   'budget' AS line_type,
                   bl.general_account_id AS general_account_id,
                   NULL::integer AS move_id,
                   NULL::integer AS partner_id,
                   NULL::integer AS activity_id,
                   %(project_column)s,
                   gmc.id AS component_id,
                   %(revenue_stream)s AS revenue_stream_id,
                   FALSE AS is_allocation,
                   bl.budget_analytic_id AS budget_analytic_id,
                   bl.id AS budget_line_id,
                   NULL::integer AS analytic_line_id,
                   %(signed_amount)s AS amount,
                   %(signed_amount)s AS budget_amount,
                   0.0 AS actual_amount,
                   0.0 AS unit_amount,
                   %(measures)s,
                   %(plan_fields)s
                   %(extra_columns)s
              FROM budget_line bl
              JOIN budget_analytic ba ON ba.id = bl.budget_analytic_id
              JOIN res_company rc ON rc.id = bl.company_id
         LEFT JOIN account_account aa ON aa.id = bl.general_account_id
                   %(component_join)s
                   %(project_join)s
        CROSS JOIN LATERAL (VALUES %(plan_values)s) AS pl(plan_id, analytic_account_id, plan_seq)
                   %(extra_joins)s
             WHERE ba.state != 'canceled'
               AND pl.analytic_account_id IS NOT NULL
            """,
            row_id=self._row_id_sql(SQL("bl.id"), plans, 0),
            extra_columns=self._extra_columns('bl'),
            extra_joins=self._extra_joins('bl'),
            primary_seq=self._primary_seq_case('bl', plans),
            project_column=self._project_column(),
            project_join=self._project_join('bl'),
            component_join=self._component_join('aa', 'bl', plans),
            currency=self._currency_column(),
            revenue_stream=self._revenue_stream_sql('bl', plans, signed_amount),
            signed_amount=signed_amount,
            measures=self._measure_columns(signed_amount),
            plan_values=self._plan_lateral('bl', plans),
            plan_fields=SQL(', ').join(
                self.env['budget.line']._field_to_sql('bl', fname)
                for fname in plan_fnames
            ),
        )

    def _get_actual_query(self, plans, plan_fnames):
        signed_amount = self._converted(SQL("aal.amount"), SQL("aal.date"))
        return SQL(
            """
            SELECT %(row_id)s AS id,
                   pl.plan_id AS plan_id,
                   pl.analytic_account_id AS analytic_account_id,
                   pl.plan_seq AS plan_sequence,
                   (pl.plan_seq = %(primary_seq)s) AS is_primary_plan,
                   aal.date AS date,
                   aal.company_id AS company_id,
                   %(currency)s AS currency_id,
                   'actual' AS line_type,
                   aal.general_account_id AS general_account_id,
                   aml.move_id AS move_id,
                   aal.partner_id AS partner_id,
                   aal.gec_activity_id AS activity_id,
                   %(project_column)s,
                   gmc.id AS component_id,
                   %(revenue_stream)s AS revenue_stream_id,
                   COALESCE(aal.gec_is_allocation, FALSE) AS is_allocation,
                   NULL::integer AS budget_analytic_id,
                   NULL::integer AS budget_line_id,
                   aal.id AS analytic_line_id,
                   %(signed_amount)s AS amount,
                   0.0 AS budget_amount,
                   %(signed_amount)s AS actual_amount,
                   aal.unit_amount AS unit_amount,
                   %(measures)s,
                   %(plan_fields)s
                   %(extra_columns)s
              FROM account_analytic_line aal
              JOIN res_company rc ON rc.id = aal.company_id
         LEFT JOIN account_move_line aml ON aml.id = aal.move_line_id
         LEFT JOIN account_account aa ON aa.id = aal.general_account_id
                   %(component_join)s
                   %(project_join)s
        CROSS JOIN LATERAL (VALUES %(plan_values)s) AS pl(plan_id, analytic_account_id, plan_seq)
                   %(extra_joins)s
             WHERE pl.analytic_account_id IS NOT NULL
            """,
            row_id=self._row_id_sql(SQL("aal.id"), plans, 1),
            extra_columns=self._extra_columns('aal'),
            extra_joins=self._extra_joins('aal'),
            primary_seq=self._primary_seq_case('aal', plans),
            project_column=self._project_column(),
            project_join=self._project_join('aal'),
            component_join=self._component_join('aa', 'aal', plans),
            currency=self._currency_column(),
            revenue_stream=self._revenue_stream_sql('aal', plans, signed_amount),
            signed_amount=signed_amount,
            measures=self._measure_columns(signed_amount),
            plan_values=self._plan_lateral('aal', plans),
            plan_fields=SQL(', ').join(
                self.env['account.analytic.line']._field_to_sql('aal', fname)
                for fname in plan_fnames
            ),
        )

    def action_open_source(self):
        """Jump from a report row to the record behind it."""
        self.ensure_one()
        model, res_id = (
            ('account.move', self.move_id.id) if self.move_id
            else ('account.analytic.line', self.analytic_line_id.id) if self.analytic_line_id
            else ('budget.analytic', self.budget_analytic_id.id) if self.budget_analytic_id
            else (None, None)
        )
        if not model:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _("Source Document"),
            'res_model': model,
            'res_id': res_id,
            'view_mode': 'form',
        }
