from odoo import _, api, fields, models


class AccountAnalyticDistributionModel(models.Model):
    """One place to set up ABC for a distribution rule: the activity, its driver, rate and allocation rules.

    The fields below are related views onto gec.activity and gec.allocation.rule, which keep their own tables."""
    _inherit = 'account.analytic.distribution.model'

    gec_activity_id = fields.Many2one(
        'gec.activity',
        string='Activity',
        ondelete='set null',
        check_company=True,
        help="Tag the analytic items produced by matching lines with this "
             "costing activity.\n\n"
             "Applies to bills, expenses and purchase or sales lines — the "
             "documents that go through analytic distribution. Timesheets do "
             "not: they take their activity from the project.",
    )

    gec_driver_label = fields.Char(
        related='gec_activity_id.driver_label', readonly=False,
        string='Driver')
    gec_source_model_id = fields.Many2one(
        related='gec_activity_id.source_model_id', readonly=False,
        string='Measured From')
    gec_source_model_name = fields.Char(
        related='gec_activity_id.source_model_name',
        string='Measured Model')
    gec_source_domain = fields.Char(
        related='gec_activity_id.source_domain', readonly=False,
        string='Filter')
    gec_source_date_field = fields.Char(
        related='gec_activity_id.source_date_field', readonly=False,
        string='Date Field')
    gec_source_analytic_path = fields.Char(
        related='gec_activity_id.source_analytic_path', readonly=False,
        string='Path to Analytic Account')
    gec_measure = fields.Selection(
        related='gec_activity_id.measure', readonly=False,
        string='Measure')
    gec_measure_field = fields.Char(
        related='gec_activity_id.measure_field', readonly=False,
        string='Measure Field')
    gec_match_own_activity = fields.Boolean(
        related='gec_activity_id.match_own_activity', readonly=False,
        string='Only Records Tagged With This Activity')
    gec_weight_by_employee_cost = fields.Boolean(
        related='gec_activity_id.weight_by_employee_cost', readonly=False,
        string='Weight By Employee Cost')
    gec_practical_capacity = fields.Float(
        related='gec_activity_id.practical_capacity', readonly=False,
        string='Practical Capacity')
    gec_rate_mode = fields.Selection(
        related='gec_activity_id.rate_mode', readonly=False,
        string='Rate Basis')
    gec_standard_rate = fields.Float(
        related='gec_activity_id.standard_rate', readonly=False,
        string='Standard Rate')
    gec_value_added = fields.Selection(
        related='gec_activity_id.value_added', readonly=False,
        string='Value')
    gec_planned_quantity = fields.Float(
        related='gec_activity_id.planned_quantity', readonly=False,
        string='Planned Quantity')
    gec_planned_cost = fields.Monetary(
        related='gec_activity_id.planned_cost',
        currency_field='gec_currency_id', string='Planned Cost')
    gec_planned_capacity_gap = fields.Float(
        related='gec_activity_id.planned_capacity_gap', string='Capacity Gap')
    gec_currency_id = fields.Many2one(
        related='gec_activity_id.currency_id', string='Activity Currency')

    gec_rule_ids = fields.One2many(
        related='gec_activity_id.rule_ids', readonly=False,
        string='Allocation Rules')

    gec_activity_shared_count = fields.Integer(
        compute='_compute_gec_activity_shared_count',
        string='Other Rules Using This Activity')
    gec_activity_shared_warning = fields.Char(
        compute='_compute_gec_activity_shared_count')

    @api.depends('gec_activity_id')
    def _compute_gec_activity_shared_count(self):
        """Warn when an edit here also changes another rule that shares the activity."""
        activities = self.gec_activity_id
        counts = {}
        if activities:
            for group in self.sudo()._read_group(
                [('gec_activity_id', 'in', activities.ids)],
                groupby=['gec_activity_id'], aggregates=['__count'],
            ):
                counts[group[0].id] = group[1]
        for record in self:
            others = max(counts.get(record.gec_activity_id.id, 0) - 1, 0)
            record.gec_activity_shared_count = others
            record.gec_activity_shared_warning = others and _(
                "%(activity)s is also used by %(count)s other distribution "
                "rule(s). Changes made here apply to all of them.",
                activity=record.gec_activity_id.name, count=others,
            ) or False

    def action_gec_open_runs(self):
        """Allocation runs are an operation, not configuration; shortcut to them in Reporting."""
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'gec_analytic_margin.action_gec_allocation_run')
        action['context'] = {'default_company_id': self.company_id.id or self.env.company.id}
        return action

    def action_gec_preview_quantities(self):
        self.ensure_one()
        return self.gec_activity_id.action_preview_quantities()
