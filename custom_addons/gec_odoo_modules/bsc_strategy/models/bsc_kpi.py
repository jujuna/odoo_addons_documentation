# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .bsc_common import computed_selection_search


class BscKpi(models.Model):
    """The definition of a measure: what, unit, which direction is good; every KPI belongs to an objective.
    The figures live in bsc.measurement."""
    _name = 'bsc.kpi'
    _description = 'BSC Key Performance Indicator'
    _inherit = ['mail.thread']
    _order = 'objective_id, sequence, id'

    name = fields.Char(required=True, translate=True, tracking=True)
    sequence = fields.Integer(default=10)
    objective_id = fields.Many2one('bsc.objective', string='Objective', required=True, ondelete='cascade', index=True)
    scorecard_id = fields.Many2one(related='objective_id.scorecard_id', store=True, index=True, readonly=True)
    perspective_id = fields.Many2one(related='objective_id.perspective_id', store=True, readonly=True)
    company_id = fields.Many2one(related='objective_id.company_id', store=True, index=True, readonly=True)
    weight = fields.Float(string='Weight (%)', default=0.0,
                          help="Weight inside its objective. Leave all weights at zero for equal treatment.")

    owner_id = fields.Many2one('res.users', string='Data Owner', required=True,
                               default=lambda self: self.env.user, tracking=True,
                               help="The person who is asked for the figure every period.")

    description = fields.Text(translate=True, string='Definition',
                                help="How exactly this figure is obtained. Write it down; "
                                   "next year nobody will remember.")
    uom_name = fields.Char(string='Unit', help="Free text on purpose: %, GEL, days, tCO2e, units.")

    direction = fields.Selection(
        [('higher_better', 'Higher is better'),
         ('lower_better', 'Lower is better'),
         ('target_range', 'Inside a range')],
        default='higher_better', required=True, tracking=True)

    default_target = fields.Float(
        string='Target',
        help="The target for each period. Written onto every new period's row and "
             "editable there; the next period carries the last target forward "
             "(or applies the target rule below). Leave it at zero only for a "
             "range KPI or one whose target is negotiated period by period.")
    target_min = fields.Float(string='Range Minimum')
    target_max = fields.Float(string='Range Maximum')
    data_source = fields.Selection([('manual', 'Entered manually'),('odoo', 'Computed from Odoo data')],
                                   default='manual', required=True,
                                   help="A manual KPI is asked of its owner every period. A computed one is "
                                        "filled from a vetted data source - see the Automated Source group.")

    aggregation = fields.Selection(
        [('last', 'Last period'),
         ('sum', 'Sum of periods'),
         ('average', 'Average of periods')],
        default='last', required=True, help="How several periods roll up into a yearly figure.")

    threshold_green = fields.Float(string='Green From (%)', default=95.0)
    threshold_amber = fields.Float(string='Amber From (%)', default=80.0)
    digits = fields.Integer(string='Decimals', default=2)
    baseline_value = fields.Float(string='Baseline')
    active = fields.Boolean(default=True)

    measurement_ids = fields.One2many('bsc.measurement', 'kpi_id', string='Measurements')
    measurement_count = fields.Integer(compute='_compute_current')

    current_measurement_id = fields.Many2one('bsc.measurement', compute='_compute_current', string='Current Measurement')
    current_target = fields.Float(compute='_compute_current', string='Current Target')
    current_actual = fields.Float(compute='_compute_current', string='Current Actual')
    current_achievement = fields.Float(compute='_compute_current', string='Achievement (%)', digits=(16, 1))

    current_status = fields.Selection(
        [('green', 'On Track'),
         ('amber', 'At Risk'),
         ('red', 'Off Track'),
         ('no_data', 'No Data')],
        compute='_compute_current', string='Status', search='_search_current_status')

    def _search_current_status(self, operator, value):
        return computed_selection_search(self, 'current_status', operator, value)

    @api.depends('measurement_ids.achievement', 'measurement_ids.status',
                 'measurement_ids.actual_value', 'measurement_ids.target_value',
                 'scorecard_id.current_period_id')
    @api.depends_context('bsc_period_id')
    def _compute_current(self):
        for kpi in self:
            period = kpi.scorecard_id.current_period_id
            measurement = kpi.measurement_ids.filtered(
                lambda m, p=period: m.period_id == p)[:1]
            kpi.measurement_count = len(kpi.measurement_ids)
            kpi.current_measurement_id = measurement
            kpi.current_target = measurement.target_value if measurement else 0.0
            kpi.current_actual = measurement.actual_value if measurement else 0.0
            kpi.current_achievement = measurement.achievement if measurement else 0.0
            kpi.current_status = measurement.status if measurement else 'no_data'

    @api.constrains('threshold_green', 'threshold_amber')
    def _check_thresholds(self):
        for kpi in self:
            if kpi.threshold_amber > kpi.threshold_green:
                raise ValidationError(_("On KPI '%s' the amber threshold cannot be higher than the green one.", kpi.name))

    @api.constrains('direction', 'target_min', 'target_max')
    def _check_range(self):
        for kpi in self:
            if kpi.direction == 'target_range' and kpi.target_min > kpi.target_max:
                raise ValidationError(_("On KPI '%s' the range minimum cannot exceed the maximum.", kpi.name))

    @api.model_create_multi
    def create(self, vals_list):
        kpis = super().create(vals_list)
        kpis._warn_on_kpi_inflation()
        # A KPI added to a live scorecard still needs a row for the open period.
        for kpi in kpis:
            period = kpi.scorecard_id.current_period_id
            if kpi.scorecard_id.state == 'active' and period and period.state == 'open':
                period._create_missing_measurements(kpi)
        return kpis

    def _is_counted(self):
        """Whether this KPI counts: active, on an active objective measured by KPIs.
        Archived KPIs and KPIs of qualitative or archived objectives keep rows but are not
prepared, completed, required at close or reminded."""
        self.ensure_one()
        objective = self.objective_id
        return self.active and objective.active and objective.assessment_mode == 'kpi'

    def write(self, vals):
        """Refuse edits that corrupt closed figures or cross scorecards.
        A KPI stays in its scorecard; its direction is fixed once a closed period holds a figure; same value passes."""
        if 'objective_id' in vals:
            objective = self.env['bsc.objective'].browse(vals['objective_id'])
            if any(kpi.objective_id != objective and kpi.scorecard_id != objective.scorecard_id
                   for kpi in self):
                raise UserError(_("A KPI cannot move to an objective of another scorecard."))
        if 'direction' in vals:
            for kpi in self.filtered(lambda k: k.direction != vals['direction']):
                if kpi.measurement_ids.filtered(
                        lambda m: m.period_id.state == 'closed' and m.actual_value_set):
                    raise UserError(_(
                        "The direction of '%s' cannot change: a closed period already "
                        "holds a figure for it.", kpi.name))
        result = super().write(vals)
        if 'default_target' in vals:
            # A target set after the rows were created must reach the open period, else it scores against zero.
            rows = self.env['bsc.measurement'].search([
                ('kpi_id', 'in', self.ids),
                ('period_id.state', '=', 'open'),
                ('target_value', '=', 0.0),
            ])
            for row in rows:
                if row.kpi_id.default_target:
                    row.target_value = row.kpi_id.default_target
        return result

    def _warn_on_kpi_inflation(self):
        """Warn when a scorecard carries too many measures."""
        limit = 25
        for scorecard in self.scorecard_id:
            count = self.search_count([('scorecard_id', '=', scorecard.id)])
            added = len(self.filtered(lambda k, s=scorecard: k.scorecard_id == s))
            if count - added <= limit < count:
                scorecard.message_post(body=_(
                    "This scorecard now holds more than %(limit)s KPIs. Scorecards that "
                    "grow past this point tend to stop being filled in. Consider whether "
                    "every measure still serves a stated objective.", limit=limit))
        return True

    def _form_action(self, record):
        return {
            'type': 'ir.actions.act_window',
            'res_model': record._name,
            'res_id': record.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_open_form(self):
        """Open the KPI itself, editable - lists that only show it link here."""
        self.ensure_one()
        return self._form_action(self)

    def action_open_current_measurement(self):
        """Open this KPI's figure for the current period, creating the row if the period is open and it is missing."""
        self.ensure_one()
        period = self.scorecard_id.current_period_id
        if not period:
            raise UserError(_("The scorecard has no period yet. Activate it first."))
        row = self.measurement_ids.filtered(lambda m: m.period_id == period)[:1]
        if not row and period.state == 'open':
            period._create_missing_measurements(self)
            row = self.measurement_ids.filtered(lambda m: m.period_id == period)[:1]
        if not row:
            raise UserError(_("There is no figure for %s in %s.", self.name, period.name))
        return self._form_action(row)

    def action_open_measurements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Measurements"),
            'res_model': 'bsc.measurement',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('kpi_id', '=', self.id)],
            'context': {'default_kpi_id': self.id, 'search_default_group_period': 1},
        }
