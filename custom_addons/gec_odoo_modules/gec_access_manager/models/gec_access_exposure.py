import copy

from odoo import api, models
from odoo.addons.base.models.ir_access import IN_SELECTION
from odoo.exceptions import UserError
from odoo.tools import frozendict

from .gec_access_rules import PERM_FIELDS, AccessRules

# the actions that open data: server, client and URL actions give no known model
DATA_ACTIONS = ('ir.actions.act_window', 'ir.actions.report')
RELATIONAL = ('many2one', 'one2many', 'many2many')
# models defined by these modules (and auth_*) keep the framework running: blocking them stops the web client
CORE_MODULES = frozenset({'base', 'web', 'mail', 'bus', 'portal', 'resource', 'digest', 'base_setup'})
LINKS_SHOWN = 5


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    def gec_hidden_exposure(self, menu_id=False):
        """ The data hidden menus still open: a menu and its subtree for the panel, all of them for the page. """
        self._gec_check_admin()
        self.ensure_one()
        return self._gec_exposure(menu_id)

    def gec_block_data(self, menu_id, model_names):
        """ Set Read, Edit, Create and Delete off for data a hidden menu opens, and its lines; return the exposure. """
        self._gec_check_admin()
        self.ensure_one()
        names = list(dict.fromkeys(model_names))
        exposed, menus = self._gec_exposed(menu_id)
        for name in names:
            if name not in exposed:
                raise UserError(self.env._("This hidden menu does not open these records: %s.", name))
            if exposed[name]['status'] == 'core':
                raise UserError(self.env._("%s: core Odoo records. They always stay open.", exposed[name]['label']))
        Wizard = self.env['gec.access.app.wizard']
        targets = dict.fromkeys(
            target for name in names for target in (name, *Wizard._line_models(name))
            if target in exposed and exposed[target]['status'] not in ('core', 'blocked'))
        for target in targets:
            self._gec_set_data_rights(menus[target], target, dict.fromkeys(PERM_FIELDS, False))
        self.env.transaction.invalidate_access_cache()
        return self._gec_exposure(menu_id)

    def gec_unblock_data(self, menu_id, model_names):
        """ Give Read back on the data named when a rule of this profile's own blocks it; a block from the level of a
        menu is changed on that menu. Returns the exposure again. """
        self._gec_check_admin()
        self.ensure_one()
        names = list(dict.fromkeys(model_names))
        exposed, menus = self._gec_exposed(menu_id)
        for name in names:
            if name not in exposed:
                raise UserError(self.env._("This hidden menu does not open these records: %s.", name))
            if not self._gec_blocked_by_line(exposed[name]):
                raise UserError(self.env._(
                    "%s is not blocked by its own settings. Change the settings of its menu instead.",
                    exposed[name]['label']))
        for name in names:
            self._gec_set_data_rights(menus[name], name, {'perm_read': True})
        self.env.transaction.invalidate_access_cache()
        return self._gec_exposure(menu_id)

    @api.model
    def _gec_blocked_by_line(self, item):
        return item['status'] == 'blocked' and item['by'] == 'line'

    def _gec_exposure(self, menu_id=False):
        """ {entries, runs_as, members, hidden}: one entry per hidden menu (``menu_id`` and its subtree, or every menu
        hidden directly); ``hidden`` counts them, so a page can tell "nobody applies" from "nothing hidden". Reads
        as sudo, like the panel. """
        profile = self.sudo()
        Menu = self.env['ir.ui.menu'].sudo()
        if menu_id:
            menu = Menu.browse(menu_id).exists()
            if not menu:
                raise UserError(self.env._("This menu no longer exists."))
            path = {int(part) for part in menu.parent_path.split('/') if part}
            roots = menu if path & set(profile.hidden_menu_ids._ids) else Menu
        else:
            roots = profile.hidden_menu_ids
        members = profile._gec_applied_members()
        result = {'entries': [], 'runs_as': [], 'members': len(members), 'hidden': len(roots)}
        if not (roots and members):
            return result
        own = profile._gec_own_rules(members[0])
        navbar = profile._gec_navbar(members, own.menus)
        linked, inherited = profile._gec_links(set(navbar), members)
        context = {
            'members': members, 'own': own, 'navbar': navbar, 'linked': linked, 'inherited': inherited,
            'groups': {user.id: set(user._get_group_ids()) for user in members},
        }
        result['entries'] = [profile._gec_entry(root, context) for root in roots]
        result['runs_as'] = profile._gec_runs_as(members)
        return result

    def _gec_exposed(self, menu_id):
        """ ({model: exposure entry}, {model: hidden menu opening it}) under ``menu_id``: what Block and Unblock check
        names against. """
        profile = self.sudo()
        exposure = profile._gec_exposure(menu_id)
        exposed, menus = {}, {}
        for entry in exposure['entries']:
            exposed.update({item['model']: item for item in entry['models']})
            root = self.env['ir.ui.menu'].sudo().browse(entry['menu_id'])
            for name, menu in profile._gec_hidden_subtree(root)[0].items():
                menus.setdefault(name, menu)
        return exposed, menus

    def _gec_entry(self, root, context):
        """ The exposure of one hidden menu: its models, each with its first fitting status (blocked, core, shared,
        linked, unused), the line models Block would also block, and the menus that open no known data. """
        Wizard = self.env['gec.access.app.wizard']
        models_of, unknown = self._gec_hidden_subtree(root)
        members, own = context['members'], context['own']
        creators = Wizard._creating_modules(models_of)
        items = []
        for name in models_of:
            readers = members.browse([
                user.id for user in members if self._gec_core_reads(context['groups'][user.id], name)])
            if not readers:
                continue
            perms = own.perms.get(name)
            blocked = perms is not None and not perms[0]
            module = creators.get(name) or ''
            also = context['navbar'].get(name, [])
            links = context['linked'].get(name, [])
            inherits = context['inherited'].get(name, [])
            if blocked:
                status = 'blocked'
            elif self._gec_is_core(name, module):
                status = 'core'
            elif also:
                status = 'shared'
            elif links or inherits:
                status = 'linked'
            else:
                status = 'unused'
            if status == 'blocked':
                readable = self._gec_readable_now(readers, name)
            elif status == 'core':
                readable = []
            else:
                readable = self._gec_still_readable(readers, own, name)
            items.append({
                'model': name,
                'label': self.env['ir.model']._get(name).name,
                'status': status,
                'by': ('menu' if name in own.sources else 'line') if blocked else False,
                'by_menus': list(own.sources.get(name, ())) if blocked else [],
                'also': also,
                'links': links,
                'inherits': inherits,
                'lines': [],
                'still_readable_by': readable,
            })
        by_model = {item['model']: item for item in items}
        for item in items:
            if item['status'] not in ('core', 'blocked'):
                item['lines'] = [
                    by_model[line]['label'] for line in Wizard._line_models(item['model'])
                    if line in by_model and by_model[line]['status'] not in ('core', 'blocked')]
        return {'menu_id': root.id, 'menu': self._gec_menu_path(root), 'unknown': unknown, 'models': items}

    @api.model
    def _gec_is_core(self, model_name, module):
        """ Whether the model is core data that always stays open: made by a framework module or auth_*. """
        return module in CORE_MODULES or module.startswith('auth_')

    @api.model
    def _gec_menu_path(self, menu):
        """ Menu names from the top down to ``menu``, joined with " › " like the rest of the page; not complete_name,
        which joins with "/" that a menu name may contain. """
        ids = [int(part) for part in menu.parent_path.split('/') if part]
        return " › ".join(self.env['ir.ui.menu'].sudo().browse(ids).mapped('name'))

    def _gec_hidden_subtree(self, root):
        """ ({model: menu opening it}, [paths of the menus with no known data]) under ``root``. A window or report
        action gives its model and, unless core data, the models of its lines (they go with a document); other
        actions give none. Transient and abstract models are left out. """
        Wizard = self.env['gec.access.app.wizard']
        opened, unknown = [], []
        menus = self.env['ir.ui.menu'].sudo().with_context(active_test=False).search([('id', 'child_of', root.id)])
        for menu in menus:
            if not menu.action:
                continue
            model_name = self._gec_data_model(menu)
            if not model_name:
                unknown.append(self._gec_menu_path(menu))
                continue
            model = self.env[model_name]
            if model._transient or model._abstract:
                continue
            opened.append((menu, model_name))
        creators = Wizard._creating_modules({model_name for menu, model_name in opened})
        models_of = {}
        for menu, model_name in opened:
            core = self._gec_is_core(model_name, creators.get(model_name) or '')
            for name in (model_name, *(() if core else Wizard._line_models(model_name))):
                models_of.setdefault(name, menu)
        return models_of, unknown

    @api.model
    def _gec_data_model(self, menu):
        """ The model a menu opens through a window or report action, or None. """
        action = menu.sudo().action
        if action and action._name in DATA_ACTIONS:
            return self.env['gec.access.app.wizard']._menu_model(menu)
        return None

    def _gec_own_rules(self, user):
        """ This profile's frozen rules among those that apply to ``user``, or None when it does not apply. """
        rules = self.env['gec.access.profile']._resolve(user.id)
        return next((profile for profile in rules.additive + rules.override if profile.id == self.id), None)

    def _gec_applied_members(self):
        """ Active members the profile applies to: _resolve drops exempt users, Settings users, other companies and an
        archived profile. """
        return self._gec_members().filtered(lambda user: user.active and self._gec_own_rules(user))

    def _gec_navbar(self, members, hidden):
        """ {model: [paths of the menus opening it]} in the members' navbars, less the menus in ``hidden``. A navbar is
        what load_menus gives (groups, our blacklist, orphans), computed without it: it would use the caller's debug
        flag and fill the member's menu cache. Visible ids come once per group and company set, under the member's. """
        Menu = self.env['ir.ui.menu']
        visible, ancestors, ids = {}, {}, set()
        for user in members:
            menu_env = Menu.with_user(user).with_context(allowed_company_ids=user.company_ids.ids)
            key = (frozenset(user._get_group_ids()), frozenset(user.company_ids.ids))
            if key not in visible:
                visible[key] = menu_env._visible_menu_ids(False)
            shown = set(visible[key]) - set(menu_env._load_menus_blacklist())
            for menu in Menu.sudo().browse(shown - set(ancestors)):
                ancestors[menu.id] = [int(part) for part in menu.parent_path.split('/') if part]
            ids.update(menu_id for menu_id in shown if all(parent in shown for parent in ancestors[menu_id]))
        navbar = {}
        for menu in Menu.sudo().browse(sorted(ids - set(hidden))):
            if model_name := self._gec_data_model(menu):
                navbar.setdefault(model_name, []).append(self._gec_menu_path(menu))
        return navbar

    def _gec_links(self, navbar_models, members):
        """ ({model: ["Lead › Tags", ...]}, {model: [labels of its _inherits children]}): the relational fields of the
        models the members open that point at a model, and the models delegating to it; blocking it breaks those
        screens. Fields whose groups no member has are skipped. """
        Model = self.env['ir.model']
        linked = {}
        for name in sorted(navbar_models):
            label = Model._get(name).name
            for field in self.env[name]._fields.values():
                if field.type not in RELATIONAL or field.comodel_name == name:
                    continue
                if field.groups and not any(user.has_groups(field.groups) for user in members):
                    continue
                linked.setdefault(field.comodel_name, set()).add(
                    "%s › %s" % (label, field._description_string(self.env)))
        inherited = {}
        for name, model in self.env.registry.items():
            if model._transient or model._abstract:
                continue
            for parent in model._inherits:
                inherited.setdefault(parent, []).append(Model._get(name).name)
        return {name: sorted(links)[:LINKS_SHOWN] for name, links in linked.items()}, inherited

    @api.model
    def _gec_core_reads(self, group_ids, model_name):
        """ Whether a user of ``group_ids`` reads the model under ir.access alone, as _access_domain computes it (a
        group's read row, and the _inherits parents too); our profiles are left out. """
        model = self.env[model_name]
        if model._check_inherits_access and not all(
                self._gec_core_reads(group_ids, parent) for parent in model._inherits):
            return False
        return any(
            access.group_id in group_ids and access.operation in IN_SELECTION['read']
            for access in self.env['ir.access']._get_all_access().get(model_name, ()))

    def _gec_still_readable(self, readers, own, model_name):
        """ The names of the readers who would still read the model if this profile refused it (their other additive
        profiles allow it): a what-if on their frozen rules, nothing is written. """
        Profile = self.env['gec.access.profile']
        refused = copy.copy(own)
        refused.perms = frozendict({**own.perms, model_name: (False,) * len(PERM_FIELDS)})
        names = []
        for user in readers:
            rules = Profile._resolve(user.id)
            what_if = AccessRules(
                additive=[refused if profile.id == own.id else profile for profile in rules.additive],
                override=[refused if profile.id == own.id else profile for profile in rules.override])
            if what_if.allows(model_name, 'read'):
                names.append(user.name)
        return names

    def _gec_readable_now(self, readers, model_name):
        """ The names of the readers whose rules, this profile's block included, still let them read the model. """
        Profile = self.env['gec.access.profile']
        return [user.name for user in readers if Profile._resolve(user.id).allows(model_name, 'read')]

    def _gec_runs_as(self, members):
        """ [{user, jobs}] for members that automatic jobs run as (crons, rs.ge syncs): a block reaches them with no
        screen to show the error on. """
        jobs = {}
        for cron in self.env['ir.cron'].search([('user_id', 'in', members.ids)]):
            jobs.setdefault(cron.user_id, []).append(cron.cron_name)
        Users = self.env['res.users']
        if hasattr(Users, '_rs_responsible_user'):
            for company in self.env['res.company'].search([]):
                user = Users._rs_responsible_user(company)
                if user in members:
                    jobs.setdefault(user, []).append(self.env._("RS responsible user of %s", company.display_name))
        return [{'user': user.name, 'jobs': names} for user, names in jobs.items()]
