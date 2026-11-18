import re

from odoo import api, models
from odoo.tools import frozendict

from .gec_access_allowed import ALLOWED_KINDS
from .login_tools import parse_networks

from .gec_access_profile_model import DOMAIN_FIELD_OF_OPERATION, DOMAIN_FIELDS
from .gec_access_rules import (
    EXEMPT_USER_XMLIDS, FIELD_MODES, FIELD_OPTIONS, FIELD_SWITCHES, GLOBAL_FLAGS, MODEL_FLAGS, NO_RULES, OPERATIONS,
    PERM_FIELDS, AccessRules, ProfileRules,
)


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    @api.model
    @api.ormcache()
    def _gec_user_fields_in_filters(self):
        """ The fields of the user the record filters read (``user.employee_id``): a change must reach the cache. """
        names = set()
        lines = self.env['gec.access.profile.model'].sudo().search([])
        for line in lines:
            for field_name in DOMAIN_FIELDS:
                names.update(re.findall(r'\buser\.(\w+)', line[field_name] or ''))
        return frozenset(names)

    @api.model
    @api.ormcache(cache='stable')
    def _gec_field_copies(self):
        """ {(model, field): copies}: related and inherited fields one hop away, as core copies a field's groups. """
        copies = {}
        for model_name, model in self.env.registry.items():
            for field in model._fields.values():
                if field.related and field.related_field:
                    source = (field.related_field.model_name, field.related_field.name)
                    copies[source] = copies.get(source, ()) + ((model_name, field.name),)
        return frozendict(copies)

    @api.model
    def _gec_eval_context(self):
        return dict(self.env['ir.access']._eval_context(), uid=self.env.uid)

    @api.model
    def _exempt_user_ids(self):
        data = self.env['ir.model.data'].sudo()
        ids = (data._xmlid_to_res_id(xmlid, raise_if_not_found=False) for xmlid in EXEMPT_USER_XMLIDS)
        return tuple(user_id for user_id in ids if user_id)

    def _allowed_filters(self, user=None):
        """ {model: domain} of the allowed records of this profile for ``user``. """
        self.ensure_one()
        allowed, per_user = {}, set()
        for line in self.allowed_ids:
            if line.kind not in ALLOWED_KINDS:
                continue
            ids = allowed.setdefault(line.kind, set())
            if line.per_user:
                per_user.add(line.kind)
            elif line.res_id:
                ids.add(line.res_id)
        if user and per_user:
            for line in user.sudo().access_allowed_ids:
                if line.kind in per_user and line.res_id:
                    allowed[line.kind].add(line.res_id)
        filters = {}
        Allowed = self.env['gec.access.allowed']
        for kind, ids in allowed.items():
            for model_name, domain in Allowed._filters(kind, ids).items():
                filters[model_name] = (
                    "['&'] + %s + %s" % (filters[model_name], domain) if model_name in filters else domain)
        return filters

    def _build_rules(self, user=None):
        """ Freeze this profile into a ProfileRules; ``user`` supplies the allowed records ticked "each user's own". """
        self.ensure_one()
        profile = self.sudo()

        flags = frozenset(flag for flag in GLOBAL_FLAGS if profile[flag])

        perms, domains, model_flags = {}, {}, {}
        for line in profile.model_ids:
            model_name = line.model_id.model
            if not model_name:
                continue
            perms[model_name] = tuple(bool(line[fname]) for fname in PERM_FIELDS)
            general = (line.domain or '').strip()
            for operation in OPERATIONS:
                specific = (line[DOMAIN_FIELD_OF_OPERATION[operation]] or '').strip()
                terms = tuple(term for term in (general, specific) if term)
                if terms:
                    domains[(model_name, operation)] = terms
            present = frozenset(flag for flag in MODEL_FLAGS if line[flag])
            if present:
                model_flags[model_name] = present

        # rights set on menus, for the data without a line of its own
        sources = {}
        for model_name, (rights, by_operation, present, menus) in profile.menu_rule_ids._gec_rights_by_model().items():
            if model_name in perms:
                continue
            sources[model_name] = menus
            perms[model_name] = rights
            for operation, terms in by_operation.items():
                domains[(model_name, operation)] = terms
            if present:
                model_flags[model_name] = present

        for model_name, domain in profile._allowed_filters(user).items():
            for operation in OPERATIONS:
                domains[(model_name, operation)] = domains.get((model_name, operation), ()) + (domain,)

        field_modes, field_options, field_domains, field_conditions = {}, {}, {}, {}
        lined = set()
        for line in profile.field_ids:
            model_name, field_name = line.model_id.model, line.field_id.name
            if not (model_name and field_name):
                continue
            key = (model_name, field_name)
            lined.add(key)
            condition = (line.condition or '').strip()
            if line.mode != 'keep' and condition:
                field_conditions[key] = field_conditions.get(key, ()) + ((line.mode, condition),)
            elif line.mode != 'keep':
                field_modes[key] = line.mode
            options = frozenset(option for option in FIELD_OPTIONS if line[option])
            if options:
                field_options[key] = options
            if (line.field_domain or '').strip():
                field_domains[key] = line.field_domain.strip()
        for switch, switch_fields in FIELD_SWITCHES:
            if not profile[switch]:
                continue
            for model_name, field_name in switch_fields:
                if model_name in self.env and field_name in self.env[model_name]._fields:
                    key = (model_name, field_name)
                    if FIELD_MODES.index(field_modes.get(key)) < FIELD_MODES.index('hide'):
                        field_modes[key] = 'hide'
        # hidden, read-only and No Export hold on the copies of a field (as core copies groups) unless they have a line
        copies = self._gec_field_copies()
        # a field locked under a condition: copies on its model take it; copies on another are locked always (its views
        # cannot evaluate the condition)
        for source, lines in list(field_conditions.items()):
            locking = tuple(line for line in lines if line[0] in ('hide', 'readonly'))
            strongest = max((line_mode for line_mode, _condition in locking), key=FIELD_MODES.index, default=None)
            pending, seen = [source], {source}
            while strongest and pending:
                for copy in copies.get(pending.pop(), ()):
                    if copy in lined or copy in seen:
                        continue
                    seen.add(copy)
                    pending.append(copy)
                    # the record itself shows the copy only when its path names no other record (the image sizes)
                    related = self.env[copy[0]]._fields[copy[1]].related or ''
                    if copy[0] == source[0] and '.' not in (related if isinstance(related, str) else '.'.join(related)):
                        field_conditions[copy] = field_conditions.get(copy, ()) + locking
                    elif FIELD_MODES.index(field_modes.get(copy)) < FIELD_MODES.index(strongest):
                        field_modes[copy] = strongest
        copy_sources = {key for key, mode in field_modes.items() if mode in ('hide', 'readonly')}
        copy_sources |= {key for key, options in field_options.items() if 'no_export' in options}
        for source in copy_sources:
            mode = field_modes.get(source) if field_modes.get(source) in ('hide', 'readonly') else None
            no_export = 'no_export' in field_options.get(source, ())
            pending, seen = [source], {source}
            while pending:
                for copy in copies.get(pending.pop(), ()):
                    if copy in lined or copy in seen:
                        continue
                    seen.add(copy)
                    pending.append(copy)
                    if FIELD_MODES.index(field_modes.get(copy)) < FIELD_MODES.index(mode):
                        field_modes[copy] = mode
                    if no_export:
                        field_options[copy] = field_options.get(copy, frozenset()) | {'no_export'}

        elements = frozenset(
            (line.model_id.model, line.element_type, line.element_name or '')
            for line in profile.element_ids
            if line.model_id.model and not (line.condition or '').strip()
        )
        element_conditions = {
            (line.model_id.model, line.element_type, line.element_name or ''): line.condition.strip()
            for line in profile.element_ids
            if line.model_id.model and (line.condition or '').strip()
        }

        buttons = tuple(
            (line.model_id.model, line.view_type, line.button_type,
             line.button_name, line.button_id or '', line.mode, (line.condition or '').strip())
            for line in profile.button_ids
            if line.model_id.model and line.button_name
        )

        menus = frozenset()
        if profile.hidden_menu_ids:
            menus = frozenset(self.env['ir.ui.menu'].sudo().with_context(active_test=False).search(
                [('id', 'child_of', profile.hidden_menu_ids.ids)]
            )._ids)

        return ProfileRules(
            id=profile.id,
            name=profile.name,
            flags=flags,
            perms=frozendict(perms),
            domains=frozendict(domains),
            menus=menus,
            buttons=buttons,
            field_modes=frozendict(field_modes),
            field_options=frozendict(field_options),
            field_domains=frozendict(field_domains),
            elements=elements,
            reports=frozenset(profile.hidden_report_ids._ids),
            actions=frozenset(profile.hidden_action_ids._ids + profile.hidden_window_action_ids._ids),
            model_flags=frozendict(model_flags),
            home_action=profile.home_action_id.id or None,
            login_slots=tuple(
                (int(slot.dayofweek), slot.hour_from, slot.hour_to) for slot in profile.login_slot_ids),
            login_tz=profile.login_tz or 'UTC',
            networks=parse_networks(profile.allowed_ips),
            field_conditions=frozendict(field_conditions),
            element_conditions=frozendict(element_conditions),
            sources=frozendict(sources),
        )

    @api.model
    @api.ormcache('uid')
    def _resolve(self, uid):
        """ The profiles that apply to ``uid``, frozen and cached per user. """
        if uid in self._exempt_user_ids():
            return NO_RULES
        user = self.env['res.users'].sudo().browse(uid)
        if not user.exists():
            return NO_RULES
        profiles = self._gec_profiles_of(user).filtered('active')
        if profiles:
            # follows the user's companies, not the switcher: core caches menus per user without the company in the key
            companies = set(user.company_ids._ids)
            profiles = profiles.filtered(lambda profile: not profile.company_id or profile.company_id.id in companies)
        if profiles and user._has_group('base.group_system'):
            profiles = profiles.filtered('apply_to_admin')
        if not profiles:
            return NO_RULES
        return AccessRules(
            additive=[p._build_rules(user) for p in profiles if p.strictness == 'additive'],
            override=[p._build_rules(user) for p in profiles if p.strictness == 'override'],
        )

    @api.model
    def _current_rules(self):
        """ The rules of the current user, or NO_RULES when nothing applies. """
        if self.env.su:
            return NO_RULES
        return self._resolve(self.env.uid)
