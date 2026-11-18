import inspect
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.fields import Command, Domain
from odoo.http import request

from .conditions import condition_domain, condition_fields
from .value_filters import eval_filter, names_read

_logger = logging.getLogger(__name__)

AGGREGATE_SEPARATOR = ':'
ARCHIVE_FIELDS = frozenset({'active', 'x_active'})
# the summary of extra totals lines of a quotation (sale.order)
EXTRA_TOTALS = 'extra_total_fields'
DOMAIN_SUBQUERY_OPERATORS = ('any', 'not any', 'any!', 'not any!')
# read methods that read through others under their own name; each argument holds a domain, an order, specs or keys
CLIENT_READ_ARGUMENTS = {
    'hierarchy_read': {'domain': 'domain', 'order': 'order', 'parent_field': 'specs', 'child_field': 'specs'},
    'get_gantt_data': {'domain': 'domain', 'groupby': 'specs', 'unavailability_fields': 'specs',
                       'progress_bar_fields': 'specs'},
    'get_cohort_data': {'domain': 'domain', 'date_start': 'specs', 'date_stop': 'specs', 'measure': 'specs'},
    'web_gantt_init_old_vals_per_pill_id': {'vals': 'keys'},
    'web_gantt_format_property_fields': {'vals': 'keys'},
}
CLIENT_READ_ENTRIES = tuple(CLIENT_READ_ARGUMENTS)
# the gantt view's writes, made under their own name: judged as a write of the client
CLIENT_WRITE_ENTRIES = ('write', 'action_rollback_scheduling', 'gantt_undo_drag_drop', 'web_gantt_reschedule')
# values judged at the entry, before an override renames their keys: (position after the ids, keyword); create: no ids
CLIENT_VALUES = {
    'create': (0, 'vals_list'),
    'write': (0, 'vals'),
    'gantt_undo_drag_drop': (1, 'data'),
    'action_rollback_scheduling': (0, 'old_vals_per_pill_id'),
}
# the website editor saves translations through this route, which makes no call_kw entry
WEBSITE_TRANSLATION_PATH = '/website/field/translation/update'
# the model of the client's own write while it runs, judged at a door (dataset.py judged_write)
CLIENT_WRITE = ContextVar('gec_access_client_write', default=None)


def is_id_number(value):
    """ Whether core takes ``value`` as a record id in a relational value: JSON and XML-RPC send 7.0 as well as 7. """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@contextmanager
def client_write(model_name, active=True):
    """ Mark the client's own write of ``model_name`` judged at the door: Odoo's writes meanwhile are not (Base.write).
    """
    if not active or CLIENT_WRITE.get() is not None:
        yield
        return
    token = CLIENT_WRITE.set(model_name)
    try:
        yield
    finally:
        CLIENT_WRITE.reset(token)

class RecordValues:
    """ The values of a record being saved, as a domain sees them: written, else held, else default; ``parent`` in
    lines. """

    def __init__(self, model, vals, record=None, parent=None):
        self._model, self._vals, self._record, self._parent = model, vals, record, parent

    def get(self, name):
        field = self._model._fields.get(name)
        if name in self._vals and not (field and field.type in ('one2many', 'many2many')):
            value = self._vals[name]
            return value.id if isinstance(value, models.BaseModel) else value
        if self._record:
            value = self._record.sudo()[name]
        else:
            value = self._model.default_get([name]).get(name, False)
            if field and field.type in ('one2many', 'many2many'):
                return []
        if isinstance(value, models.BaseModel):
            return value.ids if field.type in ('one2many', 'many2many') else value.id
        return value

    def __getattr__(self, name):
        if name.startswith('_') or name not in self._model._fields:
            raise AttributeError(name)
        return self.get(name)

    def __getitem__(self, name):
        """ ``parent['<field>']``: the same values and guard as the attribute, for expr_eval. """
        if name.startswith('_') or name not in self._model._fields:
            raise KeyError(name)
        return self.get(name)


