# Part of the GEC Georgian translation modules.
from odoo import api, models
from odoo.fields import Domain


class PosCategory(models.Model):
    _inherit = 'pos.category'
    _rec_names_search = ('complete_name', 'name')

    @api.depends('name', 'complete_name')
    @api.depends_context('lang')
    def _compute_display_name(self):
        """Build the category path from the translated names; the stored complete_name keeps one language."""
        for category in self:
            names, node = [], category
            while node:
                names.append(node.name or self.env._("New"))
                node = node.parent_id
            category.display_name = ' / '.join(reversed(names))

    @api.model
    def _search_display_name(self, operator, value):
        """Also find a category by the translated path its display name shows ("ბარი / სასმელები"); a name may
        contain " / ", so every tail of the path is tried as a name."""
        domain = super()._search_display_name(operator, value)
        if operator not in ('=', 'in'):
            return domain
        paths = {path for path in ([value] if operator == '=' else value) if isinstance(path, str) and path}
        tails = {' / '.join(parts[i:]) for parts in (path.split(' / ') for path in paths) for i in range(len(parts))}
        if not tails:
            return domain
        ids = self.search([('name', 'in', list(tails))]).filtered(lambda category: category.display_name in paths).ids
        return Domain.OR([domain, Domain('id', 'in', ids)]) if ids else domain
