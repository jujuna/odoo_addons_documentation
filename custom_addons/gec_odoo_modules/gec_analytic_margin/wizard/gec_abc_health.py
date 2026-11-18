from odoo import models, fields, api, Command, _


SEVERITY = [
    ('error', 'Wrong'),
    ('warning', 'Suspicious'),
    ('info', 'Worth knowing'),
]


class GecAbcHealth(models.TransientModel):
    """Read-only list of ABC misconfigurations that fail silently, shown before a run."""
    _name = 'gec.abc.health'
    _description = 'ABC Setup Health Check'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    date_from = fields.Date(
        required=True, default=lambda self: fields.Date.context_today(self).replace(
            month=1, day=1,
        ),
        help="Checks that count something — measured driver units, pool amounts "
             "— look at this period. A quiet January says nothing about a "
             "configuration that works in June.",
    )
    date_to = fields.Date(
        required=True, default=lambda self: fields.Date.context_today(self),
    )
    check_ids = fields.One2many('gec.abc.health.check', 'health_id', readonly=True)

    error_count = fields.Integer(compute='_compute_counts')
    warning_count = fields.Integer(compute='_compute_counts')
    info_count = fields.Integer(compute='_compute_counts')
    all_clear = fields.Boolean(compute='_compute_counts')

    @api.depends('check_ids.severity')
    def _compute_counts(self):
        for health in self:
            severities = health.check_ids.mapped('severity')
            health.error_count = severities.count('error')
            health.warning_count = severities.count('warning')
            health.info_count = severities.count('info')
            health.all_clear = not health.check_ids

    @api.model
    def default_get(self, fields_list):
        """Run the checks as the screen opens, unless the context flag asks for an empty record."""
        values = super().default_get(fields_list)
        if self.env.context.get('gec_check_on_open') and 'check_ids' in fields_list:
            values['check_ids'] = [
                Command.create(vals) for vals in self.new(values)._collect()
            ]
        return values

    def action_check(self):
        self.ensure_one()
        self.check_ids = [Command.clear()] + [
            Command.create(vals) for vals in self._collect()
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': _("ABC Setup Health Check"),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _collect(self):
        """Every finding, worst first; each check is guarded so one broken setup cannot blank the page."""
        self.ensure_one()
        found = []
        for check in (
            self._check_activities, self._check_rules, self._check_shares,
            self._check_uncovered_pools, self._check_plans, self._check_chart,
            self._check_inheritance, self._check_functions,
            self._check_revenue_streams,
        ):
            try:
                found += check()
            except Exception as error:  # noqa: BLE001 - the message is the finding
                found.append(self._finding(
                    'error', _("Health check"),
                    _("One of the checks could not complete"), str(error),
                ))
        order = {severity: index for index, (severity, _label) in enumerate(SEVERITY)}
        found.sort(key=lambda vals: order[vals['severity']])
        return found

    @staticmethod
    def _finding(severity, category, name, detail, record=None):
        return {
            'severity': severity,
            'category': category,
            'name': name,
            'detail': detail,
            'res_model': record._name if record else False,
            'res_id': record.id if record else False,
        }

    def _check_activities(self):
        """An activity that measures nothing allocates nothing, silently."""
        found = []
        activities = self.env['gec.activity'].search([
            ('company_id', '=', self.company_id.id),
        ])
        used = self.env['gec.allocation.rule'].search([
            ('company_id', '=', self.company_id.id), ('driver', '=', 'activity'),
        ]).mapped('activity_id')

        for activity in activities:
            try:
                quantities = activity.get_quantities(self.date_from, self.date_to)
            except Exception as error:  # noqa: BLE001 - the message is the finding
                found.append(self._finding(
                    'error', _("Activity"),
                    _("%s cannot count at all", activity.name),
                    str(error), activity,
                ))
                continue

            total = sum(quantities.values())
            if not total:
                found.append(self._finding(
                    'warning', _("Activity"),
                    _("%s measured no %s", activity.name, activity.driver_label),
                    _("Nothing matched between %(start)s and %(end)s. Check the "
                      "filter, the date field and the path to the analytic "
                      "account — or there is simply no data yet.",
                      start=self.date_from, end=self.date_to),
                    activity,
                ))

            # Analytic items mix units (hours, quantities, past runs), so counting all of them is meaningless.
            if (activity.source_model_name == 'account.analytic.line'
                    and activity.source_domain.strip() in ('', '[]')):
                found.append(self._finding(
                    'error', _("Activity"),
                    _("%s counts every analytic item", activity.name),
                    _("With no filter this sums timesheet hours, invoice line "
                      "quantities and the output of previous allocation runs "
                      "into one number. Narrow it, for example to "
                      "[('general_account_id', '=', False), "
                      "('gec_is_allocation', '=', False), "
                      "('unit_amount', '>', 0)]."),
                    activity,
                ))

            if activity not in used:
                found.append(self._finding(
                    'info', _("Activity"),
                    _("%s is not used by any rule", activity.name),
                    _("It measures, but nothing spends against it, so it costs "
                      "nothing. Point an allocation rule at it or leave it "
                      "parked."),
                    activity,
                ))

            if activity.rate_mode == 'standard' and not activity.practical_capacity:
                found.append(self._finding(
                    'info', _("Activity"),
                    _("%s has a standard rate but no practical capacity",
                      activity.name),
                    _("Whatever the pool fails to absorb will be reported as a "
                      "rate variance, because there is no volume to compare "
                      "against. Set a practical capacity to separate idle "
                      "capacity from overspending."),
                    activity,
                ))
        return found

    def _check_rules(self):
        """A rule with no pool, or no base to spread it over, does nothing."""
        found = []
        for rule in self.env['gec.allocation.rule'].search([
            ('company_id', '=', self.company_id.id),
        ]):
            if rule.gec_source_warning:
                found.append(self._finding(
                    'error', _("Rule"),
                    _("%s cannot draw on the accounts it names", rule.name),
                    rule.gec_source_warning, rule,
                ))

            try:
                pool = rule._get_pool_amount(self.date_from, self.date_to)
                weights = rule._compute_weights(self.date_from, self.date_to)
            except Exception as error:  # noqa: BLE001 - the message is the finding
                found.append(self._finding(
                    'error', _("Rule"),
                    _("%s cannot be computed", rule.name), str(error), rule,
                ))
                continue

            if self.company_id.currency_id.is_zero(pool):
                found.append(self._finding(
                    'warning', _("Rule"),
                    _("%s has an empty pool", rule.name),
                    _("No source cost matched between %(start)s and %(end)s, so "
                      "this rule would allocate nothing.",
                      start=self.date_from, end=self.date_to),
                    rule,
                ))
                continue

            if not weights:
                found.append(self._finding(
                    'error', _("Rule"),
                    _("%s has cost to spread and nothing to spread it over",
                      rule.name),
                    _("The pool holds %(pool)s but the '%(driver)s' driver "
                      "produced no allocation base, so the whole amount stays "
                      "on the source.",
                      pool=f"{pool:,.2f}",
                      driver=dict(rule._fields['driver'].selection)[rule.driver]),
                    rule,
                ))
        return found

    def _check_shares(self):
        """Rules competing for one pool must not claim more than all of it."""
        found = []
        rules = self.env['gec.allocation.rule'].search([
            ('company_id', '=', self.company_id.id),
        ])
        by_pool = {}
        for rule in rules:
            share, _note = rule._get_resource_share(self.date_from, self.date_to)
            by_pool.setdefault(rule._pool_signature(), []).append((rule, share))

        for competing in by_pool.values():
            total = sum(share for _rule, share in competing)
            if total > 100.01:
                found.append(self._finding(
                    'error', _("Rule"),
                    _("%s rules claim %s%% of one cost pool",
                      len(competing), f"{total:.1f}"),
                    "\n".join(
                        f"  {rule.name}: {share:.1f}%" for rule, share in competing
                    ) + _("\n\nA run over all of them is refused. Reduce the "
                          "shares, or archive the duplicate."),
                    competing[0][0],
                ))
        return found

    def _check_functions(self):
        """Pooled cost with no function, in a company that reports by function.

        It stays under Personnel or Overhead, so function lines add up to less than the company spent."""
        if self.company_id.gec_pl_mode != 'function':
            return []
        pooled = self.env['gec.margin.component'].search([('function_reclassify', '=', True)])
        if not pooled:
            return []
        groups = self.env['gec.margin.report']._read_group([
            ('line_type', '=', 'actual'),
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('is_primary_plan', '=', True),
            ('component_id', 'in', pooled.ids),
        ], ['analytic_account_id'], ['amount:sum'])
        leftover = [(account, amount) for account, amount in groups if amount]
        if not leftover:
            return []
        total = sum(amount for _account, amount in leftover)
        return [self._finding(
            'warning', _("Function"),
            _("%s of personnel and overhead cost has no function", f"{total:,.2f}"),
            "\n".join(
                f"  {account.display_name or _('No analytic account')}: {amount:,.2f}"
                for account, amount in sorted(leftover, key=lambda item: item[1])
            ) + _("\n\nThis company reports its P&L by function, but these amounts "
                  "sit on cost centres (and came through activities) that name "
                  "none. They stay under Personnel or Overhead. Set a Function on "
                  "the cost centre, or on the activity that charges the cost."),
        )]

    def _check_revenue_streams(self):
        """Revenue no stream claims, once streams are in use; it silently counts as one-off."""
        in_use = (
            self.env['account.account'].search_count([('gec_revenue_stream_id', '!=', False)], limit=1)
            or self.env['account.analytic.account'].search_count(
                [('gec_revenue_stream_id', '!=', False)], limit=1)
        )
        if not in_use:
            return []
        groups = self.env['gec.margin.report']._read_group([
            ('line_type', '=', 'actual'),
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('is_primary_plan', '=', True),
            ('direction', '=', 'revenue'),
            ('revenue_stream_id', '=', False),
        ], ['general_account_id'], ['revenue_amount:sum'])
        missing = [(account, amount) for account, amount in groups if amount]
        if not missing:
            return []
        total = sum(amount for _account, amount in missing)
        return [self._finding(
            'warning', _("Revenue stream"),
            _("%s of revenue has no revenue stream", f"{total:,.2f}"),
            "\n".join(
                f"  {account.display_name or _('No GL account')}: {amount:,.2f}"
                for account, amount in sorted(missing, key=lambda item: -item[1])
            ) + _("\n\nIt counts as one-off revenue, so the recurring share on the "
                  "dashboard is understated by whatever part of it renews. Set a "
                  "Revenue Stream on these income accounts, or on the product-line "
                  "analytic accounts."),
        )]

    def _check_uncovered_pools(self):
        """Allocatable cost no rule will ever move."""
        total, by_account = self.env['gec.allocation.rule']._uncovered_pool(
            self.date_from, self.date_to, self.company_id,
        )
        if not total:
            return []
        return [self._finding(
            'warning', _("Cost pool"),
            _("%s of allocatable cost is covered by no rule", f"{total:,.2f}"),
            "\n".join(
                f"  {account.display_name}: {amount:,.2f}"
                for account, amount in sorted(
                    by_account.items(), key=lambda item: item[1],
                )
            ) + _("\n\nIt was never charged to a project, product or customer, "
                  "so every margin is that much too good. Write a rule for it, "
                  "or mark the component non-allocatable if it is meant to stay."),
        )]

    def _check_plans(self):
        """A plan covering some cost objects and not others: an unplanned one is a gap, whatever its size."""
        found = []
        Plan = self.env['gec.activity.plan']
        for activity in self.env['gec.activity'].search([
            ('company_id', '=', self.company_id.id),
        ]):
            plans = Plan.search([
                ('activity_id', '=', activity.id),
                ('date_from', '<=', self.date_to),
                ('date_to', '>=', self.date_from),
            ])
            if not plans:
                continue
            try:
                measured = activity.get_quantities(self.date_from, self.date_to)
            except Exception:  # noqa: BLE001 - the activity check already said so
                continue

            planned = set(plans.mapped('analytic_account_id').ids)
            missing = self.env['account.analytic.account'].browse([
                account_id for account_id, quantity in measured.items()
                if quantity and account_id not in planned
            ])
            if not missing:
                continue
            found.append(self._finding(
                'warning', _("Plan"),
                _("%(count)s cost object(s) consumed %(activity)s with no plan",
                  count=len(missing), activity=activity.name),
                "\n".join(
                    f"  {account.display_name}: "
                    f"{measured[account.id]:,.1f} {activity.driver_label}"
                    for account in missing
                ) + _("\n\nThey are missing from every planned-against-actual "
                      "total, so the plan looks closer to reality than it is."),
                activity,
            ))
        return found

    def _check_inheritance(self):
        """Readings of the statement nothing can reach: no project names a product, or items predate it.

        Only plans offered as a reading of the statement are checked."""
        found = []
        plans = self.env['account.analytic.plan'].search([
            ('gec_section_key', '!=', False),
        ])
        if not plans:
            return found

        Line = self.env['account.analytic.line']
        if 'project_id' not in Line._fields:
            return found

        Project = self.env['project.project']
        for plan in plans:
            column = plan._column_name()
            if column not in Project._fields:
                continue
            if not Project.search_count([(column, '!=', False)]):
                found.append(self._finding(
                    'warning', _("Reading"),
                    _("No project names a %s", plan.display_name),
                    _("The statement offers a %(plan)s reading, but no project "
                      "says which one it delivers — so no hour logged on a "
                      "project can ever carry a %(plan)s, and the reading shows "
                      "revenue and direct cost with no labour behind it. Set "
                      "the field on the projects.",
                      plan=plan.display_name),
                    plan,
                ))
                continue
            behind = Line._gec_items_behind_project_tag(
                plan, self.date_from, self.date_to,
            )
            if behind:
                found.append(self._finding(
                    'info', _("Reading"),
                    _("%(count)s item(s) predate their project's %(plan)s",
                      count=behind, plan=plan.display_name),
                    _("They were posted before the project named a %(plan)s, so "
                      "they carry none and are invisible to anything measuring "
                      "effort per %(plan)s. The plan has a button to fill them "
                      "— and recompute any allocation run covering them, "
                      "because what those periods measured will change.",
                      plan=plan.display_name),
                    plan,
                ))
        return found

    def _check_chart(self):
        """Money on accounts with no margin component reaches no margin line."""
        groups = self.env['account.analytic.line']._read_group(
            domain=[
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('company_id', '=', self.company_id.id),
                ('general_account_id', '!=', False),
                ('general_account_id.gec_margin_component_id', '=', False),
            ],
            groupby=['general_account_id'],
            aggregates=['amount:sum'],
        )
        unclassified = [
            (account, amount) for account, amount in groups
            if not self.company_id.currency_id.is_zero(amount)
        ]
        if not unclassified:
            return []
        # Gross, not net: the question is how much money is in the wrong place.
        total = sum(abs(amount) for _account, amount in unclassified)
        return [self._finding(
            'warning', _("Chart of accounts"),
            _("%(amount)s of movement on %(count)s account(s) with no margin "
              "component", amount=f"{total:,.2f}", count=len(unclassified)),
            "\n".join(
                f"  {account.code} {account.name}: {amount:,.2f}"
                for account, amount in sorted(unclassified, key=lambda i: i[1])
            ) + _("\n\nThese amounts appear on the Unclassified line and in no "
                  "margin. Set a component on the accounts, or correct the "
                  "documents that used them."),
        )]


class GecAbcHealthCheck(models.TransientModel):
    _name = 'gec.abc.health.check'
    _description = 'ABC Setup Finding'
    _order = 'id'

    health_id = fields.Many2one(
        'gec.abc.health', required=True, ondelete='cascade', index=True,
    )
    severity = fields.Selection(SEVERITY, required=True)
    category = fields.Char(readonly=True)
    name = fields.Char(readonly=True)
    detail = fields.Text(readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)

    def action_open(self):
        """Jump to whatever is wrong, so the finding is one click from the fix."""
        self.ensure_one()
        if not self.res_model:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }
