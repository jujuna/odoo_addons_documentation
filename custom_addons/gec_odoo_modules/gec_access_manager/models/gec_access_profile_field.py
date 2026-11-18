from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .value_filters import CONTEXT_NAMES, MAX_FILTER_LENGTH, check_filter, check_filter_paths, names_read


class GecAccessProfileField(models.Model):
    _name = 'gec.access.profile.field'
    _inherit = ['gec.access.history.mixin', 'gec.access.condition.mixin']
    _description = 'Access Profile Field Rule'

    def _gec_history_kind(self):
        return _("field")

    def _gec_history_label(self):
        mode = dict(self._fields['mode']._description_selection(self.env)).get(self.mode, self.mode)
        # sudo: access managers write these lines, and only Administration users read ir.model and ir.model.fields
        line = self.sudo()
        return '%s / %s: %s' % (line.model_id.name or '', line.field_id.field_description or '', mode)
    _order = 'profile_id, model_id, id'

    _clear_cache_name = 'default'

    profile_id = fields.Many2one('gec.access.profile', required=True, ondelete='cascade', index=True)
    model_id = fields.Many2one('ir.model', string='Model', required=True, ondelete='cascade')
    model = fields.Char(string='Technical Name', related='model_id.model', store=True, index=True)
    field_id = fields.Many2one(
        'ir.model.fields', string='Field', required=True, ondelete='cascade',
        domain="[('model_id', '=', model_id)]")
    mode = fields.Selection(
        [('hide', 'Hidden'),
         ('readonly', 'Read Only'),
         ('required', 'Required'),
         ('keep', 'Keep as is')],
        default='hide', required=True,
        help="'Keep as is' leaves the field unchanged. Only the other columns of the row are used, such as 'Not "
             "Exported'.")
    no_open = fields.Boolean(
        string='No External Link',
        help="Removes the arrow that opens the linked record. Only for fields that link to other records.")
    no_create = fields.Boolean(
        string="No Create from Dropdown",
        help="Removes 'Create' and 'Create and edit' from the dropdown list. Only for fields that link to other "
             "records.")
    no_export = fields.Boolean(
        string='Not Exported',
        help="Users still see this field on screens, but cannot export it. It is left out of the Export window.")
    field_domain = fields.Char(
        string='Value Filter',
        help="Limits the choices in the dropdown. Odoo also refuses any other value when the record is saved. Only for "
             "fields that pick another record.")

    _unique_field = models.Constraint('UNIQUE(profile_id, field_id)', "A profile can have only one rule per field.")

    @api.constrains('field_domain', 'field_id', 'model_id')
    def _check_field_domain(self):
        """ Refuse a Value Filter that is too long, uses more than a filter needs (calls, indexes, user fields other
        than ids, tz and lang) or reads a field its editor cannot read (by name on the model, in a path on the
        comodel): it is judged as the superuser. ``parent.<field>`` is not checked: its values are unknown on save. """
        users = self.env['res.users']
        reader = None if self.env['gec.access.profile']._gec_editor_is_trusted() else self.env(su=False)
        for line in self:
            text = (line.field_domain or '').strip()
            if not text:
                continue
            if len(text) > MAX_FILTER_LENGTH:
                raise ValidationError(_(
                    "The Value Filter of '%(field)s' is too long. Use at most %(limit)s characters.",
                    field=line.sudo().field_id.field_description, limit=MAX_FILTER_LENGTH))
            try:
                tree = check_filter(text, users, value_filter=True)
                if reader is not None and line.model in self.env:
                    target = reader[line.model]
                    for name in names_read(text) - CONTEXT_NAMES:
                        if name in target._fields:
                            target.check_field_access(target._fields[name], 'read')
                comodel = line.sudo().field_id.relation
                if reader is not None and comodel in self.env:
                    check_filter_paths(reader[comodel], tree)
            except (ValueError, AccessError) as error:
                raise ValidationError(_(
                    "Invalid Value Filter on %(field)s: %(error)s",
                    field=line.sudo().field_id.field_description, error=error)) from error

    @api.onchange('model_id')
    def _onchange_model_id(self):
        if self.field_id.model_id != self.model_id:
            self.field_id = False
