from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain


DRIVER_SELECTION = [
    ('revenue_share', 'Revenue share'),
    ('direct_cost_share', 'Direct cost share'),
    ('headcount_share', 'Headcount share'),
    ('equal', 'Equal split'),
    ('manual', 'Manual percentages'),
]


class GecAllocationRule(models.Model):
    _name = 'gec.allocation.rule'
    _description = 'Analytic Cost Allocation Rule'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )

    source_plan_id = fields.Many2one(
        'account.analytic.plan',
        string='Source Plan',
        required=True,
        domain="[('parent_id', '=', False)]",
        help="The plan the cost is currently tagged with — typically the cost "
             "centre plan (Internal Organization).",
    )
    source_account_ids = fields.Many2many(
        'account.analytic.account',
        'gec_alloc_rule_source_account_rel', 'rule_id', 'account_id',
        string='Source Accounts',
        domain="[('plan_id', 'child_of', source_plan_id)]",
        check_company=True,
        help="Leave empty to allocate from every account of the source plan.",
    )
    source_gl_account_ids = fields.Many2many(
        'account.account',
        'gec_alloc_rule_source_gl_rel', 'rule_id', 'account_id',
        string='Source GL Accounts',
        check_company=True,
        help="Restrict to these GL accounts. Leave empty to use the Margin "
             "Component filter instead.",
    )
    source_component_id = fields.Many2one(
        'gec.margin.component',
        string='Source Component',
        domain="[('allocatable', '=', True)]",
        help="Allocate only cost sitting on accounts of this margin component "
             "(e.g. Personnel for level 2, Overhead for level 3). Ignored when "
             "Source GL Accounts is set.",
    )

    target_plan_id = fields.Many2one(
        'account.analytic.plan',
        string='Target Plan',
        required=True,
        domain="[('parent_id', '=', False)]",
        help="The plan the cost is allocated onto — typically Business Line.",
    )
    target_account_ids = fields.Many2many(
        'account.analytic.account',
        'gec_alloc_rule_target_account_rel', 'rule_id', 'account_id',
        string='Target Accounts',
        domain="[('plan_id', 'child_of', target_plan_id)]",
        check_company=True,
        help="Candidate targets. Leave empty to spread across every account of "
             "the target plan — that is what makes the rule survive new "
             "business lines without being edited.",
    )
    step = fields.Integer(
        string='Step', default=1, required=True,
        help="Order in the cascade. All step 1 rules run and their lines are "
             "written, then step 2 runs — so a step 2 pool includes what step 1 "
             "delivered.\n\n"
             "Leave everything at 1 unless one cost centre serves another. IT "
             "supporting Development is step 1; Development serving products is "
             "step 2, and Development's pool is then its own cost plus IT's "
             "share of it.\n\n"
             "This is the step-down method. It is the reason a service "
             "department's cost is not understated.",
    )
    only_untagged = fields.Boolean(
        string='Only Untagged Cost',
        default=True,
        help="Allocate only cost that carries no account on the target plan yet. "
             "Keep this on: cost already tagged directly to a business line "
             "must not be reallocated.",
    )

    driver = fields.Selection(
        DRIVER_SELECTION, required=True, default='revenue_share',
        help="How the allocation percentages are derived.\n"
             "Revenue / direct cost share: computed from the period's actuals, "
             "so they follow the business without maintenance.\n"
             "Headcount share: from the Headcount field on the target accounts.\n"
             "Equal split: identical percentage per target.\n"
             "Manual: the percentages entered below.",
    )
    line_ids = fields.One2many(
        'gec.allocation.rule.line', 'rule_id',
        string='Manual Percentages',
    )

    @api.constrains('source_plan_id', 'target_plan_id')
    def _check_plans_differ(self):
        for rule in self:
            if rule.source_plan_id == rule.target_plan_id:
                raise ValidationError(_(
                    "Rule %(name)s: source and target plan must differ. "
                    "Allocating a plan onto itself would double-count the cost.",
                    name=rule.name,
                ))

    @api.constrains('driver', 'line_ids')
    def _check_manual_lines(self):
        for rule in self:
            if rule.driver != 'manual':
                continue
            if not rule.line_ids:
                raise ValidationError(_(
                    "Rule %(name)s uses manual percentages but has none.",
                    name=rule.name,
                ))
            total = sum(rule.line_ids.mapped('percentage'))
            if abs(total - 100.0) > 0.01:
                raise ValidationError(_(
                    "Rule %(name)s: manual percentages add up to %(total).2f%%, "
                    "they must add up to 100%%.",
                    name=rule.name, total=total,
                ))

    def _get_target_accounts(self):
        """Targets of the allocation: the explicit list, or the whole plan."""
        self.ensure_one()
        if self.target_account_ids:
            return self.target_account_ids
        Account = self.env['account.analytic.account']
        return Account.search([
            ('plan_id', 'child_of', self.target_plan_id.id), *Account._check_company_domain(self.company_id),
        ])

    gec_source_warning = fields.Char(compute='_compute_gec_source_warning')

    @api.depends('source_gl_account_ids', 'source_component_id', 'company_id')
    def _compute_gec_source_warning(self):
        """Say which chosen accounts cannot be allocated: a non-allocatable component is skipped in the pool."""
        for rule in self:
            warning = False
            accounts = rule.source_gl_account_ids
            if accounts:
                blocked = accounts.filtered(
                    lambda a: a.gec_margin_component_effective_id
                    and not a.gec_margin_component_effective_id.allocatable
                )
                if blocked:
                    warning = _(
                        "%(codes)s cannot be allocated — %(component)s is not marked "
                        "allocatable. Either pick different accounts, or tick "
                        "Allocatable on that component.",
                        codes=", ".join(blocked.mapped('code')[:5]),
                        component=blocked[0].gec_margin_component_id.name,
                    )
                elif not accounts.filtered('gec_margin_component_effective_id'):
                    warning = _(
                        "None of these accounts has a margin component yet. Apply the "
                        "classification rules, or the pool will be empty."
                    )
            elif rule.source_component_id and not rule.source_component_id.allocatable:
                warning = _(
                    "%(component)s is not marked allocatable, so this rule will find "
                    "nothing to spread.",
                    component=rule.source_component_id.name,
                )
            rule.gec_source_warning = warning

    def _get_source_gl_accounts(self):
        """GL accounts whose cost this rule allocates."""
        self.ensure_one()
        if self.source_gl_account_ids:
            return self.source_gl_account_ids
        if not self.source_component_id:
            return self.env['account.account']
        return self.env['account.account'].search(Domain.AND([
            self.env['account.account']._gec_component_domain_by_id(
                self.source_component_id.id
            ),
            [('company_ids', 'in', self.company_id.ids)],
        ]))

    def _get_source_domain(self, date_from, date_to):
        """Domain on account.analytic.line selecting the cost to allocate."""
        self.ensure_one()
        source_col = self.source_plan_id._column_name()
        target_col = self.target_plan_id._column_name()

        domain = [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('company_id', '=', self.company_id.id),
            # Original cost plus what an earlier cascade step delivered here; this or a later step's output is double.
            '|',
            ('gec_is_allocation', '=', False),
            ('gec_allocation_step', '<', self.step),
        ]
        if self.source_account_ids:
            domain.append((source_col, 'in', self.source_account_ids.ids))
        else:
            domain.append((source_col, '!=', False))
        if self.only_untagged:
            domain.append((target_col, '=', False))

        gl_accounts = self._get_source_gl_accounts()
        if gl_accounts:
            domain.append(('general_account_id', 'in', gl_accounts.ids))
        elif self.source_component_id:
            domain.append(('id', '=', False))

        return domain

    @api.model
    def _uncovered_pool(self, date_from, date_to, companies=None):
        """Allocatable cost no rule reaches, for the statement warning and the setup health check.
        Only allocatable components on a plan some rule draws from count.
        Returns ``(total, {analytic_account: amount})``; empty with no rules."""
        companies = companies or self.env.companies
        rules = self.search([('company_id', 'in', companies.ids)])
        # Effective, not explicit: an account classified only by a rule would never be reported.
        allocatable = self.env['gec.margin.component'].search([('allocatable', '=', True)])
        accounts = self.env['account.account'].search([
            ('gec_margin_component_effective_id', 'in', allocatable.ids),
        ]) if allocatable else self.env['account.account']
        if not rules or not accounts:
            return 0.0, {}

        uncovered = Domain([
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('company_id', 'in', companies.ids),
            ('gec_is_allocation', '=', False),
            ('general_account_id', 'in', accounts.ids),
        ]) & Domain.OR([
            Domain(plan._column_name(), '!=', False)
            for plan in rules.mapped('source_plan_id')
        ]) & ~Domain.OR([
            Domain(rule._get_source_domain(date_from, date_to)) for rule in rules
        ])

        Line = self.env['account.analytic.line']
        groups = Line._read_group(uncovered, [], ['amount:sum'])
        total = (groups[0][0] if groups else 0.0) or 0.0
        if companies.currency_id[:1].is_zero(total):
            return 0.0, {}

        # One grouping per source plan: an amount can be tagged on several plans at once.
        by_account = {}
        for plan in rules.mapped('source_plan_id'):
            column = plan._column_name()
            for account, amount in Line._read_group(
                uncovered & Domain(column, '!=', False), [column], ['amount:sum'],
            ):
                if account and amount:
                    by_account[account] = by_account.get(account, 0.0) + amount
        return total, by_account

    def _compute_weights(self, date_from, date_to):
        """Return ``{analytic_account_id: weight}`` summing to 1, recomputed from the period's own data on each run."""
        self.ensure_one()
        targets = self._get_target_accounts()
        if not targets:
            return {}

        if self.driver == 'manual':
            raw = {
                line.account_id.id: line.percentage
                for line in self.line_ids
                if line.account_id in targets
            }
        elif self.driver == 'equal':
            raw = {account.id: 1.0 for account in targets}
        elif self.driver == 'headcount_share':
            raw = {
                account.id: float(account.gec_headcount)
                for account in targets
                if account.gec_headcount > 0
            }
        else:
            component = ('revenue' if self.driver == 'revenue_share'
                         else 'direct_cost')
            raw = self._compute_actual_weights(component, date_from, date_to, targets)

        total = sum(raw.values())
        if not total:
            return {}
        return {account_id: value / total for account_id, value in raw.items() if value}

    def _compute_actual_weights(self, component, date_from, date_to, targets):
        """Allocation base read from the period's posted analytic lines."""
        self.ensure_one()
        target_col = self.target_plan_id._column_name()
        gl_accounts = self.env['account.account'].search(Domain.AND([
            self.env['account.account']._gec_component_domain(component),
            [('company_ids', 'in', self.company_id.ids)],
        ]))
        if not gl_accounts:
            return {}

        groups = self.env['account.analytic.line']._read_group(
            domain=[
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('company_id', '=', self.company_id.id),
                ('gec_is_allocation', '=', False),
                ('general_account_id', 'in', gl_accounts.ids),
                (target_col, 'in', targets.ids),
            ],
            groupby=[target_col],
            aggregates=['amount:sum'],
        )
        # Revenue is positive and cost negative on analytic lines; a share must be a positive magnitude.
        return {
            account.id: abs(amount)
            for account, amount in groups
            if account and amount
        }


class GecAllocationRuleLine(models.Model):
    _name = 'gec.allocation.rule.line'
    _description = 'Analytic Cost Allocation Rule Percentage'
    _order = 'rule_id, id'
    _check_company_auto = True

    rule_id = fields.Many2one(
        'gec.allocation.rule', required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(related='rule_id.company_id', store=True)
    account_id = fields.Many2one(
        'account.analytic.account',
        string='Target Account',
        required=True,
        domain="[('plan_id', 'child_of', parent.target_plan_id)]",
        check_company=True,
    )
    percentage = fields.Float(string='Percentage', required=True, default=0.0)
