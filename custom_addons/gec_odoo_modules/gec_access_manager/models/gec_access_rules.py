import ipaddress
from zoneinfo import ZoneInfo

from .base_model import READONLY_OWN_RECORDS
from .value_filters import and_domains, or_domains

OPERATIONS = ('read', 'write', 'create', 'unlink')
OPERATION_INDEX = {operation: index for index, operation in enumerate(OPERATIONS)}
PERM_FIELDS = ('perm_read', 'perm_write', 'perm_create', 'perm_unlink')

# Never restricted: locking them out would leave the database with no way back in.
EXEMPT_USER_XMLIDS = ('base.user_root', 'base.user_admin')

GLOBAL_FLAG_OF_MODEL_FLAG = {
    'hide_chatter': 'hide_chatter_all',
    'hide_export': 'block_export',
    'hide_import': 'block_import',
    'hide_archive': 'block_archive',
    'hide_duplicate': 'block_duplicate',
    'hide_print': 'hide_print_all',
    'hide_action_menu': 'hide_action_menu_all',
    'hide_send_message': 'hide_send_message_all',
    'hide_followers': 'hide_followers_all',
    'hide_attachments': 'hide_attachments_all',
}
# chatter parts a profile can hide, and the form class read by chatter_parts.scss
CHATTER_CLASSES = (
    ('hide_send_message', 'o_gec_hide_send_message'),
    ('hide_followers', 'o_gec_hide_followers'),
    ('hide_attachments', 'o_gec_hide_attachments'),
)
MODEL_FLAGS = tuple(GLOBAL_FLAG_OF_MODEL_FLAG)
GLOBAL_FLAGS = (
    'global_readonly', 'hide_chatter_all', 'block_export', 'block_import',
    'block_archive', 'block_duplicate', 'hide_activities', 'hide_settings_menu',
    'lock_statusbar', 'block_rpc', 'block_developer_mode', 'block_login',
    'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all',
    'hide_attachments_all', 'single_session', 'block_custom_filter', 'block_custom_group',
    'block_favorites', 'block_properties', 'block_apps',
)
# search and form switches: a body class hides them in the web client (static/src/search); the server refuses writes
BODY_CLASSES = {
    'block_custom_filter': 'o_gec_no_custom_filter',
    'block_custom_group': 'o_gec_no_custom_group',
    'block_favorites': 'o_gec_no_favorites',
    'block_properties': 'o_gec_no_properties',
}

FIELD_MODES = (None, 'required', 'readonly', 'hide')  # ordered by severity
HIDE_MODES = ('hide', 'hide_block')
BLOCK_MODES = ('block', 'hide_block')
# what the hidden group of a profile carries (_group_values)
GROUP_FIELDS = frozenset({'name', 'user_ids', 'active', 'company_id', 'granted_group_ids'})
# never granted by a profile: its users would become administrators or access managers it cannot undo
UNGRANTABLE_GROUPS = ('base.group_system', 'base.group_erp_manager', 'gec_access_manager.group_access_manager',
                      'base.group_portal', 'base.group_public')

# Fields hidden by two switches (apps not installed skipped); reports and mirror fields still show them: hide those too.
COST_FIELDS = (
    ('product.template', 'standard_price'),
    ('product.product', 'standard_price'),
    ('product.product', 'avg_cost'),
    ('product.product', 'total_value'),
    ('sale.order', 'margin'),
    ('sale.order', 'margin_percent'),
    ('sale.order.line', 'purchase_price'),
    ('sale.order.line', 'margin'),
    ('sale.order.line', 'margin_percent'),
    ('pos.order', 'margin'),
    ('pos.order', 'margin_percent'),
    ('pos.order.line', 'total_cost'),
    ('pos.order.line', 'margin'),
    ('pos.order.line', 'margin_percent'),
    ('stock.quant', 'value'),
    ('stock.move', 'price_unit'),
    ('stock.move', 'value'),
    ('stock.move', 'remaining_value'),
    ('product.value', 'value'),
    ('product.value', 'old_value'),
    ('product.value', 'new_value'),
    ('product.value', 'current_value'),
)
SALE_PRICE_FIELDS = (
    ('product.template', 'list_price'),
    ('product.product', 'list_price'),
    ('product.product', 'lst_price'),
    ('sale.order', 'amount_untaxed'),
    ('sale.order', 'amount_tax'),
    ('sale.order', 'amount_total'),
    ('sale.order', 'tax_totals'),
    ('sale.order.line', 'price_unit'),
    ('sale.order.line', 'price_subtotal'),
    ('sale.order.line', 'price_tax'),
    ('sale.order.line', 'price_total'),
    ('sale.order.line', 'price_reduce_taxexcl'),
    ('sale.order.line', 'price_reduce_taxinc'),
    ('sale.order.line', 'discount'),
)
FIELD_SWITCHES = (('hide_costs', COST_FIELDS), ('hide_sale_prices', SALE_PRICE_FIELDS))

