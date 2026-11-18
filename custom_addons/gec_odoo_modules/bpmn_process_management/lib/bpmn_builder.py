# Part of bpmn_process_management. License LGPL-3.
"""Intermediate diagram model + BPMN 2.0 XML generator.
Importers only fill a :class:`Diagram` (absolute pixel coordinates, y axis down);
this module applies the BPMN rules (pools, lanes, flows, events, ids) and writes the DI layout."""
from lxml import etree

from .bpmn_common import (
    ACTIVITY_TAGS, FLOW_NODE_TAGS, NSMAP, add_odoo_link, make_id, q,
    set_documentation, set_odoo_item, to_string,
)

HEADER = 30  # bpmn-js pool/lane label strip width

EVENT_KINDS = {"startEvent", "endEvent", "intermediateThrowEvent",
               "intermediateCatchEvent", "boundaryEvent", "event"}
GATEWAY_KINDS = {"exclusiveGateway", "inclusiveGateway", "parallelGateway",
                 "complexGateway", "eventBasedGateway"}
DATA_KINDS = {"dataObjectReference", "dataStoreReference"}
EVENT_DEFINITIONS = {
    "message": "messageEventDefinition", "timer": "timerEventDefinition",
    "error": "errorEventDefinition", "escalation": "escalationEventDefinition",
    "cancel": "cancelEventDefinition", "compensation": "compensateEventDefinition",
    "conditional": "conditionalEventDefinition", "link": "linkEventDefinition",
    "signal": "signalEventDefinition", "terminate": "terminateEventDefinition",
}
ID_PREFIX = {
    "startEvent": "StartEvent", "endEvent": "EndEvent", "boundaryEvent": "Event",
    "intermediateThrowEvent": "Event", "intermediateCatchEvent": "Event",
    "exclusiveGateway": "Gateway", "inclusiveGateway": "Gateway",
    "parallelGateway": "Gateway", "complexGateway": "Gateway",
    "eventBasedGateway": "Gateway", "subProcess": "Activity",
    "transaction": "Activity", "callActivity": "Activity",
    "dataObjectReference": "DataObjectReference",
    "dataStoreReference": "DataStoreReference", "textAnnotation": "TextAnnotation",
}


class Box:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y = float(x), float(y)
        self.w, self.h = max(float(w), 1.0), max(float(h), 1.0)

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def area(self):
        return self.w * self.h

    def contains(self, px, py, tol=0.0):
        return (self.x - tol <= px <= self.right + tol
                and self.y - tol <= py <= self.bottom + tol)

    def touches(self, other, tol=3.0):
        return not (other.x > self.right + tol or other.right < self.x - tol
                    or other.y > self.bottom + tol or other.bottom < self.y - tol)

    def distance(self, px, py):
        dx = max(self.x - px, 0, px - self.right)
        dy = max(self.y - py, 0, py - self.bottom)
        return (dx * dx + dy * dy) ** 0.5

    def copy(self):
        return Box(self.x, self.y, self.w, self.h)

    @staticmethod
    def union(boxes):
        boxes = list(boxes)
        x = min(b.x for b in boxes)
        y = min(b.y for b in boxes)
        r = max(b.right for b in boxes)
        bt = max(b.bottom for b in boxes)
        return Box(x, y, r - x, bt - y)

    def __repr__(self):
        return "Box(%.0f,%.0f,%.0f,%.0f)" % (self.x, self.y, self.w, self.h)


def _clip_to_box(box, px, py):
    """Point on ``box`` border on the segment from its center to (px, py)."""
    cx, cy = box.cx, box.cy
    dx, dy = px - cx, py - cy
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return cx, box.y
    hw, hh = box.w / 2, box.h / 2
    tx = hw / abs(dx) if abs(dx) > 1e-9 else float("inf")
    ty = hh / abs(dy) if abs(dy) > 1e-9 else float("inf")
    t = min(tx, ty)
    return cx + dx * t, cy + dy * t


def _port(box, fx, fy):
    return box.x + box.w * fx, box.y + box.h * fy


def _attach(box, towards, orthogonal):
    """Start/end point on ``box`` for a segment heading to ``towards``."""
    px, py = towards
    if orthogonal:
        if box.x <= px <= box.right and not box.contains(px, py):
            return px, (box.y if py < box.y else box.bottom)
        if box.y <= py <= box.bottom and not box.contains(px, py):
            return (box.x if px < box.x else box.right), py
    return _clip_to_box(box, px, py)


