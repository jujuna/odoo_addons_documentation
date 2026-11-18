# -*- coding: utf-8 -*-
from odoo import fields, models


class BscPerspective(models.Model):
    """A scorecard perspective: master data, so each organisation can adapt or reorder them.
    ``sequence`` drives the layering of the strategy map, bottom to top."""
    _name = 'bsc.perspective'
    _description = 'BSC Perspective'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Technical code used by other modules, e.g. financial, customer.")
    sequence = fields.Integer(default=10, help="Bottom-to-top order on the strategy map.")
    default_weight = fields.Float(
        string='Default Weight (%)', default=25.0,
        help="Used when a scorecard does not override the weight of this perspective.")
    color = fields.Integer(string='Colour Index')
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)
    is_demo = fields.Boolean(readonly=True, copy=False,
                             help="Created by the demo data loader and removed with it.")
    company_id = fields.Many2one(
        'res.company', string='Company',
        help="Leave empty to share this perspective with every company.")

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'The perspective code must be unique per company.',
    )
