# Part of bpmn_process_management. License LGPL-3.
"""Demo processes (Georgian) that exercise every feature of the module.
Pure Python: :func:`build_demo_xml` turns a scenario from :data:`SCENARIOS` into BPMN 2.0 XML,
with Odoo responsibles and links from ``refs`` (filled in ``models/business_process_demo.py``)."""
from lxml import etree

from .bpmn_builder import Box, Diagram, Edge, Lane, Node, Pool, build_bpmn
from .bpmn_common import (
    add_odoo_link, parse_bpmn, q, remove_odoo_item, set_odoo_item, to_string,
)

X0, Y0 = 40, 40
LANE_H = 170
COL_W = 150
SIZES = {
    "event": (36, 36), "gateway": (50, 50), "task": (110, 80),
    "dataObjectReference": (36, 50), "dataStoreReference": (50, 50), "textAnnotation": (150, 56),
}
EVENT_TAGS = {"startEvent", "endEvent", "intermediateThrowEvent", "intermediateCatchEvent", "boundaryEvent"}
GATEWAY_TAGS = {"exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway", "complexGateway"}

ORANGE = ("#fde7dd", "#b8431c")
YELLOW = ("#fdf3d3", "#8a6a00")
TEAL = ("#dcf2ec", "#036b54")
BLUE = ("#e1ecf7", "#1f5f99")


def _size(kind):
    if kind in EVENT_TAGS:
        return SIZES["event"]
    if kind in GATEWAY_TAGS:
        return SIZES["gateway"]
    return SIZES.get(kind, SIZES["task"])


class Sketch:
    """Grid layout: lanes are rows, ``col`` is a column (floats allowed)."""

    def __init__(self, name):
        self.d = Diagram(name)
        self.lane_rows = {}   # lane id -> (pool id, row index)
        self.pool_top = {}
        self.next_y = Y0
        self.flows = {}       # our edge id -> Edge
        self.extras = {"responsible": {}, "links": {}, "review": {}, "conditions": {},
                       "defaults": {}, "collapsed": set(), "notes": {}}

    def pool(self, pid, name, lanes, width_cols):
        width = (width_cols + 1) * COL_W
        if not lanes:
            self.d.pools[pid] = Pool(pid, name, Box(X0, self.next_y, width + 30, 70))
            self.extras["collapsed"].add(pid)
            self.next_y += 70 + 40
            return
        top = self.next_y
        self.d.pools[pid] = Pool(pid, name, Box(X0, top, width + 30, LANE_H * len(lanes)))
        for i, (lid, lname) in enumerate(lanes):
            self.d.lanes[lid] = Lane(lid, lname, Box(X0 + 30, top + i * LANE_H, width, LANE_H), pool=pid)
            self.lane_rows[lid] = (pid, i, top)
        self.next_y = top + LANE_H * len(lanes) + 40

    def node(self, nid, kind, name, lane, col, dy=0, **kw):
        w, h = _size(kind)
        if lane is None:
            cy = Y0 + 80 + dy
        else:
            _pid, row, top = self.lane_rows[lane]
            cy = top + row * LANE_H + LANE_H / 2 + dy
        cx = X0 + 30 + 70 + col * COL_W
        n = Node(nid, kind, name, Box(cx - w / 2, cy - h / 2, w, h), **kw)
        color = kw.get("color")
        if color:
            n.fill, n.stroke = color
        self.d.add_node(n)
        return n

    def boundary(self, nid, host, name, event_def="timer", interrupting=True):
        hb = self.d.nodes[host].box
        w, h = SIZES["event"]
        box = Box(hb.right - 28 - w / 2, hb.bottom - h / 2, w, h)
        n = Node(nid, "boundaryEvent", name, box, event_def=event_def, attached_to=host,
                 cancel_activity=interrupting)
        self.d.add_node(n)
        return n

    def flow(self, fid, source, target, name="", kind="auto", condition=None, default=False):
        e = Edge(fid, source, target, name, kind=kind)
        self.d.edges.append(e)
        self.flows[fid] = e
        if condition:
            self.extras["conditions"][fid] = condition
        if default:
            self.extras["defaults"][fid] = source
        return e

    def responsible(self, lane, ref, note="", sync=True):
        if ref:
            self.extras["responsible"][lane] = dict(ref, note=note, sync=sync)

    def link(self, nid, link):
        if link:
            self.extras["links"].setdefault(nid, []).append(link)

    def review(self, nid, reason, note=""):
        self.extras["review"][nid] = (reason, note)

    def to_xml(self):
        xml, _warnings = build_bpmn(self.d, source="demo")
        root = parse_bpmn(xml.encode())
        by_id = {el.get("id"): el for el in root.iter() if isinstance(el.tag, str) and el.get("id")}
        ids = {}
        for n in self.d.nodes.values():
            ids[n.src_id] = n.bpmn_id
        for ln in self.d.lanes.values():
            ids[ln.src_id] = ln.bpmn_id
        for p in self.d.pools.values():
            ids[p.src_id] = p.bpmn_id
        for fid, e in self.flows.items():
            ids[fid] = e.bpmn_id

        # responsibles (the builder flags every lane "responsible missing")
        for lane in self.d.lanes.values():
            el = by_id[lane.bpmn_id]
            ref = self.extras["responsible"].get(lane.src_id)
            if not ref:
                continue
            remove_odoo_item(el, "review")
            set_odoo_item(el, "responsible", {
                "model": ref["model"], "resId": ref.get("resId"), "xmlid": ref.get("xmlid"),
                "name": ref.get("name"), "note": ref.get("note"),
                "syncName": "true" if ref.get("sync") else None,
            })
        for nid, links in self.extras["links"].items():
            el = by_id[ids[nid]]
            for link in links:
                add_odoo_link(el, link)
        for nid, (reason, note) in self.extras["review"].items():
            set_odoo_item(by_id[ids[nid]], "review",
                          {"status": "pending", "reason": reason, "source": "demo", "note": note})
        for fid, text in self.extras["conditions"].items():
            el = by_id[ids[fid]]
            cond = etree.SubElement(el, q("bpmn", "conditionExpression"))
            cond.set("{http://www.w3.org/2001/XMLSchema-instance}type", "bpmn:tFormalExpression")
            cond.text = text
        for fid, source in self.extras["defaults"].items():
            by_id[ids[source]].set("default", ids[fid])
        # black box pools: no process behind them, drawn collapsed
        for pid in self.extras["collapsed"]:
            part = by_id[ids[pid]]
            remove_odoo_item(part, "review")
            ext = part.find(q("bpmn", "extensionElements"))
            if ext is not None and not len(ext):
                part.remove(ext)
            proc_id = part.attrib.pop("processRef", None)
            if proc_id and proc_id in by_id:
                proc = by_id[proc_id]
                proc.getparent().remove(proc)
            for shape in root.iter(q("bpmndi", "BPMNShape")):
                if shape.get("bpmnElement") == part.get("id"):
                    shape.set("isExpanded", "false")
        return to_string(root)


