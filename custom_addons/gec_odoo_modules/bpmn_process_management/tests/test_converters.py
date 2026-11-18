# Part of bpmn_process_management. License LGPL-3.
import os
from collections import Counter

from odoo.tests import BaseCase, tagged

from ..lib.bpmn_common import BpmnError, FLOW_NODE_TAGS, local, normalize_bpmn, parse_bpmn, q
from ..lib.bpmn_index import apply_responsible_matching, extract_elements
from ..lib.bpmn_stats import process_stats
from ..lib.drawio_export import bpmn_to_drawio
from ..lib.drawio_import import convert_drawio
from ..lib.visio_import import convert_visio

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
COUNTED = FLOW_NODE_TAGS | {"lane", "participant", "sequenceFlow", "messageFlow", "association",
                            "dataObjectReference", "dataStoreReference", "textAnnotation",
                            "dataInputAssociation", "dataOutputAssociation"}


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def census(xml):
    root = parse_bpmn(xml)
    return Counter(local(e.tag) for e in root.iter()
                   if isinstance(e.tag, str) and local(e.tag) in COUNTED)


def check_valid(test, xml):
    """Structural checks every generated diagram must pass."""
    root = parse_bpmn(xml)
    ids = [e.get("id") for e in root.iter() if isinstance(e.tag, str) and e.get("id")]
    test.assertEqual(len(ids), len(set(ids)), "duplicate ids")
    idset = set(ids)
    for e in root.iter():
        if not isinstance(e.tag, str):
            continue
        for attr in ("sourceRef", "targetRef", "processRef", "attachedToRef", "bpmnElement",
                     "dataObjectRef"):
            if e.get(attr):
                test.assertIn(e.get(attr), idset, "dangling %s=%s" % (attr, e.get(attr)))
    for proc in root.iter(q("bpmn", "process")):
        test.assertEqual(proc.get("isExecutable"), "false")
    di_refs = {e.get("bpmnElement") for e in root.iter(q("bpmndi", "BPMNShape"))}
    for e in root.iter():
        if isinstance(e.tag, str) and local(e.tag) in FLOW_NODE_TAGS | {"lane", "participant"}:
            test.assertIn(e.get("id"), di_refs)
    proc_of = {}
    for proc in root.iter(q("bpmn", "process")):
        for e in proc.iter():
            if isinstance(e.tag, str) and e.get("id"):
                proc_of[e.get("id")] = proc.get("id")
    for f in root.iter(q("bpmn", "sequenceFlow")):
        test.assertEqual(proc_of.get(f.get("sourceRef")), proc_of.get(f.get("targetRef")))
    return root