# the tags that start a view (or an x2many's nested view); in REMOVED_IN_VIEWS a hidden field is removed, not hidden
VIEW_ROOTS = frozenset({
    'form', 'list', 'tree', 'kanban', 'search', 'graph', 'pivot', 'calendar', 'gantt',
    'cohort', 'map', 'activity', 'hierarchy',
})
REMOVED_IN_VIEWS = frozenset({'search', 'graph', 'pivot', 'cohort', 'gantt', 'map'})
FIELD_OPTIONS = ('no_open', 'no_create', 'no_export')

ACTIVITY_FIELDS = frozenset({'activity_ids', 'activity_state', 'activity_date_deadline'})
ACTIVITY_WIDGETS = frozenset({'list_activity', 'mail_activity'})

# the global switches that make a view worth rewriting
VIEW_FLAGS = frozenset({
    'hide_chatter_all', 'block_export', 'block_import', 'block_archive',
    'block_duplicate', 'hide_activities', 'lock_statusbar',
    'hide_send_message_all', 'hide_followers_all', 'hide_attachments_all',
})


def or_conditions(conditions):
    if 'True' in conditions:
        return 'True'
    conditions = [condition for condition in conditions if condition != 'False']
    if not conditions:
        return 'False'
    return conditions[0] if len(conditions) == 1 else ' or '.join('(%s)' % c for c in conditions)


def and_conditions(conditions):
    if 'False' in conditions:
        return 'False'
    conditions = [condition for condition in conditions if condition != 'True']
    if not conditions:
        return 'True'
    return conditions[0] if len(conditions) == 1 else ' and '.join('(%s)' % c for c in conditions)


