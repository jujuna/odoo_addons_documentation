# Part of bpmn_process_management. License LGPL-3.
"""draw.io / diagrams.net (mxGraph) -> BPMN 2.0.
Inputs: ``.drawio``/``.xml`` (plain or compressed), bare ``<mxGraphModel>``, ``.svg``/``.png`` with an embedded copy.
BPMN shapes map 1:1; generic ones by convention (rectangle task, rhombus exclusive gateway, ellipse event), flagged."""
import base64
import html
import re
import struct
import urllib.parse

from lxml import etree

from .bpmn_builder import (
    Box, Diagram, Edge, Group, Lane, Node, Pool, build_bpmn, normalize_box as _normalize_box,
    on_border as _on_border,
)
from .bpmn_common import (
    ACTIVITY_TAGS, MAX_XML_BYTES, NEUTRAL_FILLS, NEUTRAL_STROKES, BpmnError, finite, is_safe_url, norm_color,
    parse_xml, safe_inflate, safe_parser,
)

TASK_MARKERS = {
    "user": "userTask", "manual": "manualTask", "send": "sendTask",
    "receive": "receiveTask", "service": "serviceTask", "script": "scriptTask",
    "businessrule": "businessRuleTask", "business_rule": "businessRuleTask",
}
OLD_TASK_SHAPES = {
    "mxgraph.bpmn.user_task": "userTask", "mxgraph.bpmn.manual_task": "manualTask",
    "mxgraph.bpmn.send_task": "sendTask", "mxgraph.bpmn.receive_task": "receiveTask",
    "mxgraph.bpmn.service_task": "serviceTask", "mxgraph.bpmn.script_task": "scriptTask",
    "mxgraph.bpmn.business_rule_task": "businessRuleTask",
}
EVENT_SYMBOLS = {
    "message": "message", "timer": "timer", "escalation": "escalation",
    "conditional": "conditional", "link": "link", "signal": "signal", "error": "error",
    "compensation": "compensation", "cancel": "cancel", "terminate": "terminate",
    "terminate2": "terminate",
}
GATEWAY_TYPES = {
    "exclusive": "exclusiveGateway", "exclusivegw": "exclusiveGateway",
    "parallel": "parallelGateway", "parallelgw": "parallelGateway",
    "inclusive": "inclusiveGateway", "inclusivegw": "inclusiveGateway",
    "complex": "complexGateway", "complexgw": "complexGateway",
    "eventbased": "eventBasedGateway", "eventgw": "eventBasedGateway",
}
DATA_OBJECT_SHAPES = {"mxgraph.bpmn.data", "mxgraph.bpmn.data2", "note", "document",
                      "mxgraph.flowchart.document", "mxgraph.flowchart.multi-document",
                      "mxgraph.flowchart.data", "mxgraph.flowchart.paper_tape"}
DATA_STORE_SHAPES = {"datastore", "cylinder", "cylinder3", "mxgraph.flowchart.database",
                     "mxgraph.flowchart.stored_data", "mxgraph.flowchart.direct_data"}
EVENT_SHAPES = {"ellipse", "doubleellipse", "mxgraph.flowchart.start_1",
                "mxgraph.flowchart.start_2", "mxgraph.flowchart.terminator",
                "mxgraph.flowchart.on-page_reference", "mxgraph.flowchart.or",
                "mxgraph.flowchart.summing_function"}
GATEWAY_SHAPES = {"rhombus", "mxgraph.flowchart.decision", "mxgraph.bpmn.gateway",
                  "mxgraph.bpmn.gateway2"}
PLAIN_TASK_SHAPES = {"", "rect", "rectangle", "ext", "label", "process",
                     "mxgraph.flowchart.process", "mxgraph.bpmn.task", "mxgraph.bpmn.task2",
                     "mxgraph.flowchart.predefined_process"}