# Scenarios. Each function receives ``r`` (resolved Odoo references): r["role"][key] -> responsible dict
# {model, resId, xmlid, name} or None; r["link"][key] -> link dict (odoo:Link attributes) or None

def purchase_request(r, draft=False):
    s = Sketch("შესყიდვის მოთხოვნა")
    s.pool("P", "შესყიდვის მოთხოვნა", [
        ("L_req", "მოთხოვნის ავტორი"), ("L_mgr", "ხელმძღვანელი"),
        ("L_proc", "შესყიდვები"), ("L_fin", "ფინანსები"),
    ], 11)
    s.pool("P_sup", "მომწოდებელი", [], 11)
    s.responsible("L_req", r["role"]["employee"], "ნებისმიერი თანამშრომელი, ვისაც საქონელი ან მომსახურება სჭირდება")
    s.responsible("L_mgr", r["role"]["management"], "5000 ₾-ზე მეტ შესყიდვას ამტკიცებს ფინანსური დირექტორი")
    s.responsible("L_proc", r["role"]["purchase"])
    # L_fin is left without responsible on purpose: it appears in the review queue

    s.node("start", "startEvent", "საჭიროება გაჩნდა", "L_req", 0)
    t1 = s.node("fill", "userTask", "მოთხოვნის შევსება", "L_req", 1, documentation=(
        "შეავსეთ შესყიდვის მოთხოვნის ფორმა 1 სამუშაო დღეში.\n"
        "- მიუთითეთ საქონელი ან მომსახურება, რაოდენობა და სასურველი ვადა\n"
        "- დაურთეთ ტექნიკური მოთხოვნები, თუ არსებობს\n"
        "- მიუთითეთ ხარჯის ცენტრი"))
    s.link("fill", r["link"].get("form"))
    s.link("fill", r["link"].get("policy_article"))
    s.link("fill", r["link"]["discuss"])
    s.link("fill", {"linkType": "url", "url": "https://www.matsne.gov.ge",
                    "label": "საქართველოს კანონმდებლობა (მაცნე)"})
    s.node("req_doc", "dataObjectReference", "შესყიდვის მოთხოვნა", "L_req", 1.75, dy=52)
    s.flow("f_doc", "fill", "req_doc")
    s.node("amount", "exclusiveGateway", "თანხა 5000 ₾-ზე მეტია?", "L_req", 2.5, color=YELLOW)
    s.node("note", "textAnnotation", "5000 ₾-მდე შესყიდვა დამტკიცების გარეშე გრძელდება", "L_req", 3.6, dy=-42)
    s.flow("f_note", "note", "amount")
    s.node("approve", "userTask", "ხელმძღვანელის დამტკიცება", "L_mgr", 3.5, color=ORANGE, documentation=(
        "შეამოწმეთ, არის თუ არა ხარჯი ბიუჯეტში.\n"
        "1. დაამტკიცეთ ან დააბრუნეთ მოთხოვნა კომენტარით\n"
        "2. ვადა: 2 სამუშაო დღე — შემდეგ მოთხოვნა ავტომატურად ესკალირდება"))
    s.boundary("timer", "approve", "2 სამუშაო დღე")
    s.node("escalated", "endEvent", "ესკალაცია დირექტორთან", "L_mgr", 4.3, dy=58, event_def="escalation")
    s.node("approved", "exclusiveGateway", "დამტკიცდა?", "L_mgr", 5)
    s.node("rejected", "endEvent", "მოთხოვნა უარყოფილია", "L_mgr", 6.2)
    s.node("quotes", "sendTask", "შეთავაზებების მოთხოვნა", "L_proc", 5.5, loop="parallel", documentation=(
        "მოითხოვეთ შეთავაზება მინიმუმ 3 მომწოდებლისგან (თითოეულს ერთდროულად)."))
    s.node("receive", "receiveTask", "შეთავაზებების მიღება", "L_proc", 6.6)
    s.node("choose", "businessRuleTask", "მომწოდებლის შერჩევა", "L_proc", 7.7, color=TEAL, documentation=(
        "შეარჩიეთ მომწოდებელი: ფასი 60%, მიწოდების ვადა 25%, ხარისხი 15%."))
    s.node("po", "serviceTask", "შესყიდვის შეკვეთის შექმნა Odoo-ში", "L_proc", 8.8)
    s.link("po", r["link"]["discuss"])
    s.node("store", "dataStoreReference", "Odoo: შესყიდვები", "L_proc", 8.8, dy=62)
    s.flow("f_store", "po", "store")
    s.node("pay", "callActivity", "მომწოდებლის ინვოისის გადახდა", "L_fin", 9.9, color=BLUE)
    s.link("pay", r["link"].get("proc_invoice"))
    s.node("end", "endEvent", "შესყიდვა დასრულდა", "L_fin", 11)

    s.flow("f1", "start", "fill")
    s.flow("f2", "fill", "amount")
    s.flow("f3", "amount", "approve", "კი", condition="თანხა > 5000 ₾")
    s.flow("f4", "amount", "quotes", "არა", default=True)
    s.flow("f5", "approve", "approved")
    s.flow("f6", "timer", "escalated")
    s.flow("f7", "approved", "quotes", "კი", default=True)
    s.flow("f8", "approved", "rejected", "არა", condition="უარყოფილია")
    s.flow("f9", "quotes", "P_sup", "შეთავაზების მოთხოვნა")
    s.flow("f10", "P_sup", "receive", "შეთავაზება")
    s.flow("f11", "quotes", "receive")
    s.flow("f12", "receive", "choose")
    s.flow("f13", "choose", "po")
    s.flow("f14", "po", "pay")
    s.flow("f15", "pay", "end")
    if draft:
        # the next version being prepared: an outdated menu link to fix
        s.link("choose", {"linkType": "menu", "xmlid": "bpmn_process_management_demo.removed_menu",
                          "label": "შეფასების ძველი ცხრილი"})
        s.review("choose", "link_broken", "ძველი მენიუ წაიშალა: მიაბით ახალი ეკრანი ან წაშალეთ ბმული")
    return s.to_xml()


