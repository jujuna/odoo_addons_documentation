import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useChart } from "@web/core/utils/chart_hook";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

const { DateTime } = luxon;

const PALETTE = {
    revenue: "#3B82F6",
    cost: "#EF4444",
    margin: "#10B981",
    neutral: "#94A3B8",
    series: ["#3B82F6", "#8B5CF6", "#F59E0B", "#10B981", "#EC4899", "#06B6D4", "#64748B"],
};

/** The benchmark's bands (core-banking vendor, 100 employees): below base is a problem, strong is the top tier. */
const BENCHMARKS = {
    gross: { max: 1, bands: [[0, 0.6, "danger"], [0.6, 0.72, "warning"], [0.72, 1, "success"]],
             hint: _t("base 60–70% · strong 72–80%") },
    ebitda: { max: 0.5, bands: [[0, 0.1, "danger"], [0.1, 0.25, "warning"], [0.25, 0.5, "success"]],
              hint: _t("base 10–20% · strong 25–40%") },
    recurring: { max: 1, bands: [[0, 0.3, "danger"], [0.3, 0.55, "warning"], [0.55, 1, "success"]],
                 hint: _t("base 30–50% · strong 55–70%") },
    revenue_fte: { max: 750000, bands: [[0, 150000, "danger"], [150000, 400000, "warning"], [400000, 750000, "success"]],
                   hint: _t("base 225k · strong 400–500k (USD)") },
    nrr: { max: 1.3, bands: [[0, 0.95, "danger"], [0.95, 1.05, "warning"], [1.05, 1.3, "success"]],
           hint: _t("base 95–105% · strong 105–115%+") },
    grr: { max: 1, bands: [[0, 0.85, "danger"], [0.85, 0.95, "warning"], [0.95, 1, "success"]],
           hint: _t("base 85–95% · strong 95%+") },
    standard: { max: 1, bands: [[0, 0.5, "danger"], [0.5, 0.75, "warning"], [0.75, 1, "success"]],
                hint: _t("base 50–70% · strong 75–90%") },
    utilization: { max: 1, bands: [[0, 0.6, "danger"], [0.6, 0.75, "warning"], [0.75, 1, "success"]],
                   hint: _t("base 60–75% · strong 75–85%") },
    bespoke: { max: 0.6, bands: [[0, 0.25, "success"], [0.25, 0.4, "warning"], [0.4, 0.6, "danger"]],
               hint: _t("strong below 20–25% of engineering hours") },
    rework: { max: 0.3, bands: [[0, 0.1, "success"], [0.1, 0.2, "warning"], [0.2, 0.3, "danger"]],
              hint: _t("strong below 5–10% of delivery hours") },
    budget: { max: 1.5, bands: [[0, 0.9, "danger"], [0.9, 1, "warning"], [1, 1.5, "success"]],
              hint: _t("red below 90% of budget") },
    milestones: { max: 1, bands: [[0, 0.6, "danger"], [0.6, 0.85, "warning"], [0.85, 1, "success"]],
                  hint: _t("base 60–80% · strong 85–95%") },
    golive: { max: 0.5, bands: [[0, 0.15, "success"], [0.15, 0.3, "warning"], [0.3, 0.5, "danger"]],
              hint: _t("strong below 10–15% of projects") },
    dso: { max: 120, bands: [[0, 60, "success"], [60, 75, "warning"], [75, 120, "danger"]],
           hint: _t("strong below 60–75 days") },
    conversion: { max: 1.2, bands: [[0, 0.6, "danger"], [0.6, 0.8, "warning"], [0.8, 1.2, "success"]],
                  hint: _t("strong 80–100% of EBITDA") },
    accuracy: { max: 0.4, bands: [[0, 0.1, "success"], [0.1, 0.15, "warning"], [0.15, 0.4, "danger"]],
                hint: _t("strong within ±10–15%") },
};

/** One Chart.js canvas, re-created by the parent through its t-key whenever the data changes. */
export class GecDashboardChart extends Component {
    static template = "gec_analytic_margin.DashboardChart";
    props = useProps({ config: t.function() });
    chart = useChart(() => this.props.config());
}

/** One KPI card: label, value, a line of detail, a change, a benchmark gauge. */
export class GecDashboardKpi extends Component {
    static template = "gec_analytic_margin.DashboardKpi";
    props = useProps({ card: t.object() });

    /** The 12-month sparkline as an SVG path, or null without enough points. */
    get spark() {
        const values = (this.props.card.spark || []).filter((v) => v !== false && v !== null);
        if (values.length < 2) {
            return null;
        }
        const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
        const step = 100 / (values.length - 1);
        const points = values.map((v, i) => `${(i * step).toFixed(1)},${(22 - ((v - lo) / span) * 20).toFixed(1)}`);
        return { line: `M${points.join(" L")}`, last: points.at(-1).split(",") };
    }
}

/** The ABC dashboard: draws what gec.margin.dashboard computes; figures and drill-down domains come from the server. */
export class GecAbcDashboard extends Component {
    static template = "gec_analytic_margin.Dashboard";
    static components = { GecDashboardChart, GecDashboardKpi };
    props = useProps(standardActionServiceProps);

    orm = useService("orm");
    action = useService("action");

    state = proxy({
        preset: "this_year",
        dateFrom: null,
        dateTo: null,
        planId: false,
        data: null,
        loading: true,
        version: 0,
        tab: "overview",
        printAll: false,
        proof: null,
    });

