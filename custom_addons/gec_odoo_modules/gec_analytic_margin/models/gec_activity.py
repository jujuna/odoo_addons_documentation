from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools.safe_eval import safe_eval


class GecActivity(models.Model):
    """Something the company does that consumes resources, with a driver quantity per cost object.

    Quantities are read from live Odoo records, not typed in."""
    _name = 'gec.activity'
    _description = 'Costing Activity'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True, help="e.g. Deployment, Support, Onboarding")
    code = fields.Char(help="Short code, used in the allocation run log.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    driver_label = fields.Char(
        string='Driver Unit', required=True, default='unit',
        help="What one unit of this activity is — 'deployment', 'ticket', "
             "'hour'. Used when reporting cost per unit in the run log.",
    )

    TEMPLATES = {
        'timesheet_project': {
            'label': "Timesheet hours per project",
            'model': 'account.analytic.line',
            'date': 'date',
            # Resolved at apply time: the project plan's column name differs between databases.
            'path': '@project_plan',
            'domain': "[('project_id', '!=', False)]",
            'measure': 'field',
            'measure_field': 'unit_amount',
            'driver_label': 'hour',
        },
        'task_done': {
            'label': "Completed tasks per project",
            'model': 'project.task',
            'date': 'date_last_stage_update',
            'path': 'project_id.account_id',
            'domain': "[('state', '=', '1_done')]",
            'measure': 'count',
            'driver_label': 'task',
        },
        'helpdesk_ticket': {
            'label': "Helpdesk tickets closed",
            'model': 'helpdesk.ticket',
            'date': 'close_date',
            'path': 'analytic_account_id',
            # Closed, not a named stage: stages are per team and renamed freely; close_date is set by the engine.
            'domain': "[('close_date', '!=', False)]",
            'measure': 'count',
            'driver_label': 'ticket',
        },
        'helpdesk_ticket_raised': {
            'label': "Helpdesk tickets raised",
            'model': 'helpdesk.ticket',
            'date': 'create_date',
            'path': 'analytic_account_id',
            'domain': "[]",
            'measure': 'count',
            'driver_label': 'ticket',
        },
        'delivery_project': {
            'label': "Outgoing deliveries per project",
            'model': 'stock.picking',
            'date': 'date_done',
            'path': 'project_id.account_id',
            'domain': "[('state', '=', 'done'),"
                      " ('picking_type_id.code', '=', 'outgoing')]",
            'measure': 'count',
            'driver_label': 'delivery',
        },
        # Counted through the ledger: a PO line has no analytic account, but the posted bill's analytic item does.
        # Refunds are left out so they do not inflate the driver; add 'in_refund' to the filter to count them.
        'bill_lines': {
            'label': "Vendor bill lines per cost object",
            'model': 'account.analytic.line',
            'date': 'date',
            'path': '@project_plan',
            'domain': "[('move_line_id.move_id.move_type', '=', 'in_invoice')]",
            'measure': 'count',
            'driver_label': 'bill line',
        },
        'invoice_lines': {
            'label': "Customer invoice lines per cost object",
            'model': 'account.analytic.line',
            'date': 'date',
            'path': '@project_plan',
            'domain': "[('move_line_id.move_id.move_type', '=', 'out_invoice')]",
            'measure': 'count',
            'driver_label': 'invoice line',
        },
        'sale_order': {
            'label': "Confirmed sales orders per project",
            'model': 'sale.order',
            'date': 'date_order',
            'path': 'project_account_id',
            'domain': "[('state', '=', 'sale')]",
            'measure': 'count',
            'driver_label': 'order',
        },
    }

    template_key = fields.Selection(
        selection='_selection_template_key',
        string='What It Measures',
        help="Fills in every technical field below for one of the usual ways of "
             "measuring an activity. Only shapes your database can actually "
             "produce are offered, and everything stays editable afterwards.",
    )

    @api.model
    def _selection_template_key(self):
        """Only templates whose model and analytic field are installed, so no activity measures nothing
        (sale.order's project_account_id comes with sale_project, not sale)."""
        return [
            (key, spec['label']) for key, spec in self.TEMPLATES.items()
            if spec['model'] in self.env
            and self._resolve_template_path(spec['path']).partition('.')[0] in self.env[spec['model']]._fields
        ]

    @api.onchange('template_key')
    def _onchange_template_key(self):
        if self.template_key:
            self.update(self._template_values(self.TEMPLATES[self.template_key]))

    @api.model
    def _template_values(self, spec):
        """A template as values, not separate writes: the fields are only valid together
        (measure 'Sum of a field' needs its field)."""
        Fields = self.env['ir.model.fields']
        model = spec['model']
        path = self._resolve_template_path(spec['path'])
        via, _dot, leaf = path.rpartition('.')
        via_field = Fields._get(model, via) if via else False
        leaf_model = via_field.relation if via_field else model

        return {
            'source_model_id': self.env['ir.model']._get_id(model),
            'source_model_name': model,
            'source_domain': spec['domain'],
            'measure': spec['measure'],
            'measure_field': spec.get('measure_field', False),
            'driver_label': spec['driver_label'],
            'source_date_field': spec['date'],
            'source_date_field_id': Fields._get(model, spec['date']).id or False,
            'source_analytic_path': path,
            'source_analytic_via_id': via_field.id if via_field else False,
            'source_analytic_field_id': Fields._get(leaf_model, leaf).id or False,
        }

    @api.model
    def _resolve_template_path(self, path):
        """Turn the ``@project_plan`` marker into this database's own column."""
        if path != '@project_plan':
            return path
        project_plan, _others = self.env['account.analytic.plan']._get_all_plans()
        return project_plan._column_name()

    source_model_id = fields.Many2one(
        'ir.model',
        string='Counted Records',
        required=True,
        ondelete='cascade',
        help="The model whose records mean this activity happened — "
             "project.task for tasks, account.analytic.line for timesheets, "
             "stock.picking for shipments, helpdesk.ticket for tickets.",
    )
    # readonly=False: the domain widget needs this value before the record is saved.
    source_model_name = fields.Char(
        related='source_model_id.model', store=True, readonly=False,
    )
    source_domain = fields.Char(
        string='Filter', default='[]',
        help="Odoo domain restricting which records count — usually a state "
             "filter such as [('state', '=', 'done')].",
    )
    source_date_field = fields.Char(
        string='Date Field', required=True, default='date',
        help="Field deciding whether a record falls inside the run's period: "
             "'date', 'date_done', 'create_date'.",
    )
    # Pickers over the two technical fields; the stored fields stay the source of truth (paths can exceed two hops).
    source_date_field_id = fields.Many2one(
        'ir.model.fields', string='Date Field',
        domain="[('model_id', '=', source_model_id), ('ttype', 'in', ['date', 'datetime'])]",
        ondelete='set null',
        help="Which date decides whether a record falls inside a run's period.",
    )
    source_analytic_via_id = fields.Many2one(
        'ir.model.fields', string='First Go Through',
        domain="[('model_id', '=', source_model_id), ('ttype', '=', 'many2one'),"
               " ('relation', '!=', 'account.analytic.account')]",
        ondelete='set null',
        help="Only when the counted record has no analytic account of its own. "
             "A helpdesk ticket has none, but its project does — so go through "
             "Project first.\n\nLeave empty otherwise.",
    )
    source_analytic_model = fields.Char(
        compute='_compute_source_analytic_model',
        help="The model the analytic account is read from, once the hop above "
             "has been taken. Drives the choices in the field below.",
    )
    source_analytic_field_id = fields.Many2one(
        'ir.model.fields', string='Analytic Field',
        domain="[('model', '=', source_analytic_model), ('ttype', '=', 'many2one'),"
               " ('relation', '=', 'account.analytic.account')]",
        ondelete='set null',
        help="The field holding the analytic account — the cost object this "
             "quantity belongs to.",
    )

    @api.depends('source_model_name', 'source_analytic_via_id')
    def _compute_source_analytic_model(self):
        for activity in self:
            activity.source_analytic_model = (
                activity.source_analytic_via_id.relation
                or activity.source_model_name
            )

    @api.onchange('source_model_id')
    def _onchange_source_model_clears_the_pickers(self):
        """Drop the pickers that no longer fit the chosen model, one by one, so a template's fresh values survive."""
        model = self.source_model_id
        if self.source_date_field_id.model_id != model:
            self.source_date_field_id = False
        if self.source_analytic_via_id.model_id != model:
            self.source_analytic_via_id = False
        leaf_model = (
            self.source_analytic_via_id.relation or self.source_model_name
        )
        if self.source_analytic_field_id.model != leaf_model:
            self.source_analytic_field_id = False
            self.source_analytic_path = False

    @api.onchange('source_date_field_id')
    def _onchange_source_date_field_id(self):
        if self.source_date_field_id:
            self.source_date_field = self.source_date_field_id.name

    @api.onchange('source_analytic_via_id', 'source_analytic_field_id')
    def _onchange_source_analytic_pickers(self):
        if self.source_analytic_via_id and not self.source_analytic_field_id:
            self.source_analytic_path = False
            return
        if not self.source_analytic_field_id:
            return
        self.source_analytic_path = '.'.join(filter(None, (
            self.source_analytic_via_id.name,
            self.source_analytic_field_id.name,
        )))

    source_analytic_path = fields.Char(
        string='Path to Analytic Account', required=True,
        help="Dotted path from the counted record to the analytic account of "
             "the cost object it belongs to.\n\n"
             "account.analytic.line  →  x_plan2_id      (a Business Line column)\n"
             "project.task           →  project_id.account_id",
    )
    measure = fields.Selection(
        [('count', 'Count of records'), ('field', 'Sum of a field')],
        default='count', required=True,
        help="Count records (one deployment = 1) or sum a numeric field "
             "(timesheet hours = sum of unit_amount).",
    )
    measure_field = fields.Char(
        string='Summed Field',
        help="Numeric field to sum when the measure is 'Sum of a field', "
             "e.g. unit_amount for timesheet hours.",
    )
    match_own_activity = fields.Boolean(
        string='Only Records Tagged With This Activity',
        help="Count only records that carry this activity in their Activity "
             "field.\n\n"
             "Tick this whenever several activities count the same kind of "
             "record. Two activities both counting timesheets would otherwise "
             "each measure *all* the hours, and every rule would get the same "
             "split — a mistake that produces plausible-looking numbers.\n\n"
             "Leave it off when the counted records carry no activity of their "
             "own, such as invoices or completed tasks.",
    )
    weight_by_employee_cost = fields.Boolean(
        string='Weight by Employee Cost',
        help="Multiply each record's quantity by the employee's hourly cost.\n\n"
             "Without this an hour from a junior and an hour from an architect "
             "count the same, so a product staffed by juniors is charged as much "
             "as one staffed by your most expensive people.\n\n"
             "The hourly cost is used purely as a weight. The money allocated is "
             "always the posted amount — valuing hours as cost as well would "
             "count labour twice.",
    )

    practical_capacity = fields.Float(
        string='Practical Capacity',
        help="Units this activity can deliver in a period at a normal working "
             "rhythm. Leave at 0 to charge the whole pool out.\n\n"
             "When set, only the consumed share of the pool is charged and the "
             "cost of unused capacity stays on the source. That is what "
             "separates time-driven ABC from ordinary allocation: a quiet month "
             "makes idle capacity visible instead of making every product look "
             "expensive.",
    )

    rate_mode = fields.Selection(
        [('actual', 'Actual — pool ÷ what was measured'),
         ('standard', 'Standard — a fixed rate per unit')],
        string='Rate Basis', default='actual', required=True,
        help="How much one unit of this activity costs.\n\n"
             "Actual: the pool divided by whatever was measured this period. "
             "Simple, but volatile — a quiet month makes every unit look "
             "expensive, and the rate is never comparable between periods.\n\n"
             "Standard: a rate you set once, normally at the start of the year "
             "from planned cost ÷ practical capacity. Each cost object is then "
             "charged rate × quantity consumed, and whatever the pool does not "
             "cover — or over-covers — stays on the source as a variance. This "
             "is how ABC is normally run in practice.",
    )
    standard_rate = fields.Float(
        string='Standard Rate',
        digits=(16, 4),
        help="Cost of one unit — one hour, one ticket, one deployment. Used when "
             "the rate basis is Standard.\n\n"
             "Usually planned annual cost ÷ practical capacity, e.g. "
             "480,000 ÷ 9,600 hours = 50 per hour.",
    )

    @api.constrains('rate_mode', 'standard_rate')
    def _check_standard_rate(self):
        for activity in self:
            if activity.rate_mode == 'standard' and activity.standard_rate <= 0:
                raise ValidationError(_(
                    "Activity %(name)s uses a standard rate but none is set.",
                    name=activity.name,
                ))

    # The activity decides the function of the cost it charges out; the cost centre decides the rest.
    gec_function_component_id = fields.Many2one(
        'gec.margin.component', string='Function',
        domain="[('is_function', '=', True)]", ondelete='restrict',
        help="In a company reporting by function, cost this activity charges to "
             "cost objects is read under this line — Cost of Sales for "
             "implementation hours, R&D for product development. Leave empty to "
             "keep the function of the cost centre the cost came from.",
    )
    value_added = fields.Selection(
        [('value_added', 'Value-added — the customer would pay for it'),
         ('business_required', 'Business-required — necessary, but not to the customer'),
         ('non_value_added', 'Non-value-added — waste')],
        string='Value', default='value_added', required=True,
        help="Costing tells you what an activity costs. This tells you whether "
             "it should exist.\n\n"
             "Value-added: the customer would knowingly pay for it — writing the "
             "software they bought.\n\n"
             "Business-required: it has to happen but no customer wants it — "
             "statutory audit, payroll.\n\n"
             "Non-value-added: rework, waiting, moving things about. Costing "
             "makes it measurable; grouping the report by this makes it "
             "arguable.",
    )

    setup_warning = fields.Char(
        compute='_compute_setup_warning',
        help="A misconfigured activity does not fail — it measures nothing, and "
             "an allocation built on it moves no money without saying so.",
    )

    @api.depends('source_model_id', 'source_domain', 'source_date_field',
                 'source_analytic_path', 'measure', 'measure_field')
    def _compute_setup_warning(self):
        """Catch the two silent failures (nothing matches, nothing resolves) with two cheap queries;
        a full count would make the list unusable."""
        for activity in self:
            activity.setup_warning = False
            if not (activity.source_model_id and activity.source_analytic_path):
                continue
            model = self.env.get(activity.source_model_name)
            if model is None:
                activity.setup_warning = _(
                    "%(model)s is not installed, so nothing can be counted.",
                    model=activity.source_model_name,
                )
                continue
            try:
                domain = safe_eval(activity.source_domain or '[]')
            except Exception:
                activity.setup_warning = _("The filter is not a valid domain.")
                continue
            if activity.source_date_field not in model._fields:
                activity.setup_warning = _(
                    "%(model)s has no field %(field)s, so no record can be "
                    "placed in a period.",
                    model=model._description, field=activity.source_date_field,
                )
                continue

            sample = model.sudo().search(domain, limit=1)
            if not sample:
                activity.setup_warning = _(
                    "No %(model)s matches this filter. The activity would "
                    "measure nothing and its allocation would move no money.",
                    model=model._description,
                )
                continue
            try:
                accounts = sample.mapped(activity.source_analytic_path)
            except Exception:
                activity.setup_warning = _(
                    "'%(path)s' is not a valid path on %(model)s.",
                    path=activity.source_analytic_path, model=model._description,
                )
                continue
            if accounts._name != 'account.analytic.account':
                activity.setup_warning = _(
                    "'%(path)s' leads to %(found)s, but it has to lead to an "
                    "analytic account — that is the cost object the quantity "
                    "belongs to.",
                    path=activity.source_analytic_path, found=accounts._name,
                )

    planned_quantity = fields.Float(
        string='Planned Quantity',
        help="How many driver units you expect next period — 9,600 hours, "
             "4,000 tickets.\n\n"
             "Costing asks what the past cost. Budgeting asks what the plan will "
             "cost: planned quantity × rate. That is activity-based budgeting, "
             "and it is the half of ABC that changes decisions rather than "
             "explaining them.",
    )
    planned_cost = fields.Monetary(
        string='Planned Cost', compute='_compute_planned_cost', store=True,
        currency_field='currency_id',
    )
    planned_capacity_gap = fields.Float(
        string='Capacity Gap', compute='_compute_planned_cost', store=True,
        help="Planned quantity less practical capacity. Positive means the plan "
             "needs more capacity than exists — hire, or say no to the work.",
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Currency')

    @api.depends('planned_quantity', 'standard_rate', 'rate_mode', 'practical_capacity')
    def _compute_planned_cost(self):
        for activity in self:
            activity.planned_cost = activity.planned_quantity * activity.standard_rate
            activity.planned_capacity_gap = (
                activity.planned_quantity - activity.practical_capacity
                if activity.practical_capacity else 0.0
            )

    plan_ids = fields.One2many(
        'gec.activity.plan', 'activity_id', string='Planned Consumption',
    )
    plan_count = fields.Integer(compute='_compute_plan_count')

    @api.depends('plan_ids')
    def _compute_plan_count(self):
        for activity in self:
            activity.plan_count = len(activity.plan_ids)

    def action_open_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Planned vs Actual"),
            'res_model': 'gec.activity.plan',
            'view_mode': 'list,pivot,graph,form',
            'domain': [('activity_id', '=', self.id)],
            'context': {'default_activity_id': self.id},
        }

    def action_plan_from_actuals(self):
        """Carry a measured period forward as next period's plan."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Plan from Actuals"),
            'res_model': 'gec.activity.plan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_activity_id': self.id},
        }

    rule_ids = fields.One2many('gec.allocation.rule', 'activity_id', string='Rules')
    rule_count = fields.Integer(compute='_compute_rule_count')

    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for activity in self:
            activity.rule_count = len(activity.rule_ids)

    @api.constrains('measure', 'measure_field')
    def _check_measure_field(self):
        for activity in self:
            if activity.measure == 'field' and not activity.measure_field:
                raise ValidationError(_(
                    "Activity %(name)s sums a field but no field is named.",
                    name=activity.name,
                ))

    @api.constrains('source_domain')
    def _check_domain(self):
        for activity in self:
            try:
                assert isinstance(safe_eval(activity.source_domain or '[]'), list)
            except Exception:
                raise ValidationError(_(
                    "Activity %(name)s: the filter is not a valid Odoo domain.",
                    name=activity.name,
                ))

    @api.constrains('source_model_id', 'source_date_field', 'measure',
                    'measure_field', 'weight_by_employee_cost')
    def _check_fields_exist(self):
        for activity in self:
            model = activity.env.get(activity.source_model_name)
            if model is None:
                continue
            required = [activity.source_date_field]
            if activity.measure == 'field':
                required.append(activity.measure_field)
            if activity.weight_by_employee_cost:
                required.append('employee_id')
            for fname in filter(None, required):
                if fname not in model._fields:
                    raise ValidationError(_(
                        "Activity %(name)s: %(model)s has no field '%(field)s'.",
                        name=activity.name, model=activity.source_model_name,
                        field=fname,
                    ))

    def _get_domain(self, date_from, date_to):
        self.ensure_one()
        domain = list(safe_eval(self.source_domain or '[]'))
        domain += [
            (self.source_date_field, '>=', date_from),
            (self.source_date_field, '<=', date_to),
        ]
        model = self.env[self.source_model_name]
        if 'company_id' in model._fields:
            domain.append(('company_id', 'in', [self.company_id.id, False]))
        if self.match_own_activity:
            if 'gec_activity_id' not in model._fields:
                raise UserError(_(
                    "Activity %(name)s is set to count only its own records, but "
                    "%(model)s has no Activity field.",
                    name=self.name, model=self.source_model_name,
                ))
            domain.append(('gec_activity_id', '=', self.id))
        return domain

    def _record_quantity(self, record):
        """Quantity contributed by one record, before splitting across accounts."""
        self.ensure_one()
        quantity = 1.0 if self.measure == 'count' else (record[self.measure_field] or 0.0)
        if self.weight_by_employee_cost:
            employee = record.employee_id
            quantity *= (employee.hourly_cost or 0.0) if employee else 0.0
        return quantity

    def get_quantities(self, date_from, date_to):
        """Return ``{analytic_account_id: quantity}`` measured live for the period."""
        self.ensure_one()
        model = self.env[self.source_model_name].sudo()
        records = model.search(self._get_domain(date_from, date_to))

        quantities = defaultdict(float)
        for record in records:
            try:
                accounts = record.mapped(self.source_analytic_path)
            except Exception:
                raise UserError(_(
                    "Activity %(name)s: '%(path)s' is not a valid path on %(model)s.",
                    name=self.name, path=self.source_analytic_path,
                    model=self.source_model_name,
                ))
            if not accounts:
                continue
            if accounts._name != 'account.analytic.account':
                raise UserError(_(
                    "Activity %(name)s: '%(path)s' leads to %(model)s, but it must "
                    "lead to an analytic account.",
                    name=self.name, path=self.source_analytic_path,
                    model=accounts._name,
                ))
            quantity = self._record_quantity(record)
            if not quantity:
                continue
            # A record touching several accounts splits evenly, so it is never counted twice.
            share = quantity / len(accounts)
            for account in accounts:
                quantities[account.id] += share
        return dict(quantities)

    def get_rate(self, pool_amount, date_from, date_to):
        """Cost per driver unit. Standard: the rate set.
        Actual: pool / practical capacity if set, else pool / measured quantity."""
        self.ensure_one()
        if self.rate_mode == 'standard':
            return self.standard_rate
        total = sum(self.get_quantities(date_from, date_to).values())
        divisor = self.practical_capacity or total
        return (abs(pool_amount) / divisor) if divisor else 0.0

    def action_preview_quantities(self):
        """Show what this activity measures year-to-date, so a wrong path or filter shows before money moves."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        start = today.replace(month=1, day=1)
        quantities = self.get_quantities(start, today)

        if not quantities:
            raise UserError(_(
                "%(name)s measured nothing between %(start)s and %(end)s.\n\n"
                "Check the filter, the date field, and the path to the analytic "
                "account.",
                name=self.name, start=start, end=today,
            ))

        accounts = self.env['account.analytic.account'].browse(list(quantities))
        total = sum(quantities.values())
        rows = "\n".join(
            f"  {account.display_name}: {quantities[account.id]:,.2f}"
            f"  ({quantities[account.id] / total:.1%})"
            for account in accounts
        )
        capacity_note = ""
        if self.practical_capacity:
            capacity_note = _(
                "\n\nPractical capacity %(cap)s — %(used)s used. The unused share "
                "stays on the source instead of being charged to cost objects.",
                cap=f"{self.practical_capacity:,.2f}",
                used=f"{total / self.practical_capacity:.1%}",
            )
        raise UserError(_(
            "%(name)s — measured %(start)s → %(end)s\n\n%(rows)s\n\n"
            "Total: %(total)s %(unit)s%(capacity)s",
            name=self.name, start=start, end=today, rows=rows,
            total=f"{total:,.2f}", unit=self.driver_label,
            capacity=capacity_note,
        ))


class AccountAnalyticLine(models.Model):
    """Timesheets carry an activity, so ABC's first stage is measured, not declared."""
    _inherit = 'account.analytic.line'

    gec_activity_id = fields.Many2one(
        'gec.activity',
        string='Activity',
        index='btree_not_null',
        help="Which activity this time was spent on. Fill it on timesheets and "
             "the split of a cost pool across activities is measured instead of "
             "estimated.",
    )