def onboarding(r):
    s = Sketch("ახალი თანამშრომლის მიღება")
    s.pool("P", "ახალი თანამშრომლის მიღება", [
        ("L_hr", "ადამიანური რესურსები"), ("L_mgr", "უშუალო ხელმძღვანელი"), ("L_it", "IT"),
    ], 9)
    s.responsible("L_hr", r["role"]["hr"])
    s.responsible("L_mgr", r["role"]["management"], "ახალი თანამშრომლის უშუალო ხელმძღვანელი")
    s.responsible("L_it", r["role"]["it"])
    s.node("start", "startEvent", "შრომითი ხელშეკრულება გაფორმდა", "L_hr", 0)
    s.node("docs", "userTask", "დოკუმენტების შეგროვება", "L_hr", 1, loop="sequential", documentation=(
        "თითოეული დოკუმენტი მიიღეთ და შეამოწმეთ რიგრიგობით:\n"
        "- პირადობის მოწმობის ასლი\n- საბანკო რეკვიზიტები\n- განათლების დამადასტურებელი დოკუმენტი"))
    s.link("docs", {"linkType": "url", "url": "https://www.matsne.gov.ge",
                    "label": "საქართველოს შრომის კოდექსი (მაცნე)"})
    s.node("split", "parallelGateway", "", "L_hr", 2)
    s.node("access", "callActivity", "IT წვდომის მინიჭება", "L_it", 3, color=BLUE)
    s.link("access", r["link"].get("proc_access"))
    s.node("desk", "manualTask", "სამუშაო ადგილის მომზადება", "L_mgr", 3)
    s.node("join", "parallelGateway", "", "L_hr", 4)
    s.node("day1", "userTask", "პირველი დღის შეხვედრა", "L_mgr", 5)
    s.node("wait", "intermediateCatchEvent", "3 თვე", "L_mgr", 6, event_def="timer")
    s.node("probation", "userTask", "გამოსაცდელი ვადის შეფასება", "L_mgr", 7, color=ORANGE)
    s.node("end", "endEvent", "თანამშრომელი მიღებულია", "L_hr", 8.5)
    s.flow("f1", "start", "docs")
    s.flow("f2", "docs", "split")
    s.flow("f3", "split", "access")
    s.flow("f4", "split", "desk")
    s.flow("f5", "access", "join")
    s.flow("f6", "desk", "join")
    s.flow("f7", "join", "day1")
    s.flow("f8", "day1", "wait")
    s.flow("f9", "wait", "probation")
    s.flow("f10", "probation", "end")
    return s.to_xml()