    lastRequestId = 0;

    setup() {
        this.colorScheme = cookie.get("color_scheme");
        this.applyPreset("this_year");
        this.restore();
        onWillStart(() => this.load());
    }

    static STORAGE_KEY = "gec_abc_dashboard";

    restore() {
        try {
            const saved = JSON.parse(window.localStorage.getItem(GecAbcDashboard.STORAGE_KEY) || "null");
            if (!saved) {
                return;
            }
            if (saved.preset && saved.preset !== "custom") {
                this.applyPreset(saved.preset);
            } else if (saved.dateFrom && saved.dateTo) {
                Object.assign(this.state, { preset: "custom", dateFrom: saved.dateFrom, dateTo: saved.dateTo });
            }
            this.state.planId = saved.planId || false;
            this.state.tab = saved.tab || "overview";
        } catch {
            // private window, quota or corrupted value: defaults
        }
    }

    persist() {
        try {
            const { preset, dateFrom, dateTo, planId, tab } = this.state;
            window.localStorage.setItem(GecAbcDashboard.STORAGE_KEY,
                JSON.stringify({ preset, dateFrom, dateTo, planId, tab }));
        } catch {
            // the dashboard works without it
        }
    }

    /** Every tab one after the other, then the browser's print dialog (Save as PDF). */
    async print() {
        this.state.printAll = true;
        this.state.version++;
        // Charts animate on mount; give them time.
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const done = () => {
            this.state.printAll = false;
            this.state.version++;
            window.removeEventListener("afterprint", done);
        };
        window.addEventListener("afterprint", done);
        window.print();
    }

    /** The card, made to open its proof when clicked. */
    proofed(card) {
        return { ...card, action: () => this.openProof(card.proof || card.key) };
    }

    async openProof(key) {
        const { period, plan_id } = this.state.data;
        this.state.proof = { key, loading: true };
        const proof = await this.orm.call("gec.margin.dashboard", "get_proof", [
            key, period.date_from, period.date_to, plan_id,
        ]);
        if (this.state.proof && this.state.proof.key === key) {
            this.state.proof = { key, loading: false, ...proof };
        }
    }

    closeProof() {
        this.state.proof = null;
    }

    async openRows(action) {
        this.closeProof();
        await this.action.doAction(action);
    }

    showTab(key) {
        return this.state.printAll || this.state.tab === key;
    }

    get presets() {
        return [
            { key: "this_month", label: _t("This Month") },
            { key: "last_month", label: _t("Last Month") },
            { key: "this_quarter", label: _t("This Quarter") },
            { key: "this_year", label: _t("This Year") },
            { key: "last_year", label: _t("Last Year") },
            { key: "custom", label: _t("Custom") },
        ];
    }

    applyPreset(key) {
        const today = DateTime.local();
        const ranges = {
            this_month: [today.startOf("month"), today.endOf("month")],
            last_month: [
                today.minus({ months: 1 }).startOf("month"),
                today.minus({ months: 1 }).endOf("month"),
            ],
            this_quarter: [today.startOf("quarter"), today.endOf("quarter")],
            this_year: [today.startOf("year"), today.endOf("year")],
            last_year: [
                today.minus({ years: 1 }).startOf("year"),
                today.minus({ years: 1 }).endOf("year"),
            ],
        };
        this.state.preset = key;
        if (ranges[key]) {
            this.state.dateFrom = ranges[key][0].toISODate();
            this.state.dateTo = ranges[key][1].toISODate();
        }
    }

    async onPresetChange(ev) {
        this.applyPreset(ev.target.value);
        if (ev.target.value !== "custom") {
            await this.load();
        }
    }

    async onDateChange(which, ev) {
        if (!ev.target.value) {
            return;
        }
        this.state.preset = "custom";
        this.state[which] = ev.target.value;
        if (this.state.dateFrom <= this.state.dateTo) {
            await this.load();
        }
    }

    get companyWide() {
        return -1;
    }

    async onPlanChange(ev) {
        this.state.planId = parseInt(ev.target.value) || false;
        await this.load();
    }

    async load() {
        // Only the latest request may land: a slow earlier answer must not overwrite the current figures.
        const requestId = ++this.lastRequestId;
        this.state.loading = true;
        try {
            const data = await this.orm.call("gec.margin.dashboard", "get_dashboard_data", [
                this.state.dateFrom,
                this.state.dateTo,
                this.state.planId,
            ]);
            if (requestId !== this.lastRequestId) {
                return;
            }
            this.state.planId = data.plan_id;
            this.state.data = data;
            this.state.version++;
            this.persist();
        } finally {
            if (requestId === this.lastRequestId) {
                this.state.loading = false;
            }
        }
    }

    async open(kind, resId = false) {
        // The period and plan of the figures on screen, not of the inputs (a custom range may be half typed).
        const { period, plan_id } = this.state.data;
        const action = await this.orm.call("gec.margin.dashboard", "action_drilldown", [
            kind,
            period.date_from,
            period.date_to,
            plan_id,
            resId,
        ]);
        await this.action.doAction(action);
    }

    openStatement() {
        return this.action.doAction("gec_analytic_margin.action_gec_margin_statement_report");
    }

    money(value, humanReadable = false) {
        return formatCurrency(value || 0, this.state.data.currency_id, { humanReadable });
    }

