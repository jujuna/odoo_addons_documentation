# -*- coding: utf-8 -*-
from odoo import fields, models


class BscObjectiveRating(models.Model):
    """The rating a qualitative objective had when a period closed."""
    _name = 'bsc.objective.rating'
    _description = 'BSC Objective Rating by Period'
    _order = 'period_id, objective_id'
    _check_company_auto = True

    objective_id = fields.Many2one(
        'bsc.objective', required=True, ondelete='cascade', index=True, check_company=True)
    period_id = fields.Many2one(
        'bsc.period', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one(
        related='objective_id.company_id', store=True, index=True, readonly=True)
    qualitative_status = fields.Selection(
        [('green', 'On Track'),
         ('amber', 'At Risk'),
         ('red', 'Off Track')],
        string='Qualitative Rating')
    qualitative_note = fields.Text(string='Assessment Note')

    _objective_period_uniq = models.Constraint(
        'unique(objective_id, period_id)',
        'An objective has one rating per period.',
    )
