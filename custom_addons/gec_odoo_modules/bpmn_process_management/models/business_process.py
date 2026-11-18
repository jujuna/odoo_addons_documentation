# Part of bpmn_process_management. License LGPL-3.
import base64
import logging
import re

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import SQL, html2plaintext, is_html_empty
from odoo.tools.misc import format_date, format_datetime

from ..lib.bpmn_common import DEFAULT_BPMN_XML, BpmnError, is_safe_url, normalize_bpmn
from ..lib.bpmn_index import apply_responsible_matching, extract_elements
from ..lib.bpmn_thumbnail import render_thumbnail

_logger = logging.getLogger(__name__)


def escape_like(value):
    """Escape LIKE wildcards."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

# Approved content: editable only while the version is a draft.
CONTENT_FIELDS = {"name", "code", "version", "bpmn_xml", "description", "category", "level", "trigger",
                  "supplier", "process_input", "process_output", "customer"}

# Models an element can link to; the ones that are not installed are skipped.
RECORD_LINK_MODELS = [
    "knowledge.article",       # Enterprise: Knowledge
    "documents.document",      # Enterprise: Documents
    "business.process",        # another process (sub-process / next process)
    "ir.attachment",
]
RESPONSIBLE_MODELS = ["hr.department", "res.groups", "res.users", "hr.job"]
LINKABLE_MODELS = set(RECORD_LINK_MODELS + RESPONSIBLE_MODELS + ["ir.ui.menu", "ir.actions.act_window"])
CREATABLE_MODELS = ("knowledge.article", "business.process")
REVIEW_REASONS = {"responsible_missing", "responsible_auto", "type_guessed", "link_broken",
                  "imported"}


class BusinessProcess(models.Model):
    _name = "business.process"
    _description = "Business Process"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, code, name, id"
    _parent_store = True
    _rec_names_search = ["name", "code"]

    name = fields.Char("Process Name", required=True, tracking=True)
    code = fields.Char("Process Code", copy=False, tracking=True,
                       help="Short reference, e.g. SAL-03. Kept across versions.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company", index=True,
                                 default=lambda self: self.env.company,
                                 help="Leave empty to share the process with all companies.")
    version = fields.Char("Version", default="1.0", required=True, copy=False, tracking=True)
    state = fields.Selection([
        ("draft", "Draft"),
        ("review", "In Review"),
        ("published", "Published"),
        ("deprecated", "Deprecated"),
    ], default="draft", required=True, copy=False, tracking=True, index=True)
    category = fields.Selection([
        ("core", "Core (Operational)"),
        ("support", "Supporting"),
        ("management", "Management"),
    ], string="Process Type", default="core", required=True)
    parent_id = fields.Many2one("business.process", string="Parent Process", index=True,
                                ondelete="restrict",
                                help="Higher-level process in the process architecture.")
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many("business.process", "parent_id", string="Sub-processes")
    owner_id = fields.Many2one("res.users", string="Process Owner",
                               default=lambda self: self.env.user, tracking=True)
    description = fields.Html("Purpose & Description", sanitize=True)
    bpmn_xml = fields.Text("BPMN 2.0 XML", default=DEFAULT_BPMN_XML, copy=True)
    diagram_preview = fields.Binary("Diagram Preview", attachment=True, copy=True)

    root_id = fields.Many2one("business.process", string="First Version", copy=False,
                              index=True, readonly=True, ondelete="set null")
    previous_version_id = fields.Many2one("business.process", string="Previous Version",
                                          copy=False, readonly=True)
    version_count = fields.Integer(compute="_compute_version_count")
    published_date = fields.Datetime(copy=False, readonly=True, tracking=True)
    published_by_id = fields.Many2one("res.users", string="Published By", copy=False,
                                      readonly=True)
    change_type = fields.Selection([
        ("first", "First version"),
        ("minor", "Small change"),
        ("major", "Major change"),
    ], string="Kind of Change", copy=False, readonly=True,
        help="Chosen at publication. Small: people keep working as before, read confirmations are "
             "kept. Major: the way of working changes, everyone must read it again.")
    change_note = fields.Text("What Changed", copy=False, readonly=True)

    element_ids = fields.One2many("business.process.element", "process_id", string="Elements",
                                  copy=False)
    element_count = fields.Integer(compute="_compute_element_stats", store=True)
    review_count = fields.Integer("Items to Review", compute="_compute_element_stats",
                                  store=True)
    link_count = fields.Integer("Links", compute="_compute_element_stats", store=True)

    is_manager = fields.Boolean(compute="_compute_is_manager")
    is_latest_version = fields.Boolean(compute="_compute_version_count")
    is_superseded = fields.Boolean(
        "Old Version", compute="_compute_version_count", search="_search_is_superseded",
        help="Deprecated because a newer version of the same process was published.")
    other_version_id = fields.Many2one(
        "business.process", string="Current Version", compute="_compute_version_count",
        help="The version to work on instead of this one: the draft being prepared, "
             "otherwise the published version.")
    other_version_label = fields.Char("Current Version Label", compute="_compute_version_count")

    level = fields.Selection([
        ("0", "L0 - Value chain / category"),
        ("1", "L1 - Process group"),
        ("2", "L2 - Process"),
        ("3", "L3 - Sub-process"),
        ("4", "L4 - Activity / procedure"),
    ], string="Level", default="2",
        help="Level in the process architecture: from the value chain (L0) down to the "
             "detailed procedure (L4).")
    tag_ids = fields.Many2many("business.process.tag", string="Tags")

    trigger = fields.Char("Trigger", help="Event that starts the process, e.g. \"Customer asks for a return\".")
    supplier = fields.Char("Suppliers", help="Who provides the inputs.")
    process_input = fields.Text("Inputs")
    process_output = fields.Text("Outputs")
    customer = fields.Char("Customers", help="Who receives the result of the process.")
    kpi_ids = fields.One2many("business.process.kpi", "process_id", string="Indicators (KPI)",
                              copy=True)

    review_interval = fields.Integer(
        "Review Every (months)", default=12,
        help="After publication, the owner gets a to-do to check the process again. 0 = never.")
    next_review_date = fields.Date("Next Review", copy=False, tracking=True)

    # diagram revision: a save based on an older revision is refused (two editors)
    bpmn_revision = fields.Integer("Diagram Revision", default=0, copy=False, readonly=True)
    bpmn_saved_by_id = fields.Many2one("res.users", string="Diagram Saved By", copy=False, readonly=True,
                                       ondelete="set null")
    bpmn_saved_at = fields.Datetime("Diagram Saved At", copy=False, readonly=True)
    bpmn_saved_token = fields.Char("Diagram Saved By Editor", copy=False, readonly=True)
    bpmn_save_base = fields.Char(
        "Diagram Save Base", compute="_compute_bpmn_save_base", inverse="_inverse_bpmn_save_base",
        help="Technical: '<revision>:<editor token>' sent by the modeler with each diagram change.")

    ack_required = fields.Boolean(
        "Read Confirmation", help="Employees are asked to confirm they have read the published version.")
    ack_ids = fields.One2many("business.process.ack", "process_id", string="Read Confirmations",
                              copy=False)
    ack_count = fields.Integer("Read by", compute="_compute_ack")
    is_acknowledged = fields.Boolean(compute="_compute_ack")


    @api.model
    def _bpmn_load_access_rules(self):
        """Load the access files of the running Odoo version; called from security/security.xml on install/update."""
        from odoo.tools.convert import convert_file  # noqa: PLC0415
        if "ir.access" in self.env:
            files = ["security/odoo20/ir.access.csv"]
        else:
            files = ["security/odoo19/ir.model.access.csv", "security/odoo19/ir_rule.xml"]
        for path in files:
            convert_file(self.env, "bpmn_process_management", path, {}, mode="update",
                         noupdate=False)
        return True

    def _compute_is_manager(self):
        is_manager = self.env.user.has_group("bpmn_process_management.group_process_manager")
        for rec in self:
            rec.is_manager = is_manager

    @api.depends("element_ids.review_status", "element_ids.link_count")
    def _compute_element_stats(self):
        for rec in self:
            rec.element_count = len(rec.element_ids)
            rec.review_count = len(rec.element_ids.filtered(lambda e: e.review_status == "pending"))
            rec.link_count = sum(rec.element_ids.mapped("link_count"))

    @api.depends("ack_ids", "version")
    def _compute_ack(self):
        Ack = self.env["business.process.ack"].sudo()
        uid = self.env.uid
        for rec in self:
            if not rec.id:
                rec.ack_count = 0
                rec.is_acknowledged = False
                continue
            acks = Ack.search([("process_id", "=", rec.id), ("version", "=", rec.version)])
            rec.ack_count = len(acks)
            rec.is_acknowledged = uid in acks.user_id.ids

    @api.onchange("parent_id")
    def _onchange_parent_level(self):
        if self.parent_id and self.parent_id.level and self.parent_id.level < "4":
            self.level = str(int(self.parent_id.level) + 1)

    @api.depends("bpmn_revision")
    def _compute_bpmn_save_base(self):
        for rec in self:
            rec.bpmn_save_base = False

    def _inverse_bpmn_save_base(self):
        """Nothing to store: write() checks the value against bpmn_revision."""

    def _lineage_domain(self):
        self.ensure_one()
        root = self.root_id or self
        return ["|", ("id", "=", root.id), ("root_id", "=", root.id)]

    def _compute_version_count(self):
        """Version chain facts for the form, incl. the other version a manager should open (draft, else published)."""
        Process = self.with_context(active_test=False)
        for rec in self:
            rec.is_superseded = False
            rec.other_version_id = False
            rec.other_version_label = False
            if not rec.id:
                rec.version_count = 1
                rec.is_latest_version = True
                continue
            versions = Process.search(rec._lineage_domain())
            rec.version_count = len(versions)
            # an archived later draft must not hide "New Version" on the current one
            rec.is_latest_version = rec == versions.filtered("active").sorted("id")[-1:]
            others = (versions - rec).filtered("active")
            newer_released = others.filtered(lambda v: v.id > rec.id and v.state in ("published", "deprecated"))
            rec.is_superseded = rec.state == "deprecated" and bool(newer_released)
            target = others.filtered(lambda v: v.state in ("draft", "review"))[-1:] \
                or others.filtered(lambda v: v.state == "published")[-1:]
            rec.other_version_id = target
            if target:
                rec.other_version_label = self.env._(
                    "Version %(version)s (%(state)s)", version=target.version,
                    state=dict(self._fields["state"]._description_selection(self.env))[target.state])

    def _search_is_superseded(self, operator, value):
        """Deprecated versions with a newer released version in the chain, so lists can hide them."""
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(self.env._("Operation not supported"))
        self.env["business.process"].flush_model(["root_id", "state", "active"])
        self.env.cr.execute(SQL("""
            SELECT p.id FROM business_process p
             WHERE p.state = 'deprecated'
               AND EXISTS (SELECT 1 FROM business_process q
                            WHERE COALESCE(q.root_id, q.id) = COALESCE(p.root_id, p.id)
                              AND q.id > p.id AND q.active
                              AND q.state IN ('published', 'deprecated'))"""))
        ids = [r[0] for r in self.env.cr.fetchall()]
        positive = (operator == "=") == value
        return [("id", "in" if positive else "not in", ids)]

    @api.constrains("code", "version", "company_id")
    def _check_code_version_unique(self):
        for rec in self.filtered("code"):
            dup = self.with_context(active_test=False).search_count([
                ("id", "!=", rec.id), ("code", "=", rec.code), ("version", "=", rec.version),
                ("company_id", "=", rec.company_id.id),
            ], limit=1)
            if dup:
                raise ValidationError(self.env._("A process with this code and version already exists."))

    @api.constrains("parent_id")
    def _check_parent_recursion(self):
        if self._has_cycle():
            raise ValidationError(self.env._("A process cannot be its own parent."))

    @api.model
    def _prepare_bpmn(self, xml):
        if not xml:
            return DEFAULT_BPMN_XML
        try:
            return normalize_bpmn(xml)
        except BpmnError as e:
            raise ValidationError(self.env._("Invalid BPMN diagram: %s", e)) from e

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "bpmn_xml" in vals:
                vals["bpmn_xml"] = self._prepare_bpmn(vals["bpmn_xml"])
            if not vals.get("diagram_preview"):
                vals["diagram_preview"] = self._thumbnail(vals.get("bpmn_xml") or DEFAULT_BPMN_XML)
        records = super().create(vals_list)
        records._rebuild_element_index()
        return records

    def write(self, vals):
        if "state" in vals and any(rec.state != vals["state"] for rec in self):
            raise UserError(self.env._(
                "The status changes only through the buttons (Submit for Review, Publish, ...)."))
        if {"root_id", "previous_version_id"} & set(vals) and not self.env.context.get("bpmn_relink"):
            raise UserError(self.env._("The version chain is managed by the New Version button."))
        locked = {f for f in CONTENT_FIELDS & set(vals)
                  if any(rec[f] != vals[f] for rec in self)}
        if "company_id" in vals and any(rec.company_id.id != (vals["company_id"] or False) for rec in self):
            locked.add("company_id")
        if locked:
            frozen = self.filtered(lambda r: r.state != "draft")
            if frozen:
                raise UserError(self.env._(
                    "Only draft versions can be edited. \"%(name)s\" is %(state)s: create a new "
                    "version to change it.",
                    name=frozen[0].display_name,
                    state=dict(self._fields["state"]._description_selection(self.env))[frozen[0].state],
                ))
        base = vals.pop("bpmn_save_base", None)
        token = False
        if "bpmn_xml" in vals:
            if base:
                token = self._check_bpmn_revision(base)
            vals["bpmn_xml"] = self._prepare_bpmn(vals["bpmn_xml"])
            if "diagram_preview" not in vals:
                vals["diagram_preview"] = self._thumbnail(vals["bpmn_xml"])
        res = super().write(vals)
        if "bpmn_xml" in vals:
            now = fields.Datetime.now()
            for rec in self:
                super(BusinessProcess, rec).write({"bpmn_revision": rec.bpmn_revision + 1,
                                                   "bpmn_saved_by_id": self.env.uid, "bpmn_saved_at": now,
                                                   "bpmn_saved_token": token})
            self._rebuild_element_index()
        return res

    @api.model
    def _parse_save_base(self, base):
        """``"<revision>:<token>"`` -> (revision, token); revision -1 when unreadable."""
        rev, _sep, token = str(base or "").partition(":")
        try:
            rev = int(rev)
        except ValueError:
            rev = -1
        return rev, (token[:64] or False)

    def _bpmn_newer_save(self, base):
        """True when someone else saved after revision ``base`` was read; the editor's own saves never count."""
        self.ensure_one()
        rev, token = self._parse_save_base(base)
        mine = token and self.bpmn_saved_token == token
        return bool(self.bpmn_revision and rev != self.bpmn_revision and not mine)

    def _bpmn_saved_label(self):
        """(user name, local HH:MM) of the last diagram save."""
        self.ensure_one()
        when = fields.Datetime.context_timestamp(self, self.bpmn_saved_at).strftime("%H:%M") \
            if self.bpmn_saved_at else "?"
        return self.bpmn_saved_by_id.name or self.env._("Another user"), when

    def _check_bpmn_revision(self, base):
        """Refuse a save based on an older revision than the stored one (it would drop someone else's work).
        :param str base: ``"<revision>:<token>"`` from the modeler
        :return: the editor token, stored with the new revision"""
        for rec in self:
            if rec._bpmn_newer_save(base):
                user, when = rec._bpmn_saved_label()
                raise UserError(self.env._(
                    "%(user)s saved this diagram at %(time)s, after you opened it. Your changes were not "
                    "saved, so that theirs are not lost. Use the buttons above the diagram to keep a copy "
                    "of your version or to load theirs.",
                    user=user, time=when))
        return self._parse_save_base(base)[1]

    @api.model
    def _thumbnail(self, xml):
        """Kanban thumbnail (base64 SVG) drawn on the server, so every process gets one without being opened."""
        try:
            svg = render_thumbnail(xml)
        except Exception:  # noqa: BLE001 - a thumbnail must never block a save
            _logger.info("No thumbnail for a diagram", exc_info=True)
            return False
        return base64.b64encode(svg.encode()).decode() if svg else False

    @api.model
    def _bpmn_fill_previews(self):
        """Install/upgrade pass: fill the missing thumbnails."""
        Process = self.sudo().with_context(active_test=False)
        for rec in Process.search([("diagram_preview", "=", False)]):
            preview = self._thumbnail(rec.bpmn_xml or DEFAULT_BPMN_XML)
            if preview:
                super(BusinessProcess, rec).write({"diagram_preview": preview})
        return True

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        new_version = self.env.context.get("bpmn_new_version")
        for rec, vals in zip(self, vals_list):
            if new_version:
                vals["name"] = rec.name
            elif (vals.get("name") or rec.name) == rec.name:
                vals["name"] = self.env._("%s (copy)", rec.name)
        return vals_list

    @api.depends("name", "code", "version")
    def _compute_display_name(self):
        for rec in self:
            name = rec.name or ""
            if rec.code:
                name = "[%s] %s" % (rec.code, name)
            rec.display_name = "%s (v%s)" % (name, rec.version) if rec.version else name

    def _rebuild_element_index(self):
        Element = self.env["business.process.element"].sudo()
        for rec in self:
            try:
                items = extract_elements(rec.bpmn_xml or DEFAULT_BPMN_XML)
            except BpmnError as e:
                _logger.warning("Cannot index process %s: %s", rec.id, e)
                items = []
            rec.sudo().element_ids.unlink()
            vals = []
            for it in items:
                resp = it["responsible"] or {}
                model = resp.get("model") if resp.get("model") in self.env else False
                vals.append({
                    "process_id": rec.id,
                    "element_id": it["element_id"],
                    "element_type": it["element_type"],
                    "name": it["name"],
                    "lane_name": it["lane_name"],
                    "pool_name": it["pool_name"],
                    "documentation": it["documentation"],
                    "link_count": len(it["links"]),
                    "responsible_model": model,
                    "responsible_res_id": model and resp.get("resId") or False,
                    "responsible_name": resp.get("name") or False,
                    "responsible_inherited": bool(resp.get("inherited")),
                    "review_status": "pending" if it["review"] else "none",
                    "review_reason": it["review"] and (
                        it["review"].get("reason") if it["review"].get("reason") in REVIEW_REASONS
                        else "imported") or False,
                    "review_note": (it["review"] or {}).get("note") or False,
                })
            if vals:
                Element.create(vals)

    def action_rebuild_index(self):
        self._check_manager()
        self._rebuild_element_index()
        return True

    def _write_state(self, vals):
        """State change for the action methods: skips the write() lock, keeps mail tracking."""
        return super(BusinessProcess, self).write(vals)

    def unlink(self):
        # keep the version chain valid when its first version is deleted
        # sudo: versions of other companies must follow the chain too
        for root in self.filtered(lambda r: not r.root_id):
            rest = self.sudo().with_context(active_test=False).search(
                [("root_id", "=", root.id), ("id", "not in", self.ids)], order="id")
            if rest:
                new_root = rest[0]
                super(BusinessProcess, new_root).write({"root_id": False})
                super(BusinessProcess, rest[1:]).write({"root_id": new_root.id})
        return super().unlink()

    def _check_manager(self):
        if not self.env.user.has_group("bpmn_process_management.group_process_manager"):
            raise AccessError(self.env._("Only Process Managers can do this."))

    def action_submit_review(self):
        self._check_manager()
        for rec in self:
            if rec.state != "draft":
                raise UserError(self.env._("Only drafts can be submitted for review."))
        self._write_state({"state": "review"})
        return True

    def action_back_to_draft(self):
        self._check_manager()
        for rec in self:
            if rec.state != "review":
                raise UserError(self.env._("Only versions in review can go back to draft."))
        self._write_state({"state": "draft"})
        return True

    def _previous_release(self):
        """Newest other version of the chain that was ever published (published or deprecated)."""
        self.ensure_one()
        if not self.id:
            return self.browse()
        return self.sudo().with_context(active_test=False).search(
            self._lineage_domain() + [("id", "!=", self.id), ("state", "in", ("published", "deprecated"))],
            order="id desc", limit=1)

    def _release_numbers(self):
        """(small, major) numbers this draft gets when published; a typed number that goes further is kept."""
        self.ensure_one()
        prev = self._previous_release()
        if not prev:
            return self.version, self.version
        pmaj, pmin = self._split_version(prev.version)
        cmaj, cmin = self._split_version(self.version)
        small = self.version if (cmaj == pmaj and cmin > pmin) else self._next_version(prev.version)
        major = self.version if cmaj > pmaj else self._next_version(prev.version, major=True)
        return small, major

    @staticmethod
    def _split_version(version):
        m = re.match(r"^\s*(\d+)(?:\.(\d+))?", version or "")
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)

    def action_open_publish(self):
        """Publication dialog: the manager says whether it is a small or a major change."""
        self._check_manager()
        self.ensure_one()
        if self.state not in ("draft", "review"):
            raise UserError(self.env._("Only drafts or versions in review can be published."))
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Publish %s", self.display_name),
            "res_model": "business.process.publish",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {"default_process_id": self.id},
        }

    def action_publish(self, change_type=None, change_note=None):
        """Publish. ``change_type`` "minor" (default) keeps the read confirmations;
        "major" renumbers and asks everyone to read again."""
        self._check_manager()
        for rec in self:
            if rec.state not in ("draft", "review"):
                raise UserError(self.env._("Only drafts or versions in review can be published."))
            # sudo after the manager check: the whole chain, all companies, archived too
            previous = rec._previous_release()
            kind = "first" if not previous else ("major" if change_type == "major" else "minor")
            if previous:
                small, major = rec._release_numbers()
                number = major if kind == "major" else small
                if number != rec.version:
                    super(BusinessProcess, rec).write({"version": number})
            chain = self.sudo().with_context(active_test=False).search(
                rec._lineage_domain() + [("id", "!=", rec.id)])
            older = chain.filtered(lambda r: r.state == "published")
            older._write_state({"state": "deprecated"})
            older.activity_ids.filtered(
                lambda a: a.summary == self.env._("Periodic process review")).unlink()
            # sub-processes follow the new version of their parent
            chain.with_context(active_test=False).search(
                [("parent_id", "in", chain.ids)]).write({"parent_id": rec.id})
            vals = {"state": "published", "published_date": fields.Datetime.now(),
                    "published_by_id": self.env.user.id, "change_type": kind,
                    "change_note": (change_note or "").strip() or False}
            if rec.review_interval > 0:
                vals["next_review_date"] = fields.Date.today() + relativedelta(months=rec.review_interval)
            rec._write_state(vals)
            if kind == "minor" and previous:
                rec._carry_over_acks(previous)
            body = {
                "first": self.env._("Version %(version)s was published.", version=rec.version),
                "minor": self.env._("Version %(version)s was published as a small change: read "
                                    "confirmations of version %(previous)s are kept.",
                                    version=rec.version, previous=previous.version),
                "major": self.env._("Version %(version)s was published as a major change: everyone "
                                    "is asked to read it again.", version=rec.version),
            }[kind]
            if vals["change_note"]:
                body += " " + self.env._("What changed: %s", vals["change_note"])
            if rec.review_count:
                body += " " + self.env._("%(count)s diagram items are still flagged for review.",
                                         count=rec.review_count)
            rec.message_post(body=body, subtype_xmlid="mail.mt_comment")
        return True

    def _carry_over_acks(self, previous):
        """Small change: whoever confirmed the previous version does not need to confirm again."""
        self.ensure_one()
        Ack = self.env["business.process.ack"].sudo()
        done = set(Ack.search([("process_id", "=", self.id), ("version", "=", self.version)]).user_id.ids)
        Ack.create([{"process_id": self.id, "user_id": a.user_id.id, "version": self.version,
                     "date": a.date, "carried_over": True}
                    for a in Ack.search([("process_id", "=", previous.id), ("version", "=", previous.version)])
                    if a.user_id.id not in done])

    def action_acknowledge(self):
        """Current user confirms having read the published version."""
        for rec in self:
            if rec.state != "published":
                raise UserError(self.env._("Only published processes can be confirmed."))
            if not rec.is_acknowledged:
                self.env["business.process.ack"].sudo().create({
                    "process_id": rec.id, "user_id": self.env.uid, "version": rec.version})
        return True

    def action_view_acks(self):
        self.ensure_one()
        self._check_manager()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Read Confirmations"),
            "res_model": "business.process.ack",
            "view_mode": "list",
            "views": [[False, "list"]],
            "domain": [("process_id", "=", self.id)],
            "context": {"search_default_group_version": 1},
        }

    @api.model
    def _cron_review_reminders(self):
        """To-do for the owner when a published process is due for its periodic review."""
        todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        due = self.search([("state", "=", "published"), ("next_review_date", "!=", False),
                           ("next_review_date", "<=", fields.Date.today()), ("owner_id", "!=", False)])
        summary = self.env._("Periodic process review")
        for rec in due:
            if todo and rec.activity_ids.filtered(
                    lambda a, t=todo: a.activity_type_id == t and a.summary == summary):
                continue
            rec.activity_schedule(
                "mail.mail_activity_data_todo", date_deadline=rec.next_review_date, summary=summary,
                note=self.env._("Check that the process still matches reality; create a new version "
                                "if something changed."),
                user_id=rec.owner_id.id)
            # next cycle: the to-do is the reminder, the date moves on (no daily repeats)
            if rec.review_interval > 0:
                step = relativedelta(months=rec.review_interval)
                rec.next_review_date = max(rec.next_review_date + step, fields.Date.today() + step)
            else:
                rec.next_review_date = False
        return True

    def action_deprecate(self):
        """Withdraw a published process without a replacement; it leaves the Process Map, stays in All Processes."""
        self._check_manager()
        todo = self.filtered(lambda r: r.state == "published")
        todo._write_state({"state": "deprecated"})
        for rec in todo:
            rec.message_post(body=self.env._(
                "Version %s was deprecated: employees no longer see it in the Process Map.", rec.version))
        return True

    def action_restore(self):
        """Undo a deprecation, unless another version of the process was published meanwhile."""
        self._check_manager()
        for rec in self:
            if rec.state != "deprecated":
                raise UserError(self.env._("Only deprecated versions can be restored."))
            chain = self.sudo().with_context(active_test=False).search(
                rec._lineage_domain() + [("id", "!=", rec.id), ("state", "=", "published")])
            if chain:
                raise UserError(self.env._(
                    "Version %s of this process is published. Only one version can be valid at a time.",
                    chain[0].version))
            rec._write_state({"state": "published"})
            rec.message_post(body=self.env._("Version %s was restored and is published again.", rec.version))
        return True

    def action_open_other_version(self):
        """Open the version to work on (see other_version_id)."""
        self.ensure_one()
        target = self.other_version_id
        if not target:
            return False
        return {"type": "ir.actions.act_window", "res_model": "business.process", "res_id": target.id,
                "view_mode": "form", "views": [[False, "form"]], "target": "current"}

    @staticmethod
    def _next_version(version, major=False):
        m = re.match(r"^\s*(\d+)(?:\.(\d+))?", version or "")
        if not m:
            return "2.0" if major else "1.1"
        a, b = int(m.group(1)), int(m.group(2) or 0)
        return "%d.0" % (a + 1) if major else "%d.%d" % (a, b + 1)

    def action_new_version(self):
        """Editable draft copy of the latest version, next minor number (1.0 -> 1.1); major is decided at publish."""
        self._check_manager()
        self.ensure_one()
        versions = self.sudo().with_context(active_test=False).search(self._lineage_domain())
        latest = versions.sorted("id")[-1]
        open_version = versions.filtered(lambda v: v.active and v.state in ("draft", "review"))[:1]
        if open_version:
            # a second draft would fork the process: continue the one in preparation
            return {"type": "ir.actions.act_window", "res_model": "business.process",
                    "res_id": open_version.id, "view_mode": "form", "views": [[False, "form"]],
                    "target": "current"}
        latest_active = versions.filtered("active").sorted("id")[-1:]
        if latest_active and self != latest_active:
            raise UserError(self.env._(
                "Create the new version from the latest version (%s).", latest_active.version))
        new_version = self._next_version(latest.version)
        new = self.with_context(bpmn_new_version=True).copy({
            "version": new_version,
            "state": "draft",
            "code": self.code,
            "root_id": (self.root_id or self).id,
            "previous_version_id": self.id,
        })
        new.message_post(body=self.env._("Created from version %s.", self.version))
        return {
            "type": "ir.actions.act_window",
            "res_model": "business.process",
            "res_id": new.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
        }

    def action_view_versions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Versions"),
            "res_model": "business.process",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": self._lineage_domain(),
            "context": {"active_test": False},
        }

    def action_view_review_items(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Items to Review"),
            "res_model": "business.process.element",
            "view_mode": "list",
            "views": [[False, "list"]],
            "domain": [("process_id", "=", self.id), ("review_status", "=", "pending")],
        }

    def action_export_bpmn(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/bpmn_process_management/export/%s/bpmn" % self.id}

    def action_export_drawio(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/bpmn_process_management/export/%s/drawio" % self.id}

    def action_open_import(self):
        self.ensure_one()
        self._check_manager()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Import Diagram"),
            "res_model": "business.process.import",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {"default_process_id": self.id, "default_mode": "replace"},
        }

    def action_match_responsibles(self):
        """Re-run automatic matching of lanes to departments / groups."""
        self._check_manager()
        for rec in self:
            if rec.state != "draft":
                raise UserError(self.env._("Only drafts can be modified."))
            xml, matched, missing = apply_responsible_matching(
                rec.bpmn_xml, rec._responsible_matcher())
            rec.bpmn_xml = xml
            rec.message_post(body=self.env._(
                "Responsibility matching: %(matched)s matched, %(missing)s without a match.",
                matched=matched, missing=missing))
        return True

    # helpers used by the import wizard and the web client
    @api.model
    def _responsible_matcher(self):
        """Return a callable name -> responsible dict: departments, job positions, groups (exact name, any case)."""
        cache = {}

        def match(name):
            key = (name or "").strip().lower()
            if not key:
                return None
            if key in cache:
                return cache[key]
            found = None
            for model in ("hr.department", "hr.job", "res.groups"):
                if model not in self.env:
                    continue
                Model = self.env[model]
                domain = [("name", "=ilike", escape_like(name.strip()))]
                if "company_id" in Model._fields:
                    domain.append(("company_id", "in", [False, self.env.company.id]))
                recs = Model.search(domain, limit=2)
                if len(recs) == 1:
                    found = self._responsible_payload(recs)
                    break
            cache[key] = found
            return found
        return match

    @api.model
    def _responsible_payload(self, record):
        xmlid = record.get_external_id().get(record.id) or False
        if xmlid and xmlid.startswith("__"):
            xmlid = False
        return {"model": record._name, "resId": record.id, "xmlid": xmlid,
                "name": record.display_name}

    @api.model
    def bpmn_get_options(self):
        """Capabilities for the diagram editor (depends on installed apps)."""
        record_models = []
        for model in RECORD_LINK_MODELS:
            if model in self.env and self.env[model].has_access("read"):
                record_models.append({"model": model,
                                      "label": self.env["ir.model"]._get(model).name})
        responsible = []
        for model in RESPONSIBLE_MODELS:
            if model in self.env and self.env[model].has_access("read"):
                responsible.append({"model": model,
                                    "label": self.env["ir.model"]._get(model).name})
        can_create = [m for m in CREATABLE_MODELS if m in self.env and self.env[m].has_access("create")]
        return {"record_models": record_models, "responsible_models": responsible,
                "can_create": can_create,
                "is_manager": self.env.user.has_group(
                    "bpmn_process_management.group_process_manager")}

    @api.model
    def bpmn_search_targets(self, kind, term="", model=None, limit=8, process_id=None):
        """Autocomplete for links and responsibilities in the modeler."""
        self._check_manager()
        term = (term or "").strip()
        limit = min(int(limit or 8), 20)
        if kind == "menu":
            Menu = self.env["ir.ui.menu"]
            visible = Menu.browse(Menu._visible_menu_ids())
            menus = visible.filtered(lambda m: m.action and (
                not term or term.lower() in (m.complete_name or "").lower()))
            menus = menus.sorted(lambda m: len(m.complete_name or ""))[:limit]
            return [{"resId": m.id, "name": m.complete_name,
                     "xmlid": self._xmlid(m)} for m in menus]
        if kind == "action":
            acts = self.env["ir.actions.act_window"].search(
                [("name", "ilike", term)] if term else [], limit=limit)
            return [{"resId": a.id, "name": "%s (%s)" % (a.name, a.res_model),
                     "xmlid": self._xmlid(a)} for a in acts]
        if kind in ("record", "responsible"):
            allowed = RECORD_LINK_MODELS if kind == "record" else RESPONSIBLE_MODELS
            if model not in allowed or model not in self.env:
                return []
            Model = self.env[model]
            Model.check_access("read")
            domain = []
            if model == "ir.attachment":
                # only the files attached to this process (all its versions)
                proc = self.browse(int(process_id)).exists() if process_id else self.browse()
                ids = self.with_context(active_test=False).search(proc._lineage_domain()).ids if proc else []
                domain = [("res_model", "=", "business.process"), ("res_id", "in", ids)]
            if term:
                recs = Model.search(domain + [(Model._rec_name or "name", "ilike", term)], limit=limit) \
                    if domain else Model.browse([rid for rid, _name in Model.name_search(term, limit=limit)])
            else:
                recs = Model.search(domain, limit=limit)
            return [{"resId": r.id, "name": r.display_name, "xmlid": self._xmlid(r)}
                    for r in recs]
        return []

    @api.model
    def bpmn_editing_ping(self, process_id, leaving=False, base=None):
        """Presence heartbeat of the modeler; ``base`` is the editor's ``"<revision>:<token>"``.
        :return: {"others": [{name, since}], "conflict": False or {user, time}}: managers with the diagram open;
            who saved after this editor read it (next save refused)"""
        self._check_manager()
        Editor = self.env["business.process.editor"].sudo()
        now = fields.Datetime.now()
        Editor.search([("heartbeat", "<", now - Editor.STALE)]).unlink()
        proc = self.browse(int(process_id)).exists()
        if not proc:
            return {"others": [], "conflict": False}
        proc.check_access("read")
        mine = Editor.search([("process_id", "=", proc.id), ("user_id", "=", self.env.uid)])
        if leaving:
            mine.unlink()
            return {"others": [], "conflict": False}
        if mine:
            mine.write({"heartbeat": now})
        else:
            Editor.create({"process_id": proc.id, "user_id": self.env.uid, "since": now, "heartbeat": now})
        others = Editor.search([("process_id", "=", proc.id), ("user_id", "!=", self.env.uid)])
        conflict = False
        if base and proc._bpmn_newer_save(base):
            user, when = proc._bpmn_saved_label()
            conflict = {"user": user, "time": when}
        return {"others": [{"name": o.user_id.name, "since": fields.Datetime.to_string(o.since)} for o in others],
                "conflict": conflict}

    @api.model
    def bpmn_print_info(self, process_id):
        """Header data for the printed diagram, formatted in the user's language and time zone."""
        proc = self.browse(int(process_id)).exists() if process_id else self.browse()
        now = format_datetime(self.env, fields.Datetime.now())
        info = {"printed_at": now, "printed_by": self.env.user.name}
        if not proc:
            return info
        proc.check_access("read")

        def label(field):
            return dict(proc._fields[field]._description_selection(self.env)).get(proc[field], "")

        info.update({
            "name": proc.name,
            "code": proc.code or "",
            "version": proc.version or "",
            "state": label("state"),
            "state_key": proc.state,
            "category": label("category"),
            "level": label("level"),
            "owner": proc.owner_id.name or "",
            "company": proc.company_id.name or "",
            "published": format_date(self.env, proc.published_date) if proc.published_date else "",
            "published_by": proc.published_by_id.name or "",
            "saved_at": format_datetime(self.env, proc.bpmn_saved_at) if proc.bpmn_saved_at else "",
            "description": html2plaintext(proc.description or "").strip()
            if not is_html_empty(proc.description) else "",
            "sipoc": [[proc._fields[f]._description_string(self.env), proc[f].strip()]
                      for f in ("trigger", "supplier", "process_input", "process_output", "customer")
                      if (proc[f] or "").strip()],
        })
        return info

    @api.model
    def bpmn_create_target(self, model, name):
        """Create, from the modeler, the record a step links to (a Knowledge article or a process)."""
        self._check_manager()
        name = (name or "").strip()
        if not name:
            raise UserError(self.env._("Type a name first."))
        if model not in CREATABLE_MODELS or model not in self.env:
            raise UserError(self.env._("Records of this kind cannot be created from the diagram."))
        rec = self.env[model].create({"name": name})
        return {"resId": rec.id, "name": rec.display_name, "xmlid": False}

    @api.model
    def _xmlid(self, record):
        xmlid = record.get_external_id().get(record.id) or False
        if xmlid and xmlid.startswith("__"):
            return False
        return xmlid

    @api.model
    def _resolve_record(self, model, res_id=None, xmlid=None):
        """Find the target of a link, preferring the portable xmlid."""
        if not model or model not in self.env:
            return self.env["ir.ui.menu"].browse()
        rec = self.env[model].browse()
        if xmlid:
            rec = self.env.ref(xmlid, raise_if_not_found=False) or self.env[model].browse()
            if rec and rec._name != model:
                rec = self.env[model].browse()
        if not rec and res_id:
            rec = self.env[model].browse(int(res_id)).exists()
        return rec

    @api.model
    def bpmn_resolve(self, refs):
        """Check links/responsibles of a diagram.
        ``refs``: dicts with ``key``, ``linkType``/``model``, ``resId``, ``xmlid``.
        Returns ``{key: {'ok': bool, 'name': str}}`` (current name if found)."""
        out = {}
        for ref in refs or []:
            key = ref.get("key")
            ltype = ref.get("linkType") or "record"
            if ltype == "url":
                out[key] = {"ok": is_safe_url(ref.get("url")), "name": ref.get("url")}
                continue
            model = {"menu": "ir.ui.menu", "action": "ir.actions.act_window"}.get(ltype, ref.get("model"))
            if model not in LINKABLE_MODELS or model not in self.env:
                out[key] = {"ok": False, "name": False}
                continue
            try:
                rec = self._resolve_record(model, ref.get("resId"), ref.get("xmlid"))
                if rec and ltype == "menu":
                    rec = rec.filtered(lambda m: m.id in self.env["ir.ui.menu"]._visible_menu_ids())
                if rec:
                    rec.check_access("read")
                out[key] = {"ok": bool(rec), "name": rec.display_name if rec else False,
                            "resId": rec.id if rec else False}
            except (AccessError, ValueError, TypeError):
                out[key] = {"ok": False, "name": False}
        return out

    @api.model
    def bpmn_open_link(self, link):
        """Return the client action for a link stored in a diagram."""
        ltype = (link or {}).get("linkType") or "record"
        if ltype == "url":
            url = (link.get("url") or "").strip()
            if not is_safe_url(url):
                raise UserError(self.env._("This link is not allowed: %s", url))
            return {"type": "ir.actions.act_url", "url": url,
                    "target": "self" if url.startswith("/") else "new"}
        if ltype == "menu":
            menu = self._resolve_record("ir.ui.menu", link.get("resId"), link.get("xmlid"))
            if not menu or menu.id not in self.env["ir.ui.menu"]._visible_menu_ids():
                raise UserError(self.env._("The linked menu does not exist or you cannot access it."))
            if not menu.action:
                raise UserError(self.env._("The linked menu has no action."))
            return {"action_id": menu.action.id, "menu_id": menu.id}
        if ltype == "action":
            act = self._resolve_record("ir.actions.act_window", link.get("resId"), link.get("xmlid"))
            if not act:
                raise UserError(self.env._("The linked action no longer exists."))
            return {"action_id": act.id}
        model = link.get("model")
        if model not in RECORD_LINK_MODELS + RESPONSIBLE_MODELS:
            raise UserError(self.env._("The linked document no longer exists."))
        rec = self._resolve_record(model, link.get("resId"), link.get("xmlid"))
        if not rec:
            raise UserError(self.env._("The linked document no longer exists."))
        rec.check_access("read")
        return {"type": "ir.actions.act_window", "res_model": rec._name, "res_id": rec.id,
                "views": [[False, "form"]], "target": "current"}
