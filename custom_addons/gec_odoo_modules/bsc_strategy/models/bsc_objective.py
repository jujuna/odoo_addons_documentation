# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .bsc_common import (
    computed_selection_search,
    PARAM_QUALITATIVE_AMBER,
    PARAM_QUALITATIVE_GREEN,
    PARAM_QUALITATIVE_RED,
    PARAM_THRESHOLD_AMBER,
    PARAM_THRESHOLD_GREEN,
    DEFAULT_QUALITATIVE,
    DEFAULT_THRESHOLD_AMBER,
    DEFAULT_THRESHOLD_GREEN,
    rag_status,
    weighted_average,
)


class BscObjective(models.Model):
    """A strategic objective inside one perspective of one scorecard."""
    _name = 'bsc.objective'
    _description = 'BSC Strategic Objective'
    _check_company_auto = True
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scorecard_id, perspective_sequence, sequence, id'

    name = fields.Char(required=True, translate=True, tracking=True)
    code = fields.Char(help="Short identifier used on the strategy map, e.g. F1, C2.")
    sequence = fields.Integer(default=10)
    scorecard_id = fields.Many2one(
        'bsc.scorecard', string='Scorecard', required=True, ondelete='cascade', index=True)
    perspective_id = fields.Many2one(
        'bsc.perspective', string='Perspective', required=True, tracking=True,
        check_company=True)
    perspective_sequence = fields.Integer(
        related='perspective_id.sequence', store=True, index=True,
        string='Perspective Order')
    color = fields.Integer(related='perspective_id.color')
    weight = fields.Float(
        string='Weight (%)', default=0.0,
        help="Weight inside its perspective. Leave every weight at zero to treat "
             "all objectives equally.")
    owner_id = fields.Many2one(
        'res.users', string='Owner', required=True,
        default=lambda self: self.env.user, tracking=True)
    description = fields.Text(translate=True)
    company_id = fields.Many2one(
        related='scorecard_id.company_id', store=True, index=True, readonly=True)
    state = fields.Selection(related='scorecard_id.state', store=True, readonly=True)
    active = fields.Boolean(default=True)

    assessment_mode = fields.Selection(
        [('kpi', 'Measured by KPIs'),
         ('qualitative', 'Qualitative assessment')],
        default='kpi', required=True, tracking=True,
        help="Not every strategic objective becomes a number. A qualitative "
             "objective is rated by its owner and needs no KPI.")
    qualitative_status = fields.Selection(
        [('green', 'On Track'),
         ('amber', 'At Risk'),
         ('red', 'Off Track')],
        string='Qualitative Rating', tracking=True, copy=False)
    qualitative_note = fields.Text(string='Assessment Note', copy=False)
    period_rating_ids = fields.One2many(
        'bsc.objective.rating', 'objective_id', string='Ratings by Period', copy=False,
        help="The rating this objective had when each period closed.")

    kpi_ids = fields.One2many('bsc.kpi', 'objective_id', string='KPIs', copy=True)
    kpi_count = fields.Integer(compute='_compute_kpi_count')
    initiative_ids = fields.Many2many(
        'bsc.initiative', 'bsc_initiative_objective_rel', 'objective_id', 'initiative_id',
        string='Initiatives', copy=False)
    initiative_count = fields.Integer(compute='_compute_kpi_count')

    link_out_ids = fields.One2many(
        'bsc.objective.link', 'source_id', string='Contributes To')
    link_in_ids = fields.One2many(
        'bsc.objective.link', 'target_id', string='Driven By')

    score = fields.Float(string='Score (%)', compute='_compute_score', digits=(16, 1))
    status = fields.Selection(
        [('green', 'On Track'),
         ('amber', 'At Risk'),
         ('red', 'Off Track'),
         ('no_data', 'No Data')],
        compute='_compute_score', search='_search_status')

    def _search_status(self, operator, value):
        return computed_selection_search(self, 'status', operator, value)

    @api.depends('kpi_ids', 'initiative_ids')
    def _compute_kpi_count(self):
        for objective in self:
            objective.kpi_count = len(objective.kpi_ids)
            objective.initiative_count = len(objective.initiative_ids)

    @api.depends('assessment_mode', 'qualitative_status', 'period_rating_ids.qualitative_status',
                 'scorecard_id.period_ids.state',
                 'kpi_ids.weight', 'kpi_ids.current_achievement', 'kpi_ids.current_status')
    @api.depends_context('bsc_period_id')
    def _compute_score(self):
        """Qualitative objective, closed period (pinned or current): only the rating kept at close (none: no data);
        open period: live rating. Another scorecard's pinned period is ignored."""
        green = self.env['bsc.scorecard']._get_param(
            PARAM_THRESHOLD_GREEN, DEFAULT_THRESHOLD_GREEN)
        amber = self.env['bsc.scorecard']._get_param(
            PARAM_THRESHOLD_AMBER, DEFAULT_THRESHOLD_AMBER)
        qualitative = self._qualitative_scores()
        pinned = self.env['bsc.period'].browse(self.env.context.get('bsc_period_id')).exists()
        for objective in self:
            if objective.assessment_mode == 'qualitative':
                period = pinned if pinned.scorecard_id == objective.scorecard_id \
                    else objective.scorecard_id.current_period_id
                if period.state == 'closed':
                    rating = objective.period_rating_ids.filtered(lambda r: r.period_id == period)[:1]
                    rating_status = rating.qualitative_status
                else:
                    rating_status = objective.qualitative_status
                if rating_status:
                    objective.score = qualitative[rating_status]
                    objective.status = rating_status
                else:
                    objective.score = 0.0
                    objective.status = 'no_data'
                continue
            pairs = [
                (kpi.weight,
                 kpi.current_achievement if kpi.current_status != 'no_data' else None)
                for kpi in objective.kpi_ids
            ]
            value = weighted_average(pairs)
            objective.score = value or 0.0
            objective.status = rag_status(value, green, amber)

    def write(self, vals):
        """An objective stays in its scorecard once that scorecard has left draft:
        its KPIs, periods and figures belong to it. Writing the same value is allowed."""
        if 'scorecard_id' in vals:
            for objective in self:
                if (objective.scorecard_id.id != vals['scorecard_id']
                        and objective.scorecard_id.state != 'draft'):
                    raise UserError(_(
                        "Objective '%s' cannot move to another scorecard once its "
                        "scorecard has been activated.", objective.name))
        return super().write(vals)

    def _qualitative_scores(self):
        get = self.env['bsc.scorecard']._get_param
        return {
            'green': get(PARAM_QUALITATIVE_GREEN, DEFAULT_QUALITATIVE['green']),
            'amber': get(PARAM_QUALITATIVE_AMBER, DEFAULT_QUALITATIVE['amber']),
            'red': get(PARAM_QUALITATIVE_RED, DEFAULT_QUALITATIVE['red']),
        }

    @api.constrains('assessment_mode', 'qualitative_status', 'qualitative_note')
    def _check_qualitative_note(self):
        for objective in self:
            if (objective.assessment_mode == 'qualitative'
                    and objective.qualitative_status == 'red'
                    and not objective.qualitative_note):
                raise ValidationError(_(
                    "Objective '%s' is rated off track. Please explain why in the "
                    "assessment note.", objective.name))

    @api.constrains('weight')
    def _check_weight(self):
        for objective in self:
            if objective.weight < 0.0:
                raise ValidationError(_("A weight cannot be negative."))

    @api.onchange('perspective_id')
    def _onchange_perspective_id(self):
        """Warn - never block - when the weights inside a perspective do not add up."""
        if not self.perspective_id or not self.scorecard_id:
            return
        siblings = self.scorecard_id.objective_ids.filtered(
            lambda o: o.perspective_id == self.perspective_id)
        total = sum(siblings.mapped('weight'))
        if total and abs(total - 100.0) > 0.01:
            return {'warning': {
                'title': _("Weights do not add up"),
                'message': _(
                    "The objectives already in the '%(perspective)s' perspective carry "
                    "%(total)s%% in total. This is only a hint - weights are optional.",
                    perspective=self.perspective_id.name, total=round(total, 1)),
            }}

    def action_open_form(self):
        """Open the objective itself - read-only lists elsewhere link here."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_open_kpis(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("KPIs"),
            'res_model': 'bsc.kpi',
            'view_mode': 'list,form',
            'domain': [('objective_id', '=', self.id)],
            'context': {'default_objective_id': self.id},
        }

    def action_create_corrective_initiative(self):
        """Turn an off-track objective straight into a corrective initiative."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Corrective Initiative"),
            'res_model': 'bsc.initiative',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_scorecard_id': self.scorecard_id.id,
                'default_objective_ids': [self.id],
                'default_name': _("Corrective action: %s", self.name),
                'default_owner_id': self.owner_id.id,
            },
        }
