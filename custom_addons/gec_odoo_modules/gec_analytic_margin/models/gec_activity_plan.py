from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class GecActivityPlan(models.Model):
    """Expected driver units a cost object consumes in a period, to compare with actual consumption.

    Actuals are measured from the activity that drives the allocation, never stored here."""
    _name = 'gec.activity.plan'
    _description = 'Planned Driver Consumption'
    _order = 'date_from desc, activity_id, analytic_account_id'
    _check_company_auto = True

    activity_id = fields.Many2one(
        'gec.activity', required=True, ondelete='cascade', index=True,
        check_company=True,
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Cost Object', required=True,
        ondelete='cascade', index=True,
        help="The project, product, customer or business line expected to "
             "consume the units.",
    )
    company_id = fields.Many2one(
        related='activity_id.company_id', store=True, index=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    driver_label = fields.Char(related='activity_id.driver_label', string='Unit')
    rate_mode = fields.Selection(related='activity_id.rate_mode')

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)

    planned_quantity = fields.Float(
        string='Planned', required=True,
        help="Units this cost object is expected to consume — the hours a "
             "project was sold with, the tickets a contract allows for.",
    )

    actual_quantity = fields.Float(
        string='Actual', compute='_compute_actual',
        help="Units actually measured for this cost object in this period, by "
             "the same activity that drives the allocation.",
    )
    variance_quantity = fields.Float(
        string='Variance', compute='_compute_actual',
        search='_search_variance_quantity',
        help="Actual less planned. Positive means the cost object consumed "
             "more of the activity than it was supposed to.",
    )
    variance_percent = fields.Float(
        string='Variance %', compute='_compute_actual',
        help="Variance as a share of the plan. Blank when nothing was planned, "
             "because there is nothing to be a percentage of.",
    )
    rate = fields.Float(
        string='Rate', compute='_compute_actual', digits=(16, 4),
        help="Cost of one unit used to value the variance: the standard rate "
             "when there is one, otherwise the rate the last run recorded for "
             "an overlapping period.",
    )
    variance_amount = fields.Monetary(
        string='Variance Value', compute='_compute_actual',
        search='_search_variance_amount',
        help="The variance in money. This is the number to argue about: "
             "57 hours over plan at 23.76 is 1,354 nobody sold.",
    )
    has_rate = fields.Boolean(compute='_compute_actual')

    @api.depends('activity_id', 'analytic_account_id', 'date_from', 'date_to',
                 'planned_quantity')
    def _compute_actual(self):
        # One measurement per (activity, period), not per row, so timesheets are counted once.
        measured = {}
        rates = {}
        for plan in self:
            key = (plan.activity_id.id, plan.date_from, plan.date_to)
            if key not in measured:
                measured[key] = (
                    plan.activity_id.get_quantities(plan.date_from, plan.date_to)
                    if plan.activity_id and plan.date_from and plan.date_to
                    else {}
                )
                rates[key] = plan._applicable_rate()

            actual = measured[key].get(plan.analytic_account_id.id, 0.0)
            variance = actual - plan.planned_quantity
            plan.actual_quantity = actual
            plan.variance_quantity = variance
            plan.variance_percent = (
                variance / plan.planned_quantity if plan.planned_quantity else 0.0
            )
            plan.rate = rates[key]
            plan.has_rate = bool(rates[key])
            plan.variance_amount = variance * rates[key]

    # Actuals are measured, so there is no column to filter on; "over plan" is compared in Python.
    OPERATORS = {
        '=': lambda left, right: left == right,
        '!=': lambda left, right: left != right,
        '<': lambda left, right: left < right,
        '<=': lambda left, right: left <= right,
        '>': lambda left, right: left > right,
        '>=': lambda left, right: left >= right,
    }

    @api.model
    def _search_computed(self, field, operator, value):
        compare = self.OPERATORS.get(operator)
        if compare is None:
            raise NotImplementedError(_(
                "Planned consumption cannot be filtered with '%s'.", operator,
            ))
        # No domain on a computed field here, so this cannot re-enter itself.
        plans = self.search([])
        return [('id', 'in', [
            plan.id for plan in plans if compare(plan[field], value)
        ])]

    def _search_variance_quantity(self, operator, value):
        return self._search_computed('variance_quantity', operator, value)

    def _search_variance_amount(self, operator, value):
        return self._search_computed('variance_amount', operator, value)

    def _applicable_rate(self):
        """Unit cost for the variance: the standard rate, else the rate of an overlapping run, else none."""
        self.ensure_one()
        activity = self.activity_id
        if activity.rate_mode == 'standard' and activity.standard_rate:
            return activity.standard_rate
        recorded = self.env['gec.activity.rate'].search([
            ('activity_id', '=', activity.id),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ], order='date_from desc', limit=1)
        return recorded.rate

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for plan in self:
            if plan.date_to < plan.date_from:
                raise ValidationError(_("The end date cannot precede the start date."))

    _period_uniq = models.Constraint(
        'UNIQUE(activity_id, analytic_account_id, date_from, date_to)',
        "This cost object already has a plan for this activity and period.",
    )

    @api.depends('activity_id', 'analytic_account_id', 'date_from')
    def _compute_display_name(self):
        for plan in self:
            plan.display_name = _(
                "%(activity)s · %(account)s · %(period)s",
                activity=plan.activity_id.name or '',
                account=plan.analytic_account_id.display_name or '',
                period=plan.date_from or '',
            )

    def action_open_activity(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'gec.activity',
            'res_id': self.activity_id.id,
            'view_mode': 'form',
        }