@tagged("post_install", "-at_install", "bpmn")
class TestDrawioImport(BaseCase):

    def test_bpmn_library_template(self):
        (page,) = convert_drawio(fixture("drawio_bpmn_template.drawio"))
        check_valid(self, page["xml"])
        c = census(page["xml"])
        root = parse_bpmn(page["xml"])
        self.assertEqual(c["startEvent"], 3)
        timers = root.findall(".//" + q("bpmn", "startEvent") + "/" + q("bpmn", "timerEventDefinition"))
        self.assertEqual(len(timers), 2)
        self.assertEqual(c["endEvent"], 1)
        self.assertEqual(c["parallelGateway"], 3)
        self.assertGreaterEqual(c["sequenceFlow"], 14)
        self.assertGreaterEqual(c["receiveTask"] + c["task"] + c["subProcess"], 9)

    def test_swimlanes_are_grouped_into_one_pool(self):
        (page,) = convert_drawio(fixture("drawio_swimlane_template.drawio"))
        root = check_valid(self, page["xml"])
        c = census(page["xml"])
        self.assertEqual(c["participant"], 1)
        self.assertEqual(c["lane"], 7)
        lanes = {ln.get("name") for ln in root.iter(q("bpmn", "lane"))}
        self.assertIn("Sales Admin", lanes)
        for ln in root.iter(q("bpmn", "lane")):
            self.assertEqual(ln.find(".//" + q("odoo", "review")).get("reason"), "responsible_missing")

    def test_cross_functional_flowchart(self):
        for name in ("drawio_cff1.drawio", "drawio_cff2.drawio"):
            (page,) = convert_drawio(fixture(name))
            check_valid(self, page["xml"])
            c = census(page["xml"])
            self.assertEqual(c["participant"], 1, name)
            self.assertGreaterEqual(c["lane"], 3, name)
            self.assertGreaterEqual(c["exclusiveGateway"], 1, name)

    def test_generic_flowchart(self):
        (page,) = convert_drawio(fixture("drawio_workflow1.drawio"))
        check_valid(self, page["xml"])
        c = census(page["xml"])
        self.assertGreaterEqual(c["exclusiveGateway"], 5)
        self.assertEqual(c["endEvent"], 1)
        self.assertGreaterEqual(c["sequenceFlow"], 20)

    def test_compressed_and_svg_and_png(self):
        import base64
        import urllib.parse
        import zlib
        from lxml import etree
        from ..lib.drawio_import import load_pages
        (_name, model_el), = load_pages(fixture("drawio_cff1.drawio"))
        model = etree.tostring(model_el, encoding="unicode")
        plain_file = '<mxfile><diagram name="P">%s</diagram></mxfile>' % model
        (plain,) = convert_drawio(plain_file)
        comp = zlib.compressobj(9, zlib.DEFLATED, -15)
        data = comp.compress(urllib.parse.quote(model).encode()) + comp.flush()
        compressed = '<mxfile><diagram name="P">%s</diagram></mxfile>' % base64.b64encode(data).decode()
        (page,) = convert_drawio(compressed)
        self.assertEqual(census(page["xml"]), census(plain["xml"]))
        from html import escape
        svg = '<svg xmlns="http://www.w3.org/2000/svg" content="%s"></svg>' % escape(compressed, quote=True)
        (page,) = convert_drawio(svg)
        self.assertEqual(census(page["xml"]), census(plain["xml"]))

    def test_svg_without_diagram(self):
        with self.assertRaises(BpmnError):
            convert_drawio('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    def test_rejects_xxe(self):
        evil = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
                '<mxfile><diagram name="a"><mxGraphModel><root><mxCell id="0"/>'
                '<mxCell id="1" parent="0"/><mxCell id="2" value="&e;" vertex="1" parent="1">'
                '<mxGeometry width="10" height="10" as="geometry"/></mxCell></root>'
                '</mxGraphModel></diagram></mxfile>')
        try:
            pages = convert_drawio(evil)
        except BpmnError:
            return
        self.assertNotIn("root:", pages[0]["xml"])


@tagged("post_install", "-at_install", "bpmn")
class TestVisioImport(BaseCase):

    def test_bpmn_template(self):
        (page,) = convert_visio(fixture("visio_bpmn_returns.vsdx"))
        root = check_valid(self, page["xml"])
        c = census(page["xml"])
        self.assertEqual(c["participant"], 1)
        self.assertEqual(c["lane"], 2)
        self.assertEqual(c["userTask"], 1)
        self.assertEqual(c["manualTask"], 1)
        self.assertEqual(c["serviceTask"], 1)
        self.assertEqual(c["boundaryEvent"], 1)
        self.assertEqual(c["startEvent"], 1)
        self.assertEqual(c["endEvent"], 2)
        self.assertEqual(c["sequenceFlow"], 7)
        self.assertEqual(c["dataOutputAssociation"], 1)
        self.assertEqual(c["association"], 1)
        start = root.find(".//" + q("bpmn", "startEvent"))
        self.assertIsNotNone(start.find(q("bpmn", "messageEventDefinition")))
        boundary = root.find(".//" + q("bpmn", "boundaryEvent"))
        self.assertIsNotNone(boundary.find(q("bpmn", "timerEventDefinition")))
        lanes = {ln.get("name"): {r.text for r in ln.findall(q("bpmn", "flowNodeRef"))}
                 for ln in root.iter(q("bpmn", "lane"))}
        names = {e.get("id"): e.get("name") for e in root.iter() if isinstance(e.tag, str)}
        self.assertIn("Inspect product", {names[i] for i in lanes["Warehouse"]})
        self.assertIn("Register return request", {names[i] for i in lanes["Sales"]})

    def test_legacy_vsd_is_refused_with_advice(self):
        with self.assertRaisesRegex(BpmnError, "vsdx"):
            convert_visio(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)

    def test_not_a_zip(self):
        with self.assertRaises(BpmnError):
            convert_visio(b"hello")