def it_access(r):
    s = Sketch("IT წვდომის მინიჭება")
    s.pool("P", "IT წვდომის მინიჭება", [("L_it", "IT მხარდაჭერა"), ("L_sec", "ინფორმაციული უსაფრთხოება")], 6)
    s.responsible("L_it", r["role"]["it"])
    s.responsible("L_sec", r["role"]["admins"], "წვდომის უფლებებს ამოწმებს სისტემის ადმინისტრატორი")
    s.node("start", "startEvent", "მოთხოვნა მიღებულია", "L_it", 0, event_def="message")
    s.node("account", "userTask", "მომხმარებლის შექმნა Odoo-ში", "L_it", 1)
    s.link("account", r["link"].get("users_menu"))
    s.node("roles", "serviceTask", "როლების მინიჭება", "L_it", 2.3)
    s.node("check", "userTask", "წვდომის შემოწმება", "L_sec", 3.6, loop="standard", documentation=(
        "შეამოწმეთ, რომ თანამშრომელს მხოლოდ მისი როლისთვის საჭირო უფლებები აქვს. "
        "შეცდომისას დააბრუნეთ როლების მინიჭებაზე."))
    s.node("end", "endEvent", "წვდომა მზადაა", "L_sec", 5.5)
    s.flow("f1", "start", "account")
    s.flow("f2", "account", "roles")
    s.flow("f3", "roles", "check")
    s.flow("f4", "check", "roles", "უფლებები არასწორია", condition="უფლებები არასწორია")
    s.flow("f5", "check", "end", default=True)
    return s.to_xml()


def expenses(r, v2=False):
    s = Sketch("ავანსის ხარჯების ანგარიშგება")
    s.pool("P", "ავანსის ხარჯების ანგარიშგება", [("L_emp", "თანამშრომელი"), ("L_acc", "მთავარი ბუღალტერი")], 6)
    s.responsible("L_emp", r["role"]["employee"])
    s.responsible("L_acc", r["role"]["me"], "დემო: დანიშნულია კონკრეტულ მომხმარებელზე", sync=False)
    s.node("start", "startEvent", "მივლინება დასრულდა", "L_emp", 0)
    s.node("report", "userTask", "ხარჯების ანგარიშის შევსება", "L_emp", 1.2)
    s.node("check", "userTask", "ანგარიშის შემოწმება", "L_acc", 2.6)
    if v2:
        s.node("ok", "exclusiveGateway", "დოკუმენტები სრულია?", "L_acc", 3.8)
        s.node("book", "serviceTask", "ხარჯის გატარება", "L_acc", 5)
        s.node("end", "endEvent", "ანგარიში დახურულია", "L_acc", 6)
        s.flow("f1", "start", "report")
        s.flow("f2", "report", "check")
        s.flow("f3", "check", "ok")
        s.flow("f4", "ok", "book", "კი", default=True)
        s.flow("f5", "ok", "report", "არა", condition="აკლია ქვითარი")
        s.flow("f6", "book", "end")
    else:
        s.node("end", "endEvent", "ანგარიში დახურულია", "L_acc", 4)
        s.flow("f1", "start", "report")
        s.flow("f2", "report", "check")
        s.flow("f3", "check", "end")
    return s.to_xml()