class ProfileRules:
    """ Frozen rules of one profile: no recordset or environment, as the ormcache outlives the cursor. """
    __slots__ = ('id', 'name', 'flags', 'perms', 'domains', 'menus', 'buttons',
                 'field_modes', 'field_options', 'field_domains', 'elements',
                 'reports', 'actions', 'model_flags', 'home_action',
                 'login_slots', 'login_tz', 'networks', 'field_conditions', 'element_conditions',
                 'sources')

    def __init__(self, id, name, flags, perms, domains, menus, buttons,
                 field_modes, field_options, field_domains, elements,
                 reports, actions, model_flags, home_action=None,
                 login_slots=(), login_tz='UTC', networks=(), field_conditions=None,
                 element_conditions=None, sources=None):
        self.id = id
        self.name = name
        self.flags = flags                # frozenset of global flag names
        self.perms = perms                # {model: (read, write, create, unlink)}
        self.domains = domains            # {(model, operation): (terms...)}
        self.menus = menus                # frozenset of menu ids, descendants included
        self.buttons = buttons            # tuple of button rules
        self.field_modes = field_modes    # {(model, field): mode}
        self.field_options = field_options  # {(model, field): frozenset}
        self.field_domains = field_domains  # {(model, field): domain string}
        self.elements = elements          # frozenset of (model, type, name)
        self.reports = reports            # frozenset of ir.actions.report ids
        self.actions = actions            # frozenset of action ids (server or window)
        self.model_flags = model_flags    # {model: frozenset of model flag names}
        self.home_action = home_action    # window action id, or None
        self.login_slots = login_slots    # ((weekday, hour_from, hour_to), ...)
        self.login_tz = login_tz
        self.networks = networks          # (ipaddress network, ...)
        self.field_conditions = field_conditions or {}      # {(model, field): ((mode, condition), ...)}
        self.element_conditions = element_conditions or {}  # {(model, 'page', name): condition}
        self.sources = sources or {}      # {model: names of the menus its rights come from}

    def login_refusal(self, now, address):
        """ Why this profile refuses a sign-in at ``now`` (aware, UTC) from ``address``, or None. """
        if self.login_slots:
            local = now.astimezone(ZoneInfo(self.login_tz or 'UTC'))
            hour = local.hour + local.minute / 60
            if not any(day == local.weekday() and start <= hour < end for day, start, end in self.login_slots):
                return 'hours'
        if self.networks:
            try:
                ip = ipaddress.ip_address(address or '')
            except ValueError:
                return 'network'
            if not any(ip in network for network in self.networks):
                return 'network'
        return None

    def allows(self, model_name, operation, wizard=False):
        """ Read Only Everywhere spares wizards and the READONLY_OWN_RECORDS operations (limited to own records). """
        if operation != 'read' and 'global_readonly' in self.flags and not wizard:
            if operation not in READONLY_OWN_RECORDS.get(model_name, ((),))[0]:
                return False
        perms = self.perms.get(model_name)
        if perms is None:
            return True
        return perms[OPERATION_INDEX[operation]]

    def model_flag(self, model_name, flag):
        if GLOBAL_FLAG_OF_MODEL_FLAG[flag] in self.flags:
            return True
        return flag in self.model_flags.get(model_name, ())

    def domain_terms(self, model_name, operation):
        """ The domain strings this profile imposes, to be ANDed together. """
        return self.domains.get((model_name, operation), ())

    def field_mode(self, model_name, field_name):
        return self.field_modes.get((model_name, field_name))

    def field_option(self, model_name, field_name, option):
        return option in self.field_options.get((model_name, field_name), ())

    def field_domain(self, model_name, field_name):
        return self.field_domains.get((model_name, field_name))

    def hides_element(self, model_name, element_type, element_name):
        return (model_name, element_type, element_name or '') in self.elements

    def _matching_buttons(self, model_name, button_type, name, view_type=None, button_id=None):
        """ (mode, condition) of the button rules matching. """
        for rule in self.buttons:
            if rule[0] != model_name or rule[2] != button_type or rule[3] != name:
                continue
            if view_type is not None and rule[1] != 'any' and rule[1] != view_type:
                continue
            if button_id is not None and rule[4] and rule[4] != button_id:
                continue
            yield rule[5], rule[6]

    def button_condition(self, modes, model_name, button_type, name, view_type=None, button_id=None):
        """ 'True', 'False' or the condition of the rules of ``modes``; controllers pass no view or button id. """
        return or_conditions([
            condition or 'True'
            for mode, condition in self._matching_buttons(model_name, button_type, name, view_type, button_id)
            if mode in modes
        ])

    def hides_button(self, model_name, view_type, button_type, name, button_id):
        return self.button_condition(HIDE_MODES, model_name, button_type, name, view_type, button_id) == 'True'

    def blocks_button(self, model_name, button_type, name):
        return self.button_condition(BLOCK_MODES, model_name, button_type, name) == 'True'

    def field_condition(self, model_name, field_name, mode):
        """ 'True', 'False' or the condition under which the field is at least in ``mode`` (required: exactly). """
        counted = ('required',) if mode == 'required' else FIELD_MODES[FIELD_MODES.index(mode):]
        if self.field_mode(model_name, field_name) in counted:
            return 'True'
        return or_conditions([
            condition for line_mode, condition in self.field_conditions.get((model_name, field_name), ())
            if line_mode in counted
        ])

    def page_condition(self, model_name, name):
        if self.hides_element(model_name, 'page', name):
            return 'True'
        return self.element_conditions.get((model_name, 'page', name or ''), 'False')

    def blocks_action(self, action_id):
        """ /web/action/load carries only the id, so the rule's model is not matched. """
        # no record is named when loading an action, so a conditional rule can only hide the button here
        key = str(action_id)
        return any(
            rule[5] in BLOCK_MODES and not rule[6]
            for rule in self.buttons
            if rule[2] == 'action' and rule[3] == key
        )


