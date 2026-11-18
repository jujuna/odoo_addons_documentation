# Part of bpmn_process_management. License LGPL-3.
"""Microsoft Visio (.vsdx) -> BPMN 2.0.
Works with the "BPMN Diagram" template (shape data BpmnTaskType, BpmnEventType ...), "Basic Flowchart",
"Cross-Functional Flowchart" (swimlanes) and plain drawings. The legacy binary ``.vsd`` is not supported."""
import io
import math
import zlib
import posixpath
import re
import zipfile

from .bpmn_builder import (
    Box, Diagram, Edge, Group, Lane, Node, Pool, build_bpmn, normalize_box as _normalize_box, on_border,
)
from .bpmn_common import (
    ACTIVITY_TAGS, MAX_XML_BYTES, NEUTRAL_FILLS, NEUTRAL_STROKES, BpmnError, finite, norm_color,
    parse_xml,
)

V = "http://schemas.microsoft.com/office/visio/2012/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
SCALE = 96.0
MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_SHAPES = 20000


def vq(tag):
    return "{%s}%s" % (V, tag)


def _num(v, default=None):
    return finite(v, default)


class Package:
    def __init__(self, data):
        if isinstance(data, str):
            data = data.encode("latin-1")
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise BpmnError("Legacy Visio .vsd files are not supported. Open the file in "
                            "Visio and use File > Save As > Visio Drawing (*.vsdx).")
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise BpmnError("This is not a valid .vsdx file.") from e
        total = sum(i.file_size for i in self.zip.infolist())
        if total > MAX_UNCOMPRESSED:
            raise BpmnError("The Visio file is too large.")
        self.names = set(self.zip.namelist())

    def xml(self, path):
        if path not in self.names:
            return None
        if self.zip.getinfo(path).file_size > MAX_XML_BYTES:
            raise BpmnError("The Visio file is too large.")
        try:
            return parse_xml(self.zip.read(path))
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError) as e:
            raise BpmnError("The Visio file is damaged (%s)." % path) from e

    def rels(self, part):
        folder, name = posixpath.split(part)
        rel_path = posixpath.join(folder, "_rels", name + ".rels")
        root = self.xml(rel_path)
        out = {}
        if root is None:
            return out
        for rel in root.findall("{%s}Relationship" % PR):
            target = rel.get("Target", "")
            if target.startswith("/"):
                full = target.lstrip("/")
            else:
                full = posixpath.normpath(posixpath.join(folder, target))
            out[rel.get("Id")] = full
        return out


class Sheet:
    """A page shape with lazy lookup of inherited master values."""

    def __init__(self, el, master_shape=None, parent=None):
        self.el = el
        self.master = master_shape      # Sheet of the master shape or None
        self.parent = parent            # Sheet of the group containing it
        self.id = el.get("ID")
        self.children = []
        self._cells = {c.get("N"): c for c in el.findall(vq("Cell"))}

    def cell(self, name, default=None):
        c = self._cells.get(name)
        if c is not None and c.get("V") is not None:
            return c.get("V")
        if self.master is not None:
            return self.master.cell(name, default)
        return default

    def num(self, name, default=0.0):
        return _num(self.cell(name), default)

    def section_rows(self, section):
        out = {}
        if self.master is not None:
            out.update(self.master.section_rows(section))
        for sec in self.el.findall(vq("Section")):
            if sec.get("N") != section:
                continue
            for row in sec.findall(vq("Row")):
                key = row.get("N") or row.get("IX")
                vals = dict(out.get(key, {}))
                for c in row.findall(vq("Cell")):
                    vals[c.get("N")] = c.get("V")
                out[key] = vals
        return out

    def prop(self, name):
        """Shape data value (case insensitive row name)."""
        for key, vals in self.section_rows("Property").items():
            if key and key.lower() == name.lower():
                return (vals.get("Value") or "").strip()
        return ""

    def user(self, name):
        for key, vals in self.section_rows("User").items():
            if key and key.lower() == name.lower():
                return (vals.get("Value") or "").strip()
        return ""

    def text(self, deep=True):
        t = self.el.find(vq("Text"))
        if t is None and self.master is not None:
            t = self.master.el.find(vq("Text"))
        if t is None:
            if deep and self.el.get("Type") == "Group":
                parts = [ch.text(deep=False) for ch in self.children]
                return "\n".join(p for p in parts if p)
            return ""
        txt = "".join(t.itertext())
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in txt.replace(" ", "\n").splitlines()]
        return "\n".join(ln for ln in lines if ln)

    def name_u(self):
        n = self.el.get("NameU") or (self.master.el.get("NameU") if self.master is not None else "") or ""
        return re.sub(r"\.\d+$", "", n).strip()

    def geometry_rows(self):
        rows = []
        els = self.el.findall(vq("Section"))
        geos = [s for s in els if s.get("N") == "Geometry"]
        if not geos and self.master is not None:
            return self.master.geometry_rows()
        for g in geos:
            for row in g.findall(vq("Row")):
                vals = {c.get("N"): c.get("V") for c in row.findall(vq("Cell"))}
                rows.append((row.get("T"), vals))
        return rows

    def is_1d(self):
        return self.cell("BeginX") is not None and self.cell("EndX") is not None


