# Part of bpmn_process_management. License LGPL-3.
"""BPMN 2.0 -> uncompressed ``.drawio`` with the draw.io BPMN shapes.
Re-imports losslessly for what draw.io can draw.
Odoo links are kept as the ``odoo_links`` property, documentation as the shape tooltip."""
import html
from lxml import etree

from .bpmn_common import (
    ACTIVITY_TAGS, BpmnError, finite, get_documentation, local, norm_color, odoo_items, parse_bpmn, q,
)

TASK_BASE = ("points=[[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],"
             "[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];"
             "shape=mxgraph.bpmn.task2;whiteSpace=wrap;rectStyle=rounded;size=10;html=1;"
             "container=1;expand=0;collapsible=0;")
TASK_MARKERS = {
    "task": "abstract", "userTask": "user", "manualTask": "manual", "sendTask": "send",
    "receiveTask": "receive", "serviceTask": "service", "scriptTask": "script",
    "businessRuleTask": "businessRule",
}
EVENT_BASE = ("points=[[0.145,0.145,0],[0.5,0,0],[0.855,0.145,0],[1,0.5,0],[0.855,0.855,0],"
              "[0.5,1,0],[0.145,0.855,0],[0,0.5,0]];shape=mxgraph.bpmn.event;html=1;"
              "verticalLabelPosition=bottom;labelBackgroundColor=#ffffff;verticalAlign=top;"
              "align=center;perimeter=ellipsePerimeter;outlineConnect=0;aspect=fixed;")
GATEWAY_BASE = ("points=[[0.25,0.25,0],[0.5,0,0],[0.75,0.25,0],[1,0.5,0],[0.75,0.75,0],"
                "[0.5,1,0],[0.25,0.75,0],[0,0.5,0]];shape=mxgraph.bpmn.gateway2;html=1;"
                "verticalLabelPosition=bottom;labelBackgroundColor=#ffffff;verticalAlign=top;"
                "align=center;perimeter=rhombusPerimeter;outlineConnect=0;")
DEF_SYMBOL = {
    "messageEventDefinition": "message", "timerEventDefinition": "timer",
    "errorEventDefinition": "error", "escalationEventDefinition": "escalation",
    "cancelEventDefinition": "cancel", "compensateEventDefinition": "compensation",
    "conditionalEventDefinition": "conditional", "linkEventDefinition": "link",
    "signalEventDefinition": "signal", "terminateEventDefinition": "terminate",
}
SEQ_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;"
MSG_STYLE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;dashed=1;dashPattern=8 4;"
             "endArrow=blockThin;endFill=0;startArrow=oval;startFill=0;")
ASSOC_STYLE = "rounded=0;html=1;dashed=1;dashPattern=1 4;endArrow=none;"
DATA_ASSOC_STYLE = "rounded=0;html=1;dashed=1;dashPattern=1 4;endArrow=open;endFill=0;"


def _markers(el):
    m = ""
    if el.find(q("bpmn", "standardLoopCharacteristics")) is not None:
        m += "isLoopStandard=1;"
    mi = el.find(q("bpmn", "multiInstanceLoopCharacteristics"))
    if mi is not None:
        m += "isLoopMultiSeq=1;" if mi.get("isSequential") == "true" else "isLoopMultiParallel=1;"
    if el.get("isForCompensation") == "true":
        m += "isLoopComp=1;"
    return m


def _style_for(tag, el):
    return _base_style_for(tag, el) + (_markers(el) if tag in ACTIVITY_TAGS else "")