    formatDate(value) {
        return value ? DateTime.fromISO(value).toLocaleString(DateTime.DATE_MED) : "";
    }

    pct(value) {
        if (value === false || value === null || value === undefined) {
            return "";
        }
        return `${(value * 100).toFixed(1)}%`;
    }

    /** Change against the previous period, as a signed percentage of it. */
    delta(kpi) {
        if (!kpi.previous) {
            return null;
        }
        const change = (kpi.value - kpi.previous) / Math.abs(kpi.previous);
        return {
            text: `${change >= 0 ? "▲" : "▼"} ${Math.abs(change * 100).toFixed(1)}%`,
            good: kpi.is_cost ? kpi.value >= kpi.previous : change >= 0,
        };
    }

    get tabs() {
        return [
            { key: "overview", label: _t("Overview"), icon: "widgets" },
            { key: "revenue", label: _t("Revenue & Customers"), icon: "show_chart" },
            { key: "people", label: _t("People"), icon: "group" },
            { key: "projects", label: _t("Projects & Cash"), icon: "work" },
            { key: "activity", label: _t("Activity Costing"), icon: "account_tree" },
        ];
    }

    selectTab(key) {
        this.state.tab = key;
        this.persist();
        // Charts on a tab that was hidden are drawn at zero size; re-create them.
        this.state.version++;
    }

    /** Where a value sits on a benchmark scale, as the gauge draws it. */
    gauge(key, value) {
        const scale = BENCHMARKS[key];
        if (value === false || value === null || value === undefined || !scale) {
            return null;
        }
        const clamp = (v) => Math.max(0, Math.min(1, v / scale.max));
        const band = scale.bands.find(([from, to]) => value >= from && value < to) || scale.bands.at(-1);
        return {
            bands: scale.bands.map(([from, to, tone]) => ({
                tone, left: clamp(from) * 100, width: (clamp(to) - clamp(from)) * 100,
            })),
            marker: clamp(value) * 100,
            tone: value < scale.bands[0][0] ? "danger" : band[2],
            hint: scale.hint,
        };
    }

    kpi(key) {
        return this.profitability.kpis.find((k) => k.key === key);
    }

    levelPct(code) {
        const row = this.profitability.ladder.find((r) => r.kind === "level" && r.code === code);
        return row ? row.pct : false;
    }

    /** The six numbers a CEO reads first, each against the benchmark. */
    get headline() {
        const p = this.profitability;
        const cards = [];
        const revenue = this.kpi("revenue");
        const budget = p.budget && p.budget.through && p.budget.revenue_budget > 0 ? p.budget : null;
        cards.push({
            key: "revenue",
            label: _t("Revenue"),
            text: this.money(revenue.value, true),
            sub: budget ? _t("%s of budget to date", this.pct(budget.revenue / budget.revenue_budget))
                        : _t("no budget for the period"),
            delta: this.delta(revenue),
            gauge: budget ? this.gauge("budget", budget.revenue / budget.revenue_budget) : null,
            icon: "payments",
            spark: p.trend.map((m) => m.revenue),
        });
        for (const [key, code, label, icon] of [
            ["gross", "gross", _t("Gross margin"), "pie_chart"],
            ["ebitda", "ebitda", _t("EBITDA margin"), "bar_chart"],
        ]) {
            const row = p.ladder.find((r) => r.code === code);
            if (row) {
                cards.push({
                    key, label, icon,
                    text: this.pct(row.pct),
                    sub: this.money(row.amount, true),
                    gauge: this.gauge(key, row.pct),
                    spark: p.trend.map((m) => m[`${code}_pct`]),
                });
            }
        }
        const recurring = this.kpi("recurring");
        if (recurring) {
            cards.push({
                key: "recurring", label: _t("Recurring revenue"), icon: "autorenew",
                text: this.pct(recurring.pct), sub: this.money(recurring.value, true),
                gauge: this.gauge("recurring", recurring.pct),
                spark: p.trend.map((m) => m.recurring_pct),
            });
        }
        const r = p.retention;
        if (r && r.start) {
            cards.push({
                key: "nrr", label: _t("Net revenue retention"), icon: "handshake",
                text: this.pct(r.nrr),
                sub: _t("GRR %(grr)s · year on year", { grr: this.pct(r.grr) }),
                gauge: this.gauge("nrr", r.nrr),
                action: () => this.selectTab("revenue"),
            });
        }
        const prod = p.productivity;
        if (prod && prod.fte) {
            cards.push({
                key: "revenue_fte", label: _t("Revenue per FTE"), icon: "person",
                text: this.money(prod.revenue_per_fte, true),
                sub: _t("%s FTE · annualised", prod.fte.toFixed(1)),
                gauge: this.gauge("revenue_fte", prod.revenue_per_fte),
            });
        }
        const fc = p.forecast;
        if (fc && fc.backlog) {
            const months = this.backlogMonths;
            cards.push({
                key: "backlog", label: _t("Backlog"), icon: "work",
                text: this.money(fc.backlog, true),
                sub: months ? _t("%s months of revenue", months.toFixed(1)) : _t("contracted, not yet invoiced"),
                tone: "info",
                action: () => this.selectTab("projects"),
            });
        }
        if (fc && fc.counts) {
            const risk = fc.counts.loss + fc.counts.eroding;
            const total = risk + fc.counts.on_track;
            cards.push({
                key: "projects", label: _t("Projects at risk"), icon: "flag",
                text: `${risk} / ${total}`,
                sub: _t("%(loss)s loss · %(eroding)s eroding", { loss: fc.counts.loss, eroding: fc.counts.eroding }),
                tone: fc.counts.loss ? "danger" : risk ? "warning" : "success",
                action: () => this.selectTab("projects"),
            });
        }
        return cards;
    }

