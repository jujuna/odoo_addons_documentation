from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProjectProject(models.Model):
    """Block two projects sharing one analytic account: the report resolves a project by account (lowest id),
    so attribution would be arbitrary.
    A constraint, not a UNIQUE index: it would fail on existing duplicates."""
    _inherit = 'project.project'

    # Kept on the analytic account, where the report reads it; shown here because it is a project decision.
    gec_function_component_id = fields.Many2one(
        related='account_id.gec_function_component_id', readonly=False,
        string='P&L Function',
        help="For a company reporting its P&L by function. Set R&D on an "
             "internal product project — the core platform, a new module, a "
             "regulatory update every customer gets — and every hour and bill "
             "charged to it is read as R&D, whichever activity or cost centre "
             "it came through. Leave empty on customer projects: their cost is "
             "Cost of Sales through the activity or the cost centre.",
    )

    # Forecast = contract value - actual cost - estimate to complete; estimate = remaining hours x hourly cost + other.
    # Overhead to come: allocated cost beyond priced hours, as a share of invoiced revenue, times revenue to invoice.
    FORECAST_EROSION = 0.05

    gec_contract_value = fields.Monetary(
        string='Contract Value',
        help="What the customer will pay for the whole project. Leave empty to "
             "use the project's revenue budget.",
    )
    gec_remaining_other_cost = fields.Monetary(
        string='Remaining Other Cost',
        help="Cost still to come that is not hours — subcontractors, licences, "
             "travel. Hours are forecast separately from Allocated Time.",
    )
    gec_hourly_cost = fields.Monetary(
        string='Hourly Cost Override',
        help="Cost of one remaining hour. Leave empty to use the latest rate of "
             "the hours activity that charged this project.",
    )
    gec_contract_value_effective = fields.Monetary(compute='_compute_gec_forecast', string='Contract Value (used)')
    gec_actual_revenue = fields.Monetary(compute='_compute_gec_forecast', string='Revenue to Date')
    gec_actual_cost = fields.Monetary(compute='_compute_gec_forecast', string='Cost to Date')
    gec_remaining_hours = fields.Float(compute='_compute_gec_forecast', string='Hours to Go')
    gec_cost_rate = fields.Monetary(compute='_compute_gec_forecast', string='Hourly Cost (used)')
    gec_remaining_overhead = fields.Monetary(
        compute='_compute_gec_forecast', string='Overhead to Come',
        help="Backlog × (overhead allocated so far ÷ revenue invoiced so far). "
             "Overhead here is every allocated cost except the hour-based staff "
             "cost, which the hourly cost already covers.",
    )
    gec_estimate_to_complete = fields.Monetary(compute='_compute_gec_forecast', string='Estimate to Complete')
    gec_forecast_cost = fields.Monetary(compute='_compute_gec_forecast', string='Forecast Cost')
    gec_forecast_margin = fields.Monetary(compute='_compute_gec_forecast', string='Forecast Margin')
    gec_forecast_margin_pct = fields.Float(compute='_compute_gec_forecast', string='Forecast Margin %')
    gec_budget_margin_pct = fields.Float(compute='_compute_gec_forecast', string='Budgeted Margin %')
    # Percent complete is cost to cost (spent / forecast cost); it needs no timesheet rates or milestones.
    gec_backlog = fields.Monetary(
        compute='_compute_gec_forecast', string='Backlog',
        help="Contract value not yet invoiced: revenue still to come.",
    )
    gec_percent_complete = fields.Float(
        compute='_compute_gec_forecast', string='Percent Complete',
        help="Cost to date as a share of forecast cost (cost-to-cost method).",
    )
    gec_earned_revenue = fields.Monetary(
        compute='_compute_gec_forecast', string='Earned Revenue',
        help="Contract value times percent complete: what the work done so far is worth.",
    )
    gec_unbilled = fields.Monetary(
        compute='_compute_gec_forecast', string='Unbilled Work',
        help="Earned revenue less revenue invoiced. Positive: work done and not yet "
             "invoiced. Negative: invoiced ahead of the work.",
    )
    gec_collected = fields.Monetary(
        compute='_compute_gec_forecast', string='Cash Collected',
        help="The paid part of the invoices charged to this project.",
    )
    gec_cash_margin = fields.Monetary(
        compute='_compute_gec_forecast', string='Cash Margin',
        help="Cash collected less cost to date. Negative: the project is being "
             "financed by the company.",
    )
    gec_forecast_status = fields.Selection(
        [('none', 'No forecast'), ('on_track', 'On track'),
         ('eroding', 'Eroding'), ('loss', 'Loss')],
        compute='_compute_gec_forecast', string='Forecast Status',
        help="Loss: the project will cost more than it earns. Eroding: the "
             "forecast margin is more than five points below the budgeted one. "
             "No forecast: no contract value and no revenue budget.",
    )

    def _gec_project_accounts(self):
        return self.account_id

    def _gec_actuals(self, accounts):
        """Revenue, cost and budget per project account, project to date."""
        project_plan, _others = self.env['account.analytic.plan']._get_all_plans()
        today = fields.Date.context_today(self)
        Report = self.env['gec.margin.report'].sudo()
        actuals, budgets = {}, {}
        for account, revenue, expense in Report._read_group([
            ('plan_id', '=', project_plan.id),
            ('analytic_account_id', 'in', accounts.ids),
            ('line_type', '=', 'actual'),
            ('date', '<=', today),
        ], ['analytic_account_id'], ['revenue_amount:sum', 'expense_amount:sum']):
            actuals[account.id] = (revenue or 0.0, -(expense or 0.0))
        # Budgets cover the whole project, including months still to come.
        for account, revenue, expense in Report._read_group([
            ('plan_id', '=', project_plan.id),
            ('analytic_account_id', 'in', accounts.ids),
            ('line_type', '=', 'budget'),
        ], ['analytic_account_id'], ['revenue_amount:sum', 'expense_amount:sum']):
            budgets[account.id] = (revenue or 0.0, -(expense or 0.0))
        return actuals, budgets

    def _gec_hour_rates(self, accounts):
        """Latest rate of the hours activity that charged each account most; hours activities sum timesheet hours."""
        project_plan, _others = self.env['account.analytic.plan']._get_all_plans()
        column = project_plan._column_name()
        charged = self.env['account.analytic.line'].sudo()._read_group([
            ('gec_allocation_kind', '=', 'target'),
            (column, 'in', accounts.ids),
            ('gec_activity_id.source_model_name', '=', 'account.analytic.line'),
            ('gec_activity_id.measure_field', '=', 'unit_amount'),
        ], [column, 'gec_activity_id'], ['amount:sum'])
        main = {}
        for account, activity, amount in charged:
            if account.id not in main or amount < main[account.id][1]:
                main[account.id] = (activity, amount)
        Rate = self.env['gec.activity.rate'].sudo()
        return {
            account_id: Rate.search([('activity_id', '=', activity.id)],
                                    order='date_to desc, id desc', limit=1).rate
            for account_id, (activity, _amount) in main.items()
        }

    def _gec_overhead_by_account(self, accounts):
        """Allocated cost not covered by the hourly cost: hours activities are priced by it, the rest is overhead."""
        project_plan, _others = self.env['account.analytic.plan']._get_all_plans()
        column = project_plan._column_name()
        lines = self.env['account.analytic.line'].sudo()._read_group([
            (column, 'in', accounts.ids),
            ('gec_allocation_kind', '=', 'target'),
        ], [column, 'gec_activity_id'], ['amount:sum'])
        overhead = {}
        for account, activity, amount in lines:
            hourly = activity and activity.source_model_name == 'account.analytic.line' \
                and activity.measure_field == 'unit_amount'
            if not hourly:
                overhead[account.id] = overhead.get(account.id, 0.0) - (amount or 0.0)
        return overhead

    def _gec_collected_by_account(self, accounts):
        """Paid share of customer invoices charged to each account; a split invoice counts the settled part per item."""
        project_plan, _others = self.env['account.analytic.plan']._get_all_plans()
        column = project_plan._column_name()
        lines = self.env['account.analytic.line'].sudo().search([
            (column, 'in', accounts.ids),
            ('move_line_id.move_id.move_type', 'in', ('out_invoice', 'out_refund')),
            ('move_line_id.move_id.state', '=', 'posted'),
        ])
        collected = {}
        for line in lines:
            move = line.move_line_id.move_id
            total = abs(move.amount_total)
            # A payment not yet matched with the bank ("In Payment") has no entry in Odoo 20,
            # so the residual does not move: count it from the payment.
            reconciled = total - abs(move.amount_residual)
            registered = sum(
                abs(payment.amount_company_currency_signed)
                for payment in move.matched_payment_ids
                if not payment.move_id and payment.state not in ('draft', 'canceled', 'rejected')
            )
            paid = min(reconciled + registered, total) / total if total else 0.0
            key = line[column].id
            amount = line.amount * paid
            target = self.env.context.get('gec_reporting_currency_id')
            if target and line.currency_id and line.currency_id.id != target:
                amount = line.currency_id._convert(amount, self.env['res.currency'].browse(target),
                                                   self.env.company, line.date)
            collected[key] = collected.get(key, 0.0) + amount
        return collected

    @api.depends_context('gec_reporting_currency_id')
    @api.depends('account_id', 'gec_contract_value', 'gec_remaining_other_cost',
                 'gec_hourly_cost', 'allocated_hours')
    def _compute_gec_forecast(self):
        accounts = self._gec_project_accounts()
        actuals, budgets = self._gec_actuals(accounts) if accounts else ({}, {})
        rates = self._gec_hour_rates(accounts) if accounts else {}
        collected = self._gec_collected_by_account(accounts) if accounts else {}
        overhead = self._gec_overhead_by_account(accounts) if accounts else {}
        for project in self:
            account = project.account_id.id
            revenue, cost = actuals.get(account, (0.0, 0.0))
            budget_revenue, budget_cost = budgets.get(account, (0.0, 0.0))
            contract = project.gec_contract_value or budget_revenue
            remaining = max((project.allocated_hours or 0.0) - (project.effective_hours or 0.0), 0.0)
            rate = project.gec_hourly_cost or rates.get(account, 0.0)
            backlog = max(contract - revenue, 0.0) if contract else 0.0
            overhead_ratio = overhead.get(account, 0.0) / revenue if revenue > 0 else 0.0
            overhead_to_come = backlog * overhead_ratio
            to_complete = remaining * rate + (project.gec_remaining_other_cost or 0.0) + overhead_to_come
            forecast_cost = cost + to_complete
            margin = contract - forecast_cost
            margin_pct = margin / contract if contract else 0.0
            budget_pct = (budget_revenue - budget_cost) / budget_revenue if budget_revenue else 0.0

            if not contract:
                status = 'none'
            elif margin < 0:
                status = 'loss'
            elif budget_revenue and margin_pct < budget_pct - self.FORECAST_EROSION:
                status = 'eroding'
            else:
                status = 'on_track'

            project.gec_contract_value_effective = contract
            project.gec_actual_revenue = revenue
            project.gec_actual_cost = cost
            project.gec_remaining_hours = remaining
            project.gec_cost_rate = rate
            project.gec_estimate_to_complete = to_complete
            project.gec_forecast_cost = forecast_cost
            project.gec_forecast_margin = margin
            project.gec_forecast_margin_pct = margin_pct
            project.gec_budget_margin_pct = budget_pct
            project.gec_forecast_status = status
            complete = min(cost / forecast_cost, 1.0) if forecast_cost > 0 else 0.0
            earned = contract * complete
            project.gec_backlog = backlog
            project.gec_remaining_overhead = overhead_to_come
            project.gec_percent_complete = complete
            project.gec_earned_revenue = earned
            project.gec_unbilled = earned - revenue if contract else 0.0
            project.gec_collected = collected.get(account, 0.0)
            project.gec_cash_margin = collected.get(account, 0.0) - cost

    @api.constrains('account_id')
    def _check_gec_analytic_account_not_shared(self):
        for project in self.filtered('account_id'):
            other = self.search([
                ('account_id', '=', project.account_id.id),
                ('id', '!=', project.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "Analytic account %(account)s is already used by project "
                    "%(other)s.\n\n"
                    "Two projects on one analytic account cannot be told apart "
                    "by any analytic report: the cost and revenue are tagged "
                    "with the account, not with the project, so the Analytic "
                    "Margin Statement would attribute all of it to one of them. "
                    "Give this project its own analytic account.",
                    account=project.account_id.display_name,
                    other=other.display_name,
                ))
