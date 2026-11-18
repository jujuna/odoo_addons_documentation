from odoo import _, api, fields, models

from .gec_access_rules import MODEL_FLAGS, OPERATIONS, PERM_FIELDS
from .gec_access_profile_model import DRAFT_DOMAIN

RECORD_CHOICES = [
    ('all', 'All records'),
    ('own', 'Their own records'),
    ('team', 'Their sales team'),
    ('company', 'Their companies'),
    ('warehouse', 'Their warehouse'),
    ('hierarchy', 'Theirs and their team\'s (org chart)'),
    ('today', 'Created today'),
    ('week', 'Created this week'),
    ('month', 'Created this month'),
    ('year', 'Created this year'),
]


class GecAccessProfileMenu(models.Model):
    _name = 'gec.access.profile.menu'
    _inherit = ['gec.access.history.mixin', 'gec.access.rights.mixin']
    _description = 'Access Profile Menu Rule'
    _order = 'profile_id, id'

    _clear_cache_name = 'default'

    profile_id = fields.Many2one('gec.access.profile', required=True, ondelete='cascade', index=True)
    menu_id = fields.Many2one('ir.ui.menu', string='Menu', required=True, ondelete='cascade')
    records = fields.Selection(
        RECORD_CHOICES, string='Records', default='all', required=True,
        help="Used for every screen of this menu that supports the choice. 'Their own records' needs an owner on the "
             "record (salesperson, user, employee). 'Their sales team' needs a sales team, and so on. Records without "
             "such a field all stay visible.")
    edit_draft_only = fields.Boolean(
        string='Edit Drafts Only',
        help="For records that have a status, users can edit or delete only drafts.")
    include_shared = fields.Boolean(
        string='Also Shared Data',
        help="Also limit records that other apps use too (customers, products). If unticked, making Sales read only "
             "does not affect the Contacts app.")

    _unique_menu = models.Constraint('UNIQUE(profile_id, menu_id)', "A profile can have only one rule per menu.")

    # a rule can take the access profiles away from the last administrator
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.profile_id._check_last_administrator()
        return lines

    def write(self, vals):
        result = super().write(vals)
        self.profile_id._check_last_administrator()
        return result

    @api.depends('menu_id')
    def _compute_display_name(self):
        for line in self:
            line.display_name = line.menu_id.sudo().complete_name or ''

    def _gec_history_kind(self):
        return _("menu rule")

    def _gec_history_label(self):
        rights = [label for name, label in (
            ('perm_read', _("Read")), ('perm_create', _("Create")),
            ('perm_write', _("Edit")), ('perm_unlink', _("Delete"))) if self[name]]
        label = '%s: %s' % (self.display_name, ', '.join(rights) or _("no access"))
        if self.records != 'all':
            label += ' + %s' % dict(self._fields['records']._description_selection(self.env))[self.records]
        return label

    @api.model
    @api.ormcache()
    def _gec_menu_models(self):
        """ ((menu id, (the menu and its ancestors, closest first), models, is configuration), ...) for every menu
        opening data; the models of a document's lines (order lines) go with it. """
        Wizard = self.env['gec.access.app.wizard']
        Menu = self.env['ir.ui.menu'].sudo()
        lines_of = {}
        result = []
        menus = Menu.search([('action', '!=', False)])
        # the configuration submenus right under each app
        second = Menu.browse({int(menu.parent_path.split('/')[1]) for menu in menus if menu.parent_path.count('/') > 2})
        xmlids = second.get_external_id()
        config = {menu.id for menu in second
                  if 'config' in xmlids.get(menu.id, '').split('.')[-1].lower()
                  or (menu.name or '').strip().lower() == 'configuration'}
        for menu in menus:
            model_name = Wizard._menu_model(menu)
            if not model_name:
                continue
            if model_name not in lines_of:
                lines_of[model_name] = (model_name, *Wizard._line_models(model_name))
            path = tuple(int(part) for part in (menu.parent_path or '').split('/') if part)
            result.append((menu.id, path[::-1], lines_of[model_name], len(path) > 2 and path[1] in config))
        return tuple(result)

    def _gec_rights_by_model(self):
        """ {model: (rights, {operation: (domain, ...)}, flags, menu names)} for the data under these menu lines. """
        if not self:
            return {}
        settings = {line.menu_id.id: line for line in self}
        menu_models = self._gec_menu_models()
        roots = {}
        for _menu_id, path, model_names, _config in menu_models:
            for model_name in model_names:
                roots.setdefault(model_name, set()).add(path[-1])
        found, filtered = {}, {}
        for _menu_id, path, model_names, config in menu_models:
            line = next((settings[menu_id] for menu_id in path if menu_id in settings), None)
            if line is None:
                continue
            for model_name in model_names:
                # shared: other apps open it too
                if not line.include_shared and roots[model_name] - {path[-1]}:
                    continue
                found.setdefault(model_name, {})[line.id] = line
                # the record choice skips the reference data of a configuration menu (sales teams): only rights reach it
                if not config:
                    filtered.setdefault(model_name, set()).add(line.id)
        Rule = self.env['gec.access.profile.model']
        result = {}
        for model_name, lines in found.items():
            lines = list(lines.values())
            rights = tuple(all(line[name] for line in lines) for name in PERM_FIELDS)
            presets = Rule._preset_domains(model_name)
            domains = dict.fromkeys(OPERATIONS, ())
            for line in lines:
                if line.id not in filtered.get(model_name, ()):
                    continue
                if line.records != 'all' and line.records in presets:
                    domain = presets[line.records][1]
                    for operation in OPERATIONS:
                        domains[operation] += (domain,)
                if line.edit_draft_only and 'draft' in presets:
                    domains['write'] += (DRAFT_DOMAIN,)
                    domains['unlink'] += (DRAFT_DOMAIN,)
            flags = frozenset(flag for flag in MODEL_FLAGS if any(line[flag] for line in lines))
            result[model_name] = (rights, {op: terms for op, terms in domains.items() if terms}, flags,
                                  tuple(line.menu_id.sudo().complete_name for line in lines))
        return result
