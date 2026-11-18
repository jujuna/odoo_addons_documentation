# Part of bpmn_process_management. License LGPL-3.
"""Data of the management dashboard, computed with the current user's rights.

Viewers see published processes only; review, read-confirmation and status figures go to managers only."""
import logging
from collections import defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from ..lib.bpmn_common import BpmnError
from ..lib.bpmn_stats import process_stats

_logger = logging.getLogger(__name__)

MAX_PROCESSES = 2000
MATRIX_ROLES = 10
ROLE_ROWS = 15


def _pct(part, whole):
    return round(100.0 * part / whole) if whole else None


class BusinessProcess(models.Model):
    _inherit = "business.process"

    @api.model
    def _dashboard_domain(self, options):
        is_manager = self.env.user.has_group("bpmn_process_management.group_process_manager")
        if is_manager and options.get("scope") == "current":
            domain = [("state", "in", ("draft", "review", "published")), ("is_latest_candidate", "=", True)]
        else:
            domain = [("state", "=", "published")]
        return domain + self._dashboard_filter_domain(options)

    @api.model
    def _dashboard_filter_domain(self, options):
        """Type / level / tag filters chosen in the dashboard header."""
        domain = []
        if options.get("categories"):
            domain.append(("category", "in", list(options["categories"])))
        if options.get("levels"):
            domain.append(("level", "in", list(options["levels"])))
        if options.get("tag_ids"):
            domain.append(("tag_ids", "in", [int(t) for t in options["tag_ids"]]))
        return domain

    is_latest_candidate = fields.Boolean(
        compute="_compute_is_latest_candidate", search="_search_is_latest_candidate",
        help="Technical: the version that describes the process today (the draft being "
             "prepared, otherwise the published one).")

    def _compute_is_latest_candidate(self):
        current = self.search(self._search_is_latest_candidate("=", True))
        for rec in self:
            rec.is_latest_candidate = rec in current

    def _search_is_latest_candidate(self, operator, value):
        # one version per lineage: the newest one that is not deprecated
        self.flush_model(["state", "root_id", "active"])
        self.env.cr.execute("""
            SELECT DISTINCT ON (COALESCE(root_id, id)) id
              FROM business_process
             WHERE state != 'deprecated' AND active
          ORDER BY COALESCE(root_id, id), id DESC
        """)
        ids = [r[0] for r in self.env.cr.fetchall()]
        # ('f', '=', True) arrives as ('f', 'in', [True])
        if operator in ("in", "not in"):
            values = [value] if isinstance(value, (bool, int, str)) or value is None else list(value)
            positive = (operator == "in") == (True in values)
        else:
            positive = (operator in ("=", "==")) == bool(value)
        return [("id", "in" if positive else "not in", ids)]

    @api.model
    def bpmn_dashboard(self, options=None):
        options = options or {}
        is_manager = self.env.user.has_group("bpmn_process_management.group_process_manager")
        today = fields.Date.context_today(self)
        processes = self.search(self._dashboard_domain(options), limit=MAX_PROCESSES)
        sel = lambda name: dict(self._fields[name]._description_selection(self.env))  # noqa: E731

        roles = {}
        pair_count = defaultdict(int)
        pair_processes = defaultdict(set)
        totals = defaultdict(int)
        rows = []
        for proc in processes:
            try:
                st = process_stats(proc.bpmn_xml or "")
            except BpmnError as e:
                _logger.warning("Dashboard: cannot read process %s: %s", proc.id, e)
                continue
            for key, r in st["roles"].items():
                if roles.get(key) and not r.get("external"):
                    roles[key]["external"] = False
                agg = roles.setdefault(key, {
                    "key": key, "label": r["label"], "assigned": bool(r["responsible"]),
                    "model": (r["responsible"] or {}).get("model") or False,
                    "res_id": (r["responsible"] or {}).get("resId") or False,
                    "steps": 0, "decisions": 0, "documented": 0, "linked": 0,
                    "handoffs_out": 0, "handoffs_in": 0, "process_ids": set(),
                    "external": bool(r.get("external")),
                })
                for f in ("steps", "decisions", "documented", "linked"):
                    agg[f] += r[f]
                if r["steps"] or r["decisions"] or r["events"]:
                    agg["process_ids"].add(proc.id)
            for a, b in st["handoffs"]:
                pair_count[(a, b)] += 1
                pair_processes[(a, b)].add(proc.id)
                if a in roles:
                    roles[a]["handoffs_out"] += 1
                if b in roles:
                    roles[b]["handoffs_in"] += 1
            for f in ("steps", "documented", "linked", "decisions", "lanes", "lanes_assigned"):
                totals[f] += st[f]
            totals["handoffs"] += len(st["handoffs"])

            doc_pct = _pct(st["documented"], st["steps"])
            resp_pct = _pct(st["lanes_assigned"], st["lanes"])
            link_pct = _pct(st["linked"], st["steps"])
            overdue = bool(proc.state == "published" and proc.next_review_date and proc.next_review_date < today)
            # health 0-100: who 30 + what 40 + where in Odoo 10 + reviewed on time 10 + nothing to check 10
            score = round(
                0.3 * (resp_pct if resp_pct is not None else 0)
                + 0.4 * (doc_pct if doc_pct is not None else 0)
                + 0.1 * (link_pct if link_pct is not None else 0)
                + (0 if overdue else 10)
                + (10 if not proc.review_count else max(0, 10 - 2 * proc.review_count)))
            rows.append({
                "id": proc.id, "name": proc.name, "code": proc.code or "", "version": proc.version,
                "state": proc.state, "category": proc.category, "level": proc.level or "",
                "owner": proc.owner_id.name or "", "steps": st["steps"], "decisions": st["decisions"],
                "roles": st["lanes"], "handoffs": len(st["handoffs"]), "doc_pct": doc_pct,
                "resp_pct": resp_pct, "link_pct": link_pct,
                "review_items": proc.review_count if is_manager else None,
                "next_review": fields.Date.to_string(proc.next_review_date) if proc.next_review_date else False,
                "overdue": overdue, "score": score,
            })

        # workload by role (top rows; the rest folded into "other")
        role_list = sorted(roles.values(), key=lambda r: (-r["steps"], -r["decisions"], r["label"].lower()))
        for r in role_list:
            r["processes"] = len(r.pop("process_ids"))
            r["doc_pct"] = _pct(r["documented"], r["steps"])
        other = role_list[ROLE_ROWS:]
        workload = role_list[:ROLE_ROWS]
        other_row = None
        if other:
            other_row = {"count": len(other), "steps": sum(r["steps"] for r in other),
                         "decisions": sum(r["decisions"] for r in other)}

        flow_total = defaultdict(int)
        for (a, b), n in pair_count.items():
            flow_total[a] += n
            flow_total[b] += n
        matrix_keys = [k for k, _n in sorted(flow_total.items(), key=lambda kv: -kv[1])
                       if k in roles][:MATRIX_ROLES]
        index = {k: i for i, k in enumerate(matrix_keys)}
        matrix = [[0] * len(matrix_keys) for _k in matrix_keys]
        cells = {}
        for (a, b), n in pair_count.items():
            if a in index and b in index:
                matrix[index[a]][index[b]] = n
                cells["%s,%s" % (index[a], index[b])] = sorted(pair_processes[(a, b)])[:50]

        category_labels, level_labels = sel("category"), sel("level")
        by_category = defaultdict(int)
        by_level = defaultdict(int)
        for r in rows:
            by_category[r["category"]] += 1
            by_level[r["level"] or ""] += 1

        result = {
            "is_manager": is_manager,
            "scope": options.get("scope") or "published",
            "today": fields.Date.to_string(today),
            "totals": {
                "processes": len(rows),
                "steps": totals["steps"],
                "decisions": totals["decisions"],
                "roles": len(roles),
                "handoffs": totals["handoffs"],
                "doc_pct": _pct(totals["documented"], totals["steps"]),
                "resp_pct": _pct(totals["lanes_assigned"], totals["lanes"]),
                "link_pct": _pct(totals["linked"], totals["steps"]),
                "overdue": sum(1 for r in rows if r["overdue"]),
            },
            "workload": workload,
            "workload_other": other_row,
            "matrix": {"roles": [{"key": k, "label": roles[k]["label"], "assigned": roles[k]["assigned"]}
                                 for k in matrix_keys],
                       "values": matrix, "cells": cells},
            "categories": [{"key": k, "label": category_labels[k], "count": by_category.get(k, 0)}
                           for k in category_labels],
            "levels": [{"key": k, "label": level_labels[k], "count": by_level.get(k, 0)}
                       for k in level_labels] + ([{"key": "", "label": self.env._("No level"),
                                                   "count": by_level[""]}] if by_level.get("") else []),
            "processes": sorted(rows, key=lambda r: (-r["steps"] - 2 * r["handoffs"], r["name"].lower())),
            "timeline": self._dashboard_timeline(today, options),
            "upcoming_reviews": [
                {"id": r["id"], "name": r["name"], "code": r["code"], "date": r["next_review"],
                 "owner": r["owner"], "overdue": r["overdue"]}
                for r in sorted((r for r in rows if r["next_review"] and r["state"] == "published"
                                 and r["next_review"] <= fields.Date.to_string(today + timedelta(days=90))),
                                key=lambda r: r["next_review"])][:12],
            "tags": [{"id": t.id, "name": t.name, "color": t.color}
                     for t in self.env["business.process.tag"].search([])],
        }
        if is_manager:
            result["totals"]["review_items"] = sum(r["review_items"] or 0 for r in rows)
            result["states"] = self._dashboard_states(options)
            result["acks"] = self._dashboard_acks(processes)
        return result

    @api.model
    def _dashboard_timeline(self, today, options=None):
        start = (today.replace(day=1) - relativedelta(months=11))
        versions = self.with_context(active_test=False).search_read(
            [("published_date", ">=", fields.Datetime.to_string(start))]
            + self._dashboard_filter_domain(options or {}), ["published_date"])
        counts = defaultdict(int)
        for v in versions:
            d = v["published_date"]
            counts[(d.year, d.month)] += 1
        out = []
        for i in range(12):
            m = start + relativedelta(months=i)
            out.append({"key": "%04d-%02d" % (m.year, m.month), "year": m.year, "month": m.month,
                        "count": counts.get((m.year, m.month), 0)})
        return out

    @api.model
    def _dashboard_states(self, options=None):
        labels = dict(self._fields["state"]._description_selection(self.env))
        counts = dict(self._read_group(self._dashboard_filter_domain(options or {}), ["state"], ["__count"]))
        return [{"key": k, "label": labels[k], "count": counts.get(k, 0)} for k in labels]

    @api.model
    def _dashboard_acks(self, processes):
        required = processes.filtered(lambda p: p.ack_required and p.state == "published")
        if not required:
            return {"processes": 0}
        users = self.env["res.users"].search_count([
            ("share", "=", False), ("company_ids", "in", self.env.companies.ids)])
        # only confirmations of users who still work here count
        groups = self.env["business.process.ack"].sudo()._read_group(
            [("process_id", "in", required.ids), ("user_id.active", "=", True), ("user_id.share", "=", False)],
            ["process_id", "version"], ["user_id:count_distinct"])
        counts = {(proc.id, version): n for proc, version, n in groups}
        rows = []
        for p in required:
            n = counts.get((p.id, p.version), 0)
            rows.append({"id": p.id, "name": p.name, "code": p.code or "", "count": n,
                         "pct": _pct(n, users)})
        rows.sort(key=lambda r: (r["pct"] or 0, r["name"].lower()))
        return {"processes": len(rows), "users": users, "rows": rows,
                "avg_pct": round(sum(r["pct"] or 0 for r in rows) / len(rows))}