def _base_style_for(tag, el):
    if tag in TASK_MARKERS:
        return TASK_BASE + "taskMarker=%s;" % TASK_MARKERS[tag]
    if tag == "group":
        return ("rounded=1;dashed=1;dashPattern=5 2 1 2;fillColor=none;html=1;whiteSpace=wrap;"
                "verticalAlign=top;align=left;spacingLeft=5;")
    if tag in ("subProcess", "transaction", "adHocSubProcess"):
        expanded = el.get("_expanded") == "true"
        s = TASK_BASE + "taskMarker=abstract;bpmnShapeType=subprocess;"
        if tag == "transaction":
            s = TASK_BASE + "taskMarker=abstract;bpmnShapeType=transaction;"
        if tag == "adHocSubProcess":
            s += "isAdHoc=1;"
        if not expanded:
            s += "isLoopSub=1;"
        else:
            s += "verticalAlign=top;align=left;spacingLeft=5;"
        return s
    if tag == "callActivity":
        return TASK_BASE + "bpmnShapeType=call;"
    if tag.endswith("Event"):
        symbol = "general"
        for child in el:
            sym = DEF_SYMBOL.get(local(child.tag))
            if sym:
                symbol = sym
        if tag == "startEvent":
            outline = "standard"
        elif tag == "endEvent":
            outline = "end"
            if symbol == "terminate":
                symbol = "terminate2"
        elif tag == "boundaryEvent":
            outline = "boundNonint" if el.get("cancelActivity") == "false" else "boundInt"
        elif tag == "intermediateCatchEvent":
            outline = "catching"
        else:
            outline = "throwing"
        return EVENT_BASE + "outline=%s;symbol=%s;" % (outline, symbol)
    if tag.endswith("Gateway"):
        gw = {"exclusiveGateway": "outline=none;symbol=none;gwType=exclusive;",
              "parallelGateway": "outline=none;symbol=none;gwType=parallel;",
              "inclusiveGateway": "outline=end;symbol=general;",
              "complexGateway": "outline=none;symbol=none;gwType=complex;",
              "eventBasedGateway": "outline=catching;symbol=multiple;"}[tag]
        return GATEWAY_BASE + gw
    if tag == "dataObjectReference":
        return ("shape=mxgraph.bpmn.data2;labelPosition=center;verticalLabelPosition=bottom;"
                "align=center;verticalAlign=top;size=15;html=1;")
    if tag == "dataStoreReference":
        return ("shape=datastore;html=1;labelPosition=center;verticalLabelPosition=bottom;"
                "align=center;verticalAlign=top;")
    if tag == "textAnnotation":
        return "html=1;shape=mxgraph.flowchart.annotation_2;align=left;labelPosition=right;whiteSpace=wrap;"
    return TASK_BASE + "taskMarker=abstract;"


def _color_style(pair):
    fill, stroke = pair or (None, None)
    out = ""
    if fill:
        out += "fillColor=%s;" % fill
    if stroke:
        out += "strokeColor=%s;fontColor=%s;" % (stroke, stroke)
    return out


def _text_style(di):
    """draw.io style for the odoo:* text format of a DI element."""
    out = ""
    size = finite(di.get(q("odoostyle", "fontSize")), 0)
    if size:
        out += "fontSize=%g;" % size
    bits = (1 if di.get(q("odoostyle", "fontWeight")) == "bold" else 0) \
        | (2 if di.get(q("odoostyle", "fontStyle")) == "italic" else 0) \
        | (4 if di.get(q("odoostyle", "textDecoration")) == "underline" else 0)
    if bits:
        out += "fontStyle=%d;" % bits
    if di.get(q("odoostyle", "textAlign")) in ("left", "right"):
        out += "align=%s;" % di.get(q("odoostyle", "textAlign"))
    return out