class Base(models.AbstractModel):
    _inherit = 'base'

    def _gec_field_rules(self):
        rules = self.env['gec.access.profile']._current_rules()
        return rules if rules.enabled and rules.restricts_fields() else None

    @api.model
    def _gec_hidden(self, rules, model_name):
        return rules.fields_in_modes(model_name, ('hide',))

    @api.model
    def _gec_locked(self, rules, model_name):
        return rules.fields_in_modes(model_name, ('hide', 'readonly'))

    def _gec_refuse(self, model_name, field_name):
        model = self.env[model_name]
        field = model._fields.get(field_name)
        raise self.env['gec.access.profile']._gec_refusal(_(
            "Your access profile does not allow using the field '%(field)s' of '%(model)s'.",
            field=field.string if field else field_name,
            model=self.env['ir.model']._get(model_name).name or model_name), model=model_name)

    def _gec_hidden_any(self, rules):
        """ Hidden always or under a condition, with the images derived from a hidden one: filtering, grouping or
        exporting on these would tell the hidden values apart, so both are refused there. """
        return self._gec_binary_family(
            self._gec_hidden(rules, self._name) | set(rules.conditional_fields(self._name, ('hide',))))

    def _gec_binary_family(self, names):
        """ ``names`` plus the binary fields derived from them, transitively: hiding an image hides its sizes. """
        binaries = [field for field in self._fields.values() if field.type in ('binary', 'image')]
        # only a hidden binary passes it on: hiding the name does not hide the avatars computed from it
        family = {field.name for field in binaries if field.name in names}
        if not family:
            return set(names)
        while True:
            derived = {
                field.name for field in binaries
                if field.name not in family and (
                    (field.related and field.related.split('.')[0] in family)
                    or any(dotname.split('.')[0] in family for dotname in self.pool.field_depends[field]))
            }
            if not derived:
                return set(names) | family
            family |= derived

    def _gec_hides_binary(self, rules, field_name):
        """ Whether the field, or the one it derives from, is hidden under a condition on these records; asked by the
        image routes, which cannot blank a value. """
        return any(
            field_name in self._gec_binary_family({name}) and self._gec_matching(condition, self.ids)
            for name, condition in rules.conditional_fields(self._name, ('hide',)).items())

    def _gec_matching(self, condition, ids):
        """ The ids among ``ids`` whose record matches a rule's condition. """
        if not ids:
            return set()
        domain = condition_domain(condition, self, self.env.uid)
        return set(self.browse(ids).sudo().exists().filtered_domain(domain).ids)

    def _gec_path_hidden(self, rules, path):
        """ The (model, field) of the first hidden field a dotted path crosses, else None; aggregates, languages
        skipped. """
        model = self
        path = path.split(':')[0]
        for name in path.split('.'):
            name = name.split('@')[0]
            if name in model._gec_hidden_any(rules):
                return model._name, name
            field = model._fields.get(name)
            if field is None or not field.relational:
                return None
            model = self.env[field.comodel_name]
        return None

    def _gec_check_path(self, rules, path):
        """ Refuse a dotted path that crosses a hidden field. """
        if hidden := self._gec_path_hidden(rules, path):
            self._gec_refuse(*hidden)

    def _gec_check_domain(self, rules, domain):
        if isinstance(domain, Domain):
            # a domain already parsed (the /json routes pass one)
            for condition in domain.iter_conditions():
                self._gec_check_path(rules, condition.field_expr)
                # Domain(list) keeps the condition of an 'any' as a list
                if isinstance(condition.value, Domain) or (
                        condition.operator in DOMAIN_SUBQUERY_OPERATORS and isinstance(condition.value, (list, tuple))):
                    comodel = self._gec_comodel_of(condition.field_expr)
                    if comodel is not None:
                        comodel._gec_check_domain(rules, condition.value)
            return
        if not domain or not isinstance(domain, (list, tuple)):
            return
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and isinstance(leaf[0], str):
                path, operator, value = leaf
                self._gec_check_path(rules, path)
                if operator in DOMAIN_SUBQUERY_OPERATORS and isinstance(value, (list, tuple)):
                    # the condition of an 'any' applies to the records at the end of the path
                    model = self._gec_comodel_of(path)
                    if model is not None:
                        model._gec_check_domain(rules, value)

    def _gec_comodel_of(self, path):
        """ The model at the end of a relational path, or None; ``id`` keeps the model (``('id', 'any', ...)``). """
        model = self
        for name in path.split('.'):
            if name == 'id':
                continue
            field = model._fields.get(name)
            if field is None or not field.relational:
                return None
            model = self.env[field.comodel_name]
        return model

    def _gec_check_order(self, rules, order):
        for part in (order or '').split(','):
            name = part.strip().split(' ')[0]
            if name:
                self._gec_check_path(rules, name)

    def _gec_check_specs(self, rules, specs):
        """ Group-bys and aggregates: ``date:month``, ``amount:sum``, ``partner_id.name``. """
        for spec in specs or ():
            if isinstance(spec, str) and spec != '__count':
                self._gec_check_path(rules, spec.split(AGGREGATE_SEPARATOR)[0])

    def _gec_blank(self, rules, rows, specification=None):
        """ Blank the hidden fields of ``rows`` (dicts) in place, and of the records nested along ``specification``. """
        hidden = self._gec_hidden(rules, self._name)
        # hidden under a condition: blanked on matching records, derived binaries too (an onchange: _gec_blank_onchange)
        for parent, condition in rules.conditional_fields(self._name, ('hide',)).items():
            names = self._gec_binary_family({parent})
            ids = [row['id'] for row in rows if isinstance(row, dict) and isinstance(row.get('id'), int)
                   and not names.isdisjoint(row)]
            matching = self._gec_matching(condition, ids)
            for row in rows:
                if isinstance(row, dict) and row.get('id') in matching:
                    for name in names.intersection(row):
                        field = self._fields.get(name)
                        row[name] = [] if field is not None and field.type in ('one2many', 'many2many') else False
        blanked = self._gec_binary_family(hidden)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if hidden and isinstance(row.get(EXTRA_TOTALS), list):
                self._gec_strip_extra_totals(row, hidden)
            for name in blanked:
                if name in row:
                    field = self._fields.get(name)
                    row[name] = [] if field is not None and field.type in ('one2many', 'many2many') else False
            for name, sub in (specification or {}).items():
                field = self._fields.get(name)
                if name in hidden or field is None or not isinstance(sub, dict) or not sub.get('fields'):
                    continue
                if field.type in ('reference', 'many2one_reference'):
                    self._gec_blank_reference(rules, row, field, sub['fields'])
                    continue
                if not field.relational:
                    continue
                comodel = self.env[field.comodel_name]
                value = row.get(name)
                if isinstance(value, dict):
                    comodel._gec_blank(rules, [value], sub['fields'])
                elif isinstance(value, list):
                    nested = []
                    for item in value:
                        if isinstance(item, dict):
                            nested.append(item)
                        elif isinstance(item, (list, tuple)) and len(item) > 2 and isinstance(item[2], dict):
                            # onchange answers with commands: (command, id, values)
                            nested.append(item[2])
                    comodel._gec_blank(rules, nested, sub['fields'])
        return rows

    def _gec_form_record(self, vals, conditions):
        """ The record a form holds with ``vals``, as core's onchange builds it: the saved record, else a new one. """
        values = {name: value for name, value in vals.items() if name in self._fields}
        read = [name for name in {name for condition in conditions for name in condition_fields(condition)}
                if name in self._fields and name not in values]
        if self.id:
            # new() over a saved record does not take its values: core's onchange copies them in too
            saved = self.sudo()._convert_to_write({name: self.sudo()[name] for name in read})
            return self.new({**saved, **values}, origin=self)
        return self.new({**self.default_get(read), **values})

    def _gec_form_matches(self, record, condition):
        """ Whether the form ``record`` (_gec_form_record) matches a rule's condition; an unjudgeable one matches. """
        try:
            return bool(record.filtered_domain(Domain(condition_domain(condition, self, self.env.uid))))
        except (ValueError, TypeError, KeyError):
            return True

    def _gec_strip_form(self, rules, row, vals):
        """ Remove from ``row`` the fields hidden under a condition that the form holding ``vals`` matches. """
        conditional = rules.conditional_fields(self._name, ('hide',))
        hit = {name: condition for name, condition in conditional.items()
               if self._gec_binary_family({name}) & row.keys()}
        if not hit:
            return
        record = self._gec_form_record(vals, hit.values())
        for name, condition in hit.items():
            if self._gec_form_matches(record, condition):
                for key in self._gec_binary_family({name}) & row.keys():
                    del row[key]

    def _gec_blank_onchange(self, rules, values, row, specification):
        """ Leave out of an onchange answer ``row`` the values hidden under a condition the edited record matches
        (``values`` over the saved record), also in x2many lines. Left out, not blanked: the client would save a blank
        back; a new record that matches takes Odoo's default or computed value at create (_gec_drop_locked). """
        self._gec_strip_form(rules, row, values)
        for name in specification or {}:
            field = self._fields.get(name)
            if field is None or field.type not in ('one2many', 'many2many') or not isinstance(row.get(name), list):
                continue
            comodel = self.env[field.comodel_name]
            for command in row[name]:
                if not (isinstance(command, (list, tuple)) and len(command) > 2 and isinstance(command[2], dict)):
                    continue
                line = command[2]
                if command[0] == Command.UPDATE and is_id_number(command[1]):
                    comodel.browse(int(command[1]))._gec_strip_form(rules, line, line)
                else:
                    comodel._gec_strip_form(rules, line, line)

    def _gec_blank_reference(self, rules, row, field, specification):
        """ Blank the record ``row`` reads through a reference or a many2one_reference, by the rules of its own model,
        as web_read reads it: a reference names it in the value, a many2one_reference in its model field. """
        value = row.get(field.name)
        if not isinstance(value, dict):
            return
        if isinstance(value.get('id'), dict):
            model_name, record_id = value['id'].get('model'), value['id'].get('id')
        elif isinstance(row.get('id'), int):
            model_name = self.browse(row['id']).sudo()[field.model_field]
            record_id = value.get('id')
        else:
            return
        if model_name not in self.env:
            return
        # judged with its plain id (a reference shows {'id', 'model'}), the result copied back
        proxy = dict(value, id=record_id)
        self.env[model_name]._gec_blank(rules, [proxy], specification)
        for key in [key for key in value if key != 'id' and key not in proxy]:
            del value[key]
        value.update({key: item for key, item in proxy.items() if key != 'id'})

    def _gec_strip_extra_totals(self, row, hidden):
        """ Remove the totals lines that show a hidden field (e.g. the margin under a quotation), by label or value. """
        labels = [self._fields[name]._description_string(self.env) for name in hidden if name in self._fields]
        values = set()
        if isinstance(row.get('id'), int):
            record = self.browse(row['id']).sudo().exists()
            for name in hidden:
                field = self._fields.get(name)
                if record and field is not None and field.type in ('float', 'monetary') and record[name]:
                    values.add(record[name])
        for group in row[EXTRA_TOTALS]:
            if isinstance(group, dict) and isinstance(group.get('lines'), list):
                group['lines'] = [
                    line for line in group['lines']
                    if not (isinstance(line, dict) and (
                        line.get('value') in values
                        or any(str(line.get('label') or '').startswith(label) for label in labels if label)))
                ]

    def _gec_drop_locked(self, rules, vals, record=None, refuse=False, parents=None, creating=False):
        """ ``vals`` without the read-only and hidden fields, also in one2many lines; one locked under a condition goes
        when ``record`` matches it or, ``creating``, when the new record would. ``refuse`` (API doors) refuses instead,
        as core does; moves into a locked inverse field are refused (_gec_check_moves; ``parents``: records written). """
        if not isinstance(vals, dict):
            return vals
        locked = set(self._gec_locked(rules, self._name))
        conditional = rules.conditional_fields(self._name, ('hide', 'readonly'))
        if record:
            locked |= {name for name, condition in conditional.items()
                       if name in vals and self._gec_matching(condition, record.ids)}
        elif creating and (judged := {name: condition for name, condition in conditional.items() if name in vals}):
            form = self.browse()._gec_form_record(vals, judged.values())
            locked |= {name for name, condition in judged.items() if self._gec_form_matches(form, condition)}
        result = {}
        for name, value in vals.items():
            if name in locked:
                if refuse:
                    self._gec_refuse(self._name, name)
                continue
            field = self._fields.get(name)
            if field is not None and field.type == 'one2many' and field.inverse_name:
                self.env[field.comodel_name]._gec_check_moves(rules, field, value, parents or record)
            if field is not None and field.type in ('one2many', 'many2many') and isinstance(value, (list, tuple)):
                comodel = self.env[field.comodel_name]
                value = [
                    (command[0], command[1],
                     comodel._gec_drop_locked(
                         rules, command[2],
                         comodel.browse((command[1],))
                         if command[0] == 1 and is_id_number(command[1]) and command[1] else None, refuse,
                         creating=command[0] == Command.CREATE),
                     *command[3:])
                    if isinstance(command, (list, tuple)) and len(command) > 2 and isinstance(command[2], dict)
                    else command
                    for command in value
                ]
            result[name] = value
        return result

    def _gec_check_moves(self, rules, field, value, holders):
        """ Refuse a one2many value that moves records of this model in or out when its inverse field is locked for
        them: core writes that field, which the client may not set. Refused on every door, a deliberate act.
        ``holders``: the records written (core links into the last one), none for a new one. """
        inverse = field.inverse_name
        conditional = rules.conditional_fields(self._name, ('hide', 'readonly')).get(inverse)
        always = inverse in self._gec_locked(rules, self._name)
        if not (always or conditional):
            return
        if value is False or value is None:
            value = [Command.clear()]
        elif isinstance(value, (list, tuple)) and value and all(is_id_number(item) for item in value):
            value = [Command.set(value)]
        if not isinstance(value, (list, tuple)):
            return
        holders = (holders or self.env[field.model_name]).sudo().with_context(active_test=False)
        last = set(holders[-1:].mapped(field.name).ids)
        current = set(holders.mapped(field.name).ids)
        moved = set()
        for command in value:
            if not (isinstance(command, (list, tuple)) and command):
                continue
            if command[0] == Command.LINK and is_id_number(command[1]) and int(command[1]) not in last:
                moved.add(int(command[1]))
            elif command[0] == Command.UNLINK and is_id_number(command[1]):
                moved.add(int(command[1]))
            elif command[0] == Command.SET and len(command) > 2 and isinstance(command[2], (list, tuple)):
                ids = {int(item) for item in command[2] if is_id_number(item)}
                moved |= (ids - last) | (current - ids)
            elif command[0] == Command.CLEAR:
                moved |= current
        if moved and (always or self._gec_matching(conditional, list(moved))):
            self._gec_refuse(self._name, inverse)

    def _gec_value_rules(self):
        rules = self.env['gec.access.profile']._current_rules()
        return rules if rules.enabled and rules.has_value_filters() else None

    def _gec_check_values(self, rules, vals, record=None, parent=None):
        """ Refuse a value outside the value filter of its field, also in x2many lines. A many2many with a filter takes
        no new record: the client links it after a name_create, which is checked. """
        if not isinstance(vals, dict):
            return
        values = RecordValues(self, vals, record, parent)
        for name, value in vals.items():
            field = self._fields.get(name)
            if field is None or not field.relational:
                continue
            domain = rules.field_domain(self._name, name)
            if domain:
                ids = self._gec_new_ids(field, value, record)
                lines = [
                    command[2] for command in value
                    if field.type == 'one2many' and isinstance(command, (list, tuple)) and len(command) > 2
                    and command[0] == Command.CREATE and isinstance(command[2], dict)
                ] if isinstance(value, (list, tuple)) else []
                if ids or lines:
                    self._gec_check_value(name, domain, ids, values, lines)
                if field.type == 'many2many' and isinstance(value, (list, tuple)) and any(
                        isinstance(command, (list, tuple)) and command and command[0] == Command.CREATE
                        for command in value):
                    self._gec_refuse_value(name)
            if field.type in ('one2many', 'many2many') and isinstance(value, (list, tuple)):
                comodel = self.env[field.comodel_name]
                for command in value:
                    if isinstance(command, (list, tuple)) and len(command) > 2 and isinstance(command[2], dict):
                        line = comodel.browse((command[1],)) if (
                            command[0] == Command.UPDATE and is_id_number(command[1]) and command[1]) else None
                        comodel._gec_check_values(rules, command[2], line, values)

    @api.model
    def _gec_new_ids(self, field, value, record=None):
        """ The ids a relational value links, minus those the record already had: a filter only judges what changes. """
        if field.type == 'many2one':
            value = value.id if isinstance(value, models.BaseModel) else value
            if not is_id_number(value) or not value:
                return set()
            if record and len(record) == 1 and record.sudo()[field.name].id == value:
                return set()
            return {value}
        if not isinstance(value, (list, tuple)):
            return set()
        ids = set()
        for command in value:
            if is_id_number(command):
                ids.add(command)
            elif isinstance(command, (list, tuple)) and command:
                if command[0] == Command.LINK and len(command) > 1 and is_id_number(command[1]):
                    ids.add(command[1])
                elif command[0] == Command.SET and len(command) > 2 and isinstance(command[2], (list, tuple)):
                    ids.update(i for i in command[2] if is_id_number(i))
        if ids and record:
            for current in record.sudo():
                ids -= set(current[field.name].ids)
        return ids

    def _gec_check_value(self, name, domain, ids, values, lines=()):
        """ Refuse ids, and new ``lines`` (values of the records a one2many creates), outside the value filter of
        ``name``. It sees what a web client domain or an access row sees: ``user``, ``company_id``, ``company_ids``,
        unless the model has a field of that name, which then holds the record's value. """
        field = self._fields[name]
        context = {
            'context': dict(self.env.context),
            'uid': self.env.uid,
            'allowed_company_ids': self.env.companies.ids,
            'current_company_id': self.env.company.id,
            'parent': values._parent,
        }
        for key, value in (('user', self.env.user.with_context({})), ('company_id', self.env.company.id),
                           ('company_ids', self.env.companies.ids)):
            if key not in self._fields:
                context[key] = value
        try:
            for key in names_read(domain) - set(context):
                if key in self._fields:
                    context[key] = values.get(key)
            filtered = Domain(eval_filter(domain, context, self.env['res.users'], value_filter=True))
        except Exception as error:  # noqa: BLE001
            # a filter that cannot be evaluated here (parent.<field> on a line written alone) refuses, it is not skipped
            _logger.warning("Value filter %r of %s.%s cannot be evaluated, value refused: %s",
                            domain, self._name, name, error)
            raise self.env['gec.access.profile']._gec_refusal(_(
                "Odoo cannot check the allowed values of the field '%(field)s' of '%(model)s' here. Change it from "
                "the record it belongs to.", field=field._description_string(self.env),
                model=self.env['ir.model']._get(self._name).name or self._name), model=self._name) from error
        comodel = self.env[field.comodel_name].sudo().with_context(active_test=False)
        allowed = comodel.search(Domain('id', 'in', list(ids)) & filtered).ids
        if set(allowed) != set(ids):
            self._gec_refuse_value(name)
        if lines:
            # core gives a created line its defaults and the link to its parent: the filter sees them too
            read = {condition.field_expr.split('.')[0] for condition in filtered.iter_conditions()}
            defaults = comodel.default_get([key for key in read if key in comodel._fields])
            link = {field.inverse_name: values._record.id} if field.inverse_name and values._record else {}
            new_lines = comodel.concat(*(comodel.new({**defaults, **link, **line}) for line in lines))
            if new_lines.filtered_domain(filtered) != new_lines:
                self._gec_refuse_value(name)

    def _gec_refuse_value(self, name):
        """ Refuse a value of the field ``name`` that its value filter does not allow. """
        field = self._fields[name]
        raise self.env['gec.access.profile']._gec_refusal(_(
            "Your access profile does not allow this value in the field '%(field)s' of '%(model)s'.",
            field=field._description_string(self.env),
            model=self.env['ir.model']._get(self._name).name or self._name),
            model=self._name, method=name)

    def _gec_context_defaults(self):
        """ The ``default_<field>`` values of the context that core fills a new record with; the value filters judge
        them. """
        return {key[8:]: value for key, value in self.env.context.items()
                if key.startswith('default_') and key[8:] in self._fields}

    def read(self, fields=None, load='_classic_read'):
        rules = self._gec_rpc_entry('read') and self._gec_field_rules()
        result = super().read(fields, load=load)
        return self._gec_blank(rules, result) if rules else result

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **read_kwargs):
        rules = self._gec_rpc_entry('search_read') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_order(rules, order)
        result = super().search_read(domain, fields, offset=offset, limit=limit, order=order, **read_kwargs)
        return self._gec_blank(rules, result) if rules else result

    def web_read(self, specification):
        """ Read with nested orders that cross a hidden field left out and hidden values blanked, for whatever method of
        this model the client called (hierarchy_read, get_gantt_data...): core reads an order only here, and refusing
        it would break a sort or a subview. """
        rules = self._gec_client_reads_model() and not self.env.su and self._gec_field_rules()
        result = super().web_read(self._gec_strip_spec_orders(rules, specification) if rules else specification)
        return self._gec_blank(rules, result, specification) if rules else result

    def _gec_check_client_read(self, method, args, kwargs):
        """ Refuse a hidden field in what the client sent to a CLIENT_READ_ENTRIES method: it reads through other
        methods, whose checks apply only when the client calls them itself. Arguments are bound by name to the method's
        own signature; a call that does not fit is refused. """
        rules = self._gec_field_rules()
        func = getattr(type(self), method, None)
        if not rules or func is None:
            return
        if not getattr(func, '_api_model', False):
            args = args[1:]
        kwargs = {key: value for key, value in kwargs.items() if key != 'context'}
        try:
            given = inspect.signature(func).bind(self, *args, **kwargs).arguments
        except TypeError:
            raise UserError(_("The method %s does not accept these arguments.", method)) from None
        for name, kind in CLIENT_READ_ARGUMENTS[method].items():
            value = given.get(name)
            if kind == 'domain':
                self._gec_check_domain(rules, value)
            elif kind == 'order':
                self._gec_check_order(rules, value)
            elif kind == 'keys':
                self._gec_check_specs(rules, list(value) if isinstance(value, dict) else [])
            else:
                self._gec_check_specs(rules, value if isinstance(value, (list, tuple)) else [value])

    def _gec_order_hidden(self, rules, order):
        """ Whether an order crosses a hidden field, always or under a condition: what _gec_check_order refuses. """
        for part in (order or '').split(','):
            model = self
            for name in part.strip().split(' ')[0].split(':')[0].split('.'):
                name = name.split('@')[0]
                if name in model._gec_hidden_any(rules):
                    return True
                field = model._fields.get(name)
                if field is None or not field.relational:
                    break
                model = self.env[field.comodel_name]
        return False

    def _gec_strip_spec_orders(self, rules, specification):
        """ A copy of ``specification`` without the ``order`` of the nested x2many crossing a hidden field. """
        result = {}
        for name, sub in specification.items():
            field = self._fields.get(name)
            if field is None or not field.relational or not isinstance(sub, dict):
                result[name] = sub
                continue
            comodel = self.env[field.comodel_name]
            sub = dict(sub)
            if field.type in ('one2many', 'many2many') and comodel._gec_order_hidden(rules, sub.get('order')):
                del sub['order']
            if isinstance(sub.get('fields'), dict):
                sub['fields'] = comodel._gec_strip_spec_orders(rules, sub['fields'])
            result[name] = sub
        return result

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        rules = self._gec_rpc_entry('web_search_read') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_order(rules, order)
        result = super().web_search_read(
            domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)
        if rules:
            self._gec_blank(rules, result.get('records', []), specification)
        return result

    @api.model
    def search(self, domain, offset=0, limit=None, order=None):
        rules = self._gec_rpc_entry('search') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_order(rules, order)
        return super().search(domain, offset=offset, limit=limit, order=order)

    @api.model
    def search_count(self, domain, limit=None):
        rules = self._gec_rpc_entry('search_count') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
        return super().search_count(domain, limit=limit)

    @api.model
    def formatted_read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        rules = self._gec_rpc_entry('formatted_read_group') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_domain(rules, having)
            self._gec_check_specs(rules, groupby)
            self._gec_check_specs(rules, aggregates)
            self._gec_check_order(rules, order)
        return super().formatted_read_group(
            domain, groupby=groupby, aggregates=aggregates, having=having, offset=offset, limit=limit,
            order=order)

    @api.model
    def web_read_group(self, domain, groupby, aggregates=(), limit=None, offset=0, order=None, **kwargs):
        rules = self._gec_rpc_entry('web_read_group') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_specs(rules, groupby)
            self._gec_check_specs(rules, aggregates)
            self._gec_check_order(rules, order)
            # an opened group keeps the domain of a progress bar segment, at each level of the groups
            opening = list(kwargs.get('opening_info') or ())
            while opening:
                info = opening.pop()
                if isinstance(info, dict):
                    self._gec_check_domain(rules, info.get('progressbar_domain'))
                    opening.extend(info.get('groups') or ())
        result = super().web_read_group(
            domain, groupby, aggregates=aggregates, limit=limit, offset=offset, order=order, **kwargs)
        if rules:
            specification = kwargs.get('unfold_read_specification') or {}
            stack = list(result.get('groups', []))
            groupby_specs = kwargs.get('groupby_read_specification') or {}
            while stack:
                group = stack.pop()
                self._gec_blank(rules, group.get('__records', []), specification)
                # the values read for a grouped relation (groupby_read_specification)
                if isinstance(group.get('__values'), dict):
                    for name, spec in groupby_specs.items():
                        field = self._fields.get(name)
                        if field is not None and field.relational:
                            self.env[field.comodel_name]._gec_blank(rules, [group['__values']], spec)
                stack.extend(group.get('__groups', {}).get('groups', [])
                             if isinstance(group.get('__groups'), dict) else group.get('__groups', []))
        return result

    @api.model
    def read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        rules = self._gec_rpc_entry('read_group') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_domain(rules, having)
            self._gec_check_specs(rules, groupby)
            self._gec_check_specs(rules, aggregates)
            self._gec_check_order(rules, order)
        return super().read_group(
            domain, groupby=groupby, aggregates=aggregates, having=having, offset=offset, limit=limit,
            order=order)

    @api.model
    def web_name_search(self, name, specification, domain=None, operator='ilike', limit=100):
        rules = self._gec_rpc_entry('web_name_search') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
        result = super().web_name_search(name, specification, domain=domain, operator=operator, limit=limit)
        return self._gec_blank(rules, result, specification) if rules else result

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        rules = self._gec_rpc_entry('name_search') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    def export_data(self, fields_to_export):
        rules = self._gec_rpc_entry('export_data') and self._gec_field_rules()
        if rules:
            for path in fields_to_export:
                self._gec_check_path(rules, path.replace('/', '.').removesuffix('.id'))
                self._gec_check_export_path(rules, path.replace('/', '.').removesuffix('.id'))
        return super().export_data(fields_to_export)

    def _gec_check_export_path(self, rules, path):
        model = self
        for name in path.split('.'):
            name = name.split('@')[0]
            if name in rules.not_exported(model._name):
                field = model._fields.get(name)
                raise self.env['gec.access.profile']._gec_refusal(_(
                    "Your access profile does not allow exporting the field '%(field)s' of '%(model)s'.",
                    field=field.string if field else name,
                    model=self.env['ir.model']._get(model._name).name or model._name), model=model._name)
            field = model._fields.get(name)
            if field is None or not field.relational:
                return
            model = self.env[field.comodel_name]

    @api.model
    def read_progress_bar(self, domain, group_by, progress_bar):
        rules = self._gec_rpc_entry('read_progress_bar') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_specs(rules, [group_by, (progress_bar or {}).get('field') or '',
                                         (progress_bar or {}).get('sum_field') or ''])
        return super().read_progress_bar(domain, group_by, progress_bar)

    @api.model
    def formatted_read_grouping_sets(self, domain, grouping_sets, aggregates=(), **kwargs):
        rules = self._gec_rpc_entry('formatted_read_grouping_sets') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            for grouping_set in grouping_sets or ():
                self._gec_check_specs(rules, grouping_set)
            self._gec_check_specs(rules, aggregates)
            self._gec_check_order(rules, kwargs.get('order'))
        return super().formatted_read_grouping_sets(domain, grouping_sets, aggregates=aggregates, **kwargs)

    def _gec_check_search_panel(self, method, field_name, kwargs):
        """ Refuse a hidden field in what the client sent to a search panel: the field and the domains of this model,
        and on the comodel the group-by and values domain, which core reads with search_read under this model's call,
        unchecked. A tree of values whose parent field is hidden is shown flat, so the screen still opens. """
        rules = self._gec_rpc_entry(method) and self._gec_field_rules()
        if not rules:
            return
        self._gec_check_path(rules, field_name)
        for key in ('search_domain', 'category_domain', 'filter_domain'):
            self._gec_check_domain(rules, kwargs.get(key))
        group_domain = kwargs.get('group_domain')
        for domain in (group_domain.values() if isinstance(group_domain, dict) else [group_domain]):
            self._gec_check_domain(rules, domain)
        comodel = self._gec_comodel_of(field_name)
        if comodel is None:
            return
        if kwargs.get('group_by'):
            comodel._gec_check_path(rules, kwargs['group_by'])
        comodel._gec_check_domain(rules, kwargs.get('comodel_domain'))
        if method == 'search_panel_select_range' and comodel._parent_name in comodel._gec_hidden_any(rules):
            kwargs['hierarchize'] = False

    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        self._gec_check_search_panel('search_panel_select_range', field_name, kwargs)
        return super().search_panel_select_range(field_name, **kwargs)

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        self._gec_check_search_panel('search_panel_select_multi_range', field_name, kwargs)
        return super().search_panel_select_multi_range(field_name, **kwargs)

    @api.model
    def search_fetch(self, domain, field_names=None, offset=0, limit=None, order=None):
        rules = self._gec_rpc_entry('search_fetch') and self._gec_field_rules()
        if rules:
            self._gec_check_domain(rules, domain)
            self._gec_check_order(rules, order)
        return super().search_fetch(domain, field_names, offset=offset, limit=limit, order=order)

    def copy_data(self, default=None):
        """ Blank the hidden fields of each copy and its x2many lines; a conditional hide judges the source record, so
        ``id`` (left out of the values by core) is put back for the call. """
        rules = self._gec_rpc_entry('copy_data') and self._gec_field_rules()
        result = super().copy_data(default)
        if rules:
            for record, vals in zip(self, result):
                if vals is None:
                    continue
                row = dict(vals, id=record.id)
                self._gec_blank(rules, [row])
                row.pop('id')
                vals.update(row)
                self._gec_blank_lines(rules, vals)
        return result

    def _gec_blank_lines(self, rules, vals):
        """ Blank the hidden fields of the ``(0, 0, values)`` lines of ``vals``: a copy has no record to judge a
        condition on. """
        for name, value in vals.items():
            field = self._fields.get(name)
            if field is None or field.type not in ('one2many', 'many2many') or not isinstance(value, (list, tuple)):
                continue
            comodel = self.env[field.comodel_name]
            hidden = comodel._gec_hidden_any(rules)
            for command in value:
                if isinstance(command, (list, tuple)) and len(command) > 2 and isinstance(command[2], dict):
                    for hidden_name in hidden.intersection(command[2]):
                        multi = comodel._fields[hidden_name].type in ('one2many', 'many2many')
                        command[2][hidden_name] = [] if multi else False
                    comodel._gec_blank_lines(rules, command[2])

    def get_field_translations(self, field_name, langs=None):
        rules = self._gec_rpc_entry('get_field_translations') and self._gec_field_rules()
        if rules:
            self._gec_check_path(rules, field_name)
        return super().get_field_translations(field_name, langs=langs)

    def _update_field_translations(self, field_name, translations, digest=None, source_lang=''):
        """ Refuse the translations of a locked field, or one locked under a condition on the matching records: the
        client changes the field's value through them (update_field_translations, web_override_translations, website
        editor). """
        # endswith: the website may serve the route under a language prefix (/fr/website/...)
        via_website = request and request.httprequest.path.endswith(WEBSITE_TRANSLATION_PATH) and not self.env.su
        rules = (self._gec_rpc_entry('update_field_translations')
                 or self._gec_rpc_entry('web_override_translations') or via_website) and self._gec_field_rules()
        if rules:
            condition = rules.conditional_fields(self._name, ('hide', 'readonly')).get(field_name)
            if field_name in self._gec_locked(rules, self._name) or (
                    condition and self._gec_matching(condition, self.ids)):
                self._gec_refuse(self._name, field_name)
        return super()._update_field_translations(field_name, translations, digest=digest, source_lang=source_lang)

    def web_resequence(self, specification, field_name='sequence', offset=0):
        """ Refuse a locked or value-filtered field, and the archive field when a profile hides Archive. Records a
        condition locks are left out of the new order, so a drag over them does not fail; the answer reads all, hidden
        blanked. """
        entry = self._gec_rpc_entry('web_resequence')
        rules = entry and self._gec_field_rules()
        value_rules = entry and self._gec_value_rules()
        if entry:
            self.env['gec.access.profile']._check_archive_values(self._name, {field_name: True})
        if (rules and field_name in self._gec_locked(rules, self._name)) or (
                value_rules and value_rules.field_domain(self._name, field_name)):
            self._gec_refuse(self._name, field_name)
        records = self
        condition = rules and rules.conditional_fields(self._name, ('hide', 'readonly')).get(field_name)
        if condition:
            records = self - self.browse(self._gec_matching(condition, self.ids))
        result = super(Base, records).web_resequence(specification, field_name=field_name, offset=offset)
        if records != self:
            result = self.web_read(specification)
        return self._gec_blank(rules, result, specification) if rules else result

    def onchange_batch(self, values_list, field_names, fields_spec):
        rules = self._gec_rpc_entry('onchange_batch') and self._gec_field_rules()
        result = super().onchange_batch(values_list, field_names, fields_spec)
        if rules:
            records = self if len(self) == len(values_list) else [self.browse()] * len(values_list)
            for record, values, item in zip(records, values_list, result):
                if isinstance(item, dict) and isinstance(item.get('value'), dict):
                    record._gec_blank_onchange(rules, values, item['value'], fields_spec)
                    record._gec_blank(rules, [item['value']], fields_spec)
        return result

    def _gec_via_import_screen(self):
        """ Whether the Import screen runs this call: it reaches load through base_import.import.execute_import, not
        this model. """
        return 'base_import.import' in self.env and self.env['base_import.import']._gec_rpc_entry('execute_import')

    def _gec_import_rows(self):
        """ Whether the loaded rows are a client import: load marks its context with the model, read only in
        _load_records_create/_load_records_write, so Odoo's own writes on the model meanwhile (a company's contacts)
        pass. """
        return not self.env.su and self.env.context.get('gec_access_import') == self._name

    @api.model
    def load(self, fields, data):
        """ Check import columns against the locked fields; the rows it creates or writes are judged as a client's own
        in _load_records_create and _load_records_write, from the Import screen or a direct call of load. """
        imported = self._gec_rpc_entry('load') or self._gec_via_import_screen()
        rules = imported and self._gec_field_rules()
        if rules:
            # an import names its columns by path: order_line/price_unit
            for path in fields:
                self._gec_check_locked_path(rules, path.replace('/', '.').removesuffix('.id'))
        if imported:
            self = self.with_context(gec_access_import=self._name)
        return super().load(fields, data)

    def _load_records_create(self, vals_list):
        """ The rows an import creates: create right (stock.quant applies counts under sudo from here), value filters,
        locked fields. """
        if self._gec_import_rows():
            profile_rules = self.env['gec.access.profile']._current_rules()
            if profile_rules.enabled and not profile_rules.allows(self._name, 'create', self._gec_wizard()):
                raise self._make_access_error_message('create', Domain.FALSE)
            if value_rules := self._gec_value_rules():
                for vals in vals_list:
                    self._gec_check_values(value_rules, vals)
            if rules := self._gec_field_rules():
                vals_list = [self._gec_drop_locked(rules, vals, creating=True) for vals in vals_list]
        return super()._load_records_create(vals_list)

    def _load_records_write(self, values):
        """ The row an import writes on this record: value filters, locked fields, archiving, as for a client's write.
        """
        if self._gec_import_rows():
            unchanged = {name for name in ARCHIVE_FIELDS.intersection(values) if values[name] == self[name]}
            self.env['gec.access.profile']._check_archive_values(
                self._name, {name: value for name, value in values.items() if name not in unchanged})
            if value_rules := self._gec_value_rules():
                self._gec_check_values(value_rules, values, self)
            if rules := self._gec_field_rules():
                values = self._gec_drop_locked(rules, values, self)
        return super()._load_records_write(values)

    def copy(self, default=None):
        rules = self._gec_rpc_entry('copy') and self._gec_field_rules()
        value_rules = self._gec_rpc_entry('copy') and self._gec_value_rules()
        if rules and default:
            default = self._gec_drop_locked(rules, default, creating=True)
        if value_rules and default:
            for record in self:
                self._gec_check_values(value_rules, default, record)
        return super().copy(default)

    def _gec_check_locked_path(self, rules, path):
        model = self
        for name in path.split('.'):
            name = name.split('@')[0]
            if name in self._gec_locked(rules, model._name):
                self._gec_refuse(model._name, name)
            field = model._fields.get(name)
            if field is None or not field.relational:
                return
            model = self.env[field.comodel_name]

    def _gec_client_reads_model(self):
        """ Whether the client itself calls a method of this model through RPC (web, JSON-2, XML-RPC), whatever the
        method. """
        if request:
            entry = getattr(request, 'gec_rpc_entry', None)
            return isinstance(entry, tuple) and entry[0] == self._name
        marker = getattr(threading.current_thread(), 'rpc_model_method', None)
        return bool(marker) and marker.rpartition('.')[0] == self._name

    @api.model
    def _has_field_access(self, field, operation):
        """ Binary and image fields only: denied (hidden to read, locked to write), with the images derived from them,
        to /web/content, /web/image and attachment checks, but not to the model's own RPC, where the guard blanks or
        drops the value. Other field types are left alone: Odoo's own code reads them as the user. """
        if (operation in ('read', 'write') and field.type in ('binary', 'image') and not self.env.su
                and super()._has_field_access(field, operation)):
            model = self.env[field.model_name]
            if not model._gec_client_reads_model():
                rules = self.env['gec.access.profile']._current_rules()
                if rules.enabled:
                    names = (model._gec_hidden if operation == 'read' else model._gec_locked)(rules, model._name)
                    if field.name in model._gec_binary_family(names):
                        return False
        return super()._has_field_access(field, operation)

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields=allfields, attributes=attributes)
        rules = self._gec_rpc_entry('fields_get') and self._gec_field_rules()
        if rules:
            for name in self._gec_hidden_any(rules):
                result.pop(name, None)
            # the Export dialog leaves out what is not exportable
            for name in rules.not_exported(self._name):
                if name in result:
                    result[name]['exportable'] = False
        return result

    def onchange(self, values, field_names, fields_spec):
        rules = self._gec_rpc_entry('onchange') and self._gec_field_rules()
        result = super().onchange(values, field_names, fields_spec)
        if rules and isinstance(result.get('value'), dict):
            self[:1]._gec_blank_onchange(rules, values, result['value'], fields_spec)
            self._gec_blank(rules, [result['value']], fields_spec)
        return result

    def web_save(self, vals, specification, next_id=None):
        """ Records a condition treats differently are saved in one call per group, as in write; a new one takes the
        context defaults. """
        entry = self._gec_rpc_entry('web_save')
        rules = entry and self._gec_field_rules()
        pairs = [(self, vals)]
        if entry and self:
            pairs = self._gec_client_values('write', vals)
        elif entry:
            if value_rules := self._gec_value_rules():
                self._gec_check_values(value_rules, {**self._gec_context_defaults(), **vals})
            if rules:
                pairs = [(self, self._gec_drop_locked(rules, vals, creating=True))]
        if len(pairs) > 1:
            for records, values in pairs:
                super(Base, records).web_save(values, {})
            result = (self.browse(next_id) if next_id else self).web_read(specification)
        else:
            result = super().web_save(pairs[0][1], specification, next_id=next_id)
        return self._gec_blank(rules, result, specification) if rules else result

    def web_save_multi(self, vals_list, specification):
        """ Each record gets its own values: judged as a client write (value filters, locked fields, conditions on the
        record), the result blanked like a read. A list of another length is left to core, which refuses it. """
        rules = self._gec_rpc_entry('web_save_multi') and self._gec_field_rules()
        if len(self) == len(vals_list):
            if self._gec_rpc_entry('web_save_multi') and (value_rules := self._gec_value_rules()):
                for record, vals in zip(self, vals_list):
                    self._gec_check_values(value_rules, vals, record)
            if rules:
                vals_list = [self._gec_drop_locked(rules, vals, record) for record, vals in zip(self, vals_list)]
        result = super().web_save_multi(vals_list, specification)
        return self._gec_blank(rules, result, specification) if rules else result

    def _gec_client_writes(self):
        """ Whether the client's own call is a write of this model: write, or a write of the gantt view. """
        return any(self._gec_rpc_entry(method) for method in CLIENT_WRITE_ENTRIES)

    def _gec_client_values(self, method, values, *, second_line=False, refuse=False):
        """ The ``(records, values)`` pairs for ``method``, judged before overrides rename the keys, one per group
        treated alike. ``second_line`` of a create keeps the fields its create requires; a name_create setting a locked
        name or required field is refused, not dropped (the record would lack it); ``refuse``: see _gec_drop_locked. """
        value_rules, rules = self._gec_value_rules(), self._gec_field_rules()
        if not (value_rules or rules):
            return [(self, values)]
        if method in ('create', 'name_create'):
            many = isinstance(values, (list, tuple))
            vals_list = list(values) if many else [values]
            if not all(isinstance(vals, dict) for vals in vals_list):
                return [(self, values)]
            if value_rules:
                defaults = self._gec_context_defaults()
                for vals in vals_list:
                    self._gec_check_values(value_rules, {**defaults, **vals})
            if rules:
                kept = {name for name, field in self._fields.items() if field.required} if second_line else set()
                if method == 'name_create':
                    kept.add(self._rec_name)
                    locked = kept & set(self._gec_locked(rules, self._name))
                    for vals in vals_list:
                        if names := vals.keys() & locked:
                            self._gec_refuse(self._name, sorted(names)[0])
                vals_list = [{**{name: vals[name] for name in vals.keys() & kept},
                              **self._gec_drop_locked(rules, vals, refuse=refuse, creating=True)}
                             for vals in vals_list]
            return [(self, vals_list if many else vals_list[0])]
        if not isinstance(values, dict):
            return [(self, values)]
        if method == 'action_rollback_scheduling':
            judged = dict(values)
            for record in self:
                for key in (str(record.id), record.id):
                    if isinstance(values.get(key), dict):
                        if value_rules:
                            self._gec_check_values(value_rules, values[key], record)
                        if rules:
                            judged[key] = self._gec_drop_locked(rules, values[key], record, refuse)
            return [(self, judged)]
        if value_rules:
            for record in self:
                self._gec_check_values(value_rules, values, record)
        if not rules:
            return [(self, values)]
        conditional = rules.conditional_fields(self._name, ('hide', 'readonly'))
        matching = {name: self._gec_matching(condition, self.ids)
                    for name, condition in conditional.items() if name in values}
        groups = {}
        for record in self:
            matched = frozenset(name for name, ids in matching.items() if record.id in ids)
            if refuse and matched:
                self._gec_refuse(self._name, sorted(matched)[0])
            groups.setdefault(matched, []).append(record.id)
        unlocked = self._gec_drop_locked(rules, values, refuse=refuse, parents=self)
        return [(self.browse(ids), {name: value for name, value in unlocked.items() if name not in matched})
                for matched, ids in (groups or {frozenset(): []}).items()]

    def write(self, vals):
        """ Second line of the guard: a client write judged again on the values the model's overrides left, when no door
        judged it (web_gantt_reschedule, ids a door cannot read). Inside a write a door judged, what Odoo copies or
        derives (a contact's address to its company) is Odoo's, as in a form save. """
        if self._gec_client_writes() and CLIENT_WRITE.get() != self._name:
            for records, values in self._gec_client_values('write', vals):
                super(Base, records).write(values)
            return True
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """ Second line of the guard: a create or kanban quick create's name_create, judged again on the values the
        model's overrides left; required fields its own create filled stay (a name_create setting a locked one is
        refused); the client's own keys were judged at the entry. """
        name_create = self._gec_rpc_entry('name_create')
        if name_create or self._gec_rpc_entry('create'):
            [(_records, vals_list)] = self._gec_client_values(
                'name_create' if name_create else 'create', vals_list, second_line=True)
        return super().create(vals_list)