EXACT_TYPES = {
    "task", "userTask", "manualTask", "sendTask", "receiveTask", "serviceTask", "scriptTask",
    "businessRuleTask", "subProcess", "transaction", "callActivity", "startEvent", "endEvent",
    "intermediateThrowEvent", "intermediateCatchEvent", "boundaryEvent", "exclusiveGateway",
    "inclusiveGateway", "parallelGateway", "complexGateway", "eventBasedGateway",
    "dataObjectReference", "dataStoreReference", "textAnnotation",
}
OLD_EVENT_RE = re.compile(r"^mxgraph\.bpmn\.([a-z0-9_]+?)_(start|end|intermediate|boundary)(?:_\w+)?$")

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*/?\s*(br|div|p|li)\b[^>]*>", re.I)


def html_to_text(value):
    if not value:
        return ""
    txt = _BR_RE.sub("\n", value)
    txt = _TAG_RE.sub("", txt)
    txt = html.unescape(txt).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in txt.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def parse_style(style):
    """'rounded=1;ellipse;shape=x' -> ({'rounded': '1', 'shape': 'x'}, {'ellipse'})"""
    kv, names = {}, set()
    for part in (style or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k.strip()] = v.strip()
        else:
            names.add(part.lower())
    return kv, names


def _decode_diagram_text(text):
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("<"):
        return text
    try:
        raw = base64.b64decode(text)
    except Exception:  # noqa: BLE001
        raw = None
    if raw is not None:
        for wbits in (-15, 15):
            try:
                data = safe_inflate(raw, wbits).decode("utf-8")
                return urllib.parse.unquote(data)
            except Exception:  # noqa: BLE001, S112
                continue
    decoded = urllib.parse.unquote(text)
    if decoded.startswith("<"):
        return decoded
    raise BpmnError("Could not decode a compressed draw.io page.")


