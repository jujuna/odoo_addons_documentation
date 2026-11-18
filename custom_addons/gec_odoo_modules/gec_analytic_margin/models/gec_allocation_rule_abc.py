from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class GecAllocationRule(models.Model):
    """Activity-Based Costing as a driver on the allocation engine; only the weights differ.
    Stage 1: ``resource_share`` is the activity's slice of the pool;
    stage 2: measured driver quantities spread it over cost objects."""
    _inherit = 'gec.allocation.rule'

    driver = fields.Selection(
        selection_add=[('activity', 'Activity (ABC)')],
        ondelete={'activity': 'set default'},
    )
    activity_id = fields.Many2one(
        'gec.activity',
        string='Activity',
        check_company=True,
        help="The activity whose measured quantities drive this allocation.",
    )
    share_mode = fields.Selection(
        [('declared', 'Declared — typed below'),
         ('measured', 'Measured — from timesheets tagged with the activity')],
        string='Stage 1 Basis', default='declared', required=True,
        help="Where the share of the pool comes from.\n\n"
             "Declared: you work it out and type it. Simple, but it goes stale.\n\n"
             "Measured: read from analytic lines on the source that carry an "
             "Activity. Of all tagged hours on this cost centre, the proportion "
             "belonging to this activity becomes its share — recomputed every "
             "run. This is what makes stage one activity-based rather than an "
             "estimate.\n\n"
             "Measured falls back to the declared value for any period where "
             "nothing is tagged, and the run log says which was used.",
    )
    resource_share = fields.Float(
        string='Share of Pool (%)',
        default=100.0,
        help="How much of the selected cost belongs to this activity — ABC's "
             "first stage.\n\n"
             "Create one rule per activity over the same pool and give each its "
             "share: Development 70%, Support 30%. Shares below 100% in total "
             "leave the remainder on the source rather than charging it out.\n\n"
             "Used directly when Stage 1 Basis is Declared, and as the fallback "
             "when Measured finds nothing tagged.",
    )
    activity_driver_label = fields.Char(related='activity_id.driver_label', readonly=True)
    activity_capacity = fields.Float(related='activity_id.practical_capacity', readonly=True)

    @api.constrains('driver', 'activity_id')
    def _check_activity(self):
        for rule in self:
            if rule.driver == 'activity' and not rule.activity_id:
                raise ValidationError(_(
                    "Rule %(name)s uses the Activity driver but names no "
                    "activity.", name=rule.name,
                ))

    @api.constrains('resource_share')
    def _check_resource_share(self):
        for rule in self:
            if not 0 < rule.resource_share <= 100:
                raise ValidationError(_(
                    "Rule %(name)s: share of pool must be above 0 and at most "
                    "100%%, not %(share).2f%%.",
                    name=rule.name, share=rule.resource_share,
                ))

    def _pool_signature(self):
        """Identify the cost pool a rule draws from; rules with the same signature share one pool,
        so their shares must not exceed 100%."""
        self.ensure_one()
        return (
            self.company_id.id,
            self.source_plan_id.id,
            self.source_component_id.id,
            tuple(sorted(self.source_account_ids.ids)),
            tuple(sorted(self.source_gl_account_ids.ids)),
        )

    def _measured_resource_share(self, date_from, date_to):
        """Share of the pool measured from timesheets tagged with an activity;
        ``None`` when nothing is tagged, so the caller uses the declared value."""
        self.ensure_one()
        source_col = self.source_plan_id._column_name()
        domain = [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('company_id', '=', self.company_id.id),
            ('gec_is_allocation', '=', False),
            ('gec_activity_id', '!=', False),
        ]
        if self.source_account_ids:
            domain.append((source_col, 'in', self.source_account_ids.ids))
        else:
            domain.append((source_col, '!=', False))

        # Quantity, not amount: hours count whether or not payroll is posted, and timesheets are often valued at zero.
        groups = self.env['account.analytic.line']._read_group(
            domain=domain,
            groupby=['gec_activity_id'],
            aggregates=['unit_amount:sum'],
        )
        per_activity = {activity: qty for activity, qty in groups if qty}
        total = sum(per_activity.values())
        if not total:
            return None
        return 100.0 * per_activity.get(self.activity_id, 0.0) / total

    def _get_resource_share(self, date_from, date_to):
        """The share to apply, and a note for the run log."""
        self.ensure_one()
        declared = self.resource_share or 100.0
        # A rule with no activity cannot measure its share: it uses the declared figure, not zero.
        if self.share_mode != 'measured' or not self.activity_id:
            return declared, ""
        measured = self._measured_resource_share(date_from, date_to)
        if measured is None:
            return declared, _(
                " · stage 1 declared %(declared)s%% (nothing tagged with an "
                "activity in this period)", declared=f"{declared:.1f}",
            )
        return measured, _(
            " · stage 1 measured %(measured)s%% from tagged hours",
            measured=f"{measured:.1f}",
        )

    def _compute_weights(self, date_from, date_to):
        """Weights for this rule, scaled by its share of the pool, so they may sum to less than 1;
        the unallocated remainder stays on the source."""
        self.ensure_one()
        weights = (
            self._compute_activity_weights(date_from, date_to)
            if self.driver == 'activity'
            else super()._compute_weights(date_from, date_to)
        )
        share_percent, _note = self._get_resource_share(date_from, date_to)
        share = share_percent / 100.0
        if share == 1.0:
            return weights
        return {account_id: value * share for account_id, value in weights.items()}

    def _get_activity_quantities(self, date_from, date_to):
        """Measured quantities, restricted to this rule's targets."""
        self.ensure_one()
        targets = set(self._get_target_accounts().ids)
        return {
            account_id: quantity
            for account_id, quantity in self.activity_id.get_quantities(
                date_from, date_to
            ).items()
            if account_id in targets and quantity > 0
        }

    def _compute_activity_weights(self, date_from, date_to):
        """Stage 2: quantities -> weights on the pool.
        Actual: quantity shares (sum 1, or consumed fraction of practical capacity).
        Standard: ``rate x quantity`` per target as a fraction of the pool (may exceed 1); rest stays as variance."""
        self.ensure_one()
        quantities = self._get_activity_quantities(date_from, date_to)
        total = sum(quantities.values())
        if not total:
            return {}

        activity = self.activity_id

        if activity.rate_mode == 'standard':
            # Standard charge is rate x quantity, as a fraction of the pool so the engine ignores the mode.
            pool = self._get_pool_amount(date_from, date_to)
            if not pool:
                return {}
            return {
                account_id: (activity.standard_rate * quantity) / abs(pool)
                for account_id, quantity in quantities.items()
            }

        # Actual: proportional share, capped at practical capacity so idle cost stays on the source;
        # above capacity is overtime, so cap at 1.
        capacity = activity.practical_capacity
        consumed = min(total / capacity, 1.0) if capacity > 0 else 1.0
        return {
            account_id: (quantity / total) * consumed
            for account_id, quantity in quantities.items()
        }

    def _get_pool_amount(self, date_from, date_to):
        """Total source cost this rule would draw on in the period."""
        self.ensure_one()
        groups = self.env['account.analytic.line']._read_group(
            domain=self._get_source_domain(date_from, date_to),
            groupby=[],
            aggregates=['amount:sum'],
        )
        return groups[0][0] if groups else 0.0
