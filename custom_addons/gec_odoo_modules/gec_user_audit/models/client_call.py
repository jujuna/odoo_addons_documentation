import threading
from contextvars import ContextVar

from odoo import models
from odoo.http import request

# XML-RPC and JSON-RPC run without a request, so their controllers keep the client's address here
RPC_ADDRESS = ContextVar('gec_user_audit_rpc_address', default=None)
LOOKUP_METHODS = frozenset({'name_search', 'web_name_search'})
LOOKUP_BOUNDARY = ContextVar('gec_user_audit_lookup_boundary', default=None)


def mark_rpc_entry(model_name, method):
    if request:
        request.gec_rpc_entry = (model_name, method)


def client_address():
    if request:
        return request.httprequest.remote_addr
    return RPC_ADDRESS.get()


class Base(models.AbstractModel):
    _inherit = 'base'

    def _gec_rpc_entry(self, method):
        """ Whether ``method`` of this model is the call the client or the script made. """
        if self.env.su:
            return False
        if request:
            entry = getattr(request, 'gec_rpc_entry', None)
            return isinstance(entry, tuple) and entry[0] == self._name and entry[1] in (method, '*')
        marker = getattr(threading.current_thread(), 'rpc_model_method', None)
        return marker == f'{self._name}.{method}'