def bpmn_to_drawio(xml, name="Page-1"):
    root = parse_bpmn(xml)
    elements = {el.get("id"): el for el in root.iter() if isinstance(el.tag, str) and el.get("id")}
    shapes, edges, colors, texts = {}, [], {}, {}
    plane = root.find(".//" + q("bpmndi", "BPMNPlane"))
    if plane is None or not len(plane):
        raise BpmnError("The diagram has no layout yet. Open it once in the editor and save.")
    for di in plane:
        ref = di.get("bpmnElement")
        el = elements.get(ref)
        if el is None:
            continue
        colors[ref] = (norm_color(di.get(q("color", "background-color")) or di.get(q("bioc", "fill"))),
                       norm_color(di.get(q("color", "border-color")) or di.get(q("bioc", "stroke"))))
        texts[ref] = _text_style(di)
        if local(di.tag) == "BPMNShape":
            b = di.find(q("dc", "Bounds"))
            if b is None:
                continue
            if di.get("isExpanded") == "true":
                el.set("_expanded", "true")
            shapes[ref] = (el, [finite(b.get(k, 0)) for k in ("x", "y", "width", "height")],
                           di.get("isHorizontal") != "false")
        elif local(di.tag) == "BPMNEdge":
            pts = [(finite(w.get("x", 0)), finite(w.get("y", 0)))
                   for w in di.findall(q("di", "waypoint"))]
            edges.append((el, pts))

    mxfile = etree.Element("mxfile", host="Odoo", type="device")
    diagram = etree.SubElement(mxfile, "diagram", id="odoo-bpmn", name=name or "Page-1")
    model = etree.SubElement(diagram, "mxGraphModel", grid="1", gridSize="10", guides="1",
                             tooltips="1", connect="1", arrows="1", fold="1", page="1",
                             pageScale="1", math="0", shadow="0")
    mroot = etree.SubElement(model, "root")
    etree.SubElement(mroot, "mxCell", id="0")
    etree.SubElement(mroot, "mxCell", id="1", parent="0")

    # containment: pools -> lanes -> nodes (smallest container wins)
    containers = []
    for ref, (el, (x, y, w, h), horiz) in shapes.items():
        if local(el.tag) in ("participant", "lane"):
            containers.append((w * h, ref))
    parent_of = {}
    for ref, (el, (x, y, w, h), _h) in shapes.items():
        cx, cy = x + w / 2, y + h / 2
        best = None
        if local(el.tag) == "group":
            parent_of[ref] = None
            continue
        for area, cref in sorted(containers):
            if cref == ref:
                continue
            _cel, (px, py, pw, ph), _ = shapes[cref]
            if px <= cx <= px + pw and py <= cy <= py + ph and area > w * h:
                best = cref
                break
        parent_of[ref] = best

    def abs_xy(ref):
        return shapes[ref][1][0], shapes[ref][1][1]

    order = sorted(shapes, key=lambda r: (0 if local(shapes[r][0].tag) == "participant" else
                                          1 if local(shapes[r][0].tag) == "lane" else 2))
    for ref in order:
        el, (x, y, w, h), horiz = shapes[ref]
        tag = local(el.tag)
        parent = parent_of.get(ref) or "1"
        px, py = abs_xy(parent) if parent != "1" else (0, 0)
        if tag == "textAnnotation":
            t = el.find(q("bpmn", "text"))
            label = (t.text or "") if t is not None else ""
        elif tag == "group":
            cv = elements.get(el.get("categoryValueRef"))
            label = (cv.get("value") or "") if cv is not None else ""
        else:
            label = el.get("name", "")
        if tag == "participant":
            style = ("swimlane;html=1;startSize=30;horizontal=%s;whiteSpace=wrap;collapsible=0;"
                     % ("0" if horiz else "1"))
        elif tag == "lane":
            style = ("swimlane;html=1;startSize=30;horizontal=%s;swimlaneLine=1;collapsible=0;"
                     "whiteSpace=wrap;" % ("0" if horiz else "1"))
        else:
            style = _style_for(tag, el)
        style += _color_style(colors.get(ref)) + texts.get(ref, "")
        attrs = {"id": ref, "label": html.escape(label, quote=False).replace("\n", "<br>")}
        doc = get_documentation(el)
        if doc:
            attrs["tooltip"] = doc
        links = []
        for lk in odoo_items(el, "link"):
            links.append(lk.get("label") or lk.get("url") or lk.get("xmlid") or lk.get("model") or "")
            if lk.get("url") and "link" not in attrs:
                attrs["link"] = lk.get("url")
        if links:
            attrs["odoo_links"] = "; ".join(x for x in links if x)
        resp = odoo_items(el, "responsible")
        if resp:
            attrs["odoo_responsible"] = resp[0].get("name", "")
        attrs["bpmn_type"] = tag
        obj = etree.SubElement(mroot, "object", **{k: v for k, v in attrs.items() if v is not None})
        cell = etree.SubElement(obj, "mxCell", style=style, vertex="1", parent=parent)
        etree.SubElement(cell, "mxGeometry", x="%g" % (x - px), y="%g" % (y - py),
                         width="%g" % w, height="%g" % h, **{"as": "geometry"})

    for el, pts in edges:
        tag = local(el.tag)
        src_ref = tgt_ref = None
        if tag in ("sequenceFlow", "messageFlow", "association"):
            src_ref, tgt_ref = el.get("sourceRef"), el.get("targetRef")
            style = {"sequenceFlow": SEQ_STYLE, "messageFlow": MSG_STYLE,
                     "association": ASSOC_STYLE}[tag]
        elif tag == "dataInputAssociation":
            s = el.find(q("bpmn", "sourceRef"))
            src_ref = s.text if s is not None else None
            tgt_ref = el.getparent().get("id")
            style = DATA_ASSOC_STYLE
        elif tag == "dataOutputAssociation":
            t = el.find(q("bpmn", "targetRef"))
            src_ref = el.getparent().get("id")
            tgt_ref = t.text if t is not None else None
            style = DATA_ASSOC_STYLE
        else:
            continue
        stroke = (colors.get(el.get("id")) or (None, None))[1]
        if stroke:
            style += "strokeColor=%s;" % stroke
        style += texts.get(el.get("id"), "")
        if src_ref not in shapes or tgt_ref not in shapes:
            continue
        attrs = {"id": el.get("id"), "label": html.escape(el.get("name", "") or "", quote=False)}
        obj = etree.SubElement(mroot, "object", **attrs)
        cell = etree.SubElement(obj, "mxCell", style=style, edge="1", parent="1",
                                source=src_ref, target=tgt_ref)
        geo = etree.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        if len(pts) > 2:
            arr = etree.SubElement(geo, "Array", **{"as": "points"})
            for x, y in pts[1:-1]:
                etree.SubElement(arr, "mxPoint", x="%g" % x, y="%g" % y)
    return etree.tostring(mxfile, pretty_print=True, encoding="UTF-8",
                          xml_declaration=True).decode("utf-8")


__all__ = ["bpmn_to_drawio", "ACTIVITY_TAGS"]
