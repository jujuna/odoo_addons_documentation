/** Part of bpmn_process_management. License LGPL-3.
 * Dashboard client action "bpmn_process_dashboard": a thin OWL component mounts a JS app drawing with DOM and SVG. */
import * as owl from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const SVG_NS = "http://www.w3.org/2000/svg";
// validated categorical order (light + dark): teal, orange, blue, amber
const CAT = ["#049978", "#F05324", "#1F6FB5", "#B98A00"];
const STATE_COLORS = { draft: "#8A9AA8", review: "#D08A00", published: "#2E8B57", deprecated: "#C3CCD3" };

function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
        if (v === undefined || v === null || v === false) {
            continue;
        }
        if (k.startsWith("on") && typeof v === "function") {
            el.addEventListener(k.slice(2), v);
        } else if (k === "class") {
            el.className = v;
        } else {
            el.setAttribute(k, v === true ? "" : v);
        }
    }
    for (const c of children.flat(Infinity)) {
        if (c === null || c === undefined || c === false) {
            continue;
        }
        el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
}

function s(tag, attrs = {}, ...children) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) {
        if (v === undefined || v === null || v === false) {
            continue;
        }
        if (k.startsWith("on") && typeof v === "function") {
            el.addEventListener(k.slice(2), v);
        } else {
            el.setAttribute(k, String(v));
        }
    }
    for (const c of children.flat(Infinity)) {
        if (c === null || c === undefined || c === false) {
            continue;
        }
        el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
}

const LIKE_SPECIAL = new RegExp("[\\\\%_]", "g");

/** Escape % _ \ for =ilike (exact, case-insensitive match). */
function likeEscape(text) {
    return (text || "").replace(LIKE_SPECIAL, (c) => "\\" + c);
}

function fmt(n) {
    if (n === null || n === undefined) {
        return "—";
    }
    return Number(n).toLocaleString();
}

function pctText(n) {
    return n === null || n === undefined ? "—" : n + "%";
}

/** Rounded data-end, square at the baseline (horizontal bar from x0). */
function hBarPath(x0, y, w, hgt, r) {
    const rr = Math.min(r, w / 2, hgt / 2);
    if (w <= 0) {
        return "";
    }
    return ["M", x0, y, "H", x0 + w - rr, "Q", x0 + w, y, x0 + w, y + rr, "V", y + hgt - rr,
        "Q", x0 + w, y + hgt, x0 + w - rr, y + hgt, "H", x0, "Z"].join(" ");
}

/** Column with rounded top, square at the baseline. */
function vBarPath(x, base, w, hgt, r) {
    const rr = Math.min(r, w / 2, hgt);
    if (hgt <= 0) {
        return "";
    }
    return ["M", x, base, "V", base - hgt + rr, "Q", x, base - hgt, x + rr, base - hgt, "H", x + w - rr,
        "Q", x + w, base - hgt, x + w, base - hgt + rr, "V", base, "Z"].join(" ");
}

function healthStatus(score) {
    if (score >= 80) {
        return { key: "good", label: _t("Good") };
    }
    if (score >= 50) {
        return { key: "fair", label: _t("Fair") };
    }
    return { key: "weak", label: _t("Weak") };
}

export class ProcessDashboardApp {
    constructor(host, services) {
        this.host = host;
        this.orm = services.orm;
        this.action = services.action;
        this.options = { scope: "published", categories: [], levels: [], tag_ids: [] };
        this.sort = { key: "complexity", dir: -1 };
        this.data = null;
        this.root = h("div", { "class": "o_bpmn_dash" });
        this.tip = h("div", { "class": "o_bpmn_dash_tip", role: "tooltip" });
        this.host.replaceChildren(this.root, this.tip);
        this.onScroll = () => this.hideTip();
        this.host.addEventListener("scroll", this.onScroll, { passive: true });
    }

    async start() {
        this.root.replaceChildren(h("div", { "class": "o_bpmn_dash_loading" }, _t("Loading dashboard...")));
        await this.load();
    }