@tagged("post_install", "-at_install", "bpmn")
class TestRoundTrip(BaseCase):

    def test_drawio_round_trip_keeps_elements(self):
        for source in (convert_visio(fixture("visio_bpmn_returns.vsdx"))[0]["xml"],
                       convert_drawio(fixture("drawio_bpmn_template.drawio"))[0]["xml"],
                       convert_drawio(fixture("drawio_cff1.drawio"))[0]["xml"]):
            back = convert_drawio(bpmn_to_drawio(source))[0]["xml"]
            check_valid(self, back)
            self.assertEqual(census(source), census(back))

    def test_colors_round_trip(self):
        src = (b'<mxfile><diagram id="a" name="P"><mxGraphModel><root><mxCell id="0"/>'
               b'<mxCell id="1" parent="0"/>'
               b'<mxCell id="2" value="Check order" style="rounded=1;whiteSpace=wrap;html=1;'
               b'fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">'
               b'<mxGeometry x="100" y="100" width="120" height="60" as="geometry"/></mxCell>'
               b'<mxCell id="3" value="Ship" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;'
               b'strokeColor=#000000;" vertex="1" parent="1">'
               b'<mxGeometry x="300" y="100" width="120" height="60" as="geometry"/></mxCell>'
               b'<mxCell id="4" style="edgeStyle=orthogonalEdgeStyle;strokeColor=#F00;" edge="1" parent="1" '
               b'source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell>'
               b'</root></mxGraphModel></diagram></mxfile>')
        xml = convert_drawio(src)[0]["xml"]
        check_valid(self, xml)
        root = parse_bpmn(xml)
        shapes = root.findall(".//" + q("bpmndi", "BPMNShape"))
        colored = [sh for sh in shapes if sh.get(q("color", "background-color"))]
        self.assertEqual(len(colored), 1)  # white/black defaults are not copied
        self.assertEqual(colored[0].get(q("color", "background-color")), "#DAE8FC")
        self.assertEqual(colored[0].get(q("bioc", "stroke")), "#6C8EBF")
        edge = root.find(".//" + q("bpmndi", "BPMNEdge"))
        self.assertEqual(edge.get(q("color", "border-color")), "#FF0000")
        back = bpmn_to_drawio(xml)
        self.assertIn("fillColor=#DAE8FC", back)
        self.assertIn("strokeColor=#FF0000", back)

    def test_process_stats(self):
        st = process_stats(convert_visio(fixture("visio_bpmn_returns.vsdx"))[0]["xml"])
        self.assertEqual((st["steps"], st["decisions"], st["lanes"]), (3, 1, 2))
        self.assertEqual(sorted(st["handoffs"]), [("name:sales", "name:warehouse"),
                                                  ("name:warehouse", "name:sales")])
        self.assertEqual(st["roles"]["name:sales"]["steps"], 2)
        st = process_stats(convert_drawio(fixture("drawio_cff1.drawio"))[0]["xml"])
        self.assertEqual(st["lanes"], 6)
        self.assertGreater(len(st["handoffs"]), 5)

    def test_normalize_forces_not_executable(self):
        xml = ('<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">'
               '<bpmn:process id="P" isExecutable="true"/></bpmn:definitions>')
        self.assertIn('isExecutable="false"', normalize_bpmn(xml))
        same = normalize_bpmn(normalize_bpmn(xml))
        self.assertEqual(same, normalize_bpmn(xml))

    def test_not_bpmn(self):
        with self.assertRaises(BpmnError):
            normalize_bpmn("<html/>")

    def test_index_and_matching(self):
        xml = convert_visio(fixture("visio_bpmn_returns.vsdx"))[0]["xml"]
        xml, matched, missing = apply_responsible_matching(
            xml, lambda n: {"model": "hr.department", "resId": 7, "name": n} if n == "Sales" else None)
        self.assertEqual((matched, missing), (1, 1))
        items = {i["name"]: i for i in extract_elements(xml)}
        self.assertEqual(items["Sales"]["responsible"]["resId"], 7)
        self.assertEqual(items["Sales"]["review"]["reason"], "responsible_auto")
        self.assertEqual(items["Warehouse"]["review"]["reason"], "responsible_missing")
        self.assertEqual(items["Register return request"]["lane_name"], "Sales")
        self.assertTrue(items["Register return request"]["responsible"]["inherited"])


