"""Generate ``visio_bpmn_returns.vsdx``, a Visio package like the BPMN and Cross-Functional templates (test fixture).
Run: python3 make_visio_fixture.py"""
import os
import zipfile

V = "http://schemas.microsoft.com/office/visio/2012/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

MASTERS = [
    # id, NameU, width, height, geometry, default props
    ("1", "CFF Container", 10, 5, "rect", {}),
    ("2", "Swimlane", 9.7, 2.5, "rect", {}),
    ("3", "Start Event", 0.4, 0.4, "ellipse", {"BpmnEventType": "Start", "BpmnTriggerOrResult": "None"}),
    ("4", "Task", 1.2, 0.8, "rect", {"BpmnTaskType": "None"}),
    ("5", "Gateway", 0.6, 0.6, "rhombus", {"BpmnGatewayType": "Exclusive"}),
    ("6", "Intermediate Event", 0.35, 0.35, "ellipse",
     {"BpmnEventType": "Intermediate", "BpmnTriggerOrResult": "None"}),
    ("7", "End Event", 0.4, 0.4, "ellipse", {"BpmnEventType": "End", "BpmnTriggerOrResult": "None"}),
    ("8", "Data Object", 0.4, 0.55, "rect", {}),
    ("9", "Text Annotation", 1.4, 0.4, "rect", {}),
    ("10", "Sequence Flow", 1, 0, "line", {}),
    ("11", "Association", 1, 0, "line", {}),
]


def geometry(kind):
    if kind == "ellipse":
        return ("<Section N='Geometry' IX='0'><Row T='Ellipse' IX='1'><Cell N='X' V='0.5'/>"
                "<Cell N='Y' V='0.5'/><Cell N='A' V='1'/><Cell N='B' V='0.5'/>"
                "<Cell N='C' V='0.5'/><Cell N='D' V='1'/></Row></Section>")
    if kind == "rhombus":
        pts = [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5), (0.5, 0)]
    elif kind == "line":
        return ""
    else:
        pts = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    rows = "".join("<Row T='%s' IX='%d'><Cell N='X' V='%s'/><Cell N='Y' V='%s'/></Row>"
                   % ("RelMoveTo" if i == 0 else "RelLineTo", i + 1, x, y)
                   for i, (x, y) in enumerate(pts))
    return "<Section N='Geometry' IX='0'>%s</Section>" % rows


def props(d):
    if not d:
        return ""
    rows = "".join("<Row N='%s'><Cell N='Value' V='%s' U='STR'/><Cell N='Label' V='%s'/></Row>"
                   % (k, v, k) for k, v in d.items())
    return "<Section N='Property'>%s</Section>" % rows


def master_xml(mid, name, w, h, geo, dprops):
    one_d = geo == "line"
    cells = ("<Cell N='PinX' V='0.5'/><Cell N='PinY' V='0.5'/>"
             "<Cell N='Width' V='%s'/><Cell N='Height' V='%s'/>"
             "<Cell N='LocPinX' V='%s' F='Width*0.5'/><Cell N='LocPinY' V='%s' F='Height*0.5'/>"
             % (w, h, w / 2, h / 2))
    if one_d:
        cells += ("<Cell N='BeginX' V='0'/><Cell N='BeginY' V='0'/><Cell N='EndX' V='1'/>"
                  "<Cell N='EndY' V='0'/><Cell N='ObjType' V='2'/>")
        if name == "Association":
            cells += "<Cell N='LinePattern' V='3'/>"
    return ("<?xml version='1.0' encoding='utf-8' ?><MasterContents xmlns='%s' xmlns:r='%s' "
            "xml:space='preserve'><Shapes><Shape ID='5' Type='Shape'>%s%s%s</Shape></Shapes>"
            "</MasterContents>" % (V, R, cells, props(dprops), geometry(geo)))