def _geometry_kind(sheet):
    rows = sheet.geometry_rows()
    types = [t for t, _ in rows]
    if "Ellipse" in types:
        return "ellipse"
    arcs = sum(1 for t in types if t in ("EllipticalArcTo", "ArcTo", "RelEllipticalArcTo"))
    lines = [(t, v) for t, v in rows if t in ("LineTo", "RelLineTo", "MoveTo", "RelMoveTo")]
    if arcs >= 2 and len([1 for t, _ in lines if "LineTo" in t]) == 0:
        return "ellipse"
    pts = []
    for t, v in lines:
        x, y = _num(v.get("X")), _num(v.get("Y"))
        if x is None or y is None:
            continue
        if not t.startswith("Rel"):
            w, h = sheet.num("Width", 1) or 1, sheet.num("Height", 1) or 1
            x, y = x / w, y / h
        pts.append((round(x, 2), round(y, 2)))
    mids = {(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)}
    if pts and set(pts) <= mids and len(set(pts)) == 4:
        return "rhombus"
    return "rect"


TASK_TYPES = {
    "service": "serviceTask", "receive": "receiveTask", "instantiating receive": "receiveTask",
    "send": "sendTask", "manual": "manualTask", "business rule": "businessRuleTask",
    "user": "userTask", "script": "scriptTask",
}
GATEWAY_TYPES = {
    "exclusive": "exclusiveGateway", "inclusive": "inclusiveGateway",
    "parallel": "parallelGateway", "complex": "complexGateway", "event": "eventBasedGateway",
}
TRIGGERS = ["parallel multiple", "multiple", "message", "timer", "error", "escalation",
            "cancel", "compensation", "conditional", "link", "signal", "terminate"]


def _tokens(name):
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name or "")
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    return {t for t in re.split(r"[^A-Za-z0-9]+", name.lower()) if t}


def _trigger(sheet):
    val = (sheet.prop("BpmnTriggerOrResult") or sheet.prop("BpmnTrigger") or
           sheet.prop("BpmnResult")).lower()
    for t in TRIGGERS:
        if t in val:
            return None if "multiple" in t else t
    name = sheet.name_u().lower()
    for t in TRIGGERS:
        if t in name and "multiple" not in t:
            return t
    return None


