# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

DECIDED_STATES = ('approved', 'in_progress', 'done')


class BscInitiativeStage(models.Model):
    _name = 'bsc.initiative.stage'
    _description = 'BSC Initiative Stage'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)

    state = fields.Selection(
        [('proposed', 'Proposed'),
         ('approved', 'Approved'),
         ('in_progress', 'In Progress'),
         ('done', 'Done'),
         ('cancelled', 'Cancelled')],
        default='proposed', required=True, help="Maps the stage onto the lifecycle the module reasons about.")

    fold = fields.Boolean(string='Folded in Kanban')
    company_id = fields.Many2one('res.company', string='Company')
    active = fields.Boolean(default=True)


class BscInitiative(models.Model):
    """A strategic initiative: work meant to move an objective, held without a project until approved."""
    _name = 'bsc.initiative'
    _description = 'BSC Strategic Initiative'
    _check_company_auto = True
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, date_start, id'

    name = fields.Char(required=True, tracking=True)
    scorecard_id = fields.Many2one('bsc.scorecard', string='Scorecard', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='scorecard_id.company_id', store=True, index=True, readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    objective_ids = fields.Many2many('bsc.objective', 'bsc_initiative_objective_rel', 'initiative_id', 'objective_id',
                                     string='Objectives', required=True,
                                     help="Which strategic objectives this initiative serves. An initiative "
                                          "that serves none does not belong on a scorecard.")

    perspective_ids = fields.Many2many('bsc.perspective', string='Perspectives', compute='_compute_perspectives', store=True)
    impact_kpi_ids = fields.Many2many('bsc.kpi', string='Expected Impact On', domain="[('scorecard_id', '=', scorecard_id)]")

    stage_id = fields.Many2one('bsc.initiative.stage', string='Stage', group_expand='_group_expand_stages',
                               default=lambda self: self._default_stage_id(), tracking=True, ondelete='restrict',
                               copy=False)

    state = fields.Selection(related='stage_id.state', store=True, readonly=True)
    owner_id = fields.Many2one('res.users', string='Owner', required=True,default=lambda self: self.env.user, tracking=True)
    date_start = fields.Date(string='Start')
    date_end = fields.Date(string='End')
    budget_planned = fields.Monetary(string='Planned Budget', currency_field='currency_id')
    budget_actual = fields.Monetary(string='Actual Spend', currency_field='currency_id')
    budget_variance = fields.Monetary(compute='_compute_budget_variance', currency_field='currency_id', string='Budget Variance')

    priority = fields.Selection(
        [('0', 'Low'),
         ('1', 'Normal'),
         ('2', 'High'),
         ('3', 'Critical')],
        default='1', required=True)

    progress = fields.Float(string='Progress (%)', default=0.0, tracking=True)
    expected_impact = fields.Text(help="What is expected to change, on which measure, and by when.")
    result_summary = fields.Text(string='Result', help="Filled in when the initiative is closed.")
    approval_date = fields.Date(readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    color = fields.Integer()
    active = fields.Boolean(default=True)

    @api.model
    def _default_stage_id(self):
        return self.env['bsc.initiative.stage'].search([('state', '=', 'proposed')], order='sequence', limit=1)

    @api.model
    def _group_expand_stages(self, stages, domain):
        return self.env['bsc.initiative.stage'].search([], order='sequence')

    @api.depends('objective_ids.perspective_id')
    def _compute_perspectives(self):
        for initiative in self:
            initiative.perspective_ids = initiative.objective_ids.perspective_id

    @api.depends('budget_planned', 'budget_actual')
    def _compute_budget_variance(self):
        for initiative in self:
            initiative.budget_variance = initiative.budget_planned - initiative.budget_actual

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for initiative in self:
            if initiative.date_start and initiative.date_end \
                    and initiative.date_start > initiative.date_end:
                raise ValidationError(_("The end date must be after the start date."))

    @api.constrains('progress')
    def _check_progress(self):
        for initiative in self:
            if not 0.0 <= initiative.progress <= 100.0:
                raise ValidationError(_("Progress must be between 0 and 100."))

    @api.constrains('objective_ids', 'scorecard_id')
    def _check_objectives_same_scorecard(self):
        for initiative in self:
            foreign = initiative.objective_ids.filtered(
                lambda o, i=initiative: o.scorecard_id != i.scorecard_id)
            if foreign:
                raise ValidationError(_("These objectives belong to another scorecard: %s",
                                        ", ".join(foreign.mapped('name'))))

    @api.model_create_multi
    def create(self, vals_list):
        """An initiative created in a decided stage passes the same gates and approval stamp as a moved one."""
        initiatives = super().create(vals_list)
        decided = initiatives.filtered(lambda i: i.state in DECIDED_STATES)
        for initiative in decided:
            initiative._check_stage_transition(initiative.stage_id, {})
        decided._stamp_approval()
        return initiatives

    def write(self, vals):
        """Enforce the approval gates; moving back to 'proposed' clears the approval stamp."""
        if 'stage_id' in vals:
            stage = self.env['bsc.initiative.stage'].browse(vals['stage_id'])
            for initiative in self:
                initiative._check_stage_transition(stage, vals)
        result = super().write(vals)
        if 'stage_id' in vals:
            stage = self.env['bsc.initiative.stage'].browse(vals['stage_id'])
            if stage.state in DECIDED_STATES:
                self._stamp_approval()
            if stage.state == 'proposed':
                self.filtered('approval_date').sudo().write({
                    'approval_date': False, 'approved_by_id': False})
            if stage.state == 'done':
                self.filtered(lambda i: i.progress < 100.0).write({'progress': 100.0})
        return result

    def _stamp_approval(self):
        """Record who approved and when, once; set by the system, see bsc_security.py."""
        self.filtered(lambda i: not i.approval_date).sudo().write({
            'approval_date': fields.Date.context_today(self),
            'approved_by_id': self.env.uid,
        })

    def _check_stage_transition(self, stage, vals):
        """Budget before approving, starting or closing; result before closing."""
        self.ensure_one()
        if stage.state in DECIDED_STATES and not (vals.get('budget_planned') or self.budget_planned):
            raise UserError(_("Set a planned budget on '%s' before approving it. An initiative "
                              "without resources is a wish, not a plan.", self.name))
        if stage.state == 'done' and not (vals.get('result_summary') or self.result_summary):
            raise UserError(_("Describe the result of '%s' before closing it.", self.name))
        return True

    def action_open_objectives(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Objectives"),
            'res_model': 'bsc.objective',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.objective_ids.ids)],
        }