class AccessRules:
    """ Additive profiles: allowed if any allows, hidden only if all hide. Override profiles always subtract. """
    __slots__ = ('additive', 'override', 'view_flags', 'view_models', '_memo')

    def __init__(self, additive=(), override=()):
        self.additive = tuple(additive)
        self.override = tuple(override)
        self._memo = {}
        profiles = self.additive + self.override
        self.view_flags = any(profile.flags & VIEW_FLAGS for profile in profiles)
        self.view_models = frozenset(
            name
            for profile in profiles
            for name in (
                *profile.model_flags,
                *(model for model, _field in profile.field_modes),
                *(model for model, _field in profile.field_conditions),
                *(model for model, _field in profile.field_options),
                *(model for model, _field in profile.field_domains),
                *(rule[0] for rule in profile.buttons),
                *(element[0] for element in profile.elements),
                *(element[0] for element in profile.element_conditions),
            )
        )

    @property
    def enabled(self):
        return bool(self.additive or self.override)

    def _hidden(self, predicate):
        if any(predicate(profile) for profile in self.override):
            return True
        return bool(self.additive) and all(predicate(profile) for profile in self.additive)

    def _combined_condition(self, condition_of):
        """ True, None or the combined condition: an override profile counts alone, the additive ones only together. """
        conditions = [condition_of(profile) for profile in self.override]
        if self.additive:
            conditions.append(and_conditions([condition_of(profile) for profile in self.additive]))
        combined = or_conditions(conditions)
        return True if combined == 'True' else None if combined == 'False' else combined

    def field_condition(self, model_name, field_name, mode):
        return self._combined_condition(lambda profile: profile.field_condition(model_name, field_name, mode))

    def conditional_fields(self, model_name, modes=('hide', 'readonly')):
        """ {field: condition} of fields in ``modes`` only under a condition: weakest mode, stronger lines included. """
        key = ('conditional', model_name, modes)
        if key not in self._memo:
            weakest = min(modes, key=FIELD_MODES.index)
            names = {field for profile in self.additive + self.override
                     for model, field in profile.field_conditions if model == model_name}
            conditions = {name: self.field_condition(model_name, name, weakest) for name in names}
            self._memo[key] = {name: condition for name, condition in conditions.items() if isinstance(condition, str)}
        return self._memo[key]

    def conditional_models(self):
        return {model for profile in self.additive + self.override for model, _field in profile.field_conditions}

    def button_condition(self, modes, model_name, button_type, name, view_type=None, button_id=None):
        return self._combined_condition(
            lambda profile: profile.button_condition(modes, model_name, button_type, name, view_type, button_id))

    def page_condition(self, model_name, name):
        return self._combined_condition(lambda profile: profile.page_condition(model_name, name))

    def allows(self, model_name, operation, wizard=False):
        if not all(profile.allows(model_name, operation, wizard) for profile in self.override):
            return False
        return not self.additive or any(profile.allows(model_name, operation, wizard) for profile in self.additive)

    def record_domains(self, model_name, operation, wizard=False):
        """ (or_groups, and_groups) of tuples to AND; or_groups is None if an additive profile leaves it unfiltered. """
        and_groups = tuple(terms for profile in self.override if (terms := profile.domain_terms(model_name, operation)))
        or_groups = []
        for profile in self.additive:
            # a refusing profile grants no record, so it must not widen the union to every record
            if not profile.allows(model_name, operation, wizard):
                continue
            terms = profile.domain_terms(model_name, operation)
            if not terms:
                return None, and_groups
            or_groups.append(terms)
        return (tuple(or_groups) or None), and_groups

    def menu_blacklist(self):
        hidden = set()
        if self.additive:
            hidden = set(self.additive[0].menus)
            for profile in self.additive[1:]:
                hidden &= profile.menus
        for profile in self.override:
            hidden |= profile.menus
        return hidden

    def sets_model_flag(self, flag):
        """ Whether ``flag`` holds on some model as in model_flag: an override anywhere, or all additive on one. """
        def models_of(profile):
            # None: every model
            if GLOBAL_FLAG_OF_MODEL_FLAG[flag] in profile.flags:
                return None
            return {name for name, flags in profile.model_flags.items() if flag in flags}
        if any(models_of(profile) is None or models_of(profile) for profile in self.override):
            return True
        if not self.additive:
            return False
        common = None
        for profile in self.additive:
            models = models_of(profile)
            if models is not None:
                common = models if common is None else common & models
                if not common:
                    return False
        return True

    def model_flags_set(self):
        """ Whether any profile hides a whole Print or Action menu, anywhere. """
        return any(
            'hide_print_all' in profile.flags or 'hide_action_menu_all' in profile.flags
            or any({'hide_print', 'hide_action_menu'} & flags for flags in profile.model_flags.values())
            for profile in self.additive + self.override
        )

    def login_refusal(self, now, address):
        """ Why the profiles refuse a sign-in, or None: every override profile must allow it, one additive suffices. """
        for profile in self.override:
            if reason := profile.login_refusal(now, address):
                return reason
        reasons = [profile.login_refusal(now, address) for profile in self.additive]
        if reasons and all(reasons):
            return reasons[0]
        return None

    def home_action(self):
        """ The home page of the first profile that sets one: override profiles first, then additive. """
        return next((profile.home_action for profile in self.override + self.additive if profile.home_action), None)

    def has_flag(self, flag):
        return self._hidden(lambda profile: flag in profile.flags)

    def has_global_readonly(self):
        return self.has_flag('global_readonly')

    def model_flag(self, model_name, flag):
        return self._hidden(lambda profile: profile.model_flag(model_name, flag))

    def hides_report(self, action_id):
        return self._hidden(lambda profile: action_id in profile.reports)

    def hides_action(self, action_id):
        return self._hidden(lambda profile: action_id in profile.actions)

    def hides_button(self, model_name, view_type, button_type, name, button_id):
        return self._hidden(lambda profile: profile.hides_button(model_name, view_type, button_type, name, button_id))

    def blocks_button(self, model_name, button_type, name):
        return self._hidden(lambda profile: profile.blocks_button(model_name, button_type, name))

    def blocks_action(self, action_id):
        return self._hidden(lambda profile: profile.blocks_action(action_id))

    def field_mode(self, model_name, field_name):
        severity = max(
            (FIELD_MODES.index(profile.field_mode(model_name, field_name))
             for profile in self.override),
            default=0,
        )
        if self.additive:
            severity = max(severity, min(
                FIELD_MODES.index(profile.field_mode(model_name, field_name))
                for profile in self.additive
            ))
        return FIELD_MODES[severity]

    def affects_views(self):
        """ Not narrowed to one model: x2many sub views carry comodel fields. """
        return self.view_flags or bool(self.view_models)

    def field_option(self, model_name, field_name, option):
        return self._hidden(lambda profile: profile.field_option(model_name, field_name, option))

    def field_domain(self, model_name, field_name):
        """ Field value filter: additive filters ORed, none if one has none; override filters ANDed. """
        additive = None
        if self.additive:
            terms = [profile.field_domain(model_name, field_name) for profile in self.additive]
            if all(terms):
                additive = or_domains(terms)
        return and_domains([*(profile.field_domain(model_name, field_name) for profile in self.override), additive])

    def has_value_filters(self):
        return any(profile.field_domains for profile in self.additive + self.override)

    def hides_element(self, model_name, element_type, element_name=''):
        return self._hidden(lambda profile: profile.hides_element(model_name, element_type, element_name))

    def hidden_view_types(self, model_name):
        types = {
            name
            for profile in self.additive + self.override
            for model, element_type, name in profile.elements
            if model == model_name and element_type == 'view'
        }
        return {name for name in types if self.hides_element(model_name, 'view', name)}

    def fields_in_modes(self, model_name, modes):
        """ Fields whose combined mode is in ``modes``; memoised, as the field guard asks for every row and path. """
        key = (model_name, modes)
        memo = self._memo
        if key not in memo:
            memo[key] = frozenset(
                name for name in self.restricted_fields(model_name)
                if self.field_mode(model_name, name) in modes)
        return memo[key]

    def hidden_field_pairs(self):
        """ (model, field) pairs hidden always or under a condition; over-hiding is safe, no record is known here. """
        key = ('hidden_pairs',)
        if key not in self._memo:
            models = {
                model for profile in self.additive + self.override
                for model, _field in (*profile.field_modes, *profile.field_conditions)
            }
            self._memo[key] = frozenset(
                (model, name)
                for model in models
                for name in (*self.fields_in_modes(model, ('hide',)), *self.conditional_fields(model, ('hide',)))
            )
        return self._memo[key]

    def restricts_fields(self):
        """ Whether any profile hides a field, makes one read only or keeps one out of the exports. """
        return any(
            mode in ('hide', 'readonly')
            for profile in self.additive + self.override
            for mode in (*profile.field_modes.values(),
                         *(line_mode for lines in profile.field_conditions.values() for line_mode, _c in lines))
        ) or any(
            'no_export' in options
            for profile in self.additive + self.override
            for options in profile.field_options.values()
        )

    def not_exported(self, model_name):
        """ The fields of a model kept out of the exports. """
        names = {
            field_name
            for profile in self.additive + self.override
            for (model, field_name), options in profile.field_options.items()
            if model == model_name and 'no_export' in options
        }
        return {name for name in names if self.field_option(model_name, name, 'no_export')}

    def body_classes(self):
        return [css for flag, css in BODY_CLASSES.items() if self.has_flag(flag)]

    def restricted_fields(self, model_name):
        return {
            field_name
            for profile in self.additive + self.override
            for model, field_name in (*profile.field_modes, *profile.field_conditions)
            if model == model_name
        }


NO_RULES = AccessRules()
