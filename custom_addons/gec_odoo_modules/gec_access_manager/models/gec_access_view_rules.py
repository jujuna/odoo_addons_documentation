import ast
import re
import json

from lxml import etree

from odoo import api, models
from odoo.fields import Domain

from .conditions import condition_fields
from .value_filters import and_domains, names_read
from .gec_access_rules import (
    ACTIVITY_FIELDS,
    ACTIVITY_WIDGETS,
    CHATTER_CLASSES,
    HIDE_MODES,
    REMOVED_IN_VIEWS,
    VIEW_ROOTS,
    and_conditions,
)

# A groupby is a nested view on the grouped relation, including its condition fields.
VIEW_SCOPES = VIEW_ROOTS | {'groupby'}


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    @staticmethod
    def _set_option(node, key, value):
        raw = node.get('options') or '{}'
        try:
            options = json.loads(raw)
        except ValueError:
            try:
                options = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                options = {}
        if not isinstance(options, dict):
            options = {}
        options[key] = value
        node.set('options', json.dumps(options))

    @api.model
    def _gec_field_own_domain(self, model_name, field_name):
        """ The domain of the field itself, which a domain set on the view replaces in the web client. """
        field = self.env[model_name]._fields.get(field_name) if model_name in self.env else None
        domain = getattr(field, 'domain', None)
        if isinstance(domain, (list, tuple, Domain)):
            return repr(list(domain))
        return domain if isinstance(domain, str) else None

    @staticmethod
    def _merge_domain(existing, extra):
        return and_domains([existing, extra])

    def _apply_field_conditions(self, rules, node, model_name, field_name, view_type, needed):
        hide = rules.field_condition(model_name, field_name, 'hide')
        if isinstance(hide, str):
            self._add_condition(node, 'invisible', hide, model_name, view_type, needed)
        readonly = rules.field_condition(model_name, field_name, 'readonly')
        if isinstance(readonly, str):
            self._add_condition(node, 'readonly', readonly, model_name, view_type, needed)
        if not isinstance(hide, str) and readonly is not True:
            required = rules.field_condition(model_name, field_name, 'required')
            if isinstance(required, str):
                self._add_condition(node, 'required', required, model_name, view_type, needed)

    @classmethod
    def _add_condition(cls, node, attribute, condition, model_name, view_type, needed):
        """ OR a profile's condition into a view attribute. The view loads only the fields of the condition: core loads
        those of the existing expression, which may be ``parent`` or ``context``, not fields. """
        existing = (node.get(attribute) or '').strip()
        if existing in ('1', 'True', 'true'):
            return
        names = condition_fields(condition)
        if existing and existing not in ('0', 'False', 'false'):
            condition = '(%s) or (%s)' % (existing, condition)
        node.set(attribute, condition)
        root = cls._view_scope(node)
        if root is not None:
            needed.setdefault(root, (model_name, set()))[1].update(names)

    def _add_needed_names(self, node, model_name, names, needed):
        root = self._view_scope(node)
        names = names & set(self.env[model_name]._fields) if model_name in self.env else set()
        if root is not None and names:
            needed.setdefault(root, (model_name, set()))[1].update(names)

    def _add_needed_fields(self, needed):
        """ Add, invisible, the fields conditions read that the view lacks; return the names added per model. """
        added = {}
        for root, (model_name, names) in needed.items():
            model = self.env[model_name]
            present = {field.get('name') for field in root.iter('field') if self._view_scope(field) is root}
            for name in sorted(names - present):
                field = model._fields.get(name)
                if field is None or not model._has_field_access(field, 'read'):
                    continue
                attribute = 'column_invisible' if root.tag in ('list', 'tree') else 'invisible'
                root.append(etree.Element('field', {'name': name, attribute: '1'}))
                added.setdefault(model_name, set()).add(name)
        return added

    @classmethod
    def _hide_field(cls, node, view_type):
        """ Hide a field without removing it, as other parts of the view may refer to it; the field guard blanks its
        value. It is removed only in views that search or aggregate on it, where the guard would refuse it. """
        root = cls._view_scope(node)
        container = root.tag if root is not None else view_type
        if container in REMOVED_IN_VIEWS:
            cls._drop(node)
            return
        node.set('column_invisible' if container in ('list', 'tree') else 'invisible', '1')
        if container in ('list', 'tree') and node.getparent().tag == 'column':
            # Stacked columns render their children using invisible, not column_invisible.
            node.set('invisible', '1')
            node.attrib.pop('optional', None)
        node.set('readonly', '1')
        for attribute in ('sum', 'avg', 'aggregator', 'required'):
            node.attrib.pop(attribute, None)

    @staticmethod
    def _drop(node):
        """ Remove a node and keep the surrounding text tidy. """
        parent = node.getparent()
        if parent is None:
            return
        tail = node.tail
        previous = node.getprevious()
        parent.remove(node)
        if tail:
            if previous is not None:
                previous.tail = (previous.tail or '') + tail
            else:
                parent.text = (parent.text or '') + tail

    @api.model
    def _comodel(self, model_name, field_name):
        """ The model the children of a relational field or groupby belong to, or None. """
        if not (model_name and field_name):
            return None
        model = self.env.get(model_name)
        field = model._fields.get(field_name) if model is not None else None
        return field.comodel_name if field is not None and field.relational else None

    @api.model
    def _iter_nodes(self, node, model_name):
        """ Yield ``(node, model)`` following relational subviews and grouped relation headers. """
        yield node, model_name
        if node.tag in ('field', 'groupby'):
            model_name = self._comodel(model_name, node.get('name'))
        for child in node:
            yield from self._iter_nodes(child, model_name)

    @staticmethod
    def _view_scope(node):
        return next((ancestor for ancestor in node.iterancestors() if ancestor.tag in VIEW_SCOPES), None)

    def _hide_field_labels_and_wrappers(self, rules, tree, model_name, needed):
        """ Profile hiding owns explicit labels and dedicated wrappers, not shared rows or setting tiles. """
        nodes = list(self._iter_nodes(tree, model_name))
        targets = {}
        hidden = {}
        for node, node_model in nodes:
            if node.tag != 'field' or not node_model:
                continue
            name = node.get('name')
            for target in {name, node.get('id')} - {None}:
                key = (self._view_scope(node), node_model, target)
                targets.setdefault(key, []).append(node)
            condition = (True if rules.field_mode(node_model, name) == 'hide'
                         else rules.field_condition(node_model, name, 'hide'))
            if condition is True or isinstance(condition, str):
                hidden[node] = 'True' if condition is True else condition

        for node, node_model in nodes:
            if node.tag != 'label' or not node.get('for') or not node_model:
                continue
            fields = targets.get((self._view_scope(node), node_model, node.get('for')), [])
            if not fields or any(field not in hidden for field in fields):
                continue
            condition = and_conditions(list(dict.fromkeys(hidden[field] for field in fields)))
            hidden[node] = condition
            if condition == 'True':
                node.set('invisible', '1')
            else:
                self._add_condition(node, 'invisible', condition, node_model, tree.tag, needed)

        for node, node_model in reversed(nodes):
            children = list(node)
            if not children or (node.text or '').strip() or any((child.tail or '').strip() for child in children):
                continue
            if any(child not in hidden for child in children):
                continue
            if node.tag == 'column':
                # Column visibility has no row context. Conditional children cannot hide its header.
                root = self._view_scope(node)
                if (root is not None and root.tag in ('list', 'tree')
                        and all(child.tag == 'field' and hidden[child] == 'True' for child in children)):
                    node.set('column_invisible', '1')
                continue
            if node.tag != 'div' or any(key.startswith('t-') for key in node.attrib):
                continue
            classes = set((node.get('class') or '').split())
            if classes & {'o_td_label', 'o_wrap_label'}:
                if any(child.tag != 'label' for child in children):
                    continue
            elif 'o_row' in classes:
                if any(child.tag != 'field' for child in children):
                    continue
            else:
                continue
            condition = and_conditions(list(dict.fromkeys(hidden[child] for child in children)))
            if condition == 'True':
                node.set('invisible', '1')
            else:
                self._add_condition(node, 'invisible', condition, node_model, tree.tag, needed)

    @api.model
    def _apply_view_rules(self, rules, tree, model_name, view_type):
        """ Rewrite a view for the current user; return the fields it had to add, as ``{model: names}``. Cosmetic
        only: enforcement lives in Base._access_domain(), the field guard and the controllers. """
        lock_statusbar = rules.has_flag('lock_statusbar')
        hide_activities = rules.has_flag('hide_activities')
        chatter_hidden = {}
        # the fields a condition reads, per view or x2many sub-view: the client needs them there to evaluate it
        needed = {}

        for node, node_model in list(self._iter_nodes(tree, model_name)):
            tag = node.tag

            if tag == 'chatter':
                if node_model is None:
                    continue
                if node_model not in chatter_hidden:
                    chatter_hidden[node_model] = rules.model_flag(node_model, 'hide_chatter')
                if chatter_hidden[node_model]:
                    self._drop(node)
                continue

            if tag == 'form' and node_model:
                classes = [css for flag, css in CHATTER_CLASSES if rules.model_flag(node_model, flag)]
                if classes:
                    node.set('class', ' '.join(filter(None, [node.get('class'), *classes])))

            if tag == 'filter' and node_model:
                # the field guard would refuse a filter on a hidden field
                hidden = {name for name in rules.restricted_fields(node_model)
                          if rules.field_mode(node_model, name) == 'hide'}
                hidden |= set(rules.conditional_fields(node_model, ('hide',)))
                text = (node.get('domain') or '') + (node.get('context') or '')
                if hidden and any(re.search(r'''['"]%s[.'"]''' % re.escape(name), text) for name in hidden):
                    self._drop(node)
                    continue

            if tag == 'field':
                field_name = node.get('name')
                if hide_activities and (field_name in ACTIVITY_FIELDS or node.get('widget') in ACTIVITY_WIDGETS):
                    self._drop(node)
                    continue
                if node_model:
                    mode = rules.field_mode(node_model, field_name)
                    if mode == 'hide':
                        self._hide_field(node, view_type)
                        continue
                    if any(self.env[node_model]._gec_path_hidden(rules, token) for token in re.findall(
                            r'''['"]([\w.]+)['"]''', node.get('filter_domain') or '')):
                        # the client builds its search from it, and the guard refuses a hidden field there
                        del node.attrib['filter_domain']
                    if mode == 'readonly':
                        # no force_save: the field guard drops what is written to it anyway
                        node.set('readonly', '1')
                    elif mode == 'required':
                        node.set('required', '1')
                    self._apply_field_conditions(rules, node, node_model, field_name, view_type, needed)
                    if rules.field_option(node_model, field_name, 'no_open'):
                        self._set_option(node, 'no_open', True)
                    if rules.field_option(node_model, field_name, 'no_create'):
                        self._set_option(node, 'no_create', True)
                        self._set_option(node, 'no_quick_create', True)
                        self._set_option(node, 'no_create_edit', True)
                    value_filter = rules.field_domain(node_model, field_name)
                    if value_filter:
                        merged = self._merge_domain(
                            node.get('domain') or self._gec_field_own_domain(node_model, field_name), value_filter)
                        if merged:
                            node.set('domain', merged)
                            self._add_needed_names(node, node_model, names_read(merged), needed)
                if lock_statusbar and node.get('widget') == 'statusbar':
                    self._set_option(node, 'clickable', False)
                continue

            if tag == 'button' and node.get('name') and not node.get('special') and node_model:
                condition = rules.button_condition(
                    HIDE_MODES, node_model, node.get('type') or 'object', node.get('name'), view_type,
                    node.get('id') or '')
                if condition is True:
                    self._drop(node)
                elif condition:
                    self._add_condition(node, 'invisible', condition, node_model, view_type, needed)
                continue

            if tag == 'page' and node_model:
                condition = rules.page_condition(node_model, node.get('name') or '')
                if condition is True:
                    self._drop(node)
                elif condition:
                    self._add_condition(node, 'invisible', condition, node_model, view_type, needed)
                continue

            if tag == 'progressbar' and node_model:
                model = self.env[node_model]
                if model._gec_path_hidden(rules, node.get('field') or ''):
                    self._drop(node)
                    continue
                for attribute in ('sum_field', 'recurring_revenue_sum_field'):
                    if model._gec_path_hidden(rules, node.get(attribute) or ''):
                        del node.attrib[attribute]
                continue

            if tag == 'filter' and node_model:
                # a group by is a <filter> node too, so this covers both
                if rules.hides_element(node_model, 'filter', node.get('name') or ''):
                    self._drop(node)
                continue

            if tag == 'searchpanel' and node_model:
                if rules.hides_element(node_model, 'searchpanel'):
                    self._drop(node)

        self._hide_field_labels_and_wrappers(rules, tree, model_name, needed)
        added = self._add_needed_fields(needed)

        if tree.tag in ('form', 'list', 'kanban'):
            if rules.model_flag(model_name, 'hide_export'):
                tree.set('export_xlsx', '0')
            if rules.model_flag(model_name, 'hide_import'):
                # base_import reads this to offer the Import menu entry
                tree.set('import', '0')
            if rules.model_flag(model_name, 'hide_duplicate'):
                tree.set('duplicate', '0')
        return added