def classify(sheet):
    """Return (category, kind, extras). category in pool|lane|ignore|edge|node."""
    name = sheet.name_u().lower()
    cats = sheet.user("msvShapeCategories").lower()
    struct = sheet.user("msvStructureType").lower()
    text = sheet.text()
    if sheet.el.get("Type") == "Guide":
        return "ignore", None, {}
    if sheet.is_1d():
        kind = "auto"
        if "message" in name:
            kind = "message"
        elif "association" in name:
            kind = "association"
        return "edge", kind, {}
    if "cff container" in name or "cff container" in cats:
        return "pool", None, {}
    if any(k in name for k in ("phase", "separator", "title", "functional band")) or \
            any(k in cats for k in ("phase", "separator")):
        return "ignore", None, {}
    if "swimlane" in name or "lane" in name or "pool" in name or "swimlane" in cats \
            or struct == "container" and ("lane" in cats or "pool" in cats):
        return "lane", None, {}
    if (name in ("group",) or "bpmn group" in name) and sheet.master is not None:
        return "group", None, {}
    ev_type = sheet.prop("BpmnEventType").lower()
    if "start event" in name or ev_type.startswith("start") or name in ("start",):
        return "node", "startEvent", {"event_def": _trigger(sheet),
                                      "cancel_activity": "non-interrupting" not in ev_type}
    if "end event" in name or ev_type.startswith("end") or name in ("end",):
        return "node", "endEvent", {"event_def": _trigger(sheet)}
    if "intermediate" in name or ev_type.startswith("intermediate") or "boundary" in name:
        kind = "intermediateThrowEvent" if "throw" in ev_type or "throw" in name \
            else "intermediateCatchEvent"
        return "node", kind, {"event_def": _trigger(sheet),
                              "cancel_activity": "non-interrupting" not in ev_type,
                              "maybe_boundary": True}
    if "gateway" in name or sheet.prop("BpmnGatewayType"):
        gw = sheet.prop("BpmnGatewayType").lower()
        for k, v in GATEWAY_TYPES.items():
            if gw.startswith(k):
                if k == "exclusive" and "event" in sheet.prop("BpmnExclusiveType").lower():
                    return "node", "eventBasedGateway", {}
                return "node", v, {}
        for k, v in GATEWAY_TYPES.items():
            if k in name:
                return "node", v, {}
        return "node", "exclusiveGateway", {}
    if "decision" in name or "diamond" in name:
        return "node", "exclusiveGateway", {}
    if "text annotation" in name or name in ("annotation", "text", "text block") or \
            "annotation" in name:
        return ("node", "textAnnotation", {}) if text else ("ignore", None, {})
    if "data store" in name or "database" in name or "stored data" in name:
        return "node", "dataStoreReference", {}
    if "data object" in name or "document" in name or name in ("data", "message"):
        return "node", "dataObjectReference", {"guessed": "data object" not in name}
    act_type = sheet.prop("BpmnActivityType").lower()
    collapsed = sheet.prop("BpmnIsCollapsed").lower()
    if "call activity" in name or "call activity" in act_type:
        return "node", "callActivity", {}
    if "transaction" in name:
        return "node", "transaction", {"expanded": "expanded" in name}
    if "sub-process" in name or "subprocess" in name or "sub-process" in act_type \
            or name == "predefined process":
        expanded = "expanded" in name or collapsed in ("0", "false", "no")
        return "node", "subProcess", {"expanded": expanded}
    if "task" in name or name in ("process",) or sheet.prop("BpmnTaskType"):
        tt = sheet.prop("BpmnTaskType").lower()
        return "node", TASK_TYPES.get(tt, "task"), {}
    if name in ("start/end", "terminator", "ellipse", "circle"):
        return "node", "event", {}
    toks = _tokens(sheet.name_u())
    if toks & {"start", "initial"}:
        return "node", "startEvent", {}
    if toks & {"end", "final", "terminate", "terminator"}:
        return "node", "endEvent", {}
    if toks & {"fork", "join", "bar", "synchronization"}:
        return "node", "parallelGateway", {"guessed": True}
    if toks & {"decision", "merge", "choice"}:
        return "node", "exclusiveGateway", {}
    if toks & {"state", "activity", "action", "step"} and text:
        return "node", "task", {}
    if "text" in toks:
        return ("node", "textAnnotation", {}) if text else ("ignore", None, {})
    geo = _geometry_kind(sheet)
    if geo == "ellipse":
        return "node", "event", {"guessed": bool(name) and not name.startswith("shape")}
    if geo == "rhombus":
        return "node", "exclusiveGateway", {}
    if text:
        known = name in ("", "rectangle", "shape", "square", "rounded rectangle", "box")
        return "node", "task", {"guessed": not known, "maybe_isolated": True}
    return "ignore", None, {}