    /** Load the figures; only the answer to the latest request is shown. */
    async load() {
        const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
        let data;
        try {
            data = await this.orm.call("business.process", "bpmn_dashboard", [this.options]);
        } catch (e) {
            if (seq !== this.loadSeq) {
                return;
            }
            this.hideTip();
            const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
            const alert = h("div", { "class": "alert alert-danger m-3" }, msg);
            if (this.data) {
                this.render();
                this.root.insertBefore(alert, this.root.children[1] || null);
            } else {
                this.root.replaceChildren(alert);
            }
            return;
        }
        if (seq !== this.loadSeq) {
            return;
        }
        this.data = data;
        this.render();
    }

    destroy() {
        this.host.removeEventListener("scroll", this.onScroll);
    }

    showTip(ev, lines) {
        this.tip.replaceChildren(...lines.map((l, i) => h(i ? "div" : "b", {}, l)));
        this.tip.classList.add("show");
        const pad = 14;
        const hostRect = this.host.getBoundingClientRect();
        let x = ev.clientX - hostRect.left + this.host.scrollLeft + pad;
        let y = ev.clientY - hostRect.top + this.host.scrollTop + pad;
        const w = this.tip.offsetWidth, hh = this.tip.offsetHeight;
        if (x + w > this.host.scrollLeft + this.host.clientWidth - 8) {
            x = x - w - 2 * pad;
        }
        if (y + hh > this.host.scrollTop + this.host.clientHeight - 8) {
            y = y - hh - 2 * pad;
        }
        this.tip.style.left = Math.max(4, x) + "px";
        this.tip.style.top = Math.max(4, y) + "px";
    }

    hideTip() {
        this.tip.classList.remove("show");
    }

    bindTip(el, lines) {
        el.addEventListener("mousemove", (ev) => this.showTip(ev, lines));
        el.addEventListener("mouseleave", () => this.hideTip());
        return el;
    }

    openProcesses(name, domain) {
        this.hideTip();
        return this.action.doAction({
            type: "ir.actions.act_window", name, res_model: "business.process",
            views: [[false, "list"], [false, "kanban"], [false, "form"]], domain,
        });
    }