def invoice_payment(r):
    s = Sketch("მომწოდებლის ინვოისის გადახდა")
    s.pool("P", "მომწოდებლის ინვოისის გადახდა", [
        ("L_fin", "ფინანსები"), ("L_proc", "შესყიდვები"), ("L_wh", "საწყობი")], 6)
    s.responsible("L_fin", r["role"]["finance"])
    s.responsible("L_proc", r["role"]["purchase"])
    s.responsible("L_wh", r["role"]["warehouse"])
    s.node("start", "startEvent", "ინვოისი მიღებულია", "L_fin", 0, event_def="message")
    s.node("match", "businessRuleTask", "სამმხრივი შედარება", "L_fin", 1, documentation=(
        "შეადარეთ ინვოისი, შესყიდვის შეკვეთა და მიღების აქტი: რაოდენობა და ფასი უნდა ემთხვეოდეს."))
    s.node("gw", "inclusiveGateway", "რა საჭიროებს დაზუსტებას?", "L_fin", 2.2)
    s.node("ask_price", "sendTask", "ფასის დაზუსტება მომწოდებელთან", "L_proc", 3.4)
    s.node("ask_qty", "userTask", "მიღებული რაოდენობის შემოწმება", "L_wh", 3.4)
    s.node("join", "inclusiveGateway", "", "L_fin", 4.6)
    s.node("pay", "serviceTask", "გადახდა", "L_fin", 5.6)
    s.node("end", "endEvent", "გადახდილია", "L_fin", 6.6)
    s.flow("f1", "start", "match")
    s.flow("f2", "match", "gw")
    s.flow("f3", "gw", "ask_price", "ფასი", condition="ფასი არ ემთხვევა")
    s.flow("f4", "gw", "ask_qty", "რაოდენობა", condition="რაოდენობა არ ემთხვევა")
    s.flow("f5", "gw", "join", "ყველაფერი ემთხვევა", default=True)
    s.flow("f6", "ask_price", "join")
    s.flow("f7", "ask_qty", "join")
    s.flow("f8", "join", "pay")
    s.flow("f9", "pay", "end")
    return s.to_xml()


def budget(r):
    s = Sketch("წლიური ბიუჯეტის დაგეგმვა")
    s.pool("P", "წლიური ბიუჯეტის დაგეგმვა", [("L_mgmt", "ხელმძღვანელობა"), ("L_fin", "ფინანსები")], 5)
    s.responsible("L_mgmt", r["role"]["management"])
    s.responsible("L_fin", r["role"]["finance"])
    s.node("start", "startEvent", "1 ოქტომბერი", "L_mgmt", 0, event_def="timer")
    s.node("goals", "userTask", "წლიური მიზნების დამტკიცება", "L_mgmt", 1)
    s.node("draft", "userTask", "ბიუჯეტის პროექტის მომზადება", "L_fin", 2.2, loop="parallel",
           documentation="თითოეული დეპარტამენტისთვის პარალელურად.")
    s.node("approve", "userTask", "ბიუჯეტის დამტკიცება", "L_mgmt", 3.4, color=ORANGE)
    s.node("end", "endEvent", "ბიუჯეტი დამტკიცებულია", "L_mgmt", 4.6)
    s.flow("f1", "start", "goals")
    s.flow("f2", "goals", "draft")
    s.flow("f3", "draft", "approve")
    s.flow("f4", "approve", "end")
    return s.to_xml()


def value_chain(r, name, items):
    """Level 0: a chain of call activities, each linked to its process (no pool)."""
    s = Sketch(name)
    prev = None
    for i, (key, label) in enumerate(items):
        nid = "c%d" % i
        s.node(nid, "callActivity", label, None, i * 1.3, color=TEAL if i % 2 == 0 else BLUE)
        s.link(nid, r["link"].get(key))
        if prev:
            s.flow("f%d" % i, prev, nid)
        prev = nid
    return s.to_xml()
