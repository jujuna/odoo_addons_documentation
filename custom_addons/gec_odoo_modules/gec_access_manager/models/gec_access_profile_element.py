from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

ELEMENT_TYPES = [
    ('page', 'Notebook Tab'),
    ('filter', 'Search Filter or Group By'),
    ('searchpanel', 'Search Panel'),
    ('view', 'View Type'),
]

VIEW_TYPES = ('list', 'form', 'kanban', 'calendar', 'pivot', 'graph', 'activity', 'map', 'gantt', 'cohort', 'hierarchy')


class GecAccessProfileElement(models.Model):
    _name = 'gec.access.profile.element'
    _inherit = ['gec.access.history.mixin', 'gec.access.condition.mixin']
    _description = 'Access Profile View Element Rule'

    def _gec_history_kind(self):
        return _("view element")
    _order = 'profile_id, model, element_type, id'

    _clear_cache_name = 'default'
    # the label only names the element in the screens
    _clear_cache_on_fields = ('profile_id', 'model_id', 'element_type', 'element_name', 'condition')

    profile_id = fields.Many2one('gec.access.profile', required=True, ondelete='cascade', index=True)
    model_id = fields.Many2one('ir.model', string='Model', required=True, ondelete='cascade')
    model = fields.Char(string='Technical Name', related='model_id.model', store=True, index=True)

    element_type = fields.Selection(ELEMENT_TYPES, default='page', required=True)
    element_name = fields.Char(
        string='Name',
        help="The name attribute of the tab or filter, or the view type for a view rule. Leave it empty for a search "
             "panel. Each view has only one.")
    element_label = fields.Char(string='Label')

    _unique_element = models.Constraint(
        'UNIQUE(profile_id, model_id, element_type, element_name)',
        "A profile can have only one rule per view element.",
    )

    @api.constrains('element_type', 'condition')
    def _check_condition_type(self):
        for line in self:
            if (line.condition or '').strip() and line.element_type != 'page':
                raise ValidationError(_("A condition can only be set on a tab."))

    @api.constrains('element_type', 'element_name')
    def _check_element_name(self):
        labels = dict(ELEMENT_TYPES)
        for line in self:
            if line.element_type == 'searchpanel':
                continue
            if not (line.element_name or '').strip():
                raise ValidationError(_("A '%s' rule needs a name.", labels[line.element_type]))
            if line.element_type == 'view' and line.element_name not in VIEW_TYPES:
                raise ValidationError(_(
                    "'%(name)s' is not a view type. Use one of: %(types)s",
                    name=line.element_name, types=', '.join(VIEW_TYPES)))

    @api.depends('element_label', 'element_name', 'element_type')
    def _compute_display_name(self):
        for line in self:
            line.display_name = (line.element_label or line.element_name or dict(ELEMENT_TYPES)[line.element_type])
