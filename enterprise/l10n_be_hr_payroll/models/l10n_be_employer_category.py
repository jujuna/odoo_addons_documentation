# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.fields import Domain

# The employer categories reserved for the occasional workers (DIMONA category "ext") of a regular one
# Source: ONSS, list of the employer categories (017: "excluding occasional workers declared in category 317")
OCCASIONAL_WORKER_DMFA_CODES = {
    '017': '317',
}


class L10nBeEmployerCategory(models.Model):
    _name = 'l10n.be.employer.category'
    _description = 'BE: Employer Category'

    name = fields.Char(required=True, translate=True)
    sector = fields.Selection([
        ('private', 'Private'),
        ('public', 'Public'),
    ], default='private', required=True)
    egov3_code = fields.Char(required=True)
    dmfa_code = fields.Char(required=True)
    allowed_joint_committee_ids = fields.Many2many('l10n.be.joint.committee', string="Allowed Joint Committees", context={'active_test': False})
    allowed_worker_code_ids = fields.Many2many('l10n.be.worker.code', string="Worker Codes")
    regular_category_id = fields.Many2one(
        'l10n.be.employer.category', compute='_compute_regular_category_id', search='_search_regular_category_id',
        help="For a category reserved for the occasional workers, the category of the regular workers (e.g. 017 for 317)")

    def _get_occasional_worker_dmfa_code(self):
        """DMFA code to use for an occasional worker (DIMONA category "ext") under this category.

        Some employer categories have a dedicated DMFA code reserved for their occasional workers,
        e.g. in Horeca: 017 for regular workers, 317 for occasional ones. Configuring the regular
        code is enough, the occasional one is derived per employee here instead of requiring a
        second payroll configuration (e.g. a second branch) just to switch category.

        Falls back to this category's own code when it has no dedicated occasional code (False without category).
        """
        if not self:
            return False
        self.ensure_one()
        return OCCASIONAL_WORKER_DMFA_CODES.get(self.dmfa_code, self.dmfa_code)

    def _compute_regular_category_id(self):
        regular_codes = {occasional: regular for regular, occasional in OCCASIONAL_WORKER_DMFA_CODES.items()}
        codes = [regular_codes[code] for code in self.mapped('dmfa_code') if code in regular_codes]
        regular_categories = {category.dmfa_code: category for category in self.search([('dmfa_code', 'in', codes)])} if codes else {}
        for category in self:
            category.regular_category_id = regular_categories.get(regular_codes.get(category.dmfa_code))

    def _search_regular_category_id(self, operator, value):
        if operator not in ('in', '='):
            return NotImplemented
        regular_ids = [value] if operator == '=' else value
        regular_ids = [category_id for category_id in regular_ids if category_id]
        if not regular_ids:
            return Domain.FALSE
        occasional_codes = [
            OCCASIONAL_WORKER_DMFA_CODES[code] for code in self.browse(regular_ids).mapped('dmfa_code')
            if code in OCCASIONAL_WORKER_DMFA_CODES
        ]
        return Domain('dmfa_code', 'in', occasional_codes) if occasional_codes else Domain.FALSE

    @api.depends('dmfa_code')
    def _compute_display_name(self):
        for category in self:
            category.display_name = f'[{category.dmfa_code}] {category.name}'

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        result = []
        domain = Domain(domain or Domain.TRUE)
        # first search by code
        if not operator in Domain.NEGATIVE_OPERATORS and name:
            categories = self.search_fetch(domain & Domain('egov3_code', operator, name), ['display_name'], limit=limit)
            result.extend((category.id, category.display_name) for category in categories)
            domain &= Domain('id', 'not in', categories.ids)
            if limit is not None:
                limit -= len(categories)
                if limit <= 0:
                    return result
        # normal search
        result.extend(super().name_search(name, domain, operator, limit))
        return result
