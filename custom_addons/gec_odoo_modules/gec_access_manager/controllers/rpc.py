from odoo.service import model as service_model

from ..models.field_guard import CLIENT_READ_ENTRIES, client_write
from .dataset import (
    PROTECTED_METHODS, _record_ids, check_client_defaults, check_create_right, client_calls, judged_write,
)


def with_button_check(call_kw):
    """ Wrap ``odoo.service.model.call_kw`` so XML-RPC and JSON-RPC get the web client's button, archive, read and
    write/create checks. Process-wide, applied once on import for every database; the marker stops a second wrap. """
    if getattr(call_kw, 'gec_button_check', False):
        return call_kw

    def checked_call_kw(model, name, args, kwargs):
        # every database of the server goes through here, installed or not
        calls, guarded = [(args, kwargs)], 'gec.access.profile' in model.env
        if guarded:
            if name not in PROTECTED_METHODS:
                model.env['gec.access.profile']._check_button(model._name, 'object', name, _record_ids(args))
            model.env['gec.access.profile']._check_archive_call(model._name, name, args, kwargs)
            check_create_right(model.env, model._name, name, args)
            check_client_defaults(model.env, model._name, name, args, kwargs)
            if name in CLIENT_READ_ENTRIES:
                model._gec_check_client_read(name, args, kwargs)
            calls = client_calls(model.env, model._name, name, args, kwargs, refuse=True)
        with client_write(model._name, guarded and judged_write(name, args)):
            for call_args, call_kwargs in calls:
                result = call_kw(model, name, call_args, call_kwargs)
        return result
    checked_call_kw.gec_button_check = True
    return checked_call_kw


service_model.call_kw = with_button_check(service_model.call_kw)