    openProcess(id) {
        this.hideTip();
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: "business.process", res_id: id,
            views: [[false, "form"]],
        });
    }

    openRole(role) {
        this.hideTip();
        const domain = role.assigned && role.model
            ? [["responsible_model", "=", role.model], ["responsible_res_id", "=", role.res_id]]
            : ["|", ["lane_name", "=ilike", likeEscape(role.label)], "&", ["lane_name", "=", false],
                ["pool_name", "=ilike", likeEscape(role.label)]];
        for (const leaf of this.scopeDomain()) {
            domain.push(["process_id." + leaf[0], leaf[1], leaf[2]]);
        }
        return this.action.doAction({
            type: "ir.actions.act_window", name: role.label, res_model: "business.process.element",
            views: [[false, "list"]], domain,
        });
    }

    /** Same selection as the figures: scope + category / level / tag filters. */
    scopeDomain() {
        const o = this.options;
        const domain = this.data.scope === "published" ? [["state", "=", "published"]]
            : [["state", "in", ["draft", "review", "published"]], ["is_latest_candidate", "=", true]];
        if (o.categories.length) {
            domain.push(["category", "in", o.categories.slice()]);
        }
        if (o.levels.length) {
            domain.push(["level", "in", o.levels.slice()]);
        }
        if (o.tag_ids.length) {
            domain.push(["tag_ids", "in", o.tag_ids.slice()]);
        }
        return domain;
    }

    render() {
        const d = this.data;
        this.hideTip();
        this.root.replaceChildren(
            this.renderHeader(),
            this.renderTiles(),
            d.totals.processes ? h("div", { "class": "o_bpmn_dash_grid" },
                this.card(_t("Workload by role"), _t("Steps each role performs; click a bar to see its steps"),
                    this.renderWorkload(), "o_bpmn_dash_wide"),
                this.card(_t("Portfolio"), _t("Processes by type and level"), this.renderPortfolio()),
                this.card(_t("Handoffs between roles"),
                    _t("How often work passes from one role (row) to another (column)"), this.renderMatrix(),
                    "o_bpmn_dash_wide"),
                this.card(_t("Publications"), _t("Versions published per month, last 12 months"),
                    this.renderTimeline()),
                this.card(_t("Process health"),
                    _t("Documentation quality of each process; click a row to open it"),
                    this.renderTable(), "o_bpmn_dash_full"),
                this.card(_t("Upcoming reviews"), _t("Periodic reviews due in the next 90 days"),
                    this.renderReviews()),
                d.is_manager && d.acks && d.acks.processes
                    ? this.card(_t("Read confirmations"), _t("Share of internal users who confirmed the current version"),
                        this.renderAcks()) : null,
            ) : h("div", { "class": "o_bpmn_dash_empty" },
                h("b", {}, _t("No process matches these filters yet.")),
                h("div", {}, _t("Publish processes, or widen the filters, to see the figures."))),
        );
    }

    card(title, subtitle, body, cls) {
        return h("section", { "class": "o_bpmn_dash_card" + (cls ? " " + cls : "") },
            h("header", {}, h("h3", {}, title), subtitle ? h("p", {}, subtitle) : null),
            h("div", { "class": "o_bpmn_dash_body" }, body));
    }

    renderHeader() {
        const d = this.data;
        const o = this.options;
        const seg = (value, label) => h("button", {
            type: "button", "class": "o_bpmn_dash_seg" + (o.scope === value ? " active" : ""),
            "aria-pressed": o.scope === value ? "true" : "false",
            onclick: () => {
                o.scope = value;
                this.load();
            },
        }, label);
        const toggle = (list, key) => {
            const i = list.indexOf(key);
            if (i === -1) {
                list.push(key);
            } else {
                list.splice(i, 1);
            }
            this.load();
        };
        const chip = (active, label, onclick, color) => h("button", {
            type: "button", "class": "o_bpmn_dash_chip" + (active ? " active" : ""),
            "aria-pressed": active ? "true" : "false", onclick,
        }, color ? h("i", { style: "background:" + color }) : null, label);
        const filters = [];
        d.categories.forEach((c, i) => filters.push(chip(o.categories.includes(c.key), c.label,
            () => toggle(o.categories, c.key), CAT[i % CAT.length])));
        const levelSel = h("select", { "class": "o_bpmn_dash_select", "aria-label": _t("Level") },
            h("option", { value: "" }, _t("All levels")),
            d.levels.filter((l) => l.key).map((l) => h("option", { value: l.key,
                selected: o.levels[0] === l.key ? true : null }, l.label)));
        levelSel.addEventListener("change", () => {
            o.levels = levelSel.value ? [levelSel.value] : [];
            this.load();
        });
        filters.push(levelSel);
        if (d.tags.length) {
            const tagSel = h("select", { "class": "o_bpmn_dash_select", "aria-label": _t("Tag") },
                h("option", { value: "" }, _t("All tags")),
                d.tags.map((t) => h("option", { value: String(t.id),
                    selected: o.tag_ids[0] === t.id ? true : null }, t.name)));
            tagSel.addEventListener("change", () => {
                o.tag_ids = tagSel.value ? [parseInt(tagSel.value, 10)] : [];
                this.load();
            });
            filters.push(tagSel);
        }
        return h("header", { "class": "o_bpmn_dash_head" },
            h("div", {},
                h("div", { "class": "o_bpmn_dash_eyebrow" }, _t("Business processes")),
                h("h1", {}, _t("Process dashboard")),
                h("p", {}, d.scope === "published" ? _t("Published processes")
                    : _t("Current version of every process, drafts in progress included"))),
            h("div", { "class": "o_bpmn_dash_filters" },
                d.is_manager ? h("div", { "class": "o_bpmn_dash_segs", role: "group", "aria-label": _t("Scope") },
                    seg("published", _t("Published")), seg("current", _t("Including drafts"))) : null,
                filters,
                h("button", { type: "button", "class": "o_bpmn_dash_refresh", title: _t("Refresh"),
                    "aria-label": _t("Refresh"), onclick: () => this.load() }, "↻"),
                h("a", { "class": "o_bpmn_dash_refresh o_bpmn_dash_help", href: "/bpmn_process_management/guide#dashboard",
                    target: "_blank", rel: "noopener", title: _t("What the dashboard shows (user guide)"),
                    "aria-label": _t("What the dashboard shows (user guide)") }, "?")));
    }

    renderTiles() {
        const t = this.data.totals;
        const tile = (label, value, sub, meter, extra) => h("div", {
            "class": "o_bpmn_dash_tile" + (extra && extra.cls ? " " + extra.cls : ""),
            role: extra && extra.onclick ? "button" : null, tabindex: extra && extra.onclick ? "0" : null,
            onclick: extra && extra.onclick },
        h("span", { "class": "o_bpmn_dash_tile_label" }, label),
        h("b", {}, value),
        meter !== undefined && meter !== null ? h("span", { "class": "o_bpmn_dash_meter" },
            h("i", { style: "width:" + Math.max(0, Math.min(100, meter)) + "%" })) : null,
        sub ? h("small", {}, sub) : null);
        const tiles = [
            tile(_t("Processes"), fmt(t.processes), _t("Decisions in total: %s", fmt(t.decisions)), null,
                { cls: "o_bpmn_dash_tile_hero", onclick: () => this.openProcesses(_t("Processes"), this.scopeDomain()) }),
            tile(_t("Steps"), fmt(t.steps), _t("Handoffs between roles: %s", fmt(t.handoffs))),
            tile(_t("Roles"), fmt(t.roles), _t("%s of lanes have an Odoo responsible", pctText(t.resp_pct)), t.resp_pct),
            tile(_t("Work instructions"), pctText(t.doc_pct), _t("of steps have an instruction"), t.doc_pct),
            tile(_t("Linked to Odoo"), pctText(t.link_pct), _t("of steps open an Odoo screen"), t.link_pct),
            tile(_t("Reviews overdue"), fmt(t.overdue), _t("periodic review date passed"), null,
                { cls: t.overdue ? "o_bpmn_dash_tile_warn" : "" }),
        ];
        if (this.data.is_manager) {
            tiles.push(tile(_t("Items to review"), fmt(t.review_items), _t("flagged after import or change"), null,
                { cls: t.review_items ? "o_bpmn_dash_tile_warn" : "" }));
        }
        return h("div", { "class": "o_bpmn_dash_tiles" }, tiles);
    }

    renderWorkload() {
        const rows = this.data.workload;
        if (!rows.length) {
            return h("p", { "class": "o_bpmn_dash_muted" }, _t("No lanes yet: draw lanes to see who does what."));
        }
        const max = Math.max(1, ...rows.map((r) => r.steps));
        const list = h("div", { "class": "o_bpmn_dash_bars" });
        for (const r of rows) {
            const w = Math.round(100 * r.steps / max);
            const svg = s("svg", { "class": "o_bpmn_dash_barsvg", viewBox: "0 0 100 16", preserveAspectRatio: "none",
                "aria-hidden": "true" },
            s("rect", { x: 0, y: 0, width: 100, height: 16, rx: 4, "class": "o_bpmn_dash_track" }),
            r.steps ? s("path", { d: hBarPath(0, 0, Math.max(w, 1.5), 16, 3), fill: CAT[0] }) : null);
            const row = h("button", { type: "button", "class": "o_bpmn_dash_barrow",
                onclick: () => this.openRole(r) },
            h("span", { "class": "o_bpmn_dash_barlabel", title: r.label }, r.label,
                r.external ? h("em", { "class": "o_bpmn_dash_external", title: _t("Outside party (collapsed pool): customer, supplier, authority...") }, _t("outside party"))
                    : r.assigned ? null : h("em", { title: _t("No Odoo responsible assigned") }, _t("no responsible"))),
            h("span", { "class": "o_bpmn_dash_bar" }, svg),
            h("span", { "class": "o_bpmn_dash_barval" }, fmt(r.steps)),
            h("span", { "class": "o_bpmn_dash_barmeta" },
                _t("Processes: %s · handoffs: %s", r.processes, r.handoffs_out + r.handoffs_in)));
            this.bindTip(row, [r.label,
                _t("Steps: %s", fmt(r.steps)), _t("Decisions: %s", fmt(r.decisions)),
                _t("Processes: %s", fmt(r.processes)),
                _t("Hands work over: %s · receives: %s", r.handoffs_out, r.handoffs_in),
                _t("Steps with instruction: %s", pctText(r.doc_pct)),
                r.external ? _t("Outside party (collapsed pool): customer, supplier, authority...")
                    : r.assigned ? _t("Odoo responsible assigned") : _t("No Odoo responsible assigned")]);
            list.append(row);
        }
        const other = this.data.workload_other;
        return h("div", {}, h("div", { "class": "o_bpmn_dash_axisnote" }, _t("Steps")), list,
            other ? h("p", { "class": "o_bpmn_dash_muted small mt-2" },
                _t("Other roles: %s, with %s steps in total", other.count, fmt(other.steps))) : null);
    }

    renderMatrix() {
        const m = this.data.matrix;
        const n = m.roles.length;
        if (n < 2) {
            return h("p", { "class": "o_bpmn_dash_muted" },
                _t("No handoff yet: they appear when a flow goes from one lane to another."));
        }
        const max = Math.max(1, ...m.values.flat());
        const table = h("table", { "class": "o_bpmn_dash_matrix" });
        const head = h("tr", {}, h("th", { "class": "o_bpmn_dash_corner" },
            h("span", {}, _t("from")), " → ", h("span", {}, _t("to"))));
        m.roles.forEach((r) => head.append(h("th", { scope: "col", title: r.label },
            h("div", { "class": "o_bpmn_dash_colhead" }, h("span", {}, r.label)))));
        table.append(h("thead", {}, head));
        const body = h("tbody");
        m.values.forEach((row, i) => {
            const tr = h("tr", {}, h("th", { scope: "row", title: m.roles[i].label }, m.roles[i].label));
            row.forEach((v, j) => {
                const t = v / max;
                const td = h("td", {});
                if (i === j) {
                    td.className = "o_bpmn_dash_diag";
                } else if (v) {
                    const cell = h("button", { type: "button", "class": "o_bpmn_dash_cell" + (t > 0.55 ? " dark" : ""),
                        style: "background: rgba(4, 153, 120, " + (0.14 + 0.86 * t).toFixed(2) + ")",
                        "aria-label": m.roles[i].label + " → " + m.roles[j].label + ": " + v,
                        onclick: () => this.openProcesses(m.roles[i].label + " → " + m.roles[j].label,
                            [["id", "in", m.cells[i + "," + j] || []]]) }, String(v));
                    this.bindTip(cell, [m.roles[i].label + " → " + m.roles[j].label,
                        _t("Handoffs: %s · processes: %s", v, (m.cells[i + "," + j] || []).length)]);
                    td.append(cell);
                }
                tr.append(td);
            });
            body.append(tr);
        });
        table.append(body);
        return h("div", {},
            h("div", { "class": "o_bpmn_dash_matrix_wrap" }, table),
            h("div", { "class": "o_bpmn_dash_scale" }, h("span", {}, _t("fewer")), h("i"), h("span", {}, _t("more")),
                h("small", {}, _t("Many handoffs = coordination hotspots: waiting times, lost information."))));
    }

    renderPortfolio() {
        const d = this.data;
        const cats = d.categories;
        const total = cats.reduce((a, c) => a + c.count, 0) || 1;
        const R = 54, W = 18, C = 2 * Math.PI * R;
        const donut = s("svg", { viewBox: "0 0 140 140", "class": "o_bpmn_dash_donut", role: "img",
            "aria-label": _t("Processes by type") });
        donut.append(s("circle", { cx: 70, cy: 70, r: R, fill: "none", "class": "o_bpmn_dash_track_stroke",
            "stroke-width": W }));
        let offset = 0;
        const gap = cats.filter((c) => c.count).length > 1 ? 2 : 0;
        cats.forEach((c, i) => {
            if (!c.count) {
                return;
            }
            const len = C * c.count / total;
            const seg = s("circle", { cx: 70, cy: 70, r: R, fill: "none", stroke: CAT[i % CAT.length],
                "stroke-width": W, "stroke-dasharray": Math.max(0, len - gap) + " " + (C - Math.max(0, len - gap)),
                "stroke-dashoffset": -offset, transform: "rotate(-90 70 70)", "class": "o_bpmn_dash_seg_arc",
                onclick: () => this.openProcesses(c.label, this.scopeDomain().concat([["category", "=", c.key]])) });
            this.bindTip(seg, [c.label, _t("Processes: %s (%s)", c.count, Math.round(100 * c.count / total) + "%")]);
            donut.append(seg);
            offset += len;
        });
        donut.append(s("text", { x: 70, y: 68, "text-anchor": "middle", "class": "o_bpmn_dash_donut_num" },
            String(d.totals.processes)));
        donut.append(s("text", { x: 70, y: 86, "text-anchor": "middle", "class": "o_bpmn_dash_donut_lbl" },
            _t("processes")));
        const legend = h("ul", { "class": "o_bpmn_dash_legend" }, cats.map((c, i) => h("li", {},
            h("i", { style: "background:" + CAT[i % CAT.length] }), h("span", {}, c.label), h("b", {}, fmt(c.count)))));

        const levels = d.levels;
        const lmax = Math.max(1, ...levels.map((l) => l.count));
        const colW = 26, gapW = 16, base = 96, top = 14;
        const width = levels.length * (colW + gapW);
        const lsvg = s("svg", { viewBox: "0 0 " + width + " 118", "class": "o_bpmn_dash_levels", role: "img",
            "aria-label": _t("Processes by level") });
        lsvg.append(s("line", { x1: 0, x2: width, y1: base + 0.5, y2: base + 0.5, "class": "o_bpmn_dash_axis" }));
        levels.forEach((l, i) => {
            const x = i * (colW + gapW) + gapW / 2;
            const hh = Math.round((base - top) * l.count / lmax);
            const shortLabel = l.key ? "L" + l.key : "—";
            const g = s("g", { "class": "o_bpmn_dash_col",
                onclick: () => l.count && this.openProcesses(l.label, this.scopeDomain().concat([["level", "=", l.key || false]])) });
            g.append(s("rect", { x: x - gapW / 2, y: 0, width: colW + gapW, height: 118, fill: "transparent" }));
            if (l.count) {
                g.append(s("path", { d: vBarPath(x, base, colW, Math.max(hh, 2), 4), fill: CAT[0] }));
                g.append(s("text", { x: x + colW / 2, y: base - hh - 4, "text-anchor": "middle", "class": "o_bpmn_dash_val" },
                    String(l.count)));
            }
            g.append(s("text", { x: x + colW / 2, y: base + 15, "text-anchor": "middle", "class": "o_bpmn_dash_tick" },
                shortLabel));
            this.bindTip(g, [l.label, _t("Processes: %s", l.count)]);
            lsvg.append(g);
        });

        const parts = [
            h("div", { "class": "o_bpmn_dash_portfolio" }, donut, legend),
            h("h4", { "class": "o_bpmn_dash_sub" }, _t("Architecture level")),
            lsvg,
        ];
        if (d.is_manager && d.states) {
            const stotal = d.states.reduce((a, x) => a + x.count, 0) || 1;
            const bar = h("div", { "class": "o_bpmn_dash_stack", role: "img", "aria-label": _t("Versions by status") });
            d.states.forEach((st) => {
                if (!st.count) {
                    return;
                }
                const seg = h("span", { style: "flex:" + st.count + ";background:" + STATE_COLORS[st.key] });
                this.bindTip(seg, [st.label, _t("Versions: %s (%s)", st.count, Math.round(100 * st.count / stotal) + "%")]);
                bar.append(seg);
            });
            parts.push(h("h4", { "class": "o_bpmn_dash_sub" }, _t("All versions by status")), bar,
                h("ul", { "class": "o_bpmn_dash_legend o_bpmn_dash_legend_inline" }, d.states.map((st) => h("li", {},
                    h("i", { style: "background:" + STATE_COLORS[st.key] }), h("span", {}, st.label),
                    h("b", {}, fmt(st.count))))));
        }
        return h("div", {}, parts);
    }

    renderTimeline() {
        const tl = this.data.timeline;
        const max = Math.max(1, ...tl.map((m) => m.count));
        const colW = 16, gap = 10, base = 110, top = 16, left = 4;
        const width = left + tl.length * (colW + gap);
        const svg = s("svg", { viewBox: "0 0 " + width + " 134", "class": "o_bpmn_dash_timeline", role: "img",
            "aria-label": _t("Publications per month") });
        [0.5, 1].forEach((f) => svg.append(s("line", { x1: 0, x2: width, y1: Math.round(base - (base - top) * f) + 0.5,
            y2: Math.round(base - (base - top) * f) + 0.5, "class": "o_bpmn_dash_gridline" })));
        svg.append(s("line", { x1: 0, x2: width, y1: base + 0.5, y2: base + 0.5, "class": "o_bpmn_dash_axis" }));
        const lastWithData = tl.map((m) => m.count).lastIndexOf(max);
        tl.forEach((m, i) => {
            const x = left + i * (colW + gap) + gap / 2;
            const hh = Math.round((base - top) * m.count / max);
            const label = new Date(m.year, m.month - 1, 1).toLocaleDateString(undefined, { month: "short" });
            const g = s("g", { "class": "o_bpmn_dash_col" });
            g.append(s("rect", { x: x - gap / 2, y: 0, width: colW + gap, height: 134, fill: "transparent" }));
            if (m.count) {
                g.append(s("path", { d: vBarPath(x, base, colW, Math.max(hh, 2), 4),
                    fill: i === tl.length - 1 ? CAT[0] : "#7FCDB9" }));
            }
            if (m.count && (i === lastWithData || i === tl.length - 1)) {
                g.append(s("text", { x: x + colW / 2, y: base - hh - 4, "text-anchor": "middle", "class": "o_bpmn_dash_val" },
                    String(m.count)));
            }
            if (i % 2 === (tl.length - 1) % 2) {
                g.append(s("text", { x: x + colW / 2, y: base + 16, "text-anchor": "middle", "class": "o_bpmn_dash_tick" },
                    label));
            }
            this.bindTip(g, [new Date(m.year, m.month - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" }),
                _t("Versions published: %s", m.count)]);
            svg.append(g);
        });
        return svg;
    }

    renderTable() {
        const rows = this.data.processes.slice();
        const key = this.sort.key, dir = this.sort.dir;
        const val = (r) => {
            if (key === "complexity") {
                return r.steps + 2 * r.handoffs;
            }
            if (key === "name") {
                return (r.code + " " + r.name).toLowerCase();
            }
            if (key === "next_review") {
                return r.next_review || "9999";
            }
            const v = r[key];
            return v === null || v === undefined ? -1 : v;
        };
        rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * dir);
        const th = (k, label, numeric) => {
            const active = this.sort.key === k;
            return h("th", { scope: "col", "class": numeric ? "num" : "",
                "aria-sort": active ? (dir > 0 ? "ascending" : "descending") : "none" },
            h("button", { type: "button", onclick: () => {
                this.sort = { key: k, dir: active ? -dir : (numeric ? -1 : 1) };
                this.replaceTable();
            } }, label, active ? (dir > 0 ? " ↑" : " ↓") : ""));
        };
        const meter = (p) => h("span", { "class": "o_bpmn_dash_cellmeter" },
            h("span", { "class": "o_bpmn_dash_meter" }, h("i", { style: "width:" + (p || 0) + "%" })),
            h("span", {}, pctText(p)));
        const table = h("table", { "class": "o_bpmn_dash_table" },
            h("thead", {}, h("tr", {},
                th("name", _t("Process")), th("level", _t("Level")), th("steps", _t("Steps"), true),
                th("decisions", _t("Decisions"), true), th("roles", _t("Roles"), true),
                th("handoffs", _t("Handoffs"), true), th("doc_pct", _t("Instructions"), true),
                th("resp_pct", _t("Responsible"), true), th("next_review", _t("Next review")),
                th("score", _t("Health"), true))),
            h("tbody", {}, rows.map((r) => {
                const st = healthStatus(r.score);
                const tr = h("tr", { tabindex: "0", onclick: () => this.openProcess(r.id),
                    onkeydown: (ev) => ev.key === "Enter" && this.openProcess(r.id) },
                h("td", {}, r.code ? h("span", { "class": "o_bpmn_dash_code" }, r.code) : null, h("b", {}, r.name),
                    r.state !== "published" ? h("span", { "class": "o_bpmn_dash_state" }, _t("draft / review")) : null),
                h("td", {}, r.level ? "L" + r.level : "—"),
                h("td", { "class": "num" }, fmt(r.steps)),
                h("td", { "class": "num" }, fmt(r.decisions)),
                h("td", { "class": "num" }, fmt(r.roles)),
                h("td", { "class": "num" }, fmt(r.handoffs)),
                h("td", { "class": "num" }, meter(r.doc_pct)),
                h("td", { "class": "num" }, meter(r.resp_pct)),
                h("td", {}, r.next_review ? h("span", { "class": r.overdue ? "o_bpmn_dash_overdue" : "" },
                    r.overdue ? "⚠ " : "", new Date(r.next_review + "T00:00:00").toLocaleDateString()) : "—"),
                h("td", { "class": "num" }, h("span", { "class": "o_bpmn_dash_health o_bpmn_dash_health_" + st.key },
                    h("i"), String(r.score), " ", h("small", {}, st.label))));
                return tr;
            })));
        this.tableHost = h("div", { "class": "o_bpmn_dash_table_wrap" }, table);
        return this.tableHost;
    }

    replaceTable() {
        const old = this.tableHost;
        const fresh = this.renderTable();
        if (old && old.parentNode) {
            old.parentNode.replaceChild(fresh, old);
        }
    }

    renderReviews() {
        const list = this.data.upcoming_reviews;
        if (!list.length) {
            return h("p", { "class": "o_bpmn_dash_muted" }, _t("No review due in the next 90 days."));
        }
        return h("ul", { "class": "o_bpmn_dash_list" }, list.map((r) => h("li", {},
            h("button", { type: "button", onclick: () => this.openProcess(r.id) },
                h("span", { "class": "o_bpmn_dash_date" + (r.overdue ? " o_bpmn_dash_overdue" : "") },
                    r.overdue ? "⚠ " : "", new Date(r.date + "T00:00:00").toLocaleDateString()),
                h("span", { "class": "o_bpmn_dash_listname" }, r.code ? r.code + " · " : "", r.name),
                h("small", {}, r.owner)))));
    }

    renderAcks() {
        const a = this.data.acks;
        return h("div", {},
            h("p", { "class": "o_bpmn_dash_muted small" },
                _t("Processes asking for a read confirmation: %s · internal users: %s · average: %s",
                    a.processes, a.users, a.avg_pct + "%")),
            h("ul", { "class": "o_bpmn_dash_list" }, a.rows.slice(0, 10).map((r) => h("li", {},
                h("button", { type: "button", onclick: () => this.openProcess(r.id) },
                    h("span", { "class": "o_bpmn_dash_listname" }, r.code ? r.code + " · " : "", r.name),
                    h("span", { "class": "o_bpmn_dash_cellmeter" },
                        h("span", { "class": "o_bpmn_dash_meter" }, h("i", { style: "width:" + (r.pct || 0) + "%" })),
                        h("span", {}, pctText(r.pct))),
                    h("small", {}, _t("Users: %s", r.count)))))));
    }
}

export class ProcessDashboard extends owl.Component {
    static template = owl.xml`<div class="o_bpmn_dashboard_host"/>`;

    setup() {
        const services = { orm: useService("orm"), action: useService("action") };
        owl.onMounted(() => {
            const node = this.__owl__;
            const bdom = node && node.bdom;
            const el = bdom && (bdom.el || (typeof bdom.firstNode === "function" ? bdom.firstNode() : null));
            this.app = new ProcessDashboardApp(el, services);
            this.app.start();
        });
        owl.onWillUnmount(() => this.app && this.app.destroy());
    }
}

// see bpmn_field.js: props description on Owl 2 only
if (String((owl.__info__ && owl.__info__.version) || "").startsWith("2.")) {
    ProcessDashboard.props = { "*": true };
}

registry.category("actions").add("bpmn_process_dashboard", ProcessDashboard);
