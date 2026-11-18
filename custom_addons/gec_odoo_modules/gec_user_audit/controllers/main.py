import json
import logging

from odoo import api, http
from odoo.http import request
from odoo.modules.registry import Registry

from odoo.addons.rpc.controllers import jsonrpc, xmlrpc
from odoo.addons.rpc.controllers.json2 import WebJson2Controller
from odoo.addons.web.controllers.dataset import DataSet
from odoo.addons.web.controllers.export import CSVExport, ExcelExport, Export
from odoo.addons.web.controllers.json import WebJsonController
from odoo.addons.web.controllers.report import ReportController
from odoo.addons.web.controllers.webclient import ModelTranslations

from ..models.client_call import LOOKUP_BOUNDARY, LOOKUP_METHODS, RPC_ADDRESS, mark_rpc_entry

_logger = logging.getLogger(__name__)


def mark_export(data):
    try:
        model = json.loads(data).get('model')
    except (TypeError, ValueError, AttributeError):
        model = None
    if model:
        mark_rpc_entry(model, '*')


def with_address(dispatch_rpc):
    """ Keep the client's address: ``dispatch_rpc`` unbinds the request. The patch is process-wide, applied once on
    import to the XML-RPC and JSON-RPC dispatchers (the marker stops a double wrap). """
    if getattr(dispatch_rpc, 'gec_with_address', False):
        return dispatch_rpc

    def dispatch(service, method, params):
        """Let completed RPC lookups own their audit event, after authentication."""
        token = RPC_ADDRESS.set(request.httprequest.remote_addr if request else None)
        entry = ((params[3], params[4]) if service == 'object' and method in ('execute', 'execute_kw')
                 and len(params) >= 5 and params[4] in LOOKUP_METHODS else None)
        lookup_token = LOOKUP_BOUNDARY.set(entry)
        try:
            try:
                result = dispatch_rpc(service, method, params)
            finally:
                LOOKUP_BOUNDARY.reset(lookup_token)
            if entry and 'gec.user.audit.log' in (registry := Registry(params[0])):
                context = ((params[6] or {}).get('context', {}) if method == 'execute_kw' and len(params) > 6 else {})
                try:
                    with registry.cursor() as cr:
                        env = api.Environment(cr, int(params[1]), context)
                        mark_rpc_entry(*entry)
                        env[entry[0]]._gec_audit_lookup_result(entry[1], result)
                except Exception:
                    _logger.warning("Could not audit completed RPC lookup %s.%s", *entry, exc_info=True)
            return result
        finally:
            RPC_ADDRESS.reset(token)
    dispatch.gec_with_address = True
    return dispatch


# RPC routes run without a database, so controller overrides never apply: wrap the function they call instead
xmlrpc.dispatch_rpc = with_address(xmlrpc.dispatch_rpc)
jsonrpc.dispatch_rpc = with_address(jsonrpc.dispatch_rpc)


class DataSetAudit(DataSet):

    @http.route()
    def call_kw(self, model, method, args, kwargs, path=None):
        """Record the final lookup result even when a model bypasses the base hook."""
        mark_rpc_entry(model, method)
        if method not in LOOKUP_METHODS:
            return super().call_kw(model, method, args, kwargs, path=path)
        token = LOOKUP_BOUNDARY.set((model, method))
        try:
            result = super().call_kw(model, method, args, kwargs, path=path)
        finally:
            LOOKUP_BOUNDARY.reset(token)
        request.env[model].with_context(kwargs.get('context') or {})._gec_audit_lookup_result(method, result)
        return result

    @http.route()
    def call_button(self, model, method, args, kwargs, path=None):
        mark_rpc_entry(model, method)
        return super().call_button(model, method, args, kwargs, path=path)


class WebJson2Audit(WebJson2Controller):

    @http.route()
    def web_json_2_rpc(self, __model__, __method__, *args, **kwargs):
        """Record JSON-2 lookup results once after the concrete model returns."""
        mark_rpc_entry(__model__, __method__)
        if __method__ not in LOOKUP_METHODS:
            return super().web_json_2_rpc(__model__, __method__, *args, **kwargs)
        token = LOOKUP_BOUNDARY.set((__model__, __method__))
        try:
            result = super().web_json_2_rpc(__model__, __method__, *args, **kwargs)
        finally:
            LOOKUP_BOUNDARY.reset(token)
        context = kwargs.get('context') or (args[1] if len(args) > 1 else {})
        request.env[__model__].with_context(context)._gec_audit_lookup_result(__method__, result)
        return result


class WebJsonAudit(WebJsonController):
    # the /json views read the action's model with a domain and group-bys from the URL

    def _get_action(self, subpath):
        result = super()._get_action(subpath)
        mark_rpc_entry(result[0].res_model, '*')
        return result


class ExportAudit(Export):

    @http.route()
    def get_fields(self, model, domain, prefix='', parent_name='', import_compat=True, parent_field_type=None, parent_field=None, exclude=None):
        mark_rpc_entry(model, '*')
        return super().get_fields(model, domain, prefix=prefix, parent_name=parent_name, import_compat=import_compat,
            parent_field_type=parent_field_type, parent_field=parent_field, exclude=exclude)


class CSVExportAudit(CSVExport):

    @http.route()
    def web_export_csv(self, data):
        mark_export(data)
        return super().web_export_csv(data)


class ExcelExportAudit(ExcelExport):

    @http.route()
    def web_export_xlsx(self, data):
        mark_export(data)
        return super().web_export_xlsx(data)


class ModelTranslationsAudit(ModelTranslations):
    # the translation dialog reads and writes a field's translations through its own routes

    @http.route()
    def get_translation_for_field(self, res_model, field_name, res_id, target_lang=None, context=None):
        mark_rpc_entry(res_model, 'get_field_translations')
        return super().get_translation_for_field(res_model, field_name, res_id, target_lang=target_lang, context=context)

    @http.route()
    def save_translation_for_field(self, res_model, field_name, res_id, target_lang=None, changes=None, context=None):
        mark_rpc_entry(res_model, 'update_field_translations')
        return super().save_translation_for_field(res_model, field_name, res_id, target_lang=target_lang, changes=changes, context=context)


class ReportAudit(ReportController):

    @http.route()
    def report_routes(self, reportname, docids=None, converter=None, **data):
        response = super().report_routes(reportname, docids=docids, converter=converter, **data)
        report = request.env['ir.actions.report'].sudo()._get_report_from_name(reportname)
        model = request.env.get(report.model) if report else None
        if model is not None and model._gec_audit('print'):
            ids = [int(i) for i in (docids or '').split(',') if i.strip().isdigit()]
            request.env['gec.user.audit.log']._gec_log('print', model=report.model, method=reportname, record_ids=ids,
                res_id=ids[0] if len(ids) == 1 else False, res_name=model.browse(ids[0]).sudo().display_name if len(ids) == 1 else False,
                detail=report.name)
        return response
