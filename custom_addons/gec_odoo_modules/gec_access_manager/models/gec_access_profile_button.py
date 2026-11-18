from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class GecAccessProfileButton(models.Model):
    _name = 'gec.access.profile.button'
    _inherit = ['gec.access.history.mixin', 'gec.access.condition.mixin']
    _description = 'Access Profile Button Rule'

    def _gec_history_kind(self):
        return _("button")

    def _gec_history_label(self):
        # sudo: access managers write these lines, and only Administration users read ir.model
        return '%s: %s' % (self.sudo().model_id.name or '', self.display_name or '')
    _order = 'profile_id, model, button_label, id'

    _clear_cache_name = 'default'
    # the label only names the button in the screens
    _clear_cache_on_fields = ('profile_id', 'model_id', 'view_type', 'button_type', 'button_name', 'button_id',
                              'mode', 'condition')

    profile_id = fields.Many2one('gec.access.profile', required=True, ondelete='cascade', index=True)
    model_id = fields.Many2one('ir.model', string='Model', required=True, ondelete='cascade')
    model = fields.Char(string='Technical Name', related='model_id.model', store=True, index=True)

    view_type = fields.Selection(
        [('any', 'Any View'), ('form', 'Form'), ('list', 'List'), ('kanban', 'Kanban')],
        default='any', required=True)
    button_type = fields.Selection([('object', 'Method'), ('action', 'Action')], default='object', required=True)
    button_name = fields.Char(
        string='Button', required=True,
        help="The method the button calls, or the id of the action it opens.")
    button_id = fields.Char(
        string='Button Id',
        help="The button's id attribute in the view. Leave it empty to cover every button that calls the same method.")
    button_label = fields.Char(string='Label')

    mode = fields.Selection(
        [('hide', 'Hide only'),
         ('block', 'Block only'),
         ('hide_block', 'Hide and block')],
        default='hide_block', required=True,
        help="Hiding removes the button from the screen. A skilled user can still run its action another way. Blocking "
             "makes Odoo refuse the action on the server. Keep both unless you have a reason not to.")

    _unique_button = models.Constraint(
        'UNIQUE(profile_id, model_id, view_type, button_type, button_name, button_id)',
        "A profile can have only one rule per button.",
    )

    @api.constrains('button_type', 'condition', 'mode')
    def _check_action_condition(self):
        """ Loading an action names no record, so a condition can only hide an action button, never block it. """
        for line in self:
            if line.button_type == 'action' and (line.condition or '').strip() and line.mode != 'hide':
                raise ValidationError(_(
                    "An action button cannot be blocked under a condition: opening an action names no record. "
                    "Choose 'Hide only' or clear the condition."))

    @api.depends('button_label', 'button_name')
    def _compute_display_name(self):
        for line in self:
            line.display_name = line.button_label or line.button_name or ''
