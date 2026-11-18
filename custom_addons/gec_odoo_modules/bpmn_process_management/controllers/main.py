# Part of bpmn_process_management. License LGPL-3.
import re

from odoo import http
from odoo.http import request

from ..lib.bpmn_common import BpmnError
from ..lib.drawio_export import bpmn_to_drawio

try:
    from odoo.http import content_disposition
except ImportError:
    from odoo.http.stream import content_disposition


GUIDE_FILES = {"ka": "user_guide.html", "en": "user_guide_en.html"}


class BpmnExportController(http.Controller):

    @http.route("/bpmn_process_management/guide", type="http", auth="user", methods=["GET"])
    def guide(self, **kw):
        """Redirect to the user guide in the user's language; the link's #section survives."""
        lang = (request.env.user.lang or "en_US").split("_")[0]
        name = GUIDE_FILES.get(lang, GUIDE_FILES["en"])
        return request.redirect("/bpmn_process_management/static/doc/" + name, local=True)

    @http.route("/bpmn_process_management/export/<int:process_id>/<string:fmt>",
                type="http", auth="user", methods=["GET"])
    def export(self, process_id, fmt, **kw):
        process = request.env["business.process"].browse(process_id).exists()
        if not process:
            raise request.not_found()
        process.check_access("read")
        base = re.sub(r"[^\w\-. ]+", "_", "%s v%s" % (process.name, process.version)).strip() or "process"
        if fmt == "bpmn":
            data = (process.bpmn_xml or "").encode("utf-8")
            filename, ctype = base + ".bpmn", "application/xml; charset=utf-8"
        elif fmt == "drawio":
            try:
                data = bpmn_to_drawio(process.bpmn_xml, name=process.name).encode("utf-8")
            except BpmnError as e:
                return request.make_response(str(e), status=409, headers=[
                    ("Content-Type", "text/plain; charset=utf-8")])
            filename, ctype = base + ".drawio", "application/xml; charset=utf-8"
        else:
            raise request.not_found()
        return request.make_response(data, headers=[
            ("Content-Type", ctype),
            ("Content-Disposition", content_disposition(filename)),
            ("X-Content-Type-Options", "nosniff"),
        ])