def _png_mxfile(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"tEXt":
            key, _, val = chunk.partition(b"\x00")
            if key in (b"mxfile", b"mxGraphModel"):
                return urllib.parse.unquote(val.decode("latin-1"))
        elif ctype == b"zTXt":
            key, _, rest = chunk.partition(b"\x00")
            if key in (b"mxfile", b"mxGraphModel"):
                return urllib.parse.unquote(safe_inflate(rest[1:], 15).decode("latin-1"))
        elif ctype == b"iTXt":
            key, _, rest = chunk.partition(b"\x00")
            if key in (b"mxfile", b"mxGraphModel"):
                if len(rest) < 2:
                    return None
                comp_flag = rest[0]
                rest = rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _tkey, _, text = rest.partition(b"\x00")
                if comp_flag:
                    text = safe_inflate(text, 15)
                return urllib.parse.unquote(text.decode("utf-8"))
        elif ctype == b"IEND":
            break
    return None


def load_pages(data):
    """Return a list of (page_name, mxGraphModel element)."""
    return list(iter_pages(data))


def iter_pages(data):
    """Yield (page_name, mxGraphModel element), decoding pages lazily within one size budget (zip-bomb safe)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    png = _png_mxfile(data)
    if png is not None:
        data = png.encode("utf-8")
    elif data.lstrip()[:1] != b"<":
        raise BpmnError("This is not a draw.io file.")
    root = parse_xml(data)
    tag = etree.QName(root).localname
    if tag == "svg":
        content = root.get("content")
        if not content:
            raise BpmnError("This SVG does not contain an embedded draw.io diagram. "
                            "In draw.io use File > Export as > SVG and tick "
                            "'Include a copy of my diagram'.")
        content = html.unescape(content)
        if not content.lstrip().startswith("<"):
            content = _decode_diagram_text(content)
        root = parse_xml(content.encode("utf-8"))
        tag = etree.QName(root).localname
    if tag == "mxGraphModel":
        yield ("", root)
        return
    if tag != "mxfile":
        raise BpmnError("This is not a draw.io file (expected <mxfile> or <mxGraphModel>).")
    budget = MAX_XML_BYTES
    found = False
    for i, diag in enumerate(root.findall("diagram"), start=1):
        name = diag.get("name") or "Page-%d" % i
        model = diag.find("mxGraphModel")
        if model is None:
            text = _decode_diagram_text(diag.text)
            if not text:
                continue
            raw = text.encode("utf-8")
            budget -= len(raw)
            if budget < 0:
                raise BpmnError("The file is too large.")
            try:
                model = etree.fromstring(raw, parser=safe_parser())
            except etree.XMLSyntaxError as e:
                raise BpmnError("A draw.io page is not valid XML: %s" % e) from e
        found = True
        yield (name, model)
    if not found:
        raise BpmnError("The draw.io file has no pages.")


class Cell:
    __slots__ = ("id", "parent", "value", "style", "names", "vertex", "edge", "source",
                 "target", "geo", "attrs", "children", "abs")

    def __init__(self):
        self.children = []
        self.abs = None


def _float(v, default=0.0):
    return finite(v, default)


def _read_cells(model):
    root = model.find("root")
    if root is None:
        return {}
    cells = {}
    for el in root:
        if not isinstance(el.tag, str):
            continue
        attrs = {}
        if el.tag in ("object", "UserObject"):
            mx = el.find("mxCell")
            attrs = {k: v for k, v in el.attrib.items() if k not in ("id",)}
            value = el.get("label", "")
            if mx is None:
                mx = etree.Element("mxCell")
        elif el.tag == "mxCell":
            mx = el
            value = el.get("value", "")
        else:
            continue
        c = Cell()
        c.id = el.get("id")
        if not c.id:
            continue
        c.parent = mx.get("parent")
        c.value = value
        c.style = mx.get("style", "")
        c.names = set()
        c.vertex = mx.get("vertex") == "1"
        c.edge = mx.get("edge") == "1"
        c.source = mx.get("source")
        c.target = mx.get("target")
        c.geo = mx.find("mxGeometry")
        c.attrs = attrs
        cells[c.id] = c
    # break parent cycles (a crafted file could otherwise loop forever)
    for c in cells.values():
        seen, cur = {c.id}, cells.get(c.parent)
        while cur is not None:
            if cur.id in seen:
                c.parent = "1" if "1" in cells and c.id != "1" else None
                break
            seen.add(cur.id)
            cur = cells.get(cur.parent)
    for c in cells.values():
        if c.parent in cells:
            cells[c.parent].children.append(c)
    return cells


def _is_layer(cells, c):
    return c.parent is None or c.parent not in cells or cells[c.parent].parent is None


def _abs_pos(cells, c, depth=0):
    if c.abs is not None:
        return c.abs
    g = c.geo
    x = _float(g.get("x")) if g is not None else 0.0
    y = _float(g.get("y")) if g is not None else 0.0
    if g is not None and g.get("relative") == "1" and c.parent in cells and cells[c.parent].vertex:
        pw, ph = _size(cells[c.parent])
        x, y = x * pw, y * ph
        off = g.find("mxPoint[@as='offset']")
        if off is not None:
            x += _float(off.get("x"))
            y += _float(off.get("y"))
    parent = cells.get(c.parent)
    if parent is not None and not _is_layer(cells, parent) and parent.vertex and depth < 100:
        px, py = _abs_pos(cells, parent, depth + 1)
        x, y = x + px, y + py
    c.abs = (x, y)
    return c.abs


def _size(c):
    g = c.geo
    if g is None:
        return 0.0, 0.0
    return _float(g.get("width")), _float(g.get("height"))


def _box(cells, c):
    x, y = _abs_pos(cells, c)
    w, h = _size(c)
    return Box(x, y, w or 1, h or 1)


def _points(cells, c):
    g = c.geo
    if g is None:
        return [], None, None
    ox, oy = 0.0, 0.0
    parent = cells.get(c.parent)
    if parent is not None and not _is_layer(cells, parent) and parent.vertex:
        ox, oy = _abs_pos(cells, parent)
    pts = []
    arr = g.find("Array[@as='points']")
    if arr is not None:
        for p in arr.findall("mxPoint"):
            pts.append((_float(p.get("x")) + ox, _float(p.get("y")) + oy))
    sp = g.find("mxPoint[@as='sourcePoint']")
    tp = g.find("mxPoint[@as='targetPoint']")
    sp = (_float(sp.get("x")) + ox, _float(sp.get("y")) + oy) if sp is not None else None
    tp = (_float(tp.get("x")) + ox, _float(tp.get("y")) + oy) if tp is not None else None
    return pts, sp, tp


def _documentation(c):
    parts = []
    for key in ("tooltip", "documentation", "description"):
        if c.attrs.get(key):
            parts.append(html_to_text(c.attrs[key]))
    skip = {"label", "tooltip", "documentation", "description", "link", "placeholders",
            "id", "tags", "bpmn_type", "odoo_links", "odoo_responsible"}
    extra = ["%s: %s" % (k, v) for k, v in c.attrs.items() if k not in skip and v]
    if extra:
        parts.append("\n".join(extra))
    return "\n\n".join(p for p in parts if p)


def _links(c):
    link = c.attrs.get("link")
    if link and is_safe_url(link):
        return [{"url": link, "label": ""}]
    return []


def _is_swimlane(kv, names):
    shape = kv.get("shape", "").lower()
    return "swimlane" in names or shape in ("swimlane", "mxgraph.bpmn.swimlane", "pool",
                                            "mxgraph.bpmn.pool", "mxgraph.bpmn.lane")


def _classify_vertex(c, kv, names):
    """Return (kind, extras) for a flow shape, or (None, None) when not a node."""
    shape = kv.get("shape", "").lower()
    first = next(iter(names)) if len(names) == 1 else ""
    outline = kv.get("outline", "").lower()
    symbol = kv.get("symbol", "").lower()
    if shape in ("mxgraph.bpmn.event",) or (shape == "mxgraph.bpmn.shape" and outline
                                              and "rhombus" not in kv.get("perimeter", "").lower()
                                              and kv.get("background") != "gateway"):
        return _event_from_outline(outline, symbol)
    if shape in ("mxgraph.bpmn.gateway2", "mxgraph.bpmn.gateway") or (
            shape == "mxgraph.bpmn.shape" and ("rhombus" in kv.get("perimeter", "").lower()
                                               or kv.get("background") == "gateway")):
        gw = kv.get("gwType", "").lower()
        if gw in GATEWAY_TYPES:
            return GATEWAY_TYPES[gw], {}
        if symbol in GATEWAY_TYPES:
            return GATEWAY_TYPES[symbol], {}
        if outline == "end" and symbol == "general":
            return "inclusiveGateway", {}
        if symbol in EVENT_SYMBOLS or symbol in ("multiple", "parallelmultiple") or \
                outline in ("catching", "standard", "eventint", "eventnonint"):
            if symbol not in ("none", "general", ""):
                return "eventBasedGateway", {}
        return "exclusiveGateway", {}
    if shape in OLD_TASK_SHAPES:
        return OLD_TASK_SHAPES[shape], {}
    m = OLD_EVENT_RE.match(shape)
    if m:
        ev_def = EVENT_SYMBOLS.get(m.group(1).split("_")[0])
        pos = m.group(2)
        kind = {"start": "startEvent", "end": "endEvent"}.get(pos, "intermediateCatchEvent")
        return kind, {"event_def": ev_def}
    if shape == "message":
        return "dataObjectReference", {"guessed": True}
    if shape in ("mxgraph.bpmn.task", "mxgraph.bpmn.task2") or "bpmnShapeType" in kv \
            or "taskMarker" in kv:
        stype = kv.get("bpmnShapeType", "").lower()
        if stype == "call":
            return "callActivity", {}
        if stype == "transaction":
            return "transaction", {}
        if kv.get("isAdHoc") == "1":
            return "adHocSubProcess", {"collapsed": kv.get("isLoopSub") == "1"}
        if stype == "subprocess" or kv.get("isLoopSub") == "1":
            return "subProcess", {"collapsed": kv.get("isLoopSub") == "1"}
        marker = kv.get("taskMarker", "abstract").lower()
        return TASK_MARKERS.get(marker, "task"), {}
    if shape in DATA_OBJECT_SHAPES:
        return "dataObjectReference", {"guessed": shape not in ("mxgraph.bpmn.data", "mxgraph.bpmn.data2")}
    if shape in DATA_STORE_SHAPES or first in DATA_STORE_SHAPES:
        return "dataStoreReference", {"guessed": shape not in ("datastore",)}
    if shape in ("mxgraph.flowchart.annotation_1", "mxgraph.flowchart.annotation_2",
                 "mxgraph.bpmn.annotation") or "text" in names:
        return "textAnnotation", {}
    if shape in GATEWAY_SHAPES or "rhombus" in names:
        return "exclusiveGateway", {}
    if shape in EVENT_SHAPES or names & EVENT_SHAPES:
        if shape == "doubleellipse" or "doubleellipse" in names:
            return "intermediateThrowEvent", {}
        return "event", {}
    if shape in ("image",) or "image" in names:
        return "task", {"guessed": True, "require_label": True}
    if shape in PLAIN_TASK_SHAPES or not shape:
        return "task", {"require_label": True}
    return "task", {"guessed": True, "require_label": True}


def _event_from_outline(outline, symbol):
    ev_def = EVENT_SYMBOLS.get(symbol)
    extras = {"event_def": ev_def}
    if symbol in ("multiple", "parallelmultiple"):
        extras["event_def"] = None
    if outline in ("standard", "eventint", "eventnonint"):
        return "startEvent", extras
    if outline in ("end",):
        return "endEvent", extras
    if outline in ("boundint",):
        return "boundaryEvent", extras
    if outline in ("boundnonint",):
        extras["cancel_activity"] = False
        return "boundaryEvent", extras
    if outline in ("catching", "noninttimer"):
        return "intermediateCatchEvent", extras
    if outline in ("throwing",):
        return "intermediateThrowEvent", extras
    return "event", extras


def page_to_diagram(name, model):
    cells = _read_cells(model)
    d = Diagram(name)
    kinds = {}  # cell id -> 'pool' | 'lane' | 'pass' | 'node' | 'edge_label' | 'ignore'

    for c in cells.values():
        c.names = parse_style(c.style)[1]
    for c in cells.values():
        if not c.vertex or _is_layer(cells, c):
            continue
        kv, names = parse_style(c.style)
        shape = kv.get("shape", "").lower()
        parent = cells.get(c.parent)
        if parent is not None and parent.edge:
            kinds[c.id] = "edge_label"
        elif shape == "table":
            kinds[c.id] = "pool"
        elif shape == "tablerow":
            kinds[c.id] = "lane"
        elif shape == "partialrectangle":
            kinds[c.id] = "pass"
        elif "group" in names:
            kinds[c.id] = "pass"
        elif _is_swimlane(kv, names):
            kinds[c.id] = "swimlane"

    def parent_kind(c):
        p = cells.get(c.parent)
        return kinds.get(p.id) if p is not None else None

    changed = True
    while changed:
        changed = False
        for c in cells.values():
            if kinds.get(c.id) != "swimlane":
                continue
            pk = parent_kind(c)
            has_lane_children = any(kinds.get(ch.id) in ("swimlane", "lane") for ch in c.children)
            if pk == "pool":
                new = "lane"
            elif pk in ("lane",):
                new = "pass"   # phase / nested lane
            elif pk == "swimlane":
                continue
            elif has_lane_children:
                new = "pool"
            else:
                new = "lane"   # orphan lane: grouped later by the builder
            kinds[c.id] = new
            changed = True
    for c in cells.values():
        if kinds.get(c.id) == "swimlane":
            kinds[c.id] = "lane"

    for c in cells.values():
        k = kinds.get(c.id)
        if k == "pool":
            d.pools[c.id] = Pool(c.id, html_to_text(c.value), _box(cells, c),
                                 documentation=_documentation(c))
            _apply_colors(d.pools[c.id], c)
        elif k == "lane":
            pool = cells.get(c.parent)
            pool_id = pool.id if pool is not None and kinds.get(pool.id) == "pool" else None
            d.lanes[c.id] = Lane(c.id, html_to_text(c.value), _box(cells, c), pool=pool_id,
                                 documentation=_documentation(c))
            _apply_colors(d.lanes[c.id], c)

    containers = {"pool", "lane", "pass"}
    connected = set()
    for c in cells.values():
        if c.edge:
            connected.update(x for x in (c.source, c.target) if x)
    edge_labels = {}
    plus_markers = set()
    for c in cells.values():
        if not c.vertex or c.id in kinds and kinds[c.id] in containers:
            continue
        if _is_layer(cells, c):
            continue
        if kinds.get(c.id) == "edge_label":
            edge_labels.setdefault(c.parent, []).append(html_to_text(c.value))
            continue
        kv, names = parse_style(c.style)
        kind, extras = _classify_vertex(c, kv, names)
        if c.attrs.get("bpmn_type") in EXACT_TYPES:
            kind, extras = c.attrs["bpmn_type"], dict(extras, guessed=False)
        label = html_to_text(c.value)
        if kind is None:
            continue
        if kind == "textAnnotation" and not label:
            continue
        if extras.get("require_label") and not label and c.id not in connected \
                and not any(not ch.edge for ch in c.children):
            continue
        if kv.get("shape", "").lower() == "plus" and not label:
            parent = cells.get(c.parent)
            if parent is not None:
                plus_markers.add(parent.id)
            continue
        if extras.get("require_label") and c.id not in connected and not extras.get("guessed"):
            extras["guessed"] = True
        if _is_group_frame(kv, names) and not label_is_flow(c, connected):
            d.groups.append(Group(c.id, label, _box(cells, c)))
            _apply_colors(d.groups[-1], c)
            continue
        raw_box = _box(cells, c)
        box = _normalize_box(kind, raw_box)
        loop = ("standard" if kv.get("isLoopStandard") == "1" else
                "parallel" if kv.get("isLoopMultiParallel") == "1" else
                "sequential" if kv.get("isLoopMultiSeq") == "1" else None)
        node = Node(c.id, kind, label, box, hit_box=raw_box, loop=loop,
                    compensation=kv.get("isLoopComp") == "1", documentation=_documentation(c), links=_links(c),
                    event_def=extras.get("event_def"),
                    cancel_activity=extras.get("cancel_activity", True),
                    guessed=extras.get("guessed", False))
        _apply_colors(node, c)
        parent = cells.get(c.parent)
        hops = 0
        while parent is not None and kinds.get(parent.id) == "pass" and hops < 100:
            parent = cells.get(parent.parent)
            hops += 1
        if parent is not None and parent.id not in kinds and parent.vertex and \
                not _is_layer(cells, parent):
            pkv, pnames = parse_style(parent.style)
            pkind, _ = _classify_vertex(parent, pkv, pnames)
            is_activity = pkind in ACTIVITY_TAGS
            if is_activity and (kind == "boundaryEvent" or (
                    kind in ("event", "intermediateCatchEvent", "intermediateThrowEvent")
                    and _on_border(box, _box(cells, parent)))):
                node.kind = "boundaryEvent"
                node.attached_to = parent.id
            else:
                node.scope = parent.id
        d.add_node(node)

    for pid in plus_markers:
        host = d.nodes.get(pid)
        if host is not None and host.kind in ACTIVITY_TAGS:
            host.kind = "subProcess"
            host.expanded = False

    # containers with children become expanded sub-processes; other scopes are flattened
    for n in list(d.nodes.values()):
        if n.scope and n.scope in d.nodes:
            host = d.nodes[n.scope]
            if host.kind in ("subProcess", "transaction", "adHocSubProcess"):
                host.expanded = True
            elif host.kind in ACTIVITY_TAGS:
                host.kind = "subProcess"
                host.expanded = True
                host.guessed = True
            else:
                n.scope = None
        elif n.scope:
            n.scope = None

    for c in cells.values():
        if not c.edge:
            continue
        kv, names = parse_style(c.style)
        pts, sp, tp = _points(cells, c)
        label = html_to_text(c.value)
        extra = edge_labels.get(c.id)
        if extra:
            label = " ".join([label] + extra).strip()
        dash = kv.get("dashPattern", "")
        dotted = kv.get("dashed") == "1" and dash and dash.split(" ")[0] in ("1", "1.0") \
            or "dotted" in kv.get("dashPattern", "")
        dashed = kv.get("dashed") == "1"
        kind = "auto"
        if kv.get("startArrow", "").lower() == "oval" and dashed:
            kind = "message"
        exit_port = entry_port = None
        if "exitX" in kv and "exitY" in kv:
            exit_port = (_float(kv["exitX"]), _float(kv["exitY"]))
        if "entryX" in kv and "entryY" in kv:
            entry_port = (_float(kv["entryX"]), _float(kv["entryY"]))
        edge_style = kv.get("edgeStyle", "").lower()
        orthogonal = edge_style in ("orthogonaledgestyle", "elbowedgestyle",
                                    "entityrelationedgestyle") and kv.get("curved") != "1"
        source = _resolve_endpoint(d, cells, kinds, c.source)
        target = _resolve_endpoint(d, cells, kinds, c.target)
        d.edges.append(Edge(c.id, source, target, label, kind=kind, points=pts,
                            start_point=sp, end_point=tp, exit_port=exit_port,
                            entry_port=entry_port, dashed=dashed, dotted=bool(dotted),
                            orthogonal=orthogonal, documentation=_documentation(c)))
        d.edges[-1].stroke = norm_color(kv.get("strokeColor"), NEUTRAL_STROKES)
    return d


def _apply_colors(obj, cell):
    """Colors and text format of a draw.io cell (fontStyle bits: 1 bold, 2 italic, 4 underline)."""
    kv = parse_style(cell.style)[0]
    obj.fill = norm_color(kv.get("fillColor"), NEUTRAL_FILLS)
    obj.stroke = norm_color(kv.get("strokeColor"), NEUTRAL_STROKES)
    text = {}
    size = finite(kv.get("fontSize"), 0)
    if size and size not in (11, 12) and 6 <= size <= 72:
        text["fontSize"] = "%g" % size
    try:
        bits = int(kv.get("fontStyle") or 0)
    except ValueError:
        bits = 0
    if bits & 1:
        text["fontWeight"] = "bold"
    if bits & 2:
        text["fontStyle"] = "italic"
    if bits & 4:
        text["textDecoration"] = "underline"
    if kv.get("align") in ("left", "right") and getattr(obj, "kind", "") not in ("textAnnotation",):
        text["textAlign"] = kv["align"]
    obj.text = text


def _is_group_frame(kv, names):
    """draw.io BPMN group: dashed (dash-dot) rounded frame, or style 'group' shape."""
    return (kv.get("dashed") == "1" and kv.get("dashPattern", "").replace(" ", "") == "5212"
            and kv.get("rounded") == "1") or kv.get("shape", "").lower() == "mxgraph.bpmn.group"


def label_is_flow(c, connected):
    return c.id in connected


def _resolve_endpoint(d, cells, kinds, cid):
    seen = 0
    while cid and cid not in d.nodes and cid not in d.pools and seen < 20:
        seen += 1
        c = cells.get(cid)
        if c is None:
            return None
        if kinds.get(cid) == "edge_label":
            return None
        if kinds.get(cid) == "lane":
            # a lane outside any pool becomes a black-box pool: message flows may end on it
            return cid if _orphan_lane(d, cid) else None
        cid = c.parent
    return cid if cid in d.nodes or cid in d.pools or _orphan_lane(d, cid) else None


def _orphan_lane(d, cid):
    lane = d.lanes.get(cid)
    return lane is not None and (not lane.pool or lane.pool not in d.pools)


def convert_drawio(data, pages="all"):
    """Convert a draw.io file to a list of ``{'name', 'xml', 'warnings'}``, one per non-empty page."""
    out = []
    for name, model in iter_pages(data):
        d = page_to_diagram(name, model)
        if d.is_empty():
            continue  # "first page" means the first page with a drawing
        xml, warnings = build_bpmn(d, source="drawio")
        out.append({"name": name, "xml": xml, "warnings": warnings})
        if pages == "first":
            break
    if not out:
        raise BpmnError("No BPMN shapes were found in the draw.io file.")
    return out