def route(src, tgt, points=None, exit_port=None, entry_port=None, orthogonal=True):
    """Compute waypoints between two boxes (absolute coordinates)."""
    points = [tuple(p) for p in (points or [])]
    if points:
        start = _port(src, *exit_port) if exit_port else _attach(src, points[0], orthogonal)
        end = _port(tgt, *entry_port) if entry_port else _attach(tgt, points[-1], orthogonal)
        wps = [start] + points + [end]
    else:
        s = _port(src, *exit_port) if exit_port else None
        e = _port(tgt, *entry_port) if entry_port else None
        if s and e:
            wps = _manhattan(s, e) if orthogonal else [s, e]
        elif not orthogonal:
            wps = [_clip_to_box(src, tgt.cx, tgt.cy), _clip_to_box(tgt, src.cx, src.cy)]
        else:
            wps = _auto_orthogonal(src, tgt, s, e)
    out = []
    for p in wps:
        p = (round(p[0]), round(p[1]))
        if not out or out[-1] != p:
            out.append(p)
    if len(out) == 1:
        out.append((out[0][0] + 1, out[0][1]))
    return out


def _manhattan(s, e):
    if abs(s[0] - e[0]) < 1 or abs(s[1] - e[1]) < 1:
        return [s, e]
    mx = (s[0] + e[0]) / 2
    return [s, (mx, s[1]), (mx, e[1]), e]


def _auto_orthogonal(src, tgt, s=None, e=None):
    if tgt.x >= src.right or src.x >= tgt.right:
        to_right = tgt.x >= src.right
        overlap_top = max(src.y, tgt.y)
        overlap_bottom = min(src.bottom, tgt.bottom)
        if overlap_bottom - overlap_top > 4 and not (s or e):
            y = (overlap_top + overlap_bottom) / 2
            if src.y <= src.cy <= tgt.bottom and tgt.y <= src.cy <= tgt.bottom:
                y = src.cy
            elif src.y <= tgt.cy <= src.bottom:
                y = tgt.cy
            return [(src.right if to_right else src.x, y), (tgt.x if to_right else tgt.right, y)]
        s = s or (src.right if to_right else src.x, src.cy)
        e = e or (tgt.x if to_right else tgt.right, tgt.cy)
        return _manhattan(s, e)
    if tgt.y >= src.bottom or src.y >= tgt.bottom:
        down = tgt.y >= src.bottom
        overlap_l = max(src.x, tgt.x)
        overlap_r = min(src.right, tgt.right)
        if overlap_r - overlap_l > 4 and not (s or e):
            x = src.cx if overlap_l <= src.cx <= overlap_r else (overlap_l + overlap_r) / 2
            return [(x, src.bottom if down else src.y), (x, tgt.y if down else tgt.bottom)]
        s = s or (src.cx, src.bottom if down else src.y)
        e = e or (tgt.cx, tgt.y if down else tgt.bottom)
        if abs(s[0] - e[0]) < 1:
            return [s, e]
        my = (s[1] + e[1]) / 2
        return [s, (s[0], my), (e[0], my), e]
    return [_clip_to_box(src, tgt.cx, tgt.cy), _clip_to_box(tgt, src.cx, src.cy)]


def normalize_box(kind, box):
    """Give events/gateways/data the proportions BPMN tools expect."""
    if kind in ("event", "startEvent", "endEvent", "intermediateThrowEvent",
                "intermediateCatchEvent", "boundaryEvent", "exclusiveGateway",
                "inclusiveGateway", "parallelGateway", "complexGateway", "eventBasedGateway"):
        size = min(max(min(box.w, box.h), 30.0), 60.0)
        return Box(box.cx - size / 2, box.cy - size / 2, size, size)
    if kind == "dataObjectReference" and (box.w > 40 or box.h > 55):
        return Box(box.cx - 18, box.cy - 25, 36, 50)
    if kind == "dataStoreReference" and (box.w > 60 or box.h > 60):
        return Box(box.cx - 25, box.cy - 25, 50, 50)
    return box


def on_border(box, host):
    cx, cy = box.cx, box.cy
    tol = max(box.w, box.h) / 2 + 2
    near = host.contains(cx, cy, tol=tol)
    inside = host.x + tol < cx < host.right - tol and host.y + tol < cy < host.bottom - tol
    return near and not inside


