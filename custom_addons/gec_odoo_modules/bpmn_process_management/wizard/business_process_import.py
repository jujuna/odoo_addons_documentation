import base64
import logging
import os
import re

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..lib.bpmn_common import BpmnError, has_diagram, normalize_bpmn, parse_bpmn
from ..lib.bpmn_index import apply_responsible_matching
from ..lib.drawio_import import convert_drawio
from ..lib.visio_import import convert_visio

_logger = logging.getLogger(__name__)
MAX_UPLOAD = 25 * 1024 * 1024


def binary_content(value):
    """Raw bytes of a Binary field value (base64 string or BinaryValue)."""
    if not value:
        return b""
    if hasattr(value, "content"):
        return value.content
    if isinstance(value, str):
        value = value.encode()
    return base64.b64decode(value)


class BusinessProcessImport(models.TransientModel):
    _name = "business.process.import"
    _description = "Import a process diagram"

    file = fields.Binary("File")
    filename = fields.Char()
    mode = fields.Selection([
        ("new", "Create new process(es)"),
        ("replace", "Replace the diagram of a draft process"),
    ], default="new", required=True)
    process_id = fields.Many2one("business.process", string="Process",
                                 domain=[("state", "=", "draft")])
    pages = fields.Selection([
        ("all", "All pages (one process per page)"),
        ("first", "First page only"),
    ], default="all", required=True,
        help="draw.io and Visio files can contain several pages.")
    category = fields.Selection([
        ("core", "Core (Operational)"),
        ("support", "Supporting"),
        ("management", "Management"),
    ], string="Process Type", default="core")
    parent_id = fields.Many2one("business.process", string="Parent Process")
    match_responsibles = fields.Boolean(
        "Match lanes automatically", default=True,
        help="Link lanes to departments, job positions or user groups having exactly the "
             "same name. Every lane is flagged for review either way.")

    demo_loaded = fields.Boolean("Demo data loaded", compute="_compute_demo_loaded")

    def _compute_demo_loaded(self):
        loaded = self.env["business.process"].bpmn_demo_loaded()
        for rec in self:
            rec.demo_loaded = loaded

    def action_load_demo(self):
        Process = self.env["business.process"]
        Process.bpmn_load_demo()
        tag = self.env.ref("bpmn_process_management_demo.tag_demo", raise_if_not_found=False)
        domain = [("tag_ids", "in", tag.ids)] if tag else []
        name = self.env._("Demo processes")
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "bpmn_process_management.business_process_action_all")
        action.update({
            "name": name,
            "domain": domain,
            "context": {"active_test": False},
            "target": "main",
        })
        return action

    def action_remove_demo(self):
        self.env["business.process"].bpmn_remove_demo()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success", "message": self.env._("Demo data was removed."),
            "next": {"type": "ir.actions.act_window_close"}}}

    @api.onchange("mode")
    def _onchange_mode(self):
        if self.mode == "replace":
            self.pages = "first"

    def _detect_format(self, data, filename):
        ext = os.path.splitext(filename or "")[1].lower()
        if ext in (".bpmn", ".bpmn2"):
            return "bpmn"
        if ext in (".vsdx", ".vsdm", ".vsd", ".vssx"):
            return "visio"
        if ext in (".drawio", ".dio", ".svg", ".png"):
            return "drawio"
        if data[:4] == b"PK\x03\x04" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return "visio"
        if data.startswith(b"\x89PNG"):
            return "drawio"
        head = data[:65536].decode("utf-8", "ignore")
        root = re.search(r"<(?![?!])([\w.-]+:)?([\w.-]+)", re.sub(r"<!--.*?-->", "", head, flags=re.S))
        tag = root.group(2) if root else ""
        if tag in ("mxfile", "mxGraphModel"):
            return "drawio"
        if tag == "definitions":
            return "bpmn"
        raise UserError(self.env._(
            "Unsupported file. Use a .bpmn (BPMN 2.0), .drawio / .xml / .svg / .png "
            "(draw.io) or .vsdx (Visio) file."))

    def _convert(self):
        if not self.file:
            raise UserError(self.env._("Choose a file to import first."))
        data = binary_content(self.file)
        if not data:
            raise UserError(self.env._("The file is empty."))
        if len(data) > MAX_UPLOAD:
            raise UserError(self.env._("The file is larger than 25 MB."))
        fmt = self._detect_format(data, self.filename)
        pages = "first" if self.mode == "replace" else self.pages
        try:
            if fmt == "bpmn":
                xml = normalize_bpmn(data)
                root = parse_bpmn(xml)
                warnings = [] if has_diagram(root) else [("no_layout", {})]
                return fmt, [{"name": "", "xml": xml, "warnings": warnings}]
            if fmt == "visio":
                return fmt, convert_visio(data, pages=pages)
            return fmt, convert_drawio(data, pages=pages)
        except BpmnError as e:
            raise UserError(self.env._("The file could not be imported: %s", e)) from e
        except Exception as e:  # noqa: BLE001 - malformed third-party files must not give a 500
            _logger.exception("BPMN import of %s failed", self.filename)
            raise UserError(self.env._(
                "The file could not be imported: it is damaged or uses an unsupported variant "
                "of the format.")) from e

    def _warning_text(self, code, params):
        name = params.get("name") or ""
        reason = params.get("reason")
        msgs = {
            "edge_dropped": {
                "not_connected": self.env._("Connector \"%s\" is not attached to shapes at both ends and was skipped.", name),
                "self_loop": self.env._("Connector \"%s\" starts and ends on the same shape and was skipped.", name),
                "pool_connection": self.env._("Connector \"%s\" links a pool to itself and was skipped.", name),
                "crosses_subprocess": self.env._("Connector \"%s\" crosses the border of a sub-process and was skipped.", name),
                "unsupported": self.env._("Connector \"%s\" links shapes that BPMN cannot connect and was skipped.", name),
            },
            "node_outside_pool": self.env._("\"%s\" was outside every pool and was moved into the nearest one.", name),
            "dashed_in_pool": self.env._("Dashed connector \"%s\" inside one pool was converted to a sequence flow.", name),
            "boundary_detached": self.env._("Event \"%s\" is not attached to a task border; imported as an intermediate event.", name),
            "lanes_grouped": self.env._("%s separate swimlanes were grouped into one pool.", params.get("count")),
            "data_link_as_association": self.env._("Link \"%s\" between data objects was imported as an association.", name),
            "no_layout": self.env._("The file has no diagram layout; it will be laid out automatically when opened."),
        }
        msg = msgs.get(code)
        if isinstance(msg, dict):
            msg = msg.get(reason) or msg.get("unsupported")
        return msg or code

    def _report(self, fmt, page, matched, missing):
        fmt_label = {"bpmn": "BPMN 2.0", "drawio": "draw.io", "visio": "Microsoft Visio"}[fmt]
        lines = [self.env._("Imported from %(format)s file \"%(file)s\".",
                            format=fmt_label, file=self.filename or "")]
        if matched or missing:
            lines.append(self.env._(
                "Lanes: %(matched)s matched automatically (please confirm), %(missing)s need a "
                "department or role.", matched=matched, missing=missing))
        warn = [self._warning_text(c, p) for c, p in page["warnings"]]
        body = Markup("<p>%s</p>") % Markup("<br/>").join(escape(x) for x in lines)
        if warn:
            items = Markup("").join(Markup("<li>%s</li>") % w for w in warn[:50])
            if len(warn) > 50:
                items += Markup("<li>%s</li>") % self.env._("... and %s more.", len(warn) - 50)
            body += Markup("<ul>%s</ul>") % items
        return body

    def action_import(self):
        self.ensure_one()
        Process = self.env["business.process"]
        Process._check_manager()
        fmt, pages = self._convert()
        matcher = Process._responsible_matcher() if self.match_responsibles else (lambda n: None)
        stem = os.path.splitext(os.path.basename(self.filename or ""))[0] or self.env._("Imported process")
        created = Process.browse()
        for page in pages:
            xml, matched, missing = apply_responsible_matching(page["xml"], matcher)
            body = self._report(fmt, page, matched, missing)
            if self.mode == "replace":
                target = self.process_id
                if not target:
                    raise UserError(self.env._("Select the draft process to update."))
                if target.state != "draft":
                    raise UserError(self.env._("Only draft processes can be replaced."))
                target.write({"bpmn_xml": xml, "diagram_preview": False})
                target.message_post(body=body)
                created |= target
                break
            name = stem
            if len(pages) > 1 and page["name"]:
                name = "%s - %s" % (stem, page["name"])
            rec = Process.create({
                "name": name,
                "bpmn_xml": xml,
                "category": self.category or "core",
                "parent_id": self.parent_id.id,
            })
            rec.message_post(body=body)
            created |= rec
        if len(created) == 1:
            return {"type": "ir.actions.act_window", "res_model": "business.process",
                    "res_id": created.id, "views": [[False, "form"]], "target": "current"}
        return {"type": "ir.actions.act_window", "res_model": "business.process",
                "name": self.env._("Imported processes"),
                "views": [[False, "list"], [False, "form"]],
                "domain": [("id", "in", created.ids)], "target": "current"}