class PageConverter:

    def __init__(self, pkg, page_el, page_part, masters):
        self.pkg = pkg
        self.page_el = page_el
        self.part = page_part
        self.masters = masters
        sheet = page_el.find(vq("PageSheet"))
        ph = None
        if sheet is not None:
            for c in sheet.findall(vq("Cell")):
                if c.get("N") == "PageHeight":
                    ph = _num(c.get("V"))
        self.page_height = ph or 11.0
        self.sheets = {}

    def _load(self, shapes_el, parent, master_ctx):
        if shapes_el is None:
            return
        for el in shapes_el.findall(vq("Shape")):
            if len(self.sheets) > MAX_SHAPES:
                raise BpmnError("The Visio page has too many shapes.")
            mid = el.get("Master")
            ms = None
            ctx = master_ctx
            if mid and mid in self.masters:
                ctx = self.masters[mid]
                ms = ctx.get("__top__")
            elif el.get("MasterShape") and master_ctx:
                ms = master_ctx.get(el.get("MasterShape"))
            sh = Sheet(el, ms, parent)
            self.sheets[sh.id] = sh
            if parent is not None:
                parent.children.append(sh)
            self._load(el.find(vq("Shapes")), sh, ctx)

    def _origin(self, sh):
        """Absolute (left, bottom) of the local coordinate system of ``sh``'s children."""
        if sh is None:
            return 0.0, 0.0
        left, bottom = self._abs_lb(sh)
        return left, bottom

    def _abs_lb(self, sh):
        ox, oy = self._origin(sh.parent)
        left = ox + sh.num("PinX") - sh.num("LocPinX", sh.num("Width") / 2)
        bottom = oy + sh.num("PinY") - sh.num("LocPinY", sh.num("Height") / 2)
        return left, bottom

    def box(self, sh):
        left, bottom = self._abs_lb(sh)
        w, h = abs(sh.num("Width")), abs(sh.num("Height"))
        top = bottom + h
        return Box(left * SCALE, (self.page_height - top) * SCALE, w * SCALE, h * SCALE)

    def point(self, sh, xname, yname):
        ox, oy = self._origin(sh.parent)
        x, y = sh.num(xname, None), sh.num(yname, None)
        if x is None or y is None:
            return None
        return ((ox + x) * SCALE, (self.page_height - (oy + y)) * SCALE)

    def convert(self, name):
        root = self.pkg.xml(self.part)
        if root is None:
            return Diagram(name)
        self._load(root.find(vq("Shapes")), None, None)
        d = Diagram(name)
        node_of = {}   # any sheet id -> node / lane / pool src id
        edges = []
        lane_sheets, pool_sheets = [], []

        def walk(sheets):
            for sh in sheets:
                cat, kind, extras = classify(sh)
                is_plain_group = sh.el.get("Type") == "Group" and sh.master is None and \
                    cat in ("ignore", "node") and not sh.text(deep=False)
                if is_plain_group:
                    walk(sh.children)
                    continue
                if cat == "edge":
                    edges.append((sh, kind))
                elif cat == "pool":
                    pool_sheets.append(sh)
                    walk(sh.children)
                elif cat == "lane":
                    lane_sheets.append(sh)
                    walk(sh.children)
                elif cat == "group":
                    d.groups.append(Group(sh.id, sh.text(), self.box(sh)))
                    _apply_colors(d.groups[-1], sh)
                elif cat == "node":
                    raw_box = self.box(sh)
                    box = _normalize_box(kind, raw_box)
                    n = Node(sh.id, kind, sh.text(), box, hit_box=raw_box, loop=_loop(sh),
                             compensation=_yes(sh.prop("BpmnIsForCompensation")),
                             event_def=extras.get("event_def"),
                             cancel_activity=extras.get("cancel_activity", True),
                             expanded=extras.get("expanded", False),
                             guessed=extras.get("guessed", False),
                             documentation=_documentation(sh))
                    _apply_colors(n, sh)
                    n._maybe_boundary = extras.get("maybe_boundary")
                    n._maybe_isolated = extras.get("maybe_isolated")
                    d.add_node(n)
                    self._map_children(sh, sh.id, node_of)
                    node_of[sh.id] = sh.id

        walk([s for s in self.sheets.values() if s.parent is None])

        for sh in pool_sheets:
            d.pools[sh.id] = Pool(sh.id, _container_label(sh), self.box(sh))
            self._map_children(sh, sh.id, node_of, only_unmapped=True)
            node_of.setdefault(sh.id, sh.id)
        # lane candidates: those containing other candidates are pools
        lane_boxes = {sh.id: self.box(sh) for sh in lane_sheets}
        for sh in lane_sheets:
            b = lane_boxes[sh.id]
            inner = [o for o in lane_sheets if o is not sh and _inside(lane_boxes[o.id], b)]
            if inner:
                d.pools[sh.id] = Pool(sh.id, _container_label(sh), b)
        for sh in lane_sheets:
            if sh.id in d.pools:
                continue
            b = lane_boxes[sh.id]
            owners = [p for p in d.pools.values() if _inside(b, p.box)]
            pool = min(owners, key=lambda p: p.box.area).src_id if owners else None
            d.lanes[sh.id] = Lane(sh.id, _container_label(sh), b, pool=pool)

        subs = [n for n in d.nodes.values()
                if n.kind in ("subProcess", "transaction", "adHocSubProcess") and n.expanded]
        acts = [n for n in d.nodes.values() if n.kind in ACTIVITY_TAGS]
        for n in d.nodes.values():
            if getattr(n, "_maybe_boundary", False):
                hosts = [a for a in acts if on_border(n.box, a.box)]
                if hosts:
                    n.kind = "boundaryEvent"
                    n.attached_to = min(hosts, key=lambda a: a.box.area).src_id
                    continue
            cands = [s for s in subs if s is not n and _inside(n.box, s.box)]
            if cands:
                n.scope = min(cands, key=lambda s: s.box.area).src_id

        connected = set()
        connects = {}
        cs = root.find(vq("Connects"))
        if cs is not None:
            for c in cs.findall(vq("Connect")):
                connects.setdefault(c.get("FromSheet"), {})[c.get("FromCell")] = c.get("ToSheet")
        for sh, kind in edges:
            glue = connects.get(sh.id, {})
            src = node_of.get(glue.get("BeginX")) if glue.get("BeginX") else None
            tgt = node_of.get(glue.get("EndX")) if glue.get("EndX") else None
            path = self._connector_path(sh)
            if len(path) >= 2:
                start, end, pts = path[0], path[-1], path[1:-1]
            else:
                start = self.point(sh, "BeginX", "BeginY")
                end = self.point(sh, "EndX", "EndY")
                pts = []
            dashed = sh.cell("LinePattern") not in (None, "0", "1")
            dotted = sh.cell("LinePattern") in ("3", "10", "16")
            e = Edge(sh.id, src, tgt, sh.text(), kind=kind, points=pts, start_point=start,
                     end_point=end, dashed=dashed, dotted=dotted, orthogonal=True)
            e.stroke = norm_color(sh.cell("LineColor"), NEUTRAL_STROKES)
            d.edges.append(e)
            connected.update(x for x in (src, tgt) if x)
        for n in d.nodes.values():
            if getattr(n, "_maybe_isolated", False) and n.src_id not in connected:
                n.guessed = True
        return d

    def _map_children(self, sh, target, node_of, only_unmapped=False):
        for ch in sh.children:
            if not only_unmapped or ch.id not in node_of:
                node_of[ch.id] = target
            self._map_children(ch, target, node_of, only_unmapped)

    def local_to_page(self, sh, x, y):
        """Shape-local inches -> absolute page px (handles rotation / flips)."""
        ox, oy = self._origin(sh.parent)
        a = sh.num("Angle", 0.0)
        dx = x - sh.num("LocPinX", sh.num("Width") / 2)
        dy = y - sh.num("LocPinY", sh.num("Height") / 2)
        if sh.cell("FlipX") == "1":
            dx = -dx
        if sh.cell("FlipY") == "1":
            dy = -dy
        gx = sh.num("PinX") + dx * math.cos(a) - dy * math.sin(a)
        gy = sh.num("PinY") + dx * math.sin(a) + dy * math.cos(a)
        return ((ox + gx) * SCALE, (self.page_height - (oy + gy)) * SCALE)

    def _connector_path(self, sh):
        """Full polyline of a 1-D shape from its geometry, in page px."""
        pts = []
        w, h = sh.num("Width", 0.0), sh.num("Height", 0.0)
        for t, v in sh.geometry_rows():
            if t not in ("MoveTo", "LineTo", "RelMoveTo", "RelLineTo"):
                continue
            x, y = _num(v.get("X")), _num(v.get("Y"))
            if x is None or y is None:
                return []
            if t.startswith("Rel"):
                x, y = x * w, y * h
            pts.append(self.local_to_page(sh, x, y))
        return pts


