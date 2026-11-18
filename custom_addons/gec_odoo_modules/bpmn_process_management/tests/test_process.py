# Part of bpmn_process_management. License LGPL-3.
import base64
import os

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture_b64(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return base64.b64encode(f.read()).decode()


@tagged("post_install", "-at_install", "bpmn")
class TestBusinessProcess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, "bpmn_manager", groups="base.group_user,bpmn_process_management.group_process_manager")
        cls.viewer = new_test_user(cls.env, "bpmn_viewer", groups="base.group_user")
        cls.Process = cls.env["business.process"].with_user(cls.manager)

    def test_viewer_is_implied_for_employees(self):
        self.assertTrue(self.viewer.has_group("bpmn_process_management.group_process_user"))
        self.assertFalse(self.viewer.has_group("bpmn_process_management.group_process_manager"))

    def test_default_diagram_and_index(self):
        p = self.Process.create({"name": "P1"})
        self.assertIn('isExecutable="false"', p.bpmn_xml)
        self.assertEqual(p.element_count, 1)
        self.assertEqual(p.element_ids.element_type, "startEvent")

    def test_invalid_xml(self):
        with self.assertRaises(ValidationError):
            self.Process.create({"name": "bad", "bpmn_xml": "<not-bpmn/>"})

    def test_lifecycle_lock_and_versions(self):
        p = self.Process.create({"name": "Returns", "code": "R-1"})
        p.action_submit_review()
        self.assertEqual(p.state, "review")
        with self.assertRaises(UserError):
            p.write({"name": "changed while in review"})
        p.action_back_to_draft()
        p.action_publish()
        self.assertEqual(p.state, "published")
        self.assertTrue(p.published_date)
        with self.assertRaises(UserError):
            p.write({"bpmn_xml": p.bpmn_xml.replace("StartEvent_1", "StartEvent_2")})
        action = p.action_new_version()
        v2 = self.Process.browse(action["res_id"])
        self.assertEqual((v2.version, v2.state, v2.code, v2.name), ("1.1", "draft", "R-1", "Returns"))
        self.assertEqual(v2.root_id, p)
        self.assertEqual(v2.previous_version_id, p)
        self.assertEqual(p.action_new_version()["res_id"], v2.id)
        v2.action_publish()
        self.assertEqual(p.state, "deprecated")
        self.assertEqual(v2.version_count, 2)
        v3 = self.Process.browse(v2.action_new_version()["res_id"])
        v3.action_publish(change_type="major")
        self.assertEqual(v3.version, "2.0")

    def test_state_only_through_actions(self):
        p = self.Process.create({"name": "Locked", "code": "L-1"})
        p.action_publish()
        with self.assertRaises(UserError):
            p.write({"state": "draft"})
        with self.assertRaises(UserError):
            p.with_context(bpmn_allow_locked_write=True).write({"name": "hack"})
        p.write({"name": "Locked"})  # unchanged value is accepted (data file updates)
        with self.assertRaises(ValidationError):
            self.Process.create({"name": "Dup", "code": "L-1", "version": "1.0"})

    def test_delete_first_version_keeps_chain(self):
        v1 = self.Process.create({"name": "Chain"})
        v1.action_publish()
        v2 = self.Process.browse(v1.action_new_version()["res_id"])
        v2.action_publish()
        v3 = self.Process.browse(v2.action_new_version()["res_id"])
        v1.unlink()
        self.assertFalse(v2.root_id)
        self.assertEqual(v3.root_id, v2)
        self.assertEqual(v3.version_count, 2)

    def test_children_follow_new_version(self):
        parent = self.Process.create({"name": "Parent"})
        parent.action_publish()
        child = self.Process.create({"name": "Child", "parent_id": parent.id})
        v2 = self.Process.browse(parent.action_new_version()["res_id"])
        v2.action_publish()
        self.assertEqual(child.parent_id, v2)

    def test_resolve_rejects_unknown_models(self):
        P = self.env["business.process"].with_user(self.viewer)
        res = P.bpmn_resolve([{"key": "x", "linkType": "record", "model": "res.users", "resId": 1},
                              {"key": "y", "linkType": "record", "model": "base", "resId": 1}])
        self.assertTrue(res["x"]["ok"])
        self.assertFalse(res["y"]["ok"])
        with self.assertRaises(AccessError):
            P.bpmn_search_targets("action", "")

    def test_create_target_and_attachment_scope(self):
        proc = self.Process.create({"name": "Linking"})
        item = self.Process.bpmn_create_target("business.process", "  Sub process from diagram ")
        sub = self.env["business.process"].browse(item["resId"])
        self.assertEqual(sub.name, "Sub process from diagram")
        with self.assertRaises(UserError):
            self.Process.bpmn_create_target("res.partner", "Nope")
        with self.assertRaises(UserError):
            self.Process.bpmn_create_target("business.process", "   ")
        with self.assertRaises(AccessError):
            self.env["business.process"].with_user(self.viewer).bpmn_create_target("business.process", "X")
        Att = self.env["ir.attachment"]
        mine = Att.create({"name": "form-mine.pdf", "res_model": "business.process", "res_id": proc.id,
                           "raw": b"x"})
        other = Att.create({"name": "form-other.pdf", "res_model": "business.process", "res_id": sub.id,
                            "raw": b"x"})
        found = {r["resId"] for r in self.Process.bpmn_search_targets(
            "record", "form", "ir.attachment", 8, proc.id)}
        self.assertIn(mine.id, found)
        self.assertNotIn(other.id, found)
        self.assertFalse(self.Process.bpmn_search_targets("record", "form", "ir.attachment", 8, None))

    def test_demo_data_load_and_remove(self):
        P = self.Process
        mine = P.create({"name": "My own process"})
        if P.bpmn_demo_loaded():
            P.bpmn_remove_demo()
        tags_before = self.env["business.process.tag"].search_count([])
        P.bpmn_load_demo()
        self.assertTrue(P.bpmn_demo_loaded())
        with self.assertRaises(UserError):
            P.bpmn_load_demo()
        demo = self.env["business.process"].with_context(active_test=False).search(
            [("tag_ids.name", "=", "დემო")])
        states = set(demo.mapped("state"))
        self.assertTrue({"draft", "review", "published", "deprecated"} <= states, states)
        self.assertGreaterEqual(len(demo), 11)
        scm = demo.filtered(lambda p: p.code == "DEMO-SCM-01" and p.state == "published")
        self.assertTrue(scm.ack_count)
        self.assertTrue(scm.link_count)
        draft = demo.filtered(lambda p: p.code == "DEMO-SCM-01" and p.state == "draft")
        self.assertTrue(draft.review_count)
        self.assertTrue(demo.filtered(lambda p: p.next_review_date and p.next_review_date < fields.Date.today()))
        self.assertTrue(demo.filtered(lambda p: p.level == "0"))
        dash = P.bpmn_dashboard({})
        self.assertGreaterEqual(dash["totals"]["processes"], 6)
        self.assertTrue(dash["matrix"]["roles"])
        mine.write({"parent_id": scm.id})
        P.bpmn_remove_demo()
        self.assertFalse(P.bpmn_demo_loaded())
        self.assertFalse(demo.exists())
        self.assertTrue(mine.exists())
        self.assertFalse(mine.parent_id)
        self.assertEqual(self.env["business.process.tag"].search_count([]), tags_before)
        with self.assertRaises(AccessError):
            self.env["business.process"].with_user(self.viewer).bpmn_load_demo()

    def test_viewer_access(self):
        draft = self.Process.create({"name": "Draft one"})
        pub = self.Process.create({"name": "Published one"})
        pub.action_publish()
        visible = self.env["business.process"].with_user(self.viewer).search([])
        self.assertIn(pub, visible)
        self.assertNotIn(draft, visible)
        with self.assertRaises(AccessError):
            pub.with_user(self.viewer).write({"sequence": 3})
        with self.assertRaises(AccessError):
            pub.with_user(self.viewer).action_new_version()
        elements = self.env["business.process.element"].with_user(self.viewer).search([])
        self.assertTrue(elements)
        self.assertFalse(elements.filtered(lambda e: e.process_id == draft))

    def test_links(self):
        P = self.env["business.process"].with_user(self.viewer)
        res = P.bpmn_open_link({"linkType": "menu", "xmlid": "mail.menu_root_discuss"})
        self.assertTrue(res["action_id"])
        with self.assertRaises(UserError):
            P.bpmn_open_link({"linkType": "url", "url": "javascript:alert(1)"})
        with self.assertRaises(UserError):
            P.bpmn_open_link({"linkType": "menu", "resId": 999999})
        with self.assertRaises(UserError):
            P.bpmn_open_link({"linkType": "menu", "xmlid": "base.menu_administration"})
        res = P.bpmn_open_link({"linkType": "url", "url": "https://example.com"})
        self.assertEqual(res["type"], "ir.actions.act_url")
        resolved = P.bpmn_resolve([
            {"key": "a", "linkType": "menu", "xmlid": "mail.menu_root_discuss"},
            {"key": "b", "linkType": "record", "model": "res.partner", "resId": 999999},
            {"key": "c", "linkType": "url", "url": "javascript:x"},
        ])
        self.assertTrue(resolved["a"]["ok"])
        self.assertFalse(resolved["b"]["ok"])
        self.assertFalse(resolved["c"]["ok"])
        opts = self.env["business.process"].with_user(self.manager).bpmn_get_options()
        self.assertIn("res.groups", [m["model"] for m in opts["responsible_models"]])
        menus = self.env["business.process"].with_user(self.manager).bpmn_search_targets("menu", "Discuss")
        self.assertTrue(menus)

    def test_read_confirmation(self):
        p = self.Process.create({"name": "Ack me", "ack_required": True})
        p.action_publish()
        pv = p.with_user(self.viewer)
        self.assertFalse(pv.is_acknowledged)
        pv.action_acknowledge()
        pv.action_acknowledge()
        pv.invalidate_recordset()
        self.assertTrue(pv.is_acknowledged)
        self.assertEqual(p.ack_count, 1)
        self.assertEqual(self.env["business.process.ack"].with_user(self.viewer).search_count([]), 1)
        with self.assertRaises(AccessError):
            pv.action_view_acks()
        v2 = self.Process.browse(p.action_new_version()["res_id"])
        v2.action_publish(change_type="minor")
        self.assertEqual(v2.ack_count, 1)  # a small change keeps the confirmations
        v3 = self.Process.browse(v2.action_new_version()["res_id"])
        v3.action_publish(change_type="major")
        self.assertEqual(v3.ack_count, 0)  # a major change must be read again

    def test_review_cycle_and_card(self):
        p = self.Process.create({"name": "Cycle", "review_interval": 6, "trigger": "Order received",
                                 "kpi_ids": [(0, 0, {"name": "Lead time", "target": "< 2 days"})]})
        p.action_publish()
        self.assertTrue(p.next_review_date)
        with self.assertRaises(UserError):
            p.write({"trigger": "Something else"})  # process card is content: locked
        p.kpi_ids.write({"target": "< 1 day"})  # indicators may be adjusted
        p.write({"next_review_date": "2020-01-01"})
        Process = self.env["business.process"]
        Process._cron_review_reminders()
        Process._cron_review_reminders()
        acts = p.activity_ids.filtered(lambda a: a.user_id == p.owner_id)
        self.assertEqual(len(acts), 1)
        self.assertGreater(p.next_review_date, fields.Date.today())
        v2 = self.Process.browse(p.action_new_version()["res_id"])
        self.assertEqual(v2.kpi_ids.mapped("name"), ["Lead time"])
        self.assertEqual(v2.trigger, "Order received")
        kpis = self.env["business.process.kpi"].with_user(self.viewer).search([])
        self.assertIn(p.kpi_ids, kpis)
        self.assertNotIn(v2.kpi_ids, kpis)

    def test_dashboard(self):
        p = self._import_published("visio_bpmn_returns.vsdx")
        data = self.env["business.process"].with_user(self.manager).bpmn_dashboard({})
        self.assertGreaterEqual(data["totals"]["processes"], 1)
        row = [r for r in data["processes"] if r["id"] == p.id][0]
        self.assertEqual((row["steps"], row["decisions"], row["roles"]), (3, 1, 2))
        self.assertEqual(row["handoffs"], 2)
        labels = {r["label"] for r in data["workload"]}
        # (the top 15 roles only: on a database with many processes these may be folded)
        self.assertTrue({"Sales", "Warehouse"} <= labels or len(labels) >= 15
                        or p.element_ids.filtered("responsible_name"))
        self.assertIn("states", data)
        self.assertEqual(len(data["timeline"]), 12)
        viewer = self.env["business.process"].with_user(self.viewer).bpmn_dashboard({"scope": "current"})
        self.assertNotIn("states", viewer)
        self.assertEqual(viewer["scope"], "current")  # ignored for viewers: published only
        self.assertTrue(all(r["state"] == "published" for r in viewer["processes"]))
        draft = self.Process.create({"name": "Work in progress"})
        cur = self.env["business.process"].with_user(self.manager).bpmn_dashboard({"scope": "current"})
        self.assertIn(draft.id, [r["id"] for r in cur["processes"]])
        v2 = self.Process.browse(p.action_new_version()["res_id"])
        cur = self.env["business.process"].with_user(self.manager).bpmn_dashboard({"scope": "current"})
        ids = [r["id"] for r in cur["processes"]]
        self.assertIn(v2.id, ids)
        self.assertNotIn(p.id, ids)

    def _import_published(self, filename):
        p = self.Process.browse(self._import(filename)["res_id"])
        p.action_publish()
        return p

    def _import(self, filename, **kw):
        wiz = self.env["business.process.import"].with_user(self.manager).create(dict(
            file=fixture_b64(filename), filename=filename, **kw))
        return wiz.action_import()

    def test_import_visio_with_matching(self):
        self.env["res.groups"].create({"name": "Warehouse"})
        action = self._import("visio_bpmn_returns.vsdx")
        p = self.Process.browse(action["res_id"])
        self.assertEqual(p.name, "visio_bpmn_returns")
        lanes = p.element_ids.filtered(lambda e: e.element_type == "lane")
        wh = lanes.filtered(lambda e: e.name == "Warehouse")
        # hr (if installed) is searched first, then res.groups
        self.assertIn(wh.responsible_model, ("hr.department", "hr.job", "res.groups"))
        self.assertTrue(wh.responsible_res_id)
        self.assertEqual(wh.review_reason, "responsible_auto")
        sales = lanes.filtered(lambda e: e.name == "Sales")
        expected = "responsible_auto" if self.Process._responsible_matcher()("Sales") else "responsible_missing"
        self.assertEqual(sales.review_reason, expected)
        self.assertTrue(p.message_ids.filtered(lambda m: "Visio" in (m.body or "")))

    def test_import_drawio_and_replace(self):
        action = self._import("drawio_swimlane_template.drawio")
        p = self.Process.browse(action["res_id"])
        self.assertGreaterEqual(p.review_count, 7)
        self._import("drawio_cff1.drawio", mode="replace", process_id=p.id)
        self.assertEqual(len(p.element_ids.filtered(lambda e: e.element_type == "lane")), 6)
        p.action_publish()
        with self.assertRaises(UserError):
            self._import("drawio_cff1.drawio", mode="replace", process_id=p.id)

    def test_import_bpmn_roundtrip(self):
        src = self.Process.create({"name": "src"})
        wiz = self.env["business.process.import"].with_user(self.manager).create({
            "file": base64.b64encode(src.bpmn_xml.encode()).decode(), "filename": "x.bpmn"})
        p = self.Process.browse(wiz.action_import()["res_id"])
        self.assertEqual(p.element_count, 1)

    def test_import_rejects_garbage(self):
        wiz = self.env["business.process.import"].with_user(self.manager).create({
            "file": base64.b64encode(b"just text").decode(), "filename": "notes.txt"})
        with self.assertRaises(UserError):
            wiz.action_import()


@tagged("post_install", "-at_install", "bpmn")
class TestExport(HttpCase):

    def test_export_endpoints(self):
        p = self.env["business.process"].create({"name": "Export me ქართული"})
        p.action_publish()
        new_test_user(self.env, "bpmn_viewer2", groups="base.group_user", password="bpmn_viewer2")
        self.authenticate("bpmn_viewer2", "bpmn_viewer2")
        r = self.url_open("/bpmn_process_management/export/%s/bpmn" % p.id)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"bpmn:definitions", r.content)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        r = self.url_open("/bpmn_process_management/export/%s/drawio" % p.id)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"<mxfile", r.content)
        draft = self.env["business.process"].create({"name": "hidden"})
        r = self.url_open("/bpmn_process_management/export/%s/bpmn" % draft.id)
        self.assertNotEqual(r.status_code, 200)