class Node:
    fill = None
    stroke = None
    def __init__(self, src_id, kind, name="", box=None, **kw):
        self.src_id = str(src_id)
        self.kind = kind
        self.name = (name or "").strip()
        self.box = box
        self.event_def = kw.get("event_def")
        self.attached_to = kw.get("attached_to")
        self.cancel_activity = kw.get("cancel_activity", True)
        self.expanded = kw.get("expanded", False)
        self.scope = kw.get("scope")          # src_id of parent sub-process
        self.documentation = kw.get("documentation", "")
        self.links = list(kw.get("links") or [])
        self.review = list(kw.get("review") or [])
        self.guessed = kw.get("guessed", False)
        self.loop = kw.get("loop")                # standard | parallel | sequential
        self.compensation = kw.get("compensation", False)
        self.hit_box = kw.get("hit_box") or box   # original geometry, for glue detection
        self.bpmn_id = None
        self.pool = None
        self.lane = None
        self.incoming = []
        self.outgoing = []


class Lane:
    fill = None
    stroke = None
    def __init__(self, src_id, name, box, pool=None, documentation=""):
        self.src_id, self.name, self.box = str(src_id), (name or "").strip(), box
        self.pool = pool
        self.documentation = documentation
        self.bpmn_id = None
        self.nodes = []


class Pool:
    fill = None
    stroke = None
    def __init__(self, src_id, name, box, synthetic=False, documentation=""):
        self.src_id, self.name, self.box = str(src_id), (name or "").strip(), box
        self.synthetic = synthetic
        self.documentation = documentation
        self.lanes = []
        self.horizontal = True
        self.bpmn_id = None
        self.process_id = None


class Edge:
    fill = None
    stroke = None
    def __init__(self, src_id, source=None, target=None, name="", **kw):
        self.src_id = str(src_id)
        self.source, self.target = source, target
        self.name = (name or "").strip()
        self.kind = kw.get("kind", "auto")   # auto | sequence | message | association
        self.points = list(kw.get("points") or [])
        self.start_point = kw.get("start_point")
        self.end_point = kw.get("end_point")
        self.exit_port = kw.get("exit_port")
        self.entry_port = kw.get("entry_port")
        self.dashed = kw.get("dashed", False)
        self.dotted = kw.get("dotted", False)
        self.orthogonal = kw.get("orthogonal", True)
        self.documentation = kw.get("documentation", "")
        self.bpmn_id = None
        self.resolved_kind = None


class Group:
    """BPMN group artifact (dashed frame), kept apart from flow nodes."""
    fill = None
    stroke = None

    def __init__(self, src_id, name, box):
        self.src_id, self.name, self.box = str(src_id), (name or "").strip(), box
        self.bpmn_id = None


class Diagram:
    def __init__(self, name=""):
        self.name = name
        self.groups = []    # Group
        self.nodes = {}     # src_id -> Node
        self.lanes = {}     # src_id -> Lane
        self.pools = {}     # src_id -> Pool
        self.edges = []
        self.warnings = []  # (code, params)

    def warn(self, code, **params):
        self.warnings.append((code, params))

    def add_node(self, node):
        self.nodes[node.src_id] = node
        return node

    def is_empty(self):
        return not self.nodes and not self.pools and not self.lanes and not self.groups


class _UnionFind:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


