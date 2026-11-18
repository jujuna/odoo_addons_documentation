# Part of bpmn_process_management. License LGPL-3.
"""Small SVG thumbnail of a BPMN diagram for the kanban cards, drawn from its DI (layout) only.
Labels are left out on purpose (unreadable at thumbnail size)."""
from xml.sax.saxutils import quoteattr

from .bpmn_common import (
    ACTIVITY_TAGS, BIOC_NS, COLOR_NS, local, norm_color, parse_bpmn, q,
)

MAX_ITEMS = 3000
NAVY = "#22303A"
MUTED = "#8A99A6"
POOL_FILL = "#FFFFFF"
POOL_LINE = "#A9B6BF"
EVENT_TAGS = {"startEvent", "endEvent", "intermediateThrowEvent", "intermediateCatchEvent",
              "boundaryEvent"}
GATEWAY_TAGS = {"exclusiveGateway", "inclusiveGateway", "parallelGateway", "complexGateway",
                "eventBasedGateway"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _colors(di):
    fill = norm_color(di.get(q(COLOR_NS, "background-color")) or di.get(q(BIOC_NS, "fill")))
    stroke = norm_color(di.get(q(COLOR_NS, "border-color")) or di.get(q(BIOC_NS, "stroke")))
    return fill, stroke


def render_thumbnail(xml):
    """Return an SVG string, or '' when the diagram has no layout to draw."""
    root = parse_bpmn(xml.encode() if isinstance(xml, str) else xml)
    elements = {el.get("id"): el for el in root.iter()
                if isinstance(el.tag, str) and el.get("id")}
    plane = root.find(".//" + q("bpmndi", "BPMNPlane"))
    if plane is None:
        return ""
    back, front, lines = [], [], []
    xs, ys = [], []
    for i, di in enumerate(plane):
        if i > MAX_ITEMS:
            break
        el = elements.get(di.get("bpmnElement"))
        if el is None:
            continue
        kind = local(el.tag)
        fill, stroke = _colors(di)
        if local(di.tag) == "BPMNEdge":
            pts = [(_num(w.get("x")), _num(w.get("y"))) for w in di.findall(q("di", "waypoint"))]
            if len(pts) < 2:
                continue
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
            dash = {"messageFlow": "6 4", "association": "2 4", "dataInputAssociation": "2 4",
                    "dataOutputAssociation": "2 4"}.get(kind)
            lines.append('<polyline points="%s" fill="none" stroke=%s stroke-width="1.6"%s/>' % (
                " ".join("%.0f,%.0f" % p for p in pts), quoteattr(stroke or NAVY),
                ' stroke-dasharray="%s"' % dash if dash else ""))
            continue
        b = di.find(q("dc", "Bounds"))
        if b is None:
            continue
        x, y, w, h = (_num(b.get(k)) for k in ("x", "y", "width", "height"))
        if w <= 0 or h <= 0:
            continue
        xs += [x, x + w]
        ys += [y, y + h]
        st = quoteattr(stroke or NAVY)
        if kind in ("participant", "lane"):
            st = quoteattr(stroke or POOL_LINE)
            back.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill=%s stroke=%s '
                        'stroke-width="1.4"/>' % (x, y, w, h, quoteattr(fill or POOL_FILL), st))
            if kind == "participant" and w > 40:
                back.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke=%s stroke-width="1.4"/>'
                            % (x + 30, y, x + 30, y + h, st))
        elif kind in EVENT_TAGS:
            r = min(w, h) / 2
            width = "3.5" if kind == "endEvent" else "1.8"
            front.append('<circle cx="%.0f" cy="%.0f" r="%.1f" fill=%s stroke=%s stroke-width="%s"/>'
                         % (x + w / 2, y + h / 2, r, quoteattr(fill or "#FFFFFF"), st, width))
        elif kind in GATEWAY_TAGS:
            cx, cy = x + w / 2, y + h / 2
            front.append('<polygon points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill=%s stroke=%s '
                         'stroke-width="1.8"/>' % (cx, y, x + w, cy, cx, y + h, x, cy,
                                                    quoteattr(fill or "#FFFFFF"), st))
        elif kind in ACTIVITY_TAGS:
            front.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="10" fill=%s stroke=%s '
                         'stroke-width="%s"/>' % (x, y, w, h, quoteattr(fill or "#FFFFFF"), st,
                                                  "3.5" if kind == "callActivity" else "1.8"))
        elif kind in ("dataObjectReference", "dataStoreReference", "textAnnotation", "group"):
            front.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="none" stroke=%s '
                         'stroke-width="1.2" stroke-dasharray="3 3"/>' % (x, y, w, h, quoteattr(MUTED)))
    if not xs:
        return ""
    pad = 12
    x0, y0 = min(xs) - pad, min(ys) - pad
    width, height = max(xs) - x0 + pad, max(ys) - y0 + pad
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.0f %.0f %.0f %.0f" '
            'width="%.0f" height="%.0f"><style>*{vector-effect:non-scaling-stroke}</style>%s%s%s</svg>'
            % (x0, y0, width, height, width, height, "".join(back), "".join(lines), "".join(front)))