@tagged("post_install", "-at_install", "bpmn")
class TestMarkersAndGroups(BaseCase):

    def _drawio(self, cells):
        return ('<mxfile><diagram name="m"><mxGraphModel><root><mxCell id="0"/>'
                '<mxCell id="1" parent="0"/>%s</root></mxGraphModel></diagram></mxfile>' % cells)

    def test_loop_markers_group_adhoc(self):
        task = ("shape=mxgraph.bpmn.task2;whiteSpace=wrap;rectStyle=rounded;size=10;html=1;"
                "container=1;expand=0;collapsible=0;")

        def cell(i, style, x, w=120, h=80, val="T"):
            return ('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                    '<mxGeometry x="%s" y="100" width="%s" height="%s" as="geometry"/></mxCell>'
                    % (i, val, style, x, w, h))
        cells = "".join([
            cell("a", task + "taskMarker=user;isLoopStandard=1;", 100),
            cell("b", task + "taskMarker=service;isLoopMultiParallel=1;", 300),
            cell("c", task + "taskMarker=abstract;isLoopMultiSeq=1;isLoopComp=1;", 500),
            cell("d", task + "taskMarker=abstract;isAdHoc=1;isLoopSub=1;", 700),
            cell("g", "rounded=1;dashed=1;dashPattern=5 2 1 2;html=1;", 80, 560, 140, "Team"),
        ])
        (page,) = convert_drawio(self._drawio(cells))
        root = check_valid(self, page["xml"])
        self.assertIsNotNone(root.find(".//" + q("bpmn", "userTask") + "/" + q("bpmn", "standardLoopCharacteristics")))
        mis = root.findall(".//" + q("bpmn", "multiInstanceLoopCharacteristics"))
        self.assertEqual(sorted(m.get("isSequential") or "false" for m in mis), ["false", "true"])
        self.assertEqual(len(root.findall(".//*[@isForCompensation='true']")), 1)
        self.assertEqual(len(root.findall(".//" + q("bpmn", "adHocSubProcess"))), 1)
        group = root.find(".//" + q("bpmn", "group"))
        cv = root.find(".//" + q("bpmn", "categoryValue"))
        self.assertEqual(group.get("categoryValueRef"), cv.get("id"))
        self.assertEqual(cv.get("value"), "Team")
        back = convert_drawio(bpmn_to_drawio(page["xml"]))[0]["xml"]
        self.assertEqual(census(back), census(page["xml"]))
        self.assertIn("categoryValue", back)
        self.assertIn("standardLoopCharacteristics", back)


@tagged("post_install", "-at_install", "bpmn")
class TestHostileInput(BaseCase):

    def _page(self, cells):
        return ('<mxfile><diagram name="m"><mxGraphModel><root><mxCell id="0"/>'
                '<mxCell id="1" parent="0"/>%s</root></mxGraphModel></diagram></mxfile>' % cells)

    def test_parent_cycles_do_not_hang(self):
        cells = ('<mxCell id="a" style="group" vertex="1" parent="b"><mxGeometry width="10" height="10" as="geometry"/></mxCell>'
                 '<mxCell id="b" style="group" vertex="1" parent="a"><mxGeometry width="10" height="10" as="geometry"/></mxCell>'
                 '<mxCell id="c" value="x" vertex="1" parent="d"><mxGeometry width="50" height="40" as="geometry"/></mxCell>'
                 '<mxCell id="d" value="y" vertex="1" parent="c"><mxGeometry x="100" width="50" height="40" as="geometry"/></mxCell>'
                 '<mxCell id="e" edge="1" parent="1" source="c" target="d"><mxGeometry relative="1" as="geometry"/></mxCell>')
        pages = convert_drawio(self._page(cells))
        check_valid(self, pages[0]["xml"])

    def test_non_finite_coordinates(self):
        cells = ('<mxCell id="a" value="A" vertex="1" parent="1"><mxGeometry x="NaN" y="inf" width="80" height="40" as="geometry"/></mxCell>'
                 '<mxCell id="b" value="B" vertex="1" parent="1"><mxGeometry x="200" width="-inf" height="40" as="geometry"/></mxCell>'
                 '<mxCell id="e" edge="1" parent="1" source="a" target="b"><mxGeometry relative="1" as="geometry"/></mxCell>')
        check_valid(self, convert_drawio(self._page(cells))[0]["xml"])

    def test_decompression_bomb(self):
        import base64
        import zlib
        comp = zlib.compressobj(9, zlib.DEFLATED, -15)
        bomb = comp.compress(b"<" + b"a" * (60 * 1024 * 1024)) + comp.flush()
        data = '<mxfile><diagram name="p">%s</diagram></mxfile>' % base64.b64encode(bomb).decode()
        with self.assertRaises(BpmnError):
            convert_drawio(data)

    def test_url_whitelist(self):
        from ..lib.bpmn_common import is_safe_url
        for ok in ("https://odoo.com", "/odoo/action-1", "mailto:a@b.ge"):
            self.assertTrue(is_safe_url(ok), ok)
        for bad in ("javascript:alert(1)", "//evil.com", "/\\evil.com", "/\t/evil.com",
                    "data:text/html,x", "https:evil"):
            self.assertFalse(is_safe_url(bad), bad)

    def test_export_without_layout(self):
        xml = ('<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">'
               '<bpmn:process id="P" isExecutable="false"><bpmn:task id="T"/></bpmn:process>'
               '</bpmn:definitions>')
        with self.assertRaises(BpmnError):
            bpmn_to_drawio(xml)
