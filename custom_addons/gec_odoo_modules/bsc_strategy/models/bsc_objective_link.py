# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BscObjectiveLink(models.Model):
    """A cause-effect link between two objectives, stored as a hypothesis with a validation flag."""
    _name = 'bsc.objective.link'
    _description = 'BSC Cause-Effect Link'
    _order = 'source_id, target_id'

    source_id = fields.Many2one(
        'bsc.objective', string='Cause', required=True, ondelete='cascade', index=True)
    target_id = fields.Many2one(
        'bsc.objective', string='Effect', required=True, ondelete='cascade', index=True)
    scorecard_id = fields.Many2one(
        related='source_id.scorecard_id', store=True, index=True, readonly=True)
    company_id = fields.Many2one(
        related='source_id.company_id', store=True, index=True, readonly=True)
    hypothesis = fields.Text(
        required=True,
        help="State the assumption in plain words: if the cause improves, what is "
             "expected to happen to the effect, and why.")
    strength = fields.Selection(
        [('weak', 'Weak'),
         ('medium', 'Medium'),
         ('strong', 'Strong')],
        default='medium', required=True,
        help="How strongly the organisation believes in this link. A judgement, "
             "not a measurement.")
    validated = fields.Boolean(
        string='Validated with Data',
        help="Tick only once actual measurements support the hypothesis.")
    validation_note = fields.Text()

    _source_target_uniq = models.Constraint(
        'unique(source_id, target_id)',
        'This cause-effect link already exists.',
    )

    @api.depends('source_id.name', 'target_id.name')
    def _compute_display_name(self):
        for link in self:
            link.display_name = '%s -> %s' % (
                link.source_id.name or '', link.target_id.name or '')

    @api.constrains('source_id', 'target_id')
    def _check_not_self(self):
        for link in self:
            if link.source_id == link.target_id:
                raise ValidationError(_("An objective cannot cause itself."))
            if link.source_id.scorecard_id != link.target_id.scorecard_id:
                raise ValidationError(_(
                    "Cause-effect links can only join objectives of the same scorecard."))

    @api.constrains('source_id', 'target_id')
    def _check_no_cycle(self):
        """Feedback loops are legitimate, so a cycle is only posted to the scorecard chatter."""
        for link in self:
            visited = set()
            stack = [link.target_id]
            while stack:
                current = stack.pop()
                if current == link.source_id:
                    link.scorecard_id.message_post(body=_(
                        "Heads up: the link '%(link)s' closes a loop in the strategy "
                        "map. Feedback loops are allowed, but make sure this one is "
                        "intended.", link=link.display_name))
                    break
                if current.id in visited:
                    continue
                visited.add(current.id)
                stack.extend(current.link_out_ids.mapped('target_id'))
        return True

    def action_toggle_validated(self):
        for link in self:
            link.validated = not link.validated
        return True
