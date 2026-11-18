from odoo import http
from odoo.http import request

from odoo.addons.rpc.controllers.json2 import WebJson2Controller
from ..models.field_guard import CLIENT_READ_ENTRIES, client_write
from .dataset import (
    PROTECTED_METHODS, _record_ids, check_client_defaults, check_create_right, client_calls, judged_write,
)


class WebJson2Access(WebJson2Controller):

    @http.route()
    def web_json_2_rpc(self, __model__, __method__, *args, **kwargs):
        if __method__ not in PROTECTED_METHODS:
            request.env['gec.access.profile']._check_button(
                __model__, 'object', __method__, _record_ids([kwargs.get('ids')]))
        request.env['gec.access.profile']._check_archive_call(__model__, __method__, [kwargs.get('ids')], kwargs)
        if __method__ in CLIENT_READ_ENTRIES and __model__ in request.env:
            request.env[__model__]._gec_check_client_read(
                __method__, args, {key: value for key, value in kwargs.items() if key not in ('ids', 'context')})
        given = [] if __method__ == 'create' else [kwargs.get('ids')]
        check_create_right(request.env, __model__, __method__, given)
        check_client_defaults(request.env, __model__, __method__, given, kwargs)
        with client_write(__model__, judged_write(__method__, given)):
            for call_args, call_kwargs in client_calls(request.env, __model__, __method__, given, kwargs, refuse=True):
                if 'ids' in kwargs and call_args:
                    call_kwargs = dict(call_kwargs, ids=call_args[0])
                result = super().web_json_2_rpc(__model__, __method__, *args, **call_kwargs)
        return result