SHAPES = [
    # id, master, pinx, piny, w, h, text, props
    ("1", "1", 5.5, 5.0, 10, 5, "Returns handling", {}),
    ("2", "2", 5.65, 6.25, 9.7, 2.5, "Sales", {}),
    ("3", "2", 5.65, 3.75, 9.7, 2.5, "Warehouse", {}),
    ("10", "3", 1.5, 6.25, None, None, "Return requested", {"BpmnTriggerOrResult": "Message"}),
    ("11", "4", 3.0, 6.25, None, None, "Register return request", {"BpmnTaskType": "User"}),
    ("12", "5", 4.8, 6.25, None, None, "Inspection needed?", {}),
    ("13", "4", 4.8, 3.75, None, None, "Inspect product", {"BpmnTaskType": "Manual"}),
    ("14", "6", 5.2, 3.35, None, None, "2 days", {"BpmnTriggerOrResult": "Timer"}),
    ("15", "4", 6.6, 6.25, None, None, "Refund customer", {"BpmnTaskType": "Service"}),
    ("16", "7", 8.0, 6.25, None, None, "Return closed", {}),
    ("17", "7", 7.0, 3.0, None, None, "Escalated", {"BpmnTriggerOrResult": "Escalation"}),
    ("18", "8", 3.0, 4.0, None, None, "Return form", {}),
    ("19", "9", 1.5, 7.2, None, None, "Within 14 days of delivery", {}),
]
CONNECTORS = [
    # id, master, from, to, text
    ("30", "10", "10", "11", ""),
    ("31", "10", "11", "12", ""),
    ("32", "10", "12", "13", "Yes"),
    ("33", "10", "12", "15", "No"),
    ("34", "10", "13", "15", ""),
    ("35", "10", "15", "16", ""),
    ("36", "10", "14", "17", ""),
    ("37", "11", "11", "18", ""),
    ("38", "11", "19", "10", ""),
]


def page_xml():
    pos = {s[0]: s for s in SHAPES}
    out = []
    for sid, mid, px, py, w, h, text, pr in SHAPES:
        cells = "<Cell N='PinX' V='%s'/><Cell N='PinY' V='%s'/>" % (px, py)
        if w is not None:
            cells += "<Cell N='Width' V='%s'/><Cell N='Height' V='%s'/>" % (w, h)
            cells += "<Cell N='LocPinX' V='%s'/><Cell N='LocPinY' V='%s'/>" % (w / 2, h / 2)
        user = ""
        if mid in ("1", "2"):
            user = ("<Section N='User'><Row N='msvStructureType'><Cell N='Value' V='Container' "
                    "U='STR'/></Row><Row N='msvShapeCategories'><Cell N='Value' V='%s' U='STR'/>"
                    "</Row></Section>" % ("CFF Container" if mid == "1" else "Swimlane"))
        out.append("<Shape ID='%s' NameU='%s.%s' Type='Shape' Master='%s'>%s%s%s<Text>%s</Text></Shape>"
                   % (sid, dict((m[0], m[1]) for m in MASTERS)[mid], sid, mid, cells, props(pr),
                      user, text))
    connects = []
    for cid, mid, a, b, text in CONNECTORS:
        sa, sb = pos[a], pos[b]
        cells = ("<Cell N='BeginX' V='%s'/><Cell N='BeginY' V='%s'/><Cell N='EndX' V='%s'/>"
                 "<Cell N='EndY' V='%s'/>" % (sa[2], sa[3], sb[2], sb[3]))
        cells += "<Cell N='PinX' V='%s'/><Cell N='PinY' V='%s'/>" % ((sa[2] + sb[2]) / 2, (sa[3] + sb[3]) / 2)
        out.append("<Shape ID='%s' NameU='%s.%s' Type='Shape' Master='%s'>%s<Text>%s</Text></Shape>"
                   % (cid, dict((m[0], m[1]) for m in MASTERS)[mid], cid, mid, cells, text))
        connects.append("<Connect FromSheet='%s' FromCell='BeginX' FromPart='9' ToSheet='%s' "
                        "ToCell='PinX' ToPart='3'/>" % (cid, a))
        connects.append("<Connect FromSheet='%s' FromCell='EndX' FromPart='12' ToSheet='%s' "
                        "ToCell='PinX' ToPart='3'/>" % (cid, b))
    return ("<?xml version='1.0' encoding='utf-8' ?><PageContents xmlns='%s' xmlns:r='%s' "
            "xml:space='preserve'><Shapes>%s</Shapes><Connects>%s</Connects></PageContents>"
            % (V, R, "".join(out), "".join(connects)))


