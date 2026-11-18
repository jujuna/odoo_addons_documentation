import logging
from datetime import date, datetime

from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero

_logger = logging.getLogger(__name__)


class GecAllocationRun(models.Model):
    _name = 'gec.allocation.run'
    _description = 'Analytic Cost Allocation Run'
    _order = 'date_from desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    rule_ids = fields.Many2many(
        'gec.allocation.rule',
        string='Rules',
        check_company=True,
        help="Leave empty to run every active rule of the company.",
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Generated')],
        default='draft', required=True, copy=False,
    )
    line_ids = fields.One2many(
        'account.analytic.line', 'gec_allocation_run_id',
        string='Generated Analytic Lines', readonly=True,
    )
    line_count = fields.Integer(compute='_compute_totals')
    allocated_amount = fields.Monetary(
        compute='_compute_totals',
        currency_field='currency_id',
        help="Total moved onto the target plan by this run.",
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    log = fields.Text(
        string='Run Log', readonly=True, copy=False,
        help="What each rule did, and why a rule produced nothing.",
    )
    driver_warning = fields.Text(
        string='Driver Warnings', readonly=True, copy=False,
        help="Cost objects that were busy this period but measured no driver "
             "units, so the allocation passed them by. Almost always a missing "
             "timesheet or a wrong filter rather than a fact about the business.",
    )
    applied_rule_ids = fields.Many2many(
        'gec.allocation.rule', 'gec_allocation_run_applied_rule_rel',
        'run_id', 'rule_id',
        string='Rules Applied', readonly=True, copy=False,
        help="The rules this run actually applied, recorded when it was "
             "generated.\n\n"
             "Rules is what you asked for and may be empty, meaning every "
             "active rule. This is what happened — and it is what the "
             "double-allocation guard compares, because a run cannot have "
             "applied a rule that did not exist when it ran.",
    )
    rate_ids = fields.One2many(
        'gec.activity.rate', 'run_id', string='Activity Rates', readonly=True,
        help="Cost per driver unit recorded by this run, kept so rates can be "
             "compared across periods.",
    )
    rate_count = fields.Integer(compute='_compute_totals')

    @api.depends('line_ids.amount', 'line_ids.gec_allocation_kind')
    def _compute_totals(self):
        for run in self:
            run.line_count = len(run.line_ids)
            run.allocated_amount = sum(
                run.line_ids.filtered(
                    lambda line: line.gec_allocation_kind == 'target'
                ).mapped('amount')
            )
            run.rate_count = len(run.rate_ids)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for run in self:
            if run.date_from > run.date_to:
                raise ValidationError(_("The end date cannot precede the start date."))

    def _get_effective_rules(self):
        """The rules this run applies; an empty ``rule_ids`` means every active rule of the company."""
        self.ensure_one()
        return self.rule_ids or self.env['gec.allocation.rule'].search([
            ('company_id', '=', self.company_id.id),
        ])

    def _check_no_double_allocation(self):
        """Refuse the same rule applied over overlapping dates by two runs (the cost would be charged twice);
        runs applying different rules may share a period."""
        self.ensure_one()
        mine = self._get_effective_rules()
        overlapping = self.search([
            ('id', '!=', self.id),
            ('state', '=', 'done'),
            ('company_id', '=', self.company_id.id),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ])
        for other in overlapping:
            # What the other run did, not what it would do now: an empty Rules means "every active rule",
            # which would include rules written since.
            clashing = mine & (other.applied_rule_ids or other._get_effective_rules())
            if clashing:
                raise UserError(_(
                    "This would allocate the same cost twice.\n\n"
                    "Run “%(other)s” (%(start)s → %(end)s) already applied: "
                    "%(rules)s\n\n"
                    "Delete that allocation first, or narrow the Rules on one of "
                    "the two runs so they no longer overlap.",
                    other=other.name,
                    start=other.date_from,
                    end=other.date_to,
                    rules=", ".join(clashing.mapped('name')),
                ))

    def _check_resource_shares(self, rules):
        """No pool may be charged out more than 100% across rules.
        Every driver is checked, not only activity-based ones: two rules spreading the same pool
        without shares would each take all of it."""
        self.ensure_one()
        if not rules:
            return
        by_pool = {}
        for rule in rules:
            share, _note = rule._get_resource_share(self.date_from, self.date_to)
            by_pool.setdefault(rule._pool_signature(), []).append((rule, share))
        for competing in by_pool.values():
            total = sum(share for _rule, share in competing)
            if total > 100.01:
                raise UserError(_(
                    "These rules draw on the same cost pool and their shares add "
                    "up to %(total)s%%, which would charge out more than the pool "
                    "holds:\n\n%(detail)s\n\n"
                    "Reduce the shares so they total 100%% or less.",
                    total=f"{total:.1f}",
                    detail="\n".join(
                        f"  {rule.name}: {share:.1f}%" for rule, share in competing
                    ),
                ))

    def action_compute(self):
        for run in self:
            run._check_no_double_allocation()
            run._clear_lines()
            rules = run._get_effective_rules()
            run._check_resource_shares(rules)
            if not rules:
                raise UserError(_(
                    "No active allocation rule found for %(company)s.",
                    company=run.company_id.display_name,
                ))

            messages = []
            warnings = []
            # Written step by step: a step 2 pool must read what step 1 delivered, which a search cannot see in a list.
            for step in sorted(set(rules.mapped('step'))):
                vals_list = []
                for rule in rules.filtered(lambda r: r.step == step):
                    messages += run._compute_rule(rule, vals_list, warnings)
                if vals_list:
                    self.env['account.analytic.line'].create(vals_list)
                    self.env['account.analytic.line'].flush_model()

            run.log = "\n".join(messages)
            run.driver_warning = "\n".join(warnings) or False
            run.applied_rule_ids = [Command.set(rules.ids)]
            run.state = 'done'
        return True

    def _compute_rule(self, rule, vals_list, warnings=None):
        """Append one rule's lines to *vals_list*, return its log messages; *warnings* collects findings for the run."""
        self.ensure_one()
        weights = rule._compute_weights(self.date_from, self.date_to)
        if not weights:
            return [_(
                "%(rule)s: nothing allocated — the '%(driver)s' driver "
                "produced no allocation base for this period.",
                rule=rule.name,
                driver=dict(rule._fields['driver'].selection)[rule.driver],
            )]

        rule_vals = self._build_rule_lines(rule, weights)
        if not rule_vals:
            return [_(
                "%(rule)s: nothing allocated — no source cost matched "
                "in this period.", rule=rule.name,
            )]

        vals_list += rule_vals
        charged = sum(
            vals['amount'] for vals in rule_vals
            if vals.get('gec_allocation_kind') == 'target'
        )
        note = ""
        if rule.driver == 'activity' and rule.activity_id:
            share, share_note = rule._get_resource_share(self.date_from, self.date_to)
            note += share_note
            note += self._record_activity_rate(rule, charged, share)
        if warnings is not None:
            warnings += self._zero_driver_warnings(rule, weights)
        step_note = _(" [step %(step)s]", step=rule.step) if rule.step != 1 else ""
        return [_(
            "%(rule)s%(step)s: %(lines)s lines across %(targets)s targets, "
            "%(charged)s allocated%(note)s.",
            rule=rule.name, step=step_note, lines=len(rule_vals),
            targets=len(weights), charged=f"{charged:,.2f}", note=note,
        )]

    def _record_activity_rate(self, rule, charged, share=100.0):
        """Store what one unit cost this period; return a log note.
        Variance (pool less charged) stays on the source, not in product cost (under/over-absorption, idle capacity).
        *share* is the rule's slice of the source centre; each rule is costed against its own pool."""
        self.ensure_one()
        activity = rule.activity_id
        quantities = rule._get_activity_quantities(self.date_from, self.date_to)
        quantity = sum(quantities.values())
        pool = rule._get_pool_amount(self.date_from, self.date_to) * (share / 100.0)
        rate = activity.get_rate(pool, self.date_from, self.date_to)
        capacity = activity.practical_capacity
        volume, spending = self.env['gec.activity.rate']._split_variance(
            pool, charged, rate, capacity,
        )

        self.env['gec.activity.rate'].create({
            'activity_id': activity.id,
            'rule_id': rule.id,
            'run_id': self.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'rate_mode': activity.rate_mode,
            'driver_label': activity.driver_label,
            'rate': rate,
            'quantity': quantity,
            'practical_capacity': capacity,
            'capacity_used': (quantity / capacity * 100.0) if capacity else 0.0,
            'unused_quantity': (capacity - quantity) if capacity else 0.0,
            'pool_amount': pool,
            'charged_amount': charged,
            'variance_amount': pool - charged,
            'volume_variance': volume,
            'spending_variance': spending,
        })

        note = _(
            " — %(rate)s per %(unit)s (%(mode)s)",
            rate=f"{rate:,.2f}", unit=activity.driver_label,
            mode=_("standard") if activity.rate_mode == 'standard' else _("actual"),
        )
        variance = pool - charged
        currency = self.company_id.currency_id
        if not currency.is_zero(variance):
            note += _(
                "; %(variance)s left on the source%(reason)s",
                variance=f"{variance:,.2f}", reason=self._variance_reason(
                    volume, spending, capacity, quantity, activity,
                ),
            )
        return note

    def _variance_reason(self, volume, spending, capacity, quantity, activity):
        """Name which half of the variance (idle capacity or rate) dominates; the other in brackets when material."""
        currency = self.company_id.currency_id
        parts = []
        if not currency.is_zero(volume):
            parts.append(_(
                "%(amount)s as idle capacity (%(units)s %(unit)s of %(capacity)s "
                "unused)",
                amount=f"{volume:,.2f}", units=f"{capacity - quantity:,.1f}",
                unit=activity.driver_label, capacity=f"{capacity:,.1f}",
            ))
        if not currency.is_zero(spending):
            parts.append(_(
                "%(amount)s as a rate variance — the pool differs from what the "
                "standard rate assumed",
                amount=f"{spending:,.2f}",
            ))
        if not parts:
            return ""
        reason = ": " + " and ".join(parts)
        if not capacity and activity.rate_mode == 'standard':
            # With no capacity there is no volume to compare, so the whole difference is rate variance.
            reason += _(
                " (set a practical capacity on %(activity)s to separate idle "
                "volume from overspending)", activity=activity.name,
            )
        return reason

    def _zero_driver_warnings(self, rule, weights):
        """Name cost objects with their own revenue or cost this period that got nothing because nothing was measured.

        Means a missing timesheet or wrong filter or path; a dormant account is not named."""
        self.ensure_one()
        missed = rule._get_target_accounts().filtered(
            lambda account: not weights.get(account.id)
        )
        if not missed:
            return []
        busy = self._accounts_with_activity(rule, missed)
        if not busy:
            return []

        names = ", ".join(busy[:4].mapped('display_name'))
        if len(busy) > 4:
            names = _("%(names)s and %(count)s more",
                      names=names, count=len(busy) - 4)
        return [_(
            "%(rule)s: %(count)s cost object(s) had cost or revenue this period "
            "but measured no %(unit)s, so they were charged nothing — %(names)s.",
            rule=rule.name, count=len(busy), names=names,
            unit=(rule.activity_id.driver_label if rule.activity_id
                  else _("driver units")),
        )]

    def _accounts_with_activity(self, rule, accounts):
        """Of *accounts*, those with a non-zero amount of their own; allocation output is excluded."""
        self.ensure_one()
        column = rule.target_plan_id._column_name()
        groups = self.env['account.analytic.line']._read_group(
            domain=[
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('company_id', '=', self.company_id.id),
                ('gec_is_allocation', '=', False),
                (column, 'in', accounts.ids),
            ],
            groupby=[column],
            aggregates=['amount:sum'],
        )
        currency = self.company_id.currency_id
        busy = {
            account.id for account, amount in groups
            if not currency.is_zero(amount)
        }
        return accounts.filtered(lambda account: account.id in busy)

    def action_open_rates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Activity Rates"),
            'res_model': 'gec.activity.rate',
            'view_mode': 'list,form',
            'domain': [('run_id', '=', self.id)],
        }

    @api.model
    def _cron_generate_closed_periods(self):
        """Prepare the run for each company's last closed month; opt-in per company, never by the calendar alone."""
        companies = self.env['res.company'].search([
            ('gec_allocation_cron_mode', '!=', 'off'),
        ])
        for company in companies:
            self.with_company(company)._gec_cron_for_company(company)
        return True

    @api.model
    def _gec_cron_for_company(self, company):
        period = company._gec_last_closed_month()
        if not period:
            _logger.info(
                "%s: no closed period — set an accounting lock date, or switch "
                "the basis to elapsed days.", company.display_name,
            )
            return self.browse()

        start, end = period
        existing = self.search([
            ('company_id', '=', company.id),
            ('date_from', '=', start), ('date_to', '=', end),
        ], limit=1)
        if existing:
            _logger.info(
                "%s: %s to %s already has a run (%s).",
                company.display_name, start, end, existing.display_name,
            )
            return existing

        run = self.create({
            'name': company._gec_cron_run_name(start),
            'company_id': company.id,
            'date_from': start,
            'date_to': end,
        })
        if company.gec_allocation_cron_mode != 'generate':
            run.log = _(
                "Prepared by the monthly scheduled action. Press Preview to see "
                "what it would move, then Generate."
            )
            return run

        # Computed in a savepoint so a refusal (overlapping run, shares over 100%) leaves the run in draft
        # with the reason, not a rolled-back cron.
        try:
            with self.env.cr.savepoint():
                run.action_compute()
        except UserError as error:
            self.env.invalidate_all()
            run.log = _(
                "Left in draft by the monthly scheduled action:\n\n%s", error,
            )
            _logger.warning(
                "%s: %s to %s not generated — %s",
                company.display_name, start, end, error,
            )
        return run

    def action_dry_run(self):
        """Show what the run would move, without moving it."""
        self.ensure_one()
        preview = self._simulate()
        wizard = self.env['gec.allocation.preview'].create(preview)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Dry Run — %s", self.name),
            'res_model': 'gec.allocation.preview',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _simulate(self):
        """Compute for real inside a savepoint, read the result, then undo it:
        a step 2 pool is built from step 1's lines, so a cascade cannot be predicted without writing."""
        self.ensure_one()

        class _Rewind(Exception):
            """Carries nothing; exists only to leave the savepoint block."""

        captured = {}
        try:
            with self.env.cr.savepoint():
                self.action_compute()
                captured = {
                    'run_id': self.id,
                    'log': self.log,
                    'driver_warning': self.driver_warning,
                    'line_count': len(self.line_ids),
                    'allocated_amount': self.allocated_amount,
                    'line_ids': [
                        Command.create(vals) for vals in self._preview_line_vals()
                    ],
                }
                raise _Rewind()
        except _Rewind:
            pass
        # The rollback undid the writes but not the cursor's cache.
        self.env.invalidate_all()
        return captured

    def _preview_line_vals(self):
        """The generated lines as plain values, read eagerly because the records no longer exist after the rewind."""
        self.ensure_one()
        Line = self.env['account.analytic.line']
        columns = [
            column for plan in self.env['account.analytic.plan'].search([])
            if (column := plan._column_name()) in Line._fields
        ]
        return [
            {
                'name': line.name,
                'date': line.date,
                'analytic_label': ", ".join(
                    line[column].display_name for column in columns if line[column]
                ),
                'general_account_id': line.general_account_id.id,
                'kind': line.gec_allocation_kind,
                'amount': line.amount,
            }
            for line in self.line_ids
        ]

    def action_reset(self):
        for run in self:
            run._clear_lines()
            run.log = False
            run.driver_warning = False
            run.applied_rule_ids = [Command.clear()]
            run.state = 'draft'
        return True

    def action_open_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Allocation Lines"),
            'res_model': 'account.analytic.line',
            'view_mode': 'list,pivot,form',
            'domain': [('gec_allocation_run_id', '=', self.id)],
        }

    def _clear_lines(self):
        self.ensure_one()
        self.line_ids.sudo().unlink()
        # Rates describe the lines; leaving them on a recompute would stack one period's rate on another's.
        self.rate_ids.sudo().unlink()

    def _build_rule_lines(self, rule, weights):
        """Build the analytic lines for one rule: per (plans x GL account x month) group,
        one contra line on the source and one target line per weighted account, summing to zero."""
        self.ensure_one()
        AnalyticLine = self.env['account.analytic.line']
        plan_fnames = AnalyticLine._get_plan_fnames()
        target_col = rule.target_plan_id._column_name()
        currency = self.company_id.currency_id

        groups = AnalyticLine._read_group(
            domain=rule._get_source_domain(self.date_from, self.date_to),
            groupby=plan_fnames + ['general_account_id', 'date:month'],
            aggregates=['amount:sum'],
        )

        vals_list = []
        for group in groups:
            *plan_accounts, gl_account, period, amount = group
            amount = currency.round(amount or 0.0)
            if currency.is_zero(amount):
                continue

            base = {
                'company_id': self.company_id.id,
                'date': self._normalize_period(period),
                'general_account_id': gl_account.id if gl_account else False,
                'gec_allocation_run_id': self.id,
                'gec_allocation_step': rule.step,
                # Which activity produced the line, so the report shows what a product was doing.
                'gec_activity_id': rule.activity_id.id if rule.driver == 'activity' else False,
            }
            for fname, account in zip(plan_fnames, plan_accounts):
                base[fname] = account.id if account else False

            shares = self._distribute(amount, weights, currency)
            if not shares:
                continue

            # The contra matches what was charged out, not the whole pool: capacity or a pool share charges out less,
            # and the rest stays on the source.
            charged = sum(part for _account, part in shares)
            vals_list.append(dict(
                base,
                name=_("%(rule)s — contra", rule=rule.name),
                gec_allocation_kind='contra',
                amount=-charged,
            ))

            for account_id, share in shares:
                target_vals = dict(
                    base,
                    name=_("%(rule)s — allocated", rule=rule.name),
                    gec_allocation_kind='target',
                    amount=share,
                )
                target_vals[target_col] = account_id
                vals_list.append(target_vals)

        return vals_list

    @staticmethod
    def _distribute(amount, weights, currency):
        """Split ``amount`` by ``weights`` and push the rounding residual onto the largest share so the contra nets out.

        The target total is ``amount x sum(weights)``, which may be below ``amount``."""
        target = currency.round(amount * sum(weights.values()))
        shares = [
            (account_id, currency.round(amount * weight))
            for account_id, weight in sorted(
                weights.items(), key=lambda item: -item[1]
            )
        ]
        shares = [(account_id, part) for account_id, part in shares if part]
        if not shares:
            return []
        residual = currency.round(target - sum(part for _account, part in shares))
        if not currency.is_zero(residual):
            account_id, part = shares[0]
            shares[0] = (account_id, currency.round(part + residual))
        return shares

    @staticmethod
    def _normalize_period(period):
        """``_read_group`` returns a date for ``date:month``; tolerate a string or datetime."""
        if isinstance(period, datetime):
            return period.date()
        if isinstance(period, date):
            return period
        if isinstance(period, str):
            return fields.Date.to_date(period[:10])
        raise UserError(_("Unexpected period value from the group-by: %s", period))
