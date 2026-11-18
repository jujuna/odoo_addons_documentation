from odoo import http
from odoo.fields import Command, Domain
from odoo.http import request

from odoo.addons.web.controllers.dataset import DataSet

from ..models.field_guard import CLIENT_READ_ENTRIES, CLIENT_VALUES, client_write, is_id_number
from ..models.gec_access_preview import preview_allowed, preview_of_request, preview_refused

# Not button checked: denying these is Base._access_domain()'s job.
PROTECTED_METHODS = frozenset({
    'create', 'write', 'unlink', 'web_save', 'web_read', 'web_search_read',
    'read', 'search', 'search_read', 'onchange', 'copy', 'default_get',
})

# what the web client calls to show a screen and writes nothing, though not declared readonly (a preview is read only)
PREVIEW_METHODS = frozenset({
    'onchange', 'default_get', 'fields_get', 'search_panel_select_range', 'search_panel_select_multi_range',
    'get_gantt_data', 'get_unusual_days', 'display_name_for', 'get_all_currencies', 'lazy_session_info',
    'get_report_information', 'action_get', 'get_available_models', 'get_attendee_detail',
    'get_department_hierarchy', 'cycles_in_hierarchy_read', 'get_extra_print_items', 'check_move_sequence_chain',
    'retrieve_sale_dashboard', 'retrieve_dashboard',
})


def _preview_may_call(model, method):
    """ Whether ``method`` runs in a preview: declared readonly (DataSet._call_kw_readonly), or a screen needs it. """
    if method in PREVIEW_METHODS:
        return True
    for cls in request.registry[model].mro():
        func = getattr(cls, method, None)
        if func is not None and hasattr(func, '_readonly'):
            return func._readonly
    return False


def _record_ids(args):
    """ The ids core would browse: a number or a list of numbers (JSON and XML-RPC send 5.0 too), else None. """
    ids = args[0] if args else None
    numbers = ids if isinstance(ids, (list, tuple)) else [ids]
    if all(is_id_number(number) for number in numbers):
        return list(numbers)
    return None


def check_create_right(env, model, method, args):
    """ Refuse a forbidden create before the call: some core creates (stock.quant) go sudo before their own check. """
    creates = method in ('create', 'name_create') or (method == 'web_save' and not (args and args[0]))
    if not creates or model not in env:
        return
    records = env[model]
    rules = env['gec.access.profile']._current_rules()
    if rules.enabled and not rules.allows(model, 'create', records._gec_wizard()):
        raise records._make_access_error_message('create', Domain.FALSE)


# where the values of a method that creates records sit: (position among the arguments, keyword)
CREATING_VALUES = {
    'create': (0, 'vals_list'), 'write': (1, 'vals'), 'web_save': (1, 'vals'), 'web_save_multi': (1, 'vals_list'),
    'copy': (1, 'default'),
}


def check_client_defaults(env, model, method, args, kwargs):
    """ Refuse, on the API doors (json2.py, rpc.py), a default_ key of the context for a field locked on a record the
    call creates: core fills a missing field from it after the values were judged, and refuses such a key for a field
    the user may not write. The web client's doors keep Odoo's behaviour: its menus and views preset fields so. """
    context = kwargs.get('context')
    names = {key[8:] for key in context or () if isinstance(key, str) and key.startswith('default_')}
    if not names or model not in env or not (rules := env[model]._gec_field_rules()):
        return
    created = set()
    if method in ('create', 'name_create', 'copy', 'load') or (method == 'web_save' and not (args and args[0])):
        created.add(model)

    def lines(model_name, vals):
        """ Add the models of the records the x2many commands of ``vals`` create, at any depth. """
        model_fields = env[model_name]._fields
        for name, commands in (vals.items() if isinstance(vals, dict) else ()):
            field = model_fields.get(name)
            if field is None or field.type not in ('one2many', 'many2many') or not isinstance(commands, (list, tuple)):
                continue
            for command in commands:
                if isinstance(command, (list, tuple)) and command and command[0] in (Command.CREATE, Command.UPDATE):
                    if command[0] == Command.CREATE:
                        created.add(field.comodel_name)
                    if len(command) > 2:
                        lines(field.comodel_name, command[2])

    if method in CREATING_VALUES:
        position, keyword = CREATING_VALUES[method]
        values = args[position] if len(args) > position else kwargs.get(keyword)
        for vals in values if isinstance(values, (list, tuple)) else [values]:
            lines(model, vals)
    for model_name in sorted(created):
        if locked := sorted(names & set(env[model_name]._gec_locked(rules, model_name))):
            env[model_name]._gec_refuse(model_name, locked[0])


def judged_write(method, args):
    """ Whether the door judges this client write (on ids it can read); Odoo's writes meanwhile are not: Base.write. """
    return method in CLIENT_VALUES and method != 'create' and _record_ids(args) is not None


def client_calls(env, model, method, args, kwargs, refuse=False):
    """ The calls for one client call: values judged as sent, one call per group of records the conditions treat alike;
    with ``refuse`` a locked value is refused instead of dropped. """
    if method not in CLIENT_VALUES or model not in env:
        return [(args, kwargs)]
    position, keyword = CLIENT_VALUES[method]
    records = env[model].with_context(kwargs.get('context') or {})
    if method != 'create':
        ids = _record_ids(args)
        if ids is None:
            return [(args, kwargs)]
        records = records.browse(ids)
        position += 1
    if len(args) <= position and keyword not in kwargs:
        return [(args, kwargs)]
    values = args[position] if len(args) > position else kwargs[keyword]
    calls = []
    for pair_records, pair_values in records._gec_client_values(method, values, refuse=refuse):
        call_args, call_kwargs = list(args), dict(kwargs)
        if method != 'create':
            call_args[0] = pair_records.ids
        if len(args) > position:
            call_args[position] = pair_values
        else:
            call_kwargs[keyword] = pair_values
        calls.append((call_args, call_kwargs))
    return calls


class DataSetAccess(DataSet):

    @http.route()
    def call_kw(self, model, method, args, kwargs, path=None):
        if method not in PROTECTED_METHODS:
            request.env['gec.access.profile']._check_button(model, 'object', method, _record_ids(args))
        request.env['gec.access.profile']._check_archive_call(model, method, args, kwargs)
        check_create_right(request.env, model, method, args)
        if method in CLIENT_READ_ENTRIES and model in request.env:
            request.env[model]._gec_check_client_read(method, args, kwargs)
        if preview_of_request() and not _preview_may_call(model, method):
            raise preview_refused()
        with client_write(model, judged_write(method, args)):
            for call_args, call_kwargs in client_calls(request.env, model, method, args, kwargs):
                result = super().call_kw(model, method, call_args, call_kwargs, path=path)
        return result

    @http.route()
    def call_button(self, model, method, args, kwargs, path=None):
        """ The same button, archive and read checks as call_kw: a crafted call_button of write cannot archive. """
        if method not in PROTECTED_METHODS:
            request.env['gec.access.profile']._check_button(model, 'object', method, _record_ids(args))
        request.env['gec.access.profile']._check_archive_call(model, method, args, kwargs)
        check_create_right(request.env, model, method, args)
        if method in CLIENT_READ_ENTRIES and model in request.env:
            request.env[model]._gec_check_client_read(method, args, kwargs)
        if preview_of_request():
            raise preview_allowed()
        with client_write(model, judged_write(method, args)):
            for call_args, call_kwargs in client_calls(request.env, model, method, args, kwargs):
                result = super().call_button(model, method, call_args, call_kwargs, path=path)
        return result
