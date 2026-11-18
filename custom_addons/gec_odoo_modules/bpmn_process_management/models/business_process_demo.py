# Part of bpmn_process_management. License LGPL-3.
"""Demo data on demand (Import Diagram > Load demo data).
Records are tracked in ``ir.model.data`` under ``bpmn_process_management_demo``; "Remove demo data" deletes only them.
Same-name departments, groups and tags are reused, never deleted."""
import base64
import logging
import os

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..lib import demo_data as D

_logger = logging.getLogger(__name__)

DEMO_MODULE = "bpmn_process_management_demo"
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "fixtures")

ROLE_NAMES = {
    "purchase": "შესყიდვები",
    "finance": "ფინანსები",
    "hr": "ადამიანური რესურსები",
    "it": "IT",
    "management": "ხელმძღვანელობა",
    "warehouse": "საწყობი",
}


class BusinessProcess(models.Model):
    _inherit = "business.process"

    @api.model
    def _demo_register(self, record, name):
        self.env["ir.model.data"].sudo().create({
            "module": DEMO_MODULE, "name": name, "model": record._name,
            "res_id": record.id, "noupdate": True})
        return record

    @api.model
    def _demo_records(self):
        return self.env["ir.model.data"].sudo().search([("module", "=", DEMO_MODULE)])

    @api.model
    def bpmn_demo_loaded(self):
        return bool(self._demo_records())

    @api.model
    def _demo_get_or_create(self, model, name, key, vals=None):
        Model = self.env[model].sudo()
        domain = [("name", "=", name)]
        if "company_id" in Model._fields:
            domain.append(("company_id", "in", [False, self.env.company.id]))
        rec = Model.search(domain, limit=1)
        if rec:
            return rec
        rec = Model.create(dict(vals or {}, name=name))
        return self._demo_register(rec, key)

    def _demo_ref(self, record, label=None):
        """odoo:Responsible / odoo:Link attributes of a record."""
        if not record:
            return None
        return {"model": record._name, "resId": record.id, "xmlid": self._xmlid(record),
                "name": label or record.display_name}

    @api.model
    def _demo_roles(self):
        roles = {}
        use_hr = "hr.department" in self.env
        for key, name in ROLE_NAMES.items():
            if use_hr:
                rec = self._demo_get_or_create("hr.department", name, "department_" + key,
                                               {"company_id": self.env.company.id})
            else:
                rec = self._demo_get_or_create("res.groups", name, "group_" + key)
            roles[key] = self._demo_ref(rec)
        roles["employee"] = self._demo_ref(self._demo_get_or_create("res.groups", "თანამშრომლები", "group_employees"))
        roles["admins"] = self._demo_ref(self.env.ref("base.group_system"))
        roles["me"] = self._demo_ref(self.env.user)
        return roles

    @staticmethod
    def _demo_link(ref, label=None):
        if not ref:
            return None
        link = {"linkType": "record", "model": ref["model"], "resId": ref["resId"],
                "xmlid": ref["xmlid"], "label": label or ref["name"]}
        if ref["model"] == "ir.ui.menu":
            link["linkType"] = "menu"
        return link

    def _demo_publish(self, months_ago=0, days_ago=0, change_type=None):
        self.action_publish(change_type=change_type)
        when = fields.Datetime.now() - relativedelta(months=months_ago, days=days_ago)
        self.write({"published_date": when})
        if self.review_interval > 0:
            self.write({"next_review_date": fields.Date.to_date(when) + relativedelta(months=self.review_interval)})

    def _demo_new_version(self, key):
        action = self.action_new_version()
        new = self.browse(action["res_id"])
        return self._demo_register(new, key)

    @api.model
    def bpmn_load_demo(self):
        self._check_manager()
        if self.bpmn_demo_loaded():
            raise UserError(self.env._("Demo data is already loaded. Remove it first to load it again."))
        me = self.env.user
        tag_demo = self._demo_get_or_create("business.process.tag", "დემო", "tag_demo", {"color": 3})
        tag_iso = self._demo_get_or_create("business.process.tag", "ISO 9001", "tag_iso", {"color": 10})
        tag_ctrl = self._demo_get_or_create("business.process.tag", "შიდა კონტროლი", "tag_control", {"color": 1})
        tag_people = self._demo_get_or_create("business.process.tag", "თანამშრომლები", "tag_people", {"color": 4})

        def create(key, vals, tags=()):
            vals = dict(vals, owner_id=me.id, tag_ids=[(6, 0, [tag_demo.id] + [t.id for t in tags])])
            return self._demo_register(self.create(vals), key)

        # 1. records first (diagrams reference each other)
        chain_core = create("proc_chain_core", {
            "name": "ოპერაციული პროცესები", "code": "DEMO-L0-OPS", "category": "core", "level": "0",
            "description": Markup("<p>დემო: ღირებულებათა ჯაჭვის დონე. თითოეული ბლოკი ქვეპროცესს ხსნის.</p>")})
        chain_support = create("proc_chain_support", {
            "name": "მხარდამჭერი პროცესები", "code": "DEMO-L0-SUP", "category": "support", "level": "0"})
        scm = create("proc_purchase", {
            "name": "შესყიდვის მოთხოვნა", "code": "DEMO-SCM-01", "category": "core", "level": "2",
            "parent_id": chain_core.id, "ack_required": True, "review_interval": 12,
            "trigger": "თანამშრომელს საქონელი ან მომსახურება სჭირდება",
            "supplier": "თანამშრომლები, მომწოდებლები",
            "process_input": "შესყიდვის მოთხოვნის ფორმა, ტექნიკური მოთხოვნები",
            "process_output": "დადასტურებული შესყიდვის შეკვეთა, გადახდილი ინვოისი",
            "customer": "მოთხოვნის ავტორი, ფინანსები",
            "description": Markup("<p>როგორ ხდება საქონლის ან მომსახურების შესყიდვა: მოთხოვნიდან "
                                  "გადახდამდე. <b>დემო:</b> ნახეთ ზოლები, ბმულები, პირობითი და "
                                  "ნაგულისხმევი ნაკადები, ტაიმერი, შეტყობინებები მომწოდებელთან.</p>"),
            "kpi_ids": [
                (0, 0, {"name": "მოთხოვნები, რომლებიც 5 დღეში დამუშავდა", "target": ">= 90 %",
                        "frequency": "monthly", "source": "Odoo: შესყიდვების ანგარიში"}),
                (0, 0, {"name": "შესყიდვები 3 შეთავაზებით", "target": "100 %", "frequency": "quarterly"}),
            ]}, tags=(tag_iso, tag_ctrl))
        invoice = create("proc_invoice", {
            "name": "მომწოდებლის ინვოისის გადახდა", "code": "DEMO-FIN-02", "category": "core", "level": "2",
            "parent_id": chain_core.id, "review_interval": 12,
            "trigger": "მომწოდებლის ინვოისი მიღებულია", "customer": "მომწოდებელი",
            "kpi_ids": [(0, 0, {"name": "ვადაში გადახდილი ინვოისები", "target": ">= 98 %",
                                "frequency": "monthly"})]}, tags=(tag_ctrl,))
        onboarding = create("proc_onboarding", {
            "name": "ახალი თანამშრომლის მიღება", "code": "DEMO-HR-01", "category": "support", "level": "2",
            "parent_id": chain_support.id, "review_interval": 12,
            "trigger": "შრომითი ხელშეკრულება გაფორმდა", "customer": "ახალი თანამშრომელი, ხელმძღვანელი",
            "kpi_ids": [(0, 0, {"name": "პირველ დღეს სრულად აღჭურვილი თანამშრომლები", "target": "100 %",
                                "frequency": "quarterly"})]}, tags=(tag_people,))
        access = create("proc_it_access", {
            "name": "IT წვდომის მინიჭება", "code": "DEMO-IT-02", "category": "support", "level": "3",
            "parent_id": onboarding.id, "review_interval": 6}, tags=(tag_ctrl,))
        expenses = create("proc_expenses", {
            "name": "ავანსის ხარჯების ანგარიშგება", "code": "DEMO-FIN-05", "category": "support", "level": "2",
            "parent_id": chain_support.id})
        budget = create("proc_budget", {
            "name": "წლიური ბიუჯეტის დაგეგმვა", "code": "DEMO-MGT-01", "category": "management", "level": "1",
            "ack_required": True, "review_interval": 12,
            "trigger": "ყოველწლიურად, 1 ოქტომბერს"})

        form = self.env["ir.attachment"].create({
            "name": "შესყიდვის მოთხოვნის ფორმა.csv", "res_model": "business.process", "res_id": scm.id,
            "mimetype": "text/csv",
            "raw": "დასახელება,რაოდენობა,ვადა,ხარჯის ცენტრი\n".encode("utf-8")})
        self._demo_register(form, "attachment_purchase_form")
        article = None
        if "knowledge.article" in self.env:
            try:
                with self.env.cr.savepoint():
                    article = self.env["knowledge.article"].create({
                        "name": "შესყიდვების პოლიტიკა (დემო)",
                        "body": Markup("<p>5000 ₾-ზე მეტ შესყიდვას ამტკიცებს ფინანსური დირექტორი. "
                                       "ყოველ შესყიდვაზე საჭიროა მინიმუმ 3 შეთავაზება.</p>")})
                self._demo_register(article, "article_purchase_policy")
            except Exception:  # noqa: BLE001 - Knowledge rights / version differences
                _logger.info("Demo: Knowledge article not created", exc_info=True)
                article = None
        discuss = self.env.ref("mail.menu_root_discuss", raise_if_not_found=False)
        users_menu = self.env.ref("base.menu_action_res_users", raise_if_not_found=False)
        r = {
            "role": self._demo_roles(),
            "link": {
                "discuss": self._demo_link(self._demo_ref(discuss), "Discuss — შიდა ჩატი"),
                "users_menu": self._demo_link(self._demo_ref(users_menu), "პარამეტრები / მომხმარებლები"),
                "form": self._demo_link(self._demo_ref(form)),
                "policy_article": self._demo_link(self._demo_ref(article)) if article else None,
                "proc_invoice": self._demo_link(self._demo_ref(invoice, invoice.name)),
                "proc_access": self._demo_link(self._demo_ref(access, access.name)),
                "proc_purchase": self._demo_link(self._demo_ref(scm, scm.name)),
                "proc_onboarding": self._demo_link(self._demo_ref(onboarding, onboarding.name)),
                "proc_expenses": self._demo_link(self._demo_ref(expenses, expenses.name)),
            },
        }

        chain_core.write({"bpmn_xml": D.value_chain(r, chain_core.name, [
            ("proc_purchase", "შესყიდვის მოთხოვნა"), ("proc_invoice", "მომწოდებლის ინვოისის გადახდა")])})
        chain_support.write({"bpmn_xml": D.value_chain(r, chain_support.name, [
            ("proc_onboarding", "ახალი თანამშრომლის მიღება"), ("proc_expenses", "ავანსის ხარჯების ანგარიშგება")])})
        scm.write({"bpmn_xml": D.purchase_request(r)})
        invoice.write({"bpmn_xml": D.invoice_payment(r)})
        onboarding.write({"bpmn_xml": D.onboarding(r)})
        access.write({"bpmn_xml": D.it_access(r)})
        expenses.write({"bpmn_xml": D.expenses(r)})
        budget.write({"bpmn_xml": D.budget(r)})

        chain_core._demo_publish(months_ago=11)
        chain_support._demo_publish(months_ago=11)
        expenses._demo_publish(months_ago=9)
        exp2 = expenses._demo_new_version("proc_expenses_v2")
        exp2.write({"bpmn_xml": D.expenses(r, v2=True)})
        exp2._demo_publish(months_ago=2, change_type="major")
        invoice._demo_publish(months_ago=5)
        access._demo_publish(months_ago=7)
        access.write({"next_review_date": fields.Date.today() - relativedelta(days=15)})
        budget._demo_publish(months_ago=1)
        scm._demo_publish(months_ago=3)
        self.env["business.process.ack"].sudo().create({
            "process_id": scm.id, "user_id": me.id, "version": scm.version})
        scm2 = scm._demo_new_version("proc_purchase_v11")
        scm2.write({"bpmn_xml": D.purchase_request(r, draft=True)})
        onboarding.action_submit_review()

        self._demo_import("drawio_swimlane_template.drawio", "იმპორტი draw.io-დან (დემო)", "proc_import_drawio")
        self._demo_import("visio_bpmn_returns.vsdx", "იმპორტი Visio-დან (დემო)", "proc_import_visio")
        return True

    @api.model
    def _demo_import(self, filename, name, key):
        path = os.path.join(FIXTURES, filename)
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        wizard = self.env["business.process.import"].create({
            "file": data, "filename": filename, "mode": "new", "pages": "first"})
        action = wizard.action_import()
        ids = [action["res_id"]] if action.get("res_id") else list(action.get("domain", [[0, 0, []]])[0][2])
        tag = self.env.ref(DEMO_MODULE + ".tag_demo", raise_if_not_found=False)
        for i, rec in enumerate(self.browse(ids)):
            rec.write({"name": name, "tag_ids": [(4, tag.id)] if tag else []})
            self._demo_register(rec, key if not i else "%s_%s" % (key, i))

    @api.model
    def bpmn_remove_demo(self):
        """Delete what "Load demo data" created, and nothing else.
        Versions or sub-processes users made from a demo process stay;
departments, groups, tags and articles stay when something outside the demo uses them."""
        self._check_manager()
        return self._demo_remove()

    @api.model
    def _demo_remove(self):
        """Removal itself, also used by the uninstall hook (no user check)."""
        imd = self._demo_records()
        by_model = {}
        for x in imd:
            by_model.setdefault(x.model, []).append(x.res_id)
        Process = self.sudo().with_context(active_test=False)
        procs = Process.browse(by_model.get("business.process", [])).exists()
        if procs:
            Process.search([("parent_id", "in", procs.ids), ("id", "not in", procs.ids)]).write(
                {"parent_id": False})
            procs.write({"parent_id": False})
            procs.unlink()
        for model in ("ir.attachment", "knowledge.article", "business.process.tag",
                      "hr.department", "res.groups"):
            if model in by_model and model in self.env:
                recs = self.env[model].sudo().with_context(active_test=False).browse(by_model[model]).exists()
                recs.filtered(lambda r: not self._demo_in_use(r)).unlink()
        imd.exists().unlink()
        return True

    @api.model
    def _demo_in_use(self, record):
        """True when a demo record is referenced by data that is not demo data."""
        env = self.env
        if record._name == "business.process.tag":
            return bool(env["business.process"].sudo().with_context(active_test=False).search_count(
                [("tag_ids", "in", record.ids)], limit=1))
        if record._name == "res.groups":
            return bool(record.user_ids)
        if record._name == "hr.department":
            checks = [("hr.employee", "department_id"), ("hr.job", "department_id"),
                      ("hr.department", "parent_id")]
            return any(model in env and env[model].sudo().with_context(active_test=False).search_count(
                [(field, "=", record.id)], limit=1) for model, field in checks)
        if record._name == "knowledge.article":
            return "child_ids" in record._fields and bool(record.child_ids)
        return False