    /** Backlog in months of revenue, at the average of the last three months with any. */
    get backlogMonths() {
        const fc = this.profitability.forecast;
        const recent = this.profitability.trend.map((m) => m.revenue).filter((v) => v > 0).slice(-3);
        if (!fc || !fc.backlog || !recent.length) {
            return false;
        }
        return fc.backlog / (recent.reduce((a, b) => a + b, 0) / recent.length);
    }

    get retentionCards() {
        const r = this.profitability.retention;
        if (!r || !r.start) {
            return [];
        }
        const basis = r.basis === "recurring" ? _t("recurring revenue") : _t("all revenue");
        return [
            { key: "nrr", label: _t("Net revenue retention"), icon: "handshake", text: this.pct(r.nrr),
              sub: _t("of last year's %s from the same customers", basis), gauge: this.gauge("nrr", r.nrr) },
            { key: "grr", label: _t("Gross revenue retention"), icon: "autorenew", text: this.pct(r.grr),
              sub: _t("the same, growth left out"), gauge: this.gauge("grr", r.grr) },
            { key: "churn", label: _t("Customers lost / won"), icon: "group",
              text: `${r.lost} / ${r.won}`, tone: r.lost > r.won ? "warning" : "success",
              sub: _t("%(new)s from new customers, outside NRR", { new: this.money(r.new, true) }) },
        ];
    }

    get outlookCard() {
        const o = this.profitability.outlook;
        if (!o || !o.quarters) {
            return null;
        }
        const coverage = o.coverage;
        return {
            key: "outlook", label: _t("Next four quarters"), icon: "show_chart",
            text: this.money(o.plan_total, true),
            sub: _t("%(n)s of 4 quarters budgeted · backlog covers %(cov)s", {
                n: o.budgeted_quarters, cov: this.pct(coverage),
            }),
            tone: coverage >= 0.5 ? "success" : coverage >= 0.25 ? "warning" : "danger",
        };
    }

