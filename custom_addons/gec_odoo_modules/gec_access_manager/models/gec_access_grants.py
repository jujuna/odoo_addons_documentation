from odoo import SUPERUSER_ID, Command, _, api, models
from odoo.exceptions import AccessError, UserError

from .gec_access_rules import UNGRANTABLE_GROUPS

# the groups that make a user internal, public or portal: never granted by a profile
USER_TYPE_GROUPS = ('base.group_user', 'base.group_portal', 'base.group_public', 'base.group_user_regular')
HOLDERS_SHOWN = 5
ADDS_SHOWN = 5


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    def action_gec_grants(self):
        self._gec_check_admin()
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'gec_access_manager.grants',
            'name': _("What they get"),
            'context': {'active_id': self.id, 'active_model': self._name},
        }

    @api.model
    def _gec_grants_groups(self, xmlids):
        """ The groups of these XML ids that exist, with sudo. """
        data = self.env['ir.model.data'].sudo()
        ids = (data._xmlid_to_res_id(xmlid, raise_if_not_found=False) for xmlid in xmlids)
        return self.env['res.groups'].sudo().browse([group_id for group_id in ids if group_id])

    @api.model
    def _gec_grants_technical_groups(self):
        return self.sudo().with_context(active_test=False).search([]).group_id

    @api.model
    def _gec_grants_unrestricted(self):
        """ Whether the current user may grant any group: the superuser and Settings users, as in _gec_check_editor. """
        return self.env.uid == SUPERUSER_ID or self.env.user._is_system()

    def _gec_grants_offered(self):
        """ Core's hierarchy less what _check_granted_groups refuses, user types, share and Settings feature groups. """
        Groups = self.env['res.groups'].sudo()
        forbidden = self._gec_grants_groups(UNGRANTABLE_GROUPS)
        switches = Groups.concat(implied for _name, _groups, implied
                                 in self.env['res.config.settings'].sudo()._get_classified_fields()['group'])
        groups = Groups.browse(Groups._get_view_group_hierarchy()['groups'])
        groups -= (forbidden.all_implied_by_ids | self._gec_grants_groups(USER_TYPE_GROUPS) | switches
                   | self._gec_grants_technical_groups().all_implied_by_ids
                   | self._gec_grants_groups(['base.group_user']).all_implied_ids
                   | self._gec_grants_groups(['base.default_user_group', 'base.group_no_one',
                                             'base.group_sanitize_override']))
        return groups.filtered(lambda group: not group.share)

    def _gec_grants_layout(self):
        """ The offered groups for the page: ([(privilege, level ids in core order, ladder)], extra ids by name).
        ``ladder`` is true when each level implies the one before it: not so for Accounting or Payroll. """
        hierarchy = self.env['res.groups'].sudo()._get_view_group_hierarchy()
        groups = hierarchy['groups']
        offered_ids = set(self._gec_grants_offered().ids)
        privileges = []
        for privilege in hierarchy['privileges'].values():
            levels = [group_id for group_id in privilege['group_ids'] if group_id in offered_ids]
            if levels:
                ladder = all(before in groups[level]['all_implied_ids'] for before, level in zip(levels, levels[1:]))
                privileges.append((privilege, levels, ladder))
        extras = sorted((group_id for group_id in offered_ids if not groups[group_id]['privilege_id']),
                        key=lambda group_id: groups[group_id]['name'].lower())
        return privileges, extras

    def _gec_grants_locked(self, group_ids):
        """ The ids among ``group_ids`` the current user cannot give: a Settings user locks none, anyone else needs
        the group and its implied groups themselves (the rule of _gec_check_editor). """
        if self._gec_grants_unrestricted():
            return set()
        groups = self.env['res.groups'].sudo()._get_view_group_hierarchy()['groups']
        held = set(self.env.user.all_group_ids.ids)
        return {group_id for group_id in group_ids if not set(groups[group_id]['all_implied_ids']) <= held}

    def _gec_grants_members(self):
        """ (direct users, users through its Odoo groups) of the profile: active, internal, not exempt, in its company.
        Only the direct users get what the profile grants; the others carry its restrictions (_group_values). """
        self.ensure_one()
        profile = self.sudo()
        exempt = self._exempt_user_ids()
        direct = profile._gec_direct_users().filtered(
            lambda user: user.active and not user.share and user.id not in exempt)
        via_groups = profile._gec_in_company(profile.group_ids.all_user_ids).filtered(
            lambda user: user.active and not user.share and user.id not in exempt) - direct
        return direct, via_groups

    @api.model
    def _gec_grants_own_groups(self, users, technical=None):
        """ {user id: group ids} the users hold on their own form, implied included, less ``technical`` (by default
        the technical groups of all the profiles). """
        if technical is None:
            technical = self._gec_grants_technical_groups()
        return {user.id: set((user.group_ids - technical).all_implied_ids.ids) for user in users.sudo()}

    def _gec_grants_apps(self):
        """ {privilege id: (top menu, gates, is_gate, position)}: a privilege belongs to the first app it opens (a gate,
        as _gec_app_gates reads them), else to the first app whose menus its groups gate (is_gate false). The Access
        Manager app is left out, as in gec_menu_tree. """
        Menu = self.env['ir.ui.menu'].sudo()
        roots = Menu.search([('parent_id', '=', False)])
        app = self.env.ref('gec_access_manager.gec_access_root_menu', raise_if_not_found=False)
        if app:
            roots -= app
        menus = Menu.search([('id', 'child_of', roots.ids)])
        menus.fetch(['group_ids'])
        menu_ids = {}
        for menu in menus:
            menu_ids.setdefault(int(menu.parent_path.split('/')[0]), []).append(menu.id)
        apps, gated = {}, {}
        for position, root in enumerate(roots):
            gates = root.group_ids or self._gec_app_gates(root)
            for privilege in gates.privilege_id:
                apps.setdefault(privilege.id, (root, gates, True, position))
            for privilege in Menu.browse(menu_ids.get(root.id, [])).group_ids.privilege_id:
                gated.setdefault(privilege.id, (root, gates, False, position))
        for privilege_id, entry in gated.items():
            apps.setdefault(privilege_id, entry)
        return apps

    def _gec_grants_adds(self, privileges, apps):
        """ {level id: [labels of the first menus it adds, count of the rest]}: menus shown with its implied groups and
        not without it, as core shows them; a hint: hidden menus and menus under an archived one are not listed. """
        groups = self.env['res.groups'].sudo()._get_view_group_hierarchy()['groups']
        Menu = self.env['ir.ui.menu'].sudo()
        app = self.env.ref('gec_access_manager.gec_access_root_menu', raise_if_not_found=False)
        hidden = set(self.sudo().hidden_menu_ids.ids)
        active = set(Menu.search([]).ids)
        no_one = set(self._gec_grants_groups(['base.group_no_one']).ids)
        baseline = set(self._gec_grants_groups(['base.group_user']).all_implied_ids.ids) - no_one
        paths = {}
        for menu in Menu.search([('action', '!=', False)]):
            path = [int(part) for part in menu.parent_path.split('/') if part]
            if not ((app and path[0] == app.id) or hidden & set(path) or not set(path) <= active):
                paths[menu.id] = path
        node_ids = sorted({node_id for path in paths.values() for node_id in path})
        nodes = {node['id']: node for node in Menu.browse(node_ids).read(['name', 'sequence', 'group_ids'])}
        gates = {menu_id: [set(nodes[node_id]['group_ids']) for node_id in path if nodes[node_id]['group_ids']]
                 for menu_id, path in paths.items()}
        shown = {}

        def visible(group_ids):
            key = frozenset(set(group_ids) | baseline) - no_one
            if key not in shown:
                shown[key] = {menu_id for menu_id, sets in gates.items() if all(gate & key for gate in sets)}
            return shown[key]

        result = {}
        for privilege, levels, ladder in privileges:
            root = apps.get(privilege['id'], (False,))[0]
            for position, level in enumerate(levels):
                implied = set(groups[level]['all_implied_ids'])
                if ladder:
                    below = levels[position - 1:position] if position else []
                else:
                    below = [other for other in levels if other != level and other in implied]
                lower = set().union(*(groups[other]['all_implied_ids'] for other in below))
                added = visible(implied) - visible(lower)
                labels = {}
                for menu_id in sorted(added, key=lambda mid: [(nodes[nid]['sequence'], nid) for nid in paths[mid]]):
                    path = paths[menu_id]
                    depth = 2 if root and path[0] == root.id else 1
                    labels.setdefault(' › '.join(nodes[node_id]['name'] for node_id in path[:depth]), path[0])
                ordered = sorted(labels, key=lambda label: not root or labels[label] != root.id)
                result[level] = [ordered[:ADDS_SHOWN], max(len(ordered) - ADDS_SHOWN, 0)]
        return result

    def _gec_grants_rows(self, direct):
        """ (rows, extras) for the direct users; rows follow the user form: by category, then privilege, those without
        a category last under "Other". A row that opens its app counts the users who open it without this profile. """
        profile = self.sudo()
        hierarchy = self.env['res.groups'].sudo()._get_view_group_hierarchy()
        groups = hierarchy['groups']
        places = {
            privilege_id: (index, position, category['id'], category['name'])
            for index, category in enumerate(hierarchy['categories'])
            for position, privilege_id in enumerate(category['privilege_ids'])
        }
        other = (len(hierarchy['categories']), 0, 'other', _("Other"))
        privileges, extra_ids = self._gec_grants_layout()
        offered_ids = {*extra_ids, *(level for _privilege, levels, _ladder in privileges for level in levels)}
        locked = self._gec_grants_locked(offered_ids)
        own = self._gec_grants_own_groups(direct)
        without = self._gec_grants_own_groups(direct, profile.group_id)
        apps = self._gec_grants_apps()
        adds = self._gec_grants_adds(privileges, apps)
        hidden = set(profile.hidden_menu_ids.ids)

        def describe(group_id):
            return {
                'id': group_id,
                'name': groups[group_id]['name'],
                'comment': groups[group_id]['comment'] or '',
                'implies': sorted(other for other in groups[group_id]['all_implied_ids']
                                  if other != group_id and other in offered_ids),
                'locked': group_id in locked,
                'own_count': sum(1 for held in own.values() if group_id in held),
            }

        rows = []
        for privilege, levels, ladder in privileges:
            root, gates, is_gate, _position = apps.get(privilege['id'], (False, False, False, 0))
            gate_ids = set(gates.ids) if is_gate else set()
            index, position, category_id, category_name = places.get(privilege['id'], other)
            row = {
                'privilege_id': privilege['id'],
                'name': privilege['name'],
                'category': {'id': category_id, 'name': category_name},
                'description': privilege['description'] or '',
                'app': {'menu_id': root.id, 'name': root.name, 'is_gate': is_gate} if root else False,
                'section': 'more' if not root else 'other' if root.id in hidden else 'seen',
                'ladder': ladder,
                'levels': [dict(
                    describe(level),
                    opens_app=bool(gate_ids & set(groups[level]['all_implied_ids'])),
                    adds=adds[level][0], adds_more=adds[level][1],
                ) for level in levels],
            }
            if is_gate:
                row.update(gate_ids=sorted(gate_ids),
                           open_without=sum(1 for held in without.values() if held & gate_ids))
            rows.append((index, position, privilege['name'].lower(), row))
        rows.sort(key=lambda entry: entry[:3])
        return [entry[3] for entry in rows], [describe(group_id) for group_id in extra_ids]

    def gec_grants_data(self):
        """ Everything the page shows for this profile, read only; {'missing': True} when it was deleted. ``others`` are
        granted groups the page does not offer, so they can be removed; ``readonly_reason`` is the editor's refusal. """
        self._gec_check_admin()
        profile = self.exists()
        if not profile:
            return {'missing': True}
        profile.ensure_one()
        direct, via_groups = profile._gec_grants_members()
        try:
            profile._gec_check_editor()
            refusal = ''
        except AccessError as error:
            refusal = str(error)
        rows, extras = profile._gec_grants_rows(direct)
        offered_ids = {*(extra['id'] for extra in extras), *(level['id'] for row in rows for level in row['levels'])}
        others = profile.sudo().granted_group_ids.filtered(lambda group: group.id not in offered_ids)
        return {
            'profile': {
                'id': profile.id,
                'name': profile.name,
                'active': profile.active,
                'editable': not refusal,
                'readonly_reason': refusal or '',
                'direct': [{'id': user.id, 'name': user.name} for user in direct[:HOLDERS_SHOWN]],
                'n': len(direct),
                'via_groups': len(via_groups),
            },
            'granted_ids': profile.sudo().granted_group_ids.ids,
            'rows': rows,
            'extras': extras,
            'others': [{'id': group.id, 'name': group.full_name}
                       for group in sorted(others, key=lambda group: group.full_name.lower())],
        }

    def gec_grants_from_user(self, user_id):
        """ Groups to add to copy a user's access (the highest level per privilege); levels the editor lacks go to
        ``skipped`` by name. Writes nothing. """
        self._gec_check_admin()
        user = self.env['res.users'].sudo().browse(user_id).exists()
        if not user or not user.active or user.share:
            raise UserError(_("Pick an active internal user."))
        groups = self.env['res.groups'].sudo()._get_view_group_hierarchy()['groups']
        privileges, extras = self._gec_grants_layout()
        held = self._gec_grants_own_groups(user)[user.id]
        picked = []
        for _privilege, levels, ladder in privileges:
            mine = [level for level in levels if level in held]
            if ladder:
                picked += mine[-1:]
            else:
                picked += [level for level in mine if not any(
                    level in groups[other]['all_implied_ids'] for other in mine if other != level)]
        picked += [group_id for group_id in extras if group_id in held]
        picked = [group_id for group_id in picked if not any(
            group_id in groups[other]['all_implied_ids'] for other in picked if other != group_id)]
        locked = self._gec_grants_locked(picked)
        Groups = self.env['res.groups'].sudo()
        return {
            'add': [group_id for group_id in picked if group_id not in locked],
            'skipped': [Groups.browse(group_id).full_name for group_id in picked if group_id in locked],
        }

    def gec_grants_save(self, add_ids, remove_ids):
        """ Add and remove only the groups the page changed, so what it does not show, or what was saved elsewhere
        meanwhile, stays. The write is the real user's: the checks of the profile run as for the form. """
        self._gec_check_admin()
        self.ensure_one()
        add = set(add_ids or [])
        if add - set(self._gec_grants_offered().ids):
            raise UserError(_("You cannot give this group here."))
        remove = set(remove_ids or []) & set(self.sudo().granted_group_ids.ids)
        commands = [Command.link(group_id) for group_id in sorted(add)]
        commands += [Command.unlink(group_id) for group_id in sorted(remove)]
        if commands:
            self.write({'granted_group_ids': commands})
        return self.gec_grants_data()