def build(path):
    ct = ("<?xml version='1.0' encoding='utf-8' standalone='yes'?>"
          "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
          "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
          "<Default Extension='xml' ContentType='application/xml'/>"
          "<Override PartName='/visio/document.xml' ContentType='application/vnd.ms-visio.drawing.main+xml'/>"
          "<Override PartName='/visio/pages/pages.xml' ContentType='application/vnd.ms-visio.pages+xml'/>"
          "<Override PartName='/visio/pages/page1.xml' ContentType='application/vnd.ms-visio.page+xml'/>"
          "<Override PartName='/visio/masters/masters.xml' ContentType='application/vnd.ms-visio.masters+xml'/>"
          + "".join("<Override PartName='/visio/masters/master%s.xml' "
                    "ContentType='application/vnd.ms-visio.master+xml'/>" % m[0] for m in MASTERS)
          + "</Types>")
    rels = ("<?xml version='1.0' encoding='utf-8' standalone='yes'?><Relationships "
            "xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
            "<Relationship Id='rId1' Type='http://schemas.microsoft.com/visio/2010/relationships/document' "
            "Target='visio/document.xml'/></Relationships>")
    doc = ("<?xml version='1.0' encoding='utf-8' ?><VisioDocument xmlns='%s' xmlns:r='%s' "
           "xml:space='preserve'><DocumentSettings/></VisioDocument>" % (V, R))
    doc_rels = ("<?xml version='1.0' encoding='utf-8' standalone='yes'?><Relationships "
                "xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                "<Relationship Id='rId1' Type='http://schemas.microsoft.com/visio/2010/relationships/masters' Target='masters/masters.xml'/>"
                "<Relationship Id='rId2' Type='http://schemas.microsoft.com/visio/2010/relationships/pages' Target='pages/pages.xml'/>"
                "</Relationships>")
    pages = ("<?xml version='1.0' encoding='utf-8' ?><Pages xmlns='%s' xmlns:r='%s' xml:space='preserve'>"
             "<Page ID='0' NameU='Returns' Name='Returns'><PageSheet><Cell N='PageWidth' V='11'/>"
             "<Cell N='PageHeight' V='8.5'/></PageSheet><Rel r:id='rId1'/></Page></Pages>" % (V, R))
    pages_rels = ("<?xml version='1.0' encoding='utf-8' standalone='yes'?><Relationships "
                  "xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                  "<Relationship Id='rId1' Type='http://schemas.microsoft.com/visio/2010/relationships/page' "
                  "Target='page1.xml'/></Relationships>")
    masters = ("<?xml version='1.0' encoding='utf-8' ?><Masters xmlns='%s' xmlns:r='%s' xml:space='preserve'>"
               % (V, R) + "".join("<Master ID='%s' NameU='%s' Name='%s'><PageSheet/><Rel r:id='rId%s'/></Master>"
                                   % (m[0], m[1], m[1], m[0]) for m in MASTERS) + "</Masters>")
    masters_rels = ("<?xml version='1.0' encoding='utf-8' standalone='yes'?><Relationships "
                    "xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                    + "".join("<Relationship Id='rId%s' Type='http://schemas.microsoft.com/visio/2010/relationships/master' "
                              "Target='master%s.xml'/>" % (m[0], m[0]) for m in MASTERS)
                    + "</Relationships>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("visio/document.xml", doc)
        z.writestr("visio/_rels/document.xml.rels", doc_rels)
        z.writestr("visio/pages/pages.xml", pages)
        z.writestr("visio/pages/_rels/pages.xml.rels", pages_rels)
        z.writestr("visio/pages/page1.xml", page_xml())
        z.writestr("visio/masters/masters.xml", masters)
        z.writestr("visio/masters/_rels/masters.xml.rels", masters_rels)
        for m in MASTERS:
            z.writestr("visio/masters/master%s.xml" % m[0], master_xml(*m))


if __name__ == "__main__":
    build(os.path.join(os.path.dirname(os.path.abspath(__file__)), "visio_bpmn_returns.vsdx"))