    outlookConfig() {
        const o = this.profitability.outlook;
        return {
            type: "bar",
            data: {
                labels: o.quarters.map((q) => q.label),
                datasets: [
                    { label: _t("Budget"), data: o.quarters.map((q) => q.budget_revenue),
                      backgroundColor: PALETTE.revenue, borderRadius: 4 },
                    { label: _t("Run rate"), data: o.quarters.map((q) => q.run_rate_revenue),
                      backgroundColor: PALETTE.neutral, borderRadius: 4 },
                ],
            },
            options: {
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.parsed.y)}` } },
                },
                scales: { y: { beginAtZero: true, ticks: { callback: (v) => this.money(v, true) } } },
            },
        };
    }

    get standardCard() {
        const mix = this.mix;
        if (!mix || mix.standard_pct === false || mix.standard_pct === undefined) {
            return null;
        }
        return { key: "standard", label: _t("Product revenue"), icon: "widgets",
                 text: this.pct(mix.standard_pct), sub: this.money(mix.standard, true),
                 gauge: this.gauge("standard", mix.standard_pct) };
    }

    get cashCards() {
        const fc = this.profitability.forecast;
        if (!fc || !fc.projects) {
            return [];
        }
        return [
            { key: "backlog", label: _t("Backlog"), icon: "work", text: this.money(fc.backlog, true),
              sub: _t("contracted, not yet invoiced"), tone: "info" },
            { key: "unbilled", label: _t("Unbilled work"), icon: "article", text: this.money(fc.unbilled, true),
              sub: _t("work done, not yet invoiced"), tone: fc.unbilled ? "warning" : "success" },
            { key: "ahead", label: _t("Billed ahead"), icon: "payments", text: this.money(fc.billed_ahead, true),
              sub: _t("invoiced before the work") },
            { key: "cash", label: _t("Cash-negative projects"), icon: "account_balance",
              text: String(fc.cash_negative), sub: _t("cost to date above cash collected"),
              tone: fc.cash_negative ? "danger" : "success" },
        ];
    }

    get delivery() {
        return this.state.data.delivery || {};
    }

    get cash() {
        return this.state.data.cash || {};
    }

    /** On time and to plan: the benchmark's delivery controls. */
    get deliveryCards() {
        const d = this.delivery;
        const cards = [];
        if (d.milestones) {
            const m = d.milestones;
            cards.push({ key: "milestones", label: _t("Milestones on time"), icon: "flag",
                         text: this.pct(m.rate),
                         sub: _t("%(on)s of %(due)s due · %(open)s overdue and open",
                                 { on: m.on_time, due: m.due, open: m.open_overdue }),
                         gauge: this.gauge("milestones", m.rate) });
        }
        if (d.golive) {
            const g = d.golive;
            cards.push({ key: "golive", label: _t("Go-live slippage"), icon: "rocket_launch",
                         text: this.pct(g.rate),
                         sub: _t("%(s)s of %(d)s planned go-lives late · %(days)s days on average",
                                 { s: g.slipped, d: g.due, days: Math.round(g.avg_days) }),
                         gauge: this.gauge("golive", g.rate) });
        }
        if (d.completion) {
            const c = d.completion;
            cards.push({ key: "completion", label: _t("Finishing late"), icon: "event_busy",
                         text: `${c.late} / ${c.projects}`,
                         sub: _t("projects forecast to end after their planned end date"),
                         tone: c.late ? (c.rate > 0.25 ? "danger" : "warning") : "success" });
        }
        if (d.templates) {
            const t = d.templates;
            cards.push({ key: "templates", label: _t("Built from a template"), icon: "content_copy",
                         text: this.pct(t.rate),
                         sub: _t("%(n)s of %(all)s customer projects", { n: t.from_template, all: t.projects }),
                         tone: "info" });
        }
        return cards;
    }

    /** Receivables, cash and forecast quality: the financial controls. */
    get financeCards() {
        const c = this.cash;
        const cards = [];
        if (c.dso) {
            cards.push({ key: "dso", label: _t("Days sales outstanding"), icon: "schedule",
                         text: _t("%s days", Math.round(c.dso.days)),
                         sub: _t("%s receivable", this.money(c.dso.receivables, true)),
                         gauge: this.gauge("dso", c.dso.days) });
        }
        if (c.conversion) {
            const v = c.conversion;
            cards.push({ key: "conversion", label: _t("Cash conversion"), icon: "attach_money",
                         text: v.ratio === false ? "—" : this.pct(v.ratio),
                         sub: _t("%(cash)s operating cash · EBITDA %(e)s",
                                 { cash: this.money(v.operating_cash, true), e: this.money(v.ebitda, true) }),
                         gauge: v.ratio === false ? null : this.gauge("conversion", v.ratio) });
        }
        if (c.forecast) {
            const f = c.forecast;
            cards.push({ key: "cash_forecast", label: _t("Lowest cash, 13 weeks"), icon: "area_chart",
                         text: this.money(f.low, true),
                         sub: _t("in %(week)s · %(close)s at the end", { week: f.low_week, close: this.money(f.closing, true) }),
                         tone: f.low < 0 ? "danger" : f.low < f.opening * 0.25 ? "warning" : "success" });
        }
        if (c.accuracy) {
            const a = c.accuracy;
            cards.push({ key: "accuracy", label: _t("Forecast accuracy"), icon: "check_circle",
                         text: `±${(a.error * 100).toFixed(1)}%`,
                         sub: _t("%(n)s of %(m)s months within ±15%", { n: a.within, m: a.months.length }),
                         gauge: this.gauge("accuracy", a.error) });
        }
        return cards;
    }

    cashForecastConfig() {
        const f = this.cash.forecast;
        return {
            type: "bar",
            data: {
                labels: f.weeks.map((w) => w.label),
                datasets: [
                    { type: "line", label: _t("Cash at week end"), data: f.weeks.map((w) => w.closing),
                      borderColor: PALETTE.margin, backgroundColor: PALETTE.margin, tension: 0.25, yAxisID: "y" },
                    { label: _t("Customer invoices due"), data: f.weeks.map((w) => w.inflow),
                      backgroundColor: PALETTE.revenue, borderRadius: 4, stack: "flow", yAxisID: "y" },
                    { label: _t("Vendor bills and other costs"), data: f.weeks.map((w) => -(w.outflow + w.other)),
                      backgroundColor: PALETTE.cost, borderRadius: 4, stack: "flow", yAxisID: "y" },
                ],
            },
            options: {
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.parsed.y)}` } },
                },
                scales: { y: { ticks: { callback: (v) => this.money(v, true) } } },
            },
        };
    }

    retentionConfig() {
        const r = this.profitability.retention;
        const steps = [
            [_t("Last year"), 0, r.start, PALETTE.neutral],
            [_t("Expansion"), r.start, r.start + r.expansion, PALETTE.margin],
            [_t("Contraction"), r.start + r.expansion - r.contraction, r.start + r.expansion, PALETTE.series[2]],
            [_t("Churn"), r.retained, r.retained + r.churn, PALETTE.cost],
            [_t("Retained"), 0, r.retained, PALETTE.revenue],
            [_t("New customers"), r.retained, r.retained + r.new, PALETTE.series[1]],
        ];
        return {
            type: "bar",
            data: {
                labels: steps.map((s) => s[0]),
                datasets: [{
                    data: steps.map((s) => [s[1], s[2]]),
                    backgroundColor: steps.map((s) => s[3]),
                    borderRadius: 4,
                }],
            },
            options: {
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => this.money(ctx.raw[1] - ctx.raw[0]) } },
                },
                scales: { y: { beginAtZero: true, ticks: { callback: (v) => this.money(v, true) } } },
            },
        };
    }

    /** Everything that needs a decision, in one list rather than one per tab. */
    get alerts() {
        const p = this.profitability;
        const alerts = [];
        if (this.state.data.mixed_currency) {
            alerts.push({ tone: "info", text: _t("The selected companies use different currencies: every amount is converted to %s at its own date's rate.", this.state.data.currency_name) });
        }
        if (p.unclassified) {
            alerts.push({ tone: "warning", kind: "unclassified",
                text: _t("%s is on accounts with no margin component and appears in no margin level.",
                         this.money(Math.abs(p.unclassified))) });
        }
        const uncovered = this.activity.totals.uncovered;
        if (uncovered) {
            alerts.push({ tone: "warning",
                text: _t("%s of allocatable cost sits where no allocation rule reaches it — every margin is that much too good.",
                         this.money(uncovered)) });
        }
        const fc = p.forecast;
        if (fc && fc.counts && fc.counts.loss) {
            alerts.push({ tone: "danger", tab: "projects",
                text: _t("%s project(s) will finish at a loss.", fc.counts.loss) });
        }
        const conc = p.concentration;
        if (conc && conc.top_pct > 0.2) {
            alerts.push({ tone: "danger", tab: "revenue",
                text: _t("%(name)s is %(pct)s of revenue — above the 20% the benchmark tolerates.",
                         { name: conc.customers[0].name, pct: this.pct(conc.top_pct) }) });
        }
        const hours = p.productivity && p.productivity.hours;
        if (hours && hours.coverage !== false && hours.coverage < 0.9) {
            alerts.push({ tone: "info", tab: "people",
                text: _t("Only %s of available hours are in timesheets; hour-based figures undercount.",
                         this.pct(hours.coverage)) });
        }
        return alerts;
    }

    get ladderMax() {
        return Math.max(1, ...this.profitability.ladder.map((r) => Math.abs(r.amount)));
    }

    barWidth(value, max) {
        return `${Math.min(100, (Math.abs(value) / (max || 1)) * 100).toFixed(1)}%`;
    }

    get profitability() {
        return this.state.data.profitability;
    }

    get activity() {
        return this.state.data.activity;
    }

    get objectBlocks() {
        const { top, bottom } = this.profitability.objects;
        return [
            { key: "top", title: _t("Most profitable"), objects: top },
            { key: "bottom", title: _t("Least profitable"), objects: bottom },
        ].filter((block) => block.objects.length);
    }

    get activityCards() {
        const totals = this.activity.totals;
        return [
            { key: "pool", label: _t("Activity cost pool"), value: totals.pool },
            { key: "charged", label: _t("Charged to cost objects"), value: totals.charged },
            { key: "not_charged", label: _t("Not charged"), value: totals.not_charged, warn: true },
            { key: "idle", label: _t("Idle capacity"), value: totals.idle, warn: true },
            { key: "rate_variance", label: _t("Rate variance"), value: totals.rate_variance, warn: true },
        ];
    }

    /** Benchmark: largest customer below 15–20% of revenue, ten largest below 40–50%; red past the upper figure. */
    get concentrationCards() {
        const conc = this.profitability.concentration;
        const card = (key, label, value, previous, [ok, limit], hint) => ({
            key,
            label,
            value,
            hint,
            css: value > limit ? "text-danger" : value > ok ? "text-warning" : "text-success",
            delta: previous === false ? null : {
                text: `${value >= previous ? "▲" : "▼"} ${Math.abs((value - previous) * 100).toFixed(1)} pt`,
                good: value <= previous,
            },
        });
        return [
            card("top", _t("Largest customer"), conc.top_pct, conc.prev_top_pct, [0.15, 0.2],
                 _t("%s · target below 15–20%%", conc.customers[0].name)),
            card("top_n", _t("Top %s customers", conc.top_n), conc.top_n_pct, conc.prev_top_n_pct,
                 [0.4, 0.5], _t("target below 40–50%")),
        ];
    }

    get productivityCards() {
        const prod = this.profitability.productivity;
        const change = (value, previous) => {
            if (!previous) {
                return null;
            }
            const rate = (value - previous) / Math.abs(previous);
            return { text: `${rate >= 0 ? "▲" : "▼"} ${Math.abs(rate * 100).toFixed(1)}%`, good: rate >= 0 };
        };
        const cards = [
            {
                key: "fte",
                label: _t("Average FTE"),
                text: prod.fte.toFixed(1),
                hint: prod.by_type.map((t) => `${t.label} ${t.fte.toFixed(1)}`).join(" · "),
                title: _t("Full-time equivalents over the period, contractors included"),
            },
            {
                key: "revenue",
                label: _t("Revenue per FTE"),
                text: this.money(prod.revenue_per_fte, true),
                hint: _t("annualised"),
                title: _t("Benchmark figures are in USD"),
                delta: change(prod.revenue_per_fte, prod.prev_revenue_per_fte),
            },
        ];
        if (prod.revenue_growth !== false && prod.fte_growth !== false) {
            const signed = (value) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
            cards.push({
                key: "growth",
                label: _t("Revenue vs FTE growth"),
                text: signed(prod.revenue_growth),
                hint: _t("FTE %s · revenue should grow faster", signed(prod.fte_growth)),
                title: _t("Annualised, against the previous period"),
                delta: {
                    text: prod.revenue_growth > prod.fte_growth ? _t("leverage") : _t("dilution"),
                    good: prod.revenue_growth > prod.fte_growth,
                },
            });
        }
        const hours = prod.hours;
        if (hours && hours.utilization !== false) {
            const h = (value) => `${Math.round(value).toLocaleString()} h`;
            cards.push({
                key: "utilization",
                label: _t("Utilization"),
                text: this.pct(hours.utilization),
                hint: _t("customer hours of %s available · target 75–85%%", h(hours.available)),
                title: hours.buckets.map((b) => `${b.label}: ${h(b.hours)}`).join("\n"),
            });
            cards.push({
                key: "coverage",
                label: _t("Timesheet coverage"),
                text: this.pct(hours.coverage),
                hint: _t("%s logged — below 90%% the hours figures undercount", h(hours.logged)),
            });
        }
        if (hours && hours.product_share !== false) {
            cards.push({
                key: "product_share",
                label: _t("Product share of hours"),
                text: this.pct(hours.product_share),
                hint: _t("R&D projects vs customer projects · product work every customer gets"),
            });
        }
        if (hours && hours.delivery_utilization !== false && hours.delivery_utilization !== undefined) {
            cards.push({
                key: "delivery", label: _t("Delivery utilization"),
                text: this.pct(hours.delivery_utilization),
                hint: _t("Cost of Sales staff only · target 75–85%"),
                gauge: "utilization", value: hours.delivery_utilization,
            });
        }
        if (hours && hours.bespoke_share !== false && hours.bespoke_share !== undefined) {
            cards.push({
                key: "bespoke", label: _t("Bespoke engineering"),
                text: this.pct(hours.bespoke_share),
                hint: _t("engineers' hours on one customer's project"),
                gauge: "bespoke", value: hours.bespoke_share,
            });
        }
        if (hours && hours.rework_share !== false && hours.rework_share !== undefined) {
            cards.push({
                key: "rework", label: _t("Rework"),
                text: this.pct(hours.rework_share),
                hint: _t("%s h on tasks tagged as rework", Math.round(hours.rework_hours).toLocaleString()),
                gauge: "rework", value: hours.rework_share,
            });
        }
        if (prod.rnd_per_customer) {
            cards.push({
                key: "rnd_customer", label: _t("R&D per active customer"),
                text: this.money(prod.rnd_per_customer, true),
                hint: _t("annual R&D ÷ %s paying customers", prod.active_customers),
            });
        }
        if (prod.gross_per_fte !== null) {
            cards.push({ key: "gross", label: _t("Gross profit per FTE"), text: this.money(prod.gross_per_fte, true) });
        }
        if (this.mix) {
            cards.push({ key: "recurring", label: _t("Recurring per FTE"), text: this.money(prod.recurring_per_fte, true) });
        }
        return cards;
    }

    /** Actual against the budget prorated to the same days, through today. */
    get budgetCards() {
        const budget = this.profitability.budget;
        if (!budget || !budget.through) {
            return [];
        }
        const through = DateTime.fromISO(budget.through).toLocaleString(DateTime.DATE_MED);
        const card = (key, label, actual, planned) => {
            // A share of a negative budget means nothing: show the gap instead.
            const achieved = planned > 0 ? actual / planned : false;
            const variance = actual - planned;
            return {
                key,
                label,
                text: achieved === false
                    ? `${variance >= 0 ? "+" : ""}${this.money(variance, true)}`
                    : this.pct(achieved),
                // Net budgets can be negative; ahead of plan is simply more.
                tone: variance >= 0 ? "success" : "danger",
                icon: key === "revenue" ? "payments" : "balance",
                sub: _t("%(actual)s of %(budget)s · %(variance)s", {
                    actual: this.money(actual, true),
                    budget: this.money(planned, true),
                    variance: `${variance >= 0 ? "+" : ""}${this.money(variance, true)}`,
                }),
                title: _t("Budget prorated by day, through %s", through),
            };
        };
        return [
            { ...card("revenue", _t("Revenue vs budget"), budget.revenue, budget.revenue_budget), proof: "budget_revenue" },
            { ...card("net", _t("Net vs budget"), budget.net, budget.net_budget), proof: "budget_net" },
        ];
    }

    get concentrationKpis() {
        return this.concentrationCards.map((c) => ({
            key: c.key, label: c.label, text: this.pct(c.value), sub: c.hint, delta: c.delta, icon: "account_balance",
            tone: c.css === "text-danger" ? "danger" : c.css === "text-warning" ? "warning" : "success",
        }));
    }

    get productivityKpis() {
        const prod = this.profitability.productivity;
        const proofs = { revenue: "revenue_fte", gross: "gross_fte", recurring: "recurring_fte" };
        return this.productivityCards.map((c) => ({
            key: c.key, proof: proofs[c.key] || c.key,
            label: c.label, text: c.text, sub: c.hint, title: c.title, delta: c.delta,
            gauge: c.key === "revenue" ? this.gauge("revenue_fte", prod.revenue_per_fte)
                : c.gauge ? this.gauge(c.gauge, c.value) : null,
        }));
    }

    get activityKpis() {
        const totals = this.activity.totals;
        return [
            ...this.activityCards.map((c) => ({
                key: c.key, label: c.label, text: this.money(c.value, true), title: this.money(c.value),
                tone: c.warn && c.value ? "warning" : "neutral",
            })),
            {
                key: "capacity", label: this.capacityLabel, icon: "work",
                text: totals.capacity_used === false ? "—" : this.pct(totals.capacity_used),
            },
        ];
    }

    get capacityLabel() {
        return _t("Capacity used");
    }

    outsideTarget(row) {
        return row.target && (row.pct < row.target[0] || row.pct > row.target[1]);
    }

    /** [icon, colour class] for a forecast status. */
    forecastIcon(status) {
        return {
            loss: ["error", "text-danger"],
            eroding: ["warning", "text-warning"],
            on_track: ["check", "text-success"],
        }[status];
    }

    get mix() {
        const mix = this.profitability.mix;
        return mix && mix.streams ? mix : null;
    }

    get revenueTotal() {
        return this.profitability.kpis.find((k) => k.key === "revenue")?.value || 0;
    }

    get unassignedShare() {
        return this.revenueTotal ? this.mix.unassigned / this.revenueTotal : false;
    }

    mixConfig() {
        const streams = this.mix.streams;
        const labels = streams.map((s) => s.name);
        const data = streams.map((s) => s.amount);
        const colors = streams.map((s, index) => this.color(index));
        if (this.mix.unassigned) {
            labels.push(_t("No stream"));
            data.push(this.mix.unassigned);
            colors.push(PALETTE.neutral);
        }
        return {
            type: "doughnut",
            data: { labels, datasets: [{ data, backgroundColor: colors }] },
            options: {
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: { label: (ctx) => `${ctx.label}: ${this.money(ctx.parsed)}` },
                    },
                },
            },
        };
    }

    /** An internal project's cost as a share of the period's revenue. */
    internalShare(object) {
        const revenue = this.profitability.kpis.find((k) => k.key === "revenue")?.value;
        return revenue ? Math.abs(object.net) / revenue : false;
    }

    marginLabel(kpi) {
        return _t("%s of revenue", this.pct(kpi.pct));
    }

    previousTitle(kpi) {
        return _t("Previous period: %s", this.money(kpi.previous));
    }

    get previousLabel() {
        const { prev_from, prev_to } = this.state.data.period;
        const fmt = (d) => DateTime.fromISO(d).toLocaleString(DateTime.DATE_MED);
        return _t("vs %(from)s – %(to)s", { from: fmt(prev_from), to: fmt(prev_to) });
    }

    color(index) {
        return PALETTE.series[index % PALETTE.series.length];
    }

    trendConfig() {
        const trend = this.profitability.trend;
        return {
            type: "bar",
            data: {
                labels: trend.map((m) => DateTime.fromISO(m.month).toFormat("LLL yy")),
                datasets: [
                    {
                        type: "line",
                        label: _t("Net"),
                        data: trend.map((m) => m.net),
                        borderColor: PALETTE.margin,
                        backgroundColor: PALETTE.margin,
                        borderWidth: 3,
                        pointRadius: 3,
                        tension: 0.3,
                        order: 0,
                    },
                    {
                        label: _t("Revenue"),
                        data: trend.map((m) => m.revenue),
                        backgroundColor: PALETTE.revenue,
                        borderRadius: 4,
                        order: 1,
                    },
                    {
                        label: _t("Expense"),
                        data: trend.map((m) => m.expense),
                        backgroundColor: PALETTE.cost + "B3",
                        borderRadius: 4,
                        order: 1,
                    },
                ],
            },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.parsed.y)}`,
                        },
                    },
                },
                scales: { y: { ticks: { callback: (v) => this.money(v, true) } } },
                onClick: (_ev, elements) => {
                    if (elements.length) {
                        this.open("month", trend[elements[0].index].month);
                    }
                },
            },
        };
    }

    objectsConfig() {
        const objects = this.profitability.objects.chart;
        return {
            type: "bar",
            data: {
                labels: objects.map((o) => o.name),
                datasets: [
                    {
                        label: _t("Net"),
                        data: objects.map((o) => o.net),
                        backgroundColor: objects.map((o) => (o.net >= 0 ? PALETTE.margin : PALETTE.cost)),
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const o = objects[ctx.dataIndex];
                                const margin = o.pct === false ? "" : ` (${this.pct(o.pct)})`;
                                return `${this.money(o.net)}${margin}`;
                            },
                        },
                    },
                },
                scales: {
                    x: { ticks: { callback: (v) => this.money(v, true), maxRotation: 0, maxTicksLimit: 5 } },
                },
                onClick: (_ev, elements) => {
                    if (elements.length) {
                        this.open("object", objects[elements[0].index].id);
                    }
                },
            },
        };
    }

    activityConfig() {
        const activities = this.activity.activities.slice(0, 10);
        return {
            type: "bar",
            data: {
                labels: activities.map((a) => a.name),
                datasets: [
                    {
                        label: _t("Charged to cost objects"),
                        data: activities.map((a) => a.charged),
                        backgroundColor: PALETTE.revenue,
                    },
                    {
                        label: _t("Not charged"),
                        data: activities.map((a) => a.not_charged),
                        backgroundColor: PALETTE.series[2],
                    },
                ],
            },
            options: {
                indexAxis: "y",
                maintainAspectRatio: false,
                scales: {
                    x: { stacked: true, ticks: { callback: (v) => this.money(v, true) } },
                    y: { stacked: true },
                },
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.parsed.x)}`,
                        },
                    },
                },
                onClick: (_ev, elements) => {
                    if (elements.length) {
                        this.open("activity", activities[elements[0].index].id);
                    }
                },
            },
        };
    }

    valueConfig() {
        const split = this.activity.value_split;
        const colors = { value_added: PALETTE.margin, business_required: PALETTE.series[2], non_value_added: PALETTE.cost };
        return {
            type: "doughnut",
            data: {
                labels: split.map((s) => s.label),
                datasets: [
                    {
                        data: split.map((s) => s.amount),
                        backgroundColor: split.map((s) => colors[s.key] || PALETTE.neutral),
                    },
                ],
            },
            options: {
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: ${this.money(ctx.parsed)}`,
                        },
                    },
                },
            },
        };
    }
}

registry.category("actions").add("gec_analytic_margin.dashboard", GecAbcDashboard);