def _yes(value):
    return (value or "").strip().lower() in ("1", "true", "yes", "-1")


def _loop(sh):
    """Loop / multi-instance marker from BPMN shape data (BpmnLoopType & co)."""
    for key, vals in sh.section_rows("Property").items():
        if not key or not key.lower().startswith("bpmnloop"):
            continue
        v = (vals.get("Value") or "").lower()
        if "sequential" in v:
            return "sequential"
        if "parallel" in v or "multi" in v:
            return "parallel"
        if "standard" in v or v in ("loop", "while"):
            return "standard"
    return None


def _documentation(sh):
    skip = {"bpmntasktype", "bpmneventtype", "bpmntriggerorresult", "bpmngatewaytype",
            "bpmnexclusivetype", "bpmnactivitytype", "bpmniscollapsed", "bpmnname",
            "bpmnboundaryeventtype", "bpmnloopcharacteristics", "bpmnbooleanattribute"}
    out = []
    for key, vals in sh.section_rows("Property").items():
        v = (vals.get("Value") or "").strip()
        if not key or not v or key.lower() in skip or key.lower().startswith("bpmn"):
            continue
        label = vals.get("Label") or key
        out.append("%s: %s" % (label, v))
    return "\n".join(out)


def _container_label(sh):
    text = sh.text()
    if text:
        return text
    for ch in sh.children:
        t = ch.text()
        if t:
            return t
    return ""