class BpmnBuilder:

    def __init__(self, diagram, source="import"):
        self.d = diagram
        self.source = source
        self.used_ids = set()

    def _node_label(self, n):
        return n.name or n.src_id

    def _scope_root(self, node):
        seen = set()
        while node.scope and node.scope in self.d.nodes and node.scope not in seen:
            seen.add(node.scope)
            node = self.d.nodes[node.scope]
        return node

    def _resolve_dangling(self):
        nodes = [n for n in self.d.nodes.values() if n.hit_box and n.kind != "textAnnotation"]
        for e in self.d.edges:
            for attr, pt in (("source", e.start_point), ("target", e.end_point)):
                if getattr(e, attr) or not pt:
                    continue
                cands = [n for n in nodes if n.hit_box.contains(pt[0], pt[1], tol=6)]
                if cands:
                    setattr(e, attr, min(cands, key=lambda n: n.hit_box.area).src_id)

    def _group_orphan_lanes(self):
        d = self.d
        orphans = [ln for ln in d.lanes.values() if not ln.pool or ln.pool not in d.pools]
        if not orphans:
            return
        uf = _UnionFind([ln.src_id for ln in orphans])
        for i, a in enumerate(orphans):
            for b in orphans[i + 1:]:
                if a.box.touches(b.box):
                    uf.union(a.src_id, b.src_id)

        def lane_of_point(n):
            best = [ln for ln in orphans if ln.box.contains(n.box.cx, n.box.cy)]
            return min(best, key=lambda ln: ln.box.area).src_id if best else None

        for e in d.edges:
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            if not (s and t and s.box and t.box) or e.dashed or e.dotted or e.kind != "auto":
                continue
            ls, lt = lane_of_point(s), lane_of_point(t)
            if ls and lt:
                uf.union(ls, lt)
        groups = {}
        for ln in orphans:
            groups.setdefault(uf.find(ln.src_id), []).append(ln)
        for n, members in enumerate(groups.values(), start=1):
            if len(members) == 1:
                ln = members[0]
                del d.lanes[ln.src_id]
                d.pools[ln.src_id] = Pool(ln.src_id, ln.name, ln.box, documentation=ln.documentation)
            else:
                pid = "__pool_%d" % n
                d.pools[pid] = Pool(pid, d.name or "", Box.union(m.box for m in members), synthetic=True)
                for ln in members:
                    ln.pool = pid
                d.warn("lanes_grouped", count=len(members))

    def _layout_pools(self):
        d = self.d
        for ln in d.lanes.values():
            if ln.pool in d.pools:
                d.pools[ln.pool].lanes.append(ln)
        for pool in d.pools.values():
            lanes = pool.lanes
            if len(lanes) >= 2:
                xs = max(ln.box.x for ln in lanes) - min(ln.box.x for ln in lanes)
                ys = max(ln.box.y for ln in lanes) - min(ln.box.y for ln in lanes)
                pool.horizontal = ys >= xs
            else:
                pool.horizontal = pool.box.w >= pool.box.h
            if not lanes:
                continue
            u = Box.union(ln.box for ln in lanes)
            if pool.horizontal:
                pool.box = Box(u.x - HEADER, u.y, u.w + HEADER, u.h)
                for ln in lanes:
                    ln.box = Box(u.x, ln.box.y, u.w, ln.box.h)
                lanes.sort(key=lambda ln: ln.box.y)
            else:
                pool.box = Box(u.x, u.y - HEADER, u.w, u.h + HEADER)
                for ln in lanes:
                    ln.box = Box(ln.box.x, u.y, ln.box.w, u.h)
                lanes.sort(key=lambda ln: ln.box.x)

    def _assign_nodes(self):
        d = self.d
        pools = list(d.pools.values())
        for n in d.nodes.values():
            if n.scope or n.attached_to:
                continue
            if not pools or not n.box:
                continue
            cands = [p for p in pools if p.box.contains(n.box.cx, n.box.cy)]
            if cands:
                n.pool = min(cands, key=lambda p: p.box.area).src_id
            elif n.kind == "textAnnotation":
                n.pool = None  # goes to the collaboration
            else:
                n.pool = min(pools, key=lambda p: p.box.distance(n.box.cx, n.box.cy)).src_id
                d.warn("node_outside_pool", name=self._node_label(n))
        for n in d.nodes.values():
            host = n
            if n.attached_to and n.attached_to in d.nodes:
                host = d.nodes[n.attached_to]
            root = self._scope_root(host)
            if root is not n:
                n.pool = root.pool
        for n in d.nodes.values():
            # lanes list top-level nodes only (sub-process content is not a lane member)
            if n.pool is None or n.kind not in FLOW_NODE_TAGS or not n.box or n.scope:
                continue
            lanes = d.pools[n.pool].lanes
            if not lanes:
                continue
            ref = self._scope_root(d.nodes[n.attached_to] if n.attached_to in d.nodes else n)
            cands = [ln for ln in lanes if ln.box.contains(ref.box.cx, ref.box.cy)]
            lane = min(cands, key=lambda ln: ln.box.area) if cands else \
                min(lanes, key=lambda ln: ln.box.distance(ref.box.cx, ref.box.cy))
            n.lane = lane.src_id
            lane.nodes.append(n)

    def _attach_boundaries(self):
        d = self.d
        activities = [n for n in d.nodes.values()
                      if n.kind in ACTIVITY_TAGS and n.box]
        for n in d.nodes.values():
            if n.kind != "boundaryEvent" or n.attached_to in d.nodes:
                continue
            cands = [a for a in activities
                     if a.box.contains(n.box.cx, n.box.cy, tol=n.box.h / 2)
                     and not (a.box.x + 4 < n.box.cx < a.box.right - 4
                              and a.box.y + 4 < n.box.cy < a.box.bottom - 4)]
            if cands:
                n.attached_to = min(cands, key=lambda a: a.box.area).src_id
            else:
                n.kind = "intermediateCatchEvent"
                d.warn("boundary_detached", name=self._node_label(n))
        for n in d.nodes.values():
            if n.kind == "boundaryEvent":
                n.scope = d.nodes[n.attached_to].scope

    def _classify_edges(self):
        d = self.d
        kept = []
        for e in d.edges:
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            sp, tp = d.pools.get(e.source), d.pools.get(e.target)
            label = e.name or e.src_id
            if not (s or sp) or not (t or tp):
                d.warn("edge_dropped", name=label, reason="not_connected")
                continue
            if s is t and s is not None:
                d.warn("edge_dropped", name=label, reason="self_loop")
                continue
            if sp or tp:
                # message flow from/to a pool (black box participant)
                ps = sp.src_id if sp else s.pool
                pt = tp.src_id if tp else t.pool
                if ps and pt and ps != pt:
                    e.resolved_kind = "message"
                    kept.append(e)
                else:
                    d.warn("edge_dropped", name=label, reason="pool_connection")
                continue
            if "textAnnotation" in (s.kind, t.kind):
                e.resolved_kind = "association"
            elif s.kind in DATA_KINDS or t.kind in DATA_KINDS:
                if s.kind in DATA_KINDS and t.kind in ACTIVITY_TAGS:
                    e.resolved_kind = "data_input"
                elif t.kind in DATA_KINDS and s.kind in ACTIVITY_TAGS:
                    e.resolved_kind = "data_output"
                else:
                    e.resolved_kind = "association"
                    d.warn("data_link_as_association", name=label)
            elif s.kind not in FLOW_NODE_TAGS | {"event"} or t.kind not in FLOW_NODE_TAGS | {"event"}:
                d.warn("edge_dropped", name=label, reason="unsupported")
                continue
            elif s.pool != t.pool:
                e.resolved_kind = "message"
            elif e.kind == "message" or (e.dashed and not e.dotted and e.kind == "auto"):
                if d.pools:
                    d.warn("dashed_in_pool", name=label)
                e.resolved_kind = "sequence"
            elif e.kind == "association" or e.dotted:
                e.resolved_kind = "association"
            else:
                e.resolved_kind = "sequence"
            if e.resolved_kind == "message" and not (s.pool and t.pool):
                e.resolved_kind = "sequence"
            if e.resolved_kind == "sequence" and (s.scope or None) != (t.scope or None):
                # BPMN: a sequence flow cannot leave or enter a sub-process
                d.warn("edge_dropped", name=label, reason="crosses_subprocess")
                continue
            if e.resolved_kind == "sequence":
                if t.kind == "startEvent" or s.kind == "endEvent":
                    pass  # keep what the author drew
                s.outgoing.append(e)
                t.incoming.append(e)
            kept.append(e)
        d.edges = kept

    def _infer_events(self):
        for n in self.d.nodes.values():
            if n.kind != "event":
                continue
            if not n.incoming:
                n.kind = "startEvent"
            elif not n.outgoing:
                n.kind = "endEvent"
            elif n.event_def:
                n.kind = "intermediateCatchEvent"
            else:
                n.kind = "intermediateThrowEvent"
            if n.kind == "startEvent" and n.event_def == "terminate":
                n.event_def = None

    def _bid(self, prefix, raw):
        return make_id(prefix, raw, self.used_ids)

    def _extension(self, el, obj, review_default=None):
        for link in getattr(obj, "links", []):
            add_odoo_link(el, dict(linkType="url", url=link.get("url"), label=link.get("label")))
        reasons = list(getattr(obj, "review", []) or [])
        if review_default:
            reasons.append(review_default)
        if reasons:
            set_odoo_item(el, "review", {"status": "pending", "reason": reasons[0],
                                         "source": self.source})

    def _node_xml(self, parent, n, children_by_scope):
        el = etree.SubElement(parent, q("bpmn", n.kind), id=n.bpmn_id)
        if n.kind == "textAnnotation":
            txt = etree.SubElement(el, q("bpmn", "text"))
            txt.text = n.name
            return el
        if n.name:
            el.set("name", n.name)
        if n.documentation:
            set_documentation(el, n.documentation)
        self._extension(el, n, "type_guessed" if n.guessed else None)
        if n.kind == "boundaryEvent":
            el.set("attachedToRef", self.d.nodes[n.attached_to].bpmn_id)
            if not n.cancel_activity:
                el.set("cancelActivity", "false")
        if n.kind == "dataObjectReference":
            do_id = self._bid("DataObject", n.src_id)
            el.set("dataObjectRef", do_id)
            etree.SubElement(parent, q("bpmn", "dataObject"), id=do_id)
            return el
        if n.kind == "dataStoreReference":
            return el
        for e in n.incoming:
            etree.SubElement(el, q("bpmn", "incoming")).text = e.bpmn_id
        for e in n.outgoing:
            etree.SubElement(el, q("bpmn", "outgoing")).text = e.bpmn_id
        if n.kind in ACTIVITY_TAGS:
            inputs = [e for e in self.d.edges if e.resolved_kind == "data_input" and e.target == n.src_id]
            outputs = [e for e in self.d.edges if e.resolved_kind == "data_output" and e.source == n.src_id]
            if inputs:
                prop_id = self._bid("Property", n.src_id)
                etree.SubElement(el, q("bpmn", "property"), id=prop_id, name="__targetRef_placeholder")
                for e in inputs:
                    a = etree.SubElement(el, q("bpmn", "dataInputAssociation"), id=e.bpmn_id)
                    etree.SubElement(a, q("bpmn", "sourceRef")).text = self.d.nodes[e.source].bpmn_id
                    etree.SubElement(a, q("bpmn", "targetRef")).text = prop_id
            for e in outputs:
                a = etree.SubElement(el, q("bpmn", "dataOutputAssociation"), id=e.bpmn_id)
                etree.SubElement(a, q("bpmn", "targetRef")).text = self.d.nodes[e.target].bpmn_id
        if n.kind in ACTIVITY_TAGS and n.loop in ("standard", "parallel", "sequential"):
            if n.loop == "standard":
                etree.SubElement(el, q("bpmn", "standardLoopCharacteristics"),
                                 id=self._bid("Loop", n.src_id))
            else:
                mi = etree.SubElement(el, q("bpmn", "multiInstanceLoopCharacteristics"),
                                      id=self._bid("MultiInstance", n.src_id))
                if n.loop == "sequential":
                    mi.set("isSequential", "true")
        if n.kind in ACTIVITY_TAGS and n.compensation:
            el.set("isForCompensation", "true")
        if n.kind in EVENT_KINDS and n.event_def in EVENT_DEFINITIONS:
            etree.SubElement(el, q("bpmn", EVENT_DEFINITIONS[n.event_def]),
                             id=self._bid("EventDefinition", n.src_id))
        if n.kind in ("subProcess", "transaction", "adHocSubProcess"):
            self._fill_container(el, n.src_id, children_by_scope)
        return el

    def _emit_association(self, el, e):
        etree.SubElement(el, q("bpmn", "association"), id=e.bpmn_id,
                         sourceRef=self._ref(e.source), targetRef=self._ref(e.target))

    def _fill_container(self, el, scope_id, children_by_scope, pool_id=None, collaboration=False):
        d = self.d
        collab_notes = {n.src_id for n in d.nodes.values()
                        if d.pools and n.kind == "textAnnotation" and n.pool is None and not n.scope}
        if collaboration:
            for n in children_by_scope.get(None, []):
                if n.src_id in collab_notes:
                    self._node_xml(el, n, children_by_scope)
            for e in d.edges:
                if e.resolved_kind == "association" and (e.source in collab_notes or e.target in collab_notes):
                    self._emit_association(el, e)
            return
        nodes = children_by_scope.get(scope_id, [])
        if scope_id is None:
            nodes = [n for n in nodes if n.pool == pool_id and n.src_id not in collab_notes]
        flow = [n for n in nodes if n.kind != "textAnnotation"]
        notes = [n for n in nodes if n.kind == "textAnnotation"]
        for n in flow:
            self._node_xml(el, n, children_by_scope)
        for e in d.edges:
            if e.resolved_kind == "sequence" and self._edge_scope(e) == (scope_id, pool_id):
                f = etree.SubElement(el, q("bpmn", "sequenceFlow"), id=e.bpmn_id,
                                     sourceRef=d.nodes[e.source].bpmn_id,
                                     targetRef=d.nodes[e.target].bpmn_id)
                if e.name:
                    f.set("name", e.name)
                if e.documentation:
                    set_documentation(f, e.documentation)
        for n in notes:
            self._node_xml(el, n, children_by_scope)
        for e in d.edges:
            if (e.resolved_kind == "association"
                    and e.source not in collab_notes and e.target not in collab_notes
                    and self._edge_scope(e) == (scope_id, pool_id)):
                self._emit_association(el, e)

    def _ref(self, src_id):
        if src_id in self.d.nodes:
            return self.d.nodes[src_id].bpmn_id
        return self.d.pools[src_id].bpmn_id

    def _edge_scope(self, e):
        s, t = self.d.nodes[e.source], self.d.nodes[e.target]
        if s.kind == "textAnnotation":
            s = t
        chain_s, cur = [], s
        while cur is not None and len(chain_s) < 100:
            chain_s.append(cur.scope)
            cur = self.d.nodes.get(cur.scope) if cur.scope else None
        cur, hops = t, 0
        while cur is not None and hops < 100:
            hops += 1
            if cur.scope in chain_s:
                return (cur.scope, s.pool if cur.scope is None else None)
            cur = self.d.nodes.get(cur.scope) if cur.scope else None
        return (None, s.pool)

    def _break_scope_cycles(self):
        for n in self.d.nodes.values():
            seen, cur = {n.src_id}, n
            while cur.scope:
                if cur.scope in seen or cur.scope not in self.d.nodes:
                    n.scope = None
                    break
                seen.add(cur.scope)
                cur = self.d.nodes[cur.scope]

    def build(self):
        d = self.d
        self._break_scope_cycles()
        self._resolve_dangling()
        self._group_orphan_lanes()
        self._layout_pools()
        self._attach_boundaries()
        self._assign_nodes()
        self._classify_edges()
        self._infer_events()

        for n in d.nodes.values():
            prefix = ID_PREFIX.get(n.kind, "Activity" if n.kind in ACTIVITY_TAGS else "Element")
            n.bpmn_id = self._bid(prefix, n.src_id)
        for e in d.edges:
            prefix = {"sequence": "Flow", "message": "MessageFlow", "association": "Association",
                      "data_input": "DataInputAssociation",
                      "data_output": "DataOutputAssociation"}[e.resolved_kind]
            e.bpmn_id = self._bid(prefix, e.src_id)
        for ln in d.lanes.values():
            ln.bpmn_id = self._bid("Lane", ln.src_id)
        for p in d.pools.values():
            p.bpmn_id = self._bid("Participant", p.src_id)
            p.process_id = self._bid("Process", p.src_id)

        children_by_scope = {}
        for n in d.nodes.values():
            children_by_scope.setdefault(n.scope, []).append(n)
        for lst in children_by_scope.values():
            lst.sort(key=lambda n: (n.box.x, n.box.y) if n.box else (0, 0))

        defs = etree.Element(q("bpmn", "definitions"), nsmap=NSMAP)
        defs.set("id", "Definitions_1")
        defs.set("targetNamespace", "http://bpmn.io/schema/bpmn")
        defs.set("exporter", "Odoo BPMN Process Management")
        defs.set("exporterVersion", "1.0")

        pools = sorted(d.pools.values(), key=lambda p: (p.box.y, p.box.x))
        if pools:
            collab = etree.SubElement(defs, q("bpmn", "collaboration"), id="Collaboration_1")
            for p in pools:
                part = etree.SubElement(collab, q("bpmn", "participant"), id=p.bpmn_id,
                                        processRef=p.process_id)
                if p.name:
                    part.set("name", p.name)
                if p.documentation:
                    set_documentation(part, p.documentation)
                if not p.lanes:
                    set_odoo_item(part, "review", {"status": "pending", "reason": "responsible_missing",
                                                   "source": self.source})
            for e in d.edges:
                if e.resolved_kind == "message":
                    mf = etree.SubElement(collab, q("bpmn", "messageFlow"), id=e.bpmn_id,
                                          sourceRef=self._ref(e.source), targetRef=self._ref(e.target))
                    if e.name:
                        mf.set("name", e.name)
            self._fill_container(collab, None, children_by_scope, pool_id=None, collaboration=True)
            plane_ref = "Collaboration_1"
            for p in pools:
                proc = etree.SubElement(defs, q("bpmn", "process"), id=p.process_id, isExecutable="false")
                if p.lanes:
                    ls = etree.SubElement(proc, q("bpmn", "laneSet"), id=self._bid("LaneSet", p.src_id))
                    for ln in p.lanes:
                        lel = etree.SubElement(ls, q("bpmn", "lane"), id=ln.bpmn_id)
                        if ln.name:
                            lel.set("name", ln.name)
                        if ln.documentation:
                            set_documentation(lel, ln.documentation)
                        set_odoo_item(lel, "review", {"status": "pending", "reason": "responsible_missing",
                                                      "source": self.source})
                        for n in ln.nodes:
                            if n.kind in FLOW_NODE_TAGS:
                                etree.SubElement(lel, q("bpmn", "flowNodeRef")).text = n.bpmn_id
                self._fill_container(proc, None, children_by_scope, pool_id=p.src_id)
        else:
            proc = etree.SubElement(defs, q("bpmn", "process"), id="Process_1", isExecutable="false")
            if d.name:
                proc.set("name", d.name)
            self._fill_container(proc, None, children_by_scope, pool_id=None)
            plane_ref = "Process_1"

        if d.groups:
            container = defs.find(q("bpmn", "collaboration"))
            if container is None:
                container = defs.find(q("bpmn", "process"))
            for g in d.groups:
                g.bpmn_id = self._bid("Group", g.src_id)
                cat = etree.Element(q("bpmn", "category"), id=self._bid("Category", g.src_id))
                cv = etree.SubElement(cat, q("bpmn", "categoryValue"),
                                      id=self._bid("CategoryValue", g.src_id))
                if g.name:
                    cv.set("value", g.name)
                defs.insert(0, cat)
                etree.SubElement(container, q("bpmn", "group"), id=g.bpmn_id,
                                 categoryValueRef=cv.get("id"))
        self._build_di(defs, plane_ref, pools)
        return to_string(defs)

    def _bounds(self, parent, box):
        etree.SubElement(parent, q("dc", "Bounds"), x="%d" % round(box.x), y="%d" % round(box.y),
                         width="%d" % round(box.w), height="%d" % round(box.h))

    @staticmethod
    def _color(di, obj):
        """Write imported colors in both notations read by bpmn-js and others."""
        fill, stroke = getattr(obj, "fill", None), getattr(obj, "stroke", None)
        if fill:
            di.set(q("color", "background-color"), fill)
            di.set(q("bioc", "fill"), fill)
        if stroke:
            di.set(q("color", "border-color"), stroke)
            di.set(q("bioc", "stroke"), stroke)
        for key, value in (getattr(obj, "text", None) or {}).items():
            di.set(q("odoostyle", key), value)

    def _build_di(self, defs, plane_ref, pools):
        d = self.d
        diag = etree.SubElement(defs, q("bpmndi", "BPMNDiagram"), id="BPMNDiagram_1")
        plane = etree.SubElement(diag, q("bpmndi", "BPMNPlane"), id="BPMNPlane_1", bpmnElement=plane_ref)
        for p in pools:
            sh = etree.SubElement(plane, q("bpmndi", "BPMNShape"), id=p.bpmn_id + "_di",
                                  bpmnElement=p.bpmn_id, isHorizontal="true" if p.horizontal else "false")
            self._color(sh, p)
            self._bounds(sh, p.box)
            for ln in p.lanes:
                sh = etree.SubElement(plane, q("bpmndi", "BPMNShape"), id=ln.bpmn_id + "_di",
                                      bpmnElement=ln.bpmn_id,
                                      isHorizontal="true" if p.horizontal else "false")
                self._color(sh, ln)
                self._bounds(sh, ln.box)

        for g in d.groups:
            sh = etree.SubElement(plane, q("bpmndi", "BPMNShape"), id=g.bpmn_id + "_di",
                                  bpmnElement=g.bpmn_id)
            self._color(sh, g)
            self._bounds(sh, g.box)

        def depth(n):
            k, cur = 0, n
            while cur.scope and cur.scope in d.nodes and k < 50:
                k += 1
                cur = d.nodes[cur.scope]
            return k + (1 if n.kind == "boundaryEvent" else 0)

        for n in sorted(d.nodes.values(), key=depth):
            if not n.box:
                continue
            sh = etree.SubElement(plane, q("bpmndi", "BPMNShape"), id=n.bpmn_id + "_di",
                                  bpmnElement=n.bpmn_id)
            if n.kind in ("subProcess", "transaction", "adHocSubProcess"):
                sh.set("isExpanded", "true" if n.expanded else "false")
            if n.kind == "exclusiveGateway":
                sh.set("isMarkerVisible", "true")
            self._color(sh, n)
            self._bounds(sh, n.box)
        for e in d.edges:
            src = d.nodes[e.source].box if e.source in d.nodes else d.pools[e.source].box
            tgt = d.nodes[e.target].box if e.target in d.nodes else d.pools[e.target].box
            wps = route(src, tgt, e.points, e.exit_port, e.entry_port, e.orthogonal)
            ed = etree.SubElement(plane, q("bpmndi", "BPMNEdge"), id=e.bpmn_id + "_di",
                                  bpmnElement=e.bpmn_id)
            if e.stroke:
                ed.set(q("color", "border-color"), e.stroke)
                ed.set(q("bioc", "stroke"), e.stroke)
            for x, y in wps:
                etree.SubElement(ed, q("di", "waypoint"), x="%d" % x, y="%d" % y)


def build_bpmn(diagram, source="import"):
    """Return (bpmn_xml, warnings) for an intermediate :class:`Diagram`."""
    xml = BpmnBuilder(diagram, source=source).build()
    return xml, list(diagram.warnings)
