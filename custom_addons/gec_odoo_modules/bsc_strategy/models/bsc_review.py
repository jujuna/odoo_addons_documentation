# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import is_html_empty


class BscReview(models.Model):
    """The periodic strategy review: findings, decisions, corrective action."""
    _name = 'bsc.review'
    _description = 'BSC Strategy Review'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'review_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    scorecard_id = fields.Many2one(
        'bsc.scorecard', string='Scorecard', required=True, ondelete='cascade', index=True)
    period_id = fields.Many2one(
        'bsc.period', string='Period', required=True, ondelete='cascade',
        domain="[('scorecard_id', '=', scorecard_id)]")
    company_id = fields.Many2one(
        related='scorecard_id.company_id', store=True, index=True, readonly=True)
    review_date = fields.Date(
        required=True, default=fields.Date.context_today, tracking=True)
    participant_ids = fields.Many2many('res.users', string='Participants')
    score_snapshot = fields.Float(
        string='Score at Review (%)', readonly=True, digits=(16, 1),
        help="The scorecard index as it stood when the review was prepared. "
             "Stored, because live scores keep moving and minutes must not.")
    completion_snapshot = fields.Float(string='Completion at Review (%)', readonly=True,
                                       digits=(16, 1))
    red_objective_ids = fields.Many2many(
        'bsc.objective', 'bsc_review_red_objective_rel', 'review_id', 'objective_id',
        string='Off-track Objectives', readonly=True)
    period_measurement_ids = fields.One2many(
        related='period_id.measurement_ids', string='Figures of the Period', readonly=True)
    findings = fields.Html(string='Findings')
    decisions = fields.Html(string='Decisions')
    strategy_adjustment = fields.Text(
        string='Strategy Adjustment',
        help="Objectives, targets or cause-effect links that this review changed. "
             "A strategy that never changes was never being tested.")
    action_initiative_ids = fields.One2many(
        'bsc.initiative', 'review_id', string='Corrective Initiatives')
    state = fields.Selection(
        [('draft', 'Draft'),
         ('done', 'Done')],
        default='draft', required=True, tracking=True)

    _scorecard_period_uniq = models.Constraint(
        'unique(scorecard_id, period_id)',
        'That period has already been reviewed.',
    )

    @api.constrains('scorecard_id', 'period_id')
    def _check_period_scorecard(self):
        for review in self:
            if review.period_id.scorecard_id != review.scorecard_id:
                raise ValidationError(_("The period of a review must belong to its scorecard."))

    @api.depends('scorecard_id.name', 'period_id.name')
    def _compute_name(self):
        for review in self:
            review.name = _("Strategy review - %s", review.period_id.name or '')

    @api.onchange('scorecard_id')
    def _onchange_scorecard_id(self):
        if self.scorecard_id:
            self.period_id = self.scorecard_id.current_period_id

    def action_prepare(self):
        """Freeze the picture the review is about."""
        for review in self:
            # Without the period context the snapshot would freeze the period containing today.
            scorecard = review.scorecard_id.with_context(bsc_period_id=review.period_id.id)
            review.score_snapshot = scorecard.score
            review.completion_snapshot = review.period_id.completion_rate
            review.red_objective_ids = scorecard.objective_ids.filtered(
                lambda o: o.status == 'red')
            review.message_post(body=_(
                "Prepared: score %(score)s%%, completion %(completion)s%%, "
                "%(count)s objective(s) off track.",
                score=round(review.score_snapshot, 1),
                completion=round(review.completion_snapshot, 1),
                count=len(review.red_objective_ids)))
        return True

    def action_done(self):
        for review in self:
            if is_html_empty(review.decisions):
                raise UserError(_(
                    "Record the decisions before closing the review. A review with no "
                    "decision is a report."))
            review.state = 'done'
        return True

    def action_back_to_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_create_initiative(self):
        """Open a new corrective initiative pre-filled from this review."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Corrective Initiative"),
            'res_model': 'bsc.initiative',
            'view_mode': 'form',
            'context': {
                'default_scorecard_id': self.scorecard_id.id,
                'default_review_id': self.id,
                'default_objective_ids': self.red_objective_ids.ids,
                'default_name': _("Corrective action after %s", self.period_id.name),
                'default_owner_id': self.scorecard_id.responsible_id.id,
            },
        }

    def action_print(self):
        """The board pack is a scorecard report; a review just triggers it."""
        self.ensure_one()
        return self.env.ref('bsc_strategy.action_report_bsc_board').with_context(
            bsc_period_id=self.period_id.id).report_action(self.scorecard_id)


class BscInitiativeReview(models.Model):
    _inherit = 'bsc.initiative'

    review_id = fields.Many2one(
        'bsc.review', string='Originating Review', ondelete='set null',
        help="Set when the initiative was decided in a strategy review.")