def _inside(inner, outer, tol=2.0):
    return (inner.x >= outer.x - tol and inner.y >= outer.y - tol
            and inner.right <= outer.right + tol and inner.bottom <= outer.bottom + tol
            and inner.area < outer.area)


def _load_masters(pkg):
    masters = {}
    part = "visio/masters/masters.xml"
    root = pkg.xml(part)
    if root is None:
        return masters
    rels = pkg.rels(part)
    for m in root.findall(vq("Master")):
        rel = m.find(vq("Rel"))
        target = rels.get(rel.get("{%s}id" % R)) if rel is not None else None
        content = pkg.xml(target) if target else None
        ctx = {}
        if content is not None:
            shapes = content.find(vq("Shapes"))

            def load(shapes_el, parent_sheet):
                if shapes_el is None:
                    return
                for el in shapes_el.findall(vq("Shape")):
                    sh = Sheet(el, None, parent_sheet)
                    ctx[sh.id] = sh
                    if "__top__" not in ctx:
                        ctx["__top__"] = sh
                    load(el.find(vq("Shapes")), sh)
            load(shapes, None)
            top = ctx.get("__top__")
            if top is not None and not top.el.get("NameU"):
                top.el.set("NameU", m.get("NameU") or m.get("Name") or "")
            elif top is not None:
                top.el.set("NameU", m.get("NameU") or top.el.get("NameU"))
        masters[m.get("ID")] = ctx
    return masters


def convert_visio(data, pages="all"):
    pkg = Package(data)
    part = "visio/pages/pages.xml"
    root = pkg.xml(part)
    if root is None:
        raise BpmnError("This is not a valid .vsdx file (no pages found).")
    rels = pkg.rels(part)
    masters = _load_masters(pkg)
    out = []
    page_els = [p for p in root.findall(vq("Page")) if p.get("Background") != "1"]
    for p in page_els:
        rel = p.find(vq("Rel"))
        target = rels.get(rel.get("{%s}id" % R)) if rel is not None else None
        if not target:
            continue
        name = p.get("Name") or p.get("NameU") or ""
        d = PageConverter(pkg, p, target, masters).convert(name)
        if d.is_empty():
            continue
        xml, warnings = build_bpmn(d, source="visio")
        out.append({"name": name, "xml": xml, "warnings": warnings})
        if pages == "first":
            break  # the first page with a drawing
    if not out:
        raise BpmnError("No shapes were found in the Visio file.")
    return out


def _apply_colors(obj, sh):
    """Visio: FillForegnd / LineColor hold '#rrggbb' once resolved (themes give formulas: skipped)."""
    obj.fill = norm_color(sh.cell("FillForegnd"), NEUTRAL_FILLS)
    obj.stroke = norm_color(sh.cell("LineColor"), NEUTRAL_STROKES)
