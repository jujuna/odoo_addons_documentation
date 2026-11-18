from odoo import _, models
from odoo.exceptions import UserError
from odoo.addons.base.models.ir_access import IN_SELECTION
from odoo.fields import Domain

from .base_model import READONLY_OWN_RECORDS
from .gec_access_rules import OPERATIONS

RESULT_MODELS = 20


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    def _gec_group_rights(self, model_names, groups=None):
        """ {model: {operation: {'allowed', 'filtered'}}} for what ``groups`` give: by default the granted groups of
        this profile and of an internal user, with all they imply. Read from the ir.access rows as core matches an
        operation (IN_SELECTION). 'filtered': every granting row has a domain; domains are not evaluated. """
        self.ensure_one()
        profile = self.sudo()
        if groups is None:
            groups = profile.granted_group_ids.all_implied_ids | self.env.ref('base.group_user').all_implied_ids
        group_ids = set(groups._ids)
        access = self.env['ir.access']._get_all_access()
        return {
            model_name: {
                operation: dict(zip(('allowed', 'filtered'),
                                    self._gec_group_right(access, group_ids, model_name, operation)))
                for operation in OPERATIONS
            }
            for model_name in model_names
        }

    def _gec_group_right(self, access, group_ids, model_name, operation):
        """ (allowed, filtered) for one model and operation: a row of the groups, and of each _inherits parent. """
        rows = [
            info for info in access.get(model_name, ())
            if info.group_id in group_ids and info.operation in IN_SELECTION[operation]
            and not (isinstance(info.domain, Domain) and info.domain.is_false())
        ]
        if not rows:
            return False, False
        filtered = not any(isinstance(info.domain, Domain) and info.domain.is_true() for info in rows)
        model = self.env[model_name]
        if model._check_inherits_access:
            for parent in model._inherits:
                parent_allowed, parent_filtered = self._gec_group_right(access, group_ids, parent, operation)
                if not parent_allowed:
                    return False, False
                filtered = filtered or parent_filtered
        return True, filtered

    def _gec_result_models(self, menu):
        """ [(model, shared)] for ``menu``: the data it and the menus below it open, in menu-tree order (main menus
        before Configuration ones); shared data is only flagged, never moved. """
        root = int(menu.parent_path.split('/')[0])
        menus = self.env['ir.ui.menu'].sudo().search_fetch([('id', 'child_of', menu.id)], ['sequence'])
        position = {other.id: (other.sequence, other.id) for other in menus}
        entries = self.env['gec.access.profile.menu']._gec_menu_models()
        roots = {}
        for _menu_id, path, model_names, _config in entries:
            for model_name in model_names:
                roots.setdefault(model_name, set()).add(path[-1])
        found = []
        for menu_id, path, model_names, config in entries:
            if menu_id not in position:
                continue
            model = self.env[model_names[0]]
            if model._transient or model._abstract:
                continue
            chain = path[::-1]
            chain = chain[chain.index(menu.id):]
            shared = bool(roots[model._name] - {root})
            found.append((config, tuple(position[step] for step in chain), model._name, shared))
        names = {}
        for _config, _key, model_name, shared in sorted(found):
            names.setdefault(model_name, shared)
        return list(names.items())

    def _gec_exempt(self, user):
        """ Whether no profile limits ``user``: root, the administrator, and Settings users no profile applies to. """
        Profile = self.env['gec.access.profile']
        return user.id in Profile._exempt_user_ids() or (
            user._has_group('base.group_system') and not Profile._resolve(user.id).enabled)

    def _gec_not_applied(self, user, rules):
        """ Why this profile does not limit ``user`` (the resolver skipped it), or False when it applies. """
        profile = self.sudo()
        if profile.id in {applied.id for applied in rules.additive + rules.override}:
            return False
        if not profile.active:
            return _("it is archived")
        if profile.company_id and profile.company_id not in user.company_ids:
            return _("it is set for a company they do not belong to")
        if not profile.apply_to_admin and user._has_group('base.group_system'):
            return _("they are a Settings administrator and 'Apply to Settings Users' is off")
        return _("it is not applied to them")

    def _gec_panel_result(self, menu, user=None):
        """ Per model and operation: can the members do it, who filters the records ('filtered' the group,
        'profile_filtered' the profiles) and what denies it: 'group', 'readonly' (Read Only Everywhere), 'row' (Models
        tab), 'menu' (menu rule) or 'other'. With ``user``: their groups and all their profiles, 'not_applied' says why
        this one is not among them. 'row_id' is the Models line that cancels the menu rules of its model, 'limited_by'
        the menus whose rule would reach it. """
        profile = self.sudo()
        if user and profile._gec_exempt(user):
            return {'models': [], 'more': 0, 'readonly_everywhere': False, 'exempt': True}
        found = profile._gec_result_models(menu)
        shown = found[:RESULT_MODELS]
        own = profile._build_rules(user)
        rules = self.env['gec.access.profile']._resolve(user.id) if user else own
        not_applied = profile._gec_not_applied(user, rules) if user else False
        readonly = rules.has_global_readonly() if user else 'global_readonly' in own.flags
        group_rights = profile._gec_group_rights(
            [model_name for model_name, _shared in shown], user.sudo().all_group_ids if user else None)
        from_menus = profile.menu_rule_ids._gec_rights_by_model()
        lines = {line.model_id.model: line.id for line in profile.model_ids}
        models = []
        for model_name, shared in shown:
            ops = {}
            for operation in OPERATIONS:
                right = group_rights[model_name][operation]
                allowed = right['allowed'] and rules.allows(model_name, operation)
                if not right['allowed']:
                    source = 'group'
                elif allowed:
                    source = False
                elif not_applied or own.allows(model_name, operation) or (
                        user and profile.strictness == 'additive' and any(
                            not other.allows(model_name, operation) for other in rules.override)):
                    source = 'other'
                elif ('global_readonly' in own.flags and operation != 'read'
                      and operation not in READONLY_OWN_RECORDS.get(model_name, ((),))[0]):
                    source = 'readonly'
                else:
                    source = 'menu' if model_name in own.sources else 'row'
                ops[operation] = {
                    'allowed': allowed,
                    'filtered': allowed and right['filtered'],
                    'profile_filtered': allowed and self._gec_profile_filters(rules, model_name, operation, user),
                    'source': source,
                }
            models.append({
                'model': model_name,
                'name': self.env['ir.model']._get(model_name).name,
                'shared': shared,
                'ops': ops,
                'row_id': lines.get(model_name, False),
                'limited_by': list(from_menus[model_name][3]) if model_name in from_menus else [],
            })
        result = {'models': models, 'more': len(found) - len(shown), 'readonly_everywhere': readonly}
        if not_applied:
            result['not_applied'] = not_applied
        return result

    def _gec_profile_filters(self, rules, model_name, operation, user):
        if not user:
            return bool(rules.domain_terms(model_name, operation))
        or_groups, and_groups = rules.record_domains(model_name, operation)
        return bool(or_groups or and_groups)

    def _gec_panel_members(self):
        return self.sudo()._gec_members().filtered(lambda user: user.active and not user.share).sorted('name')

    def gec_panel_result(self, menu_id, user_id):
        self._gec_check_admin()
        self.ensure_one()
        menu = self.env['ir.ui.menu'].sudo().browse(menu_id).exists()
        user = self.env['res.users'].sudo().browse(user_id)
        if not menu:
            raise UserError(_("This menu no longer exists."))
        if user not in self._gec_panel_members():
            raise UserError(_("Pick an active internal user of this profile."))
        return self._gec_panel_result(menu, user)
