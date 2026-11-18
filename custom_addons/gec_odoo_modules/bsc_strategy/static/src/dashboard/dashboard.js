/** @odoo-module **/

import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { formatFloat } from "@web/core/utils/numbers";
import { useSetupAction } from "@web/search/action_hook";

const CHART_W = 560;
const CHART_H = 190;
const CHART_PAD = { top: 16, right: 16, bottom: 34, left: 40 };

/** The manager dashboard: where the scorecard stands for one period; everything arrives in one server call. */
export class BscDashboard extends Component {
    static template = "bsc_strategy.Dashboard";

    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            data: null,
            loading: true,
            error: null,
            scorecardId: false,
            periodId: false,
            kpiFilter: "all",
        });
        useSetupAction({
            getLocalState: () => ({
                scorecardId: this.state.scorecardId,
                periodId: this.state.periodId,
            }),
        });
        onWillStart(async () => {
            const saved = this.props.state || {};
            const params = this.props.action?.params || {};
            this.state.scorecardId = saved.scorecardId || params.scorecard_id || false;
            this.state.periodId = saved.periodId || params.period_id || false;
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("bsc.scorecard", "get_dashboard_data", [], {
                scorecard_id: this.state.scorecardId || false,
                period_id: this.state.periodId || false,
            });
            this.state.data = data;
            this.state.scorecardId = data.scorecard ? data.scorecard.id : false;
            this.state.periodId = data.period ? data.period.id : false;
        } catch (error) {
            this.state.error = error.data?.message || error.message || String(error);
        }
        this.state.loading = false;
    }

    async onScorecardChange(ev) {
        this.state.scorecardId = parseInt(ev.target.value, 10);
        this.state.periodId = false;
        await this.load();
    }

    async onPeriodChange(ev) {
        this.state.periodId = parseInt(ev.target.value, 10);
        await this.load();
    }

    setKpiFilter(filter) {
        this.state.kpiFilter = this.state.kpiFilter === filter ? "all" : filter;
    }

    fmt(value, digits = 1) {
        if (value === null || value === undefined || value === false) {
            return "–";
        }
        return formatFloat(Number(value), { digits: [0, digits], trailingZeros: false });
    }

    money(value) {
        const symbol = this.state.data?.currency || "";
        return `${this.fmt(value, 0)} ${symbol}`.trim();
    }

    statusClass(status) {
        return `o_bsc_dash_status o_bsc_dash_${status || "no_data"}`;
    }

    barWidth(value) {
        const width = Math.max(0, Math.min(100, Number(value) || 0));
        return `width: ${width}%`;
    }

    trendIcon(trend) {
        return { up: "arrow_upward", down: "arrow_downward" }[trend] || "arrow_forward";
    }

    get filteredKpis() {
        const kpis = this.state.data?.kpis || [];
        switch (this.state.kpiFilter) {
            case "red":
            case "amber":
            case "green":
                return kpis.filter((k) => k.status === this.state.kpiFilter);
            case "missing":
                return kpis.filter((k) => !k.reported);
            case "no_data":
                return kpis.filter((k) => k.status === "no_data");
            default:
                return kpis;
        }
    }

    get attentionCount() {
        const a = this.state.data?.attention;
        if (!a) {
            return 0;
        }
        return (
            a.missing_by_owner.length +
            a.red_without_comment.length +
            a.held.length +
            a.red_without_action.length +
            a.overdue.length +
            a.over_budget.length
        );
    }

    get budgetPercent() {
        const i = this.state.data?.initiatives;
        if (!i || !i.budget_planned) {
            return 0;
        }
        return Math.round((i.budget_actual / i.budget_planned) * 100);
    }

    get linkPercent() {
        const l = this.state.data?.links;
        if (!l || !l.total) {
            return 0;
        }
        return Math.round((l.validated / l.total) * 100);
    }

    /** Trend of the scorecard index across the cycle, as SVG geometry. */
    get chart() {
        const trend = this.state.data?.trend || [];
        if (!trend.length) {
            return null;
        }
        const scores = trend.map((t) => t.score).filter((s) => s !== null);
        const maxScore = Math.max(110, ...scores);
        const innerW = CHART_W - CHART_PAD.left - CHART_PAD.right;
        const innerH = CHART_H - CHART_PAD.top - CHART_PAD.bottom;
        const step = innerW / trend.length;
        const x = (i) => CHART_PAD.left + step * (i + 0.5);
        const y = (v) => CHART_PAD.top + innerH - (v / maxScore) * innerH;
        const points = trend.map((t, i) => ({
            ...t,
            x: x(i),
            y: t.score === null ? null : y(t.score),
            label: t.score === null ? "–" : `${this.fmt(t.score)}%`,
        }));
        const drawn = points.filter((p) => p.y !== null);
        const path = drawn.map((p, i) => `${i ? "L" : "M"} ${p.x} ${p.y}`).join(" ");
        const thresholds = this.state.data.thresholds || { green: 95, amber: 80 };
        const grid = [0, 50, 100].map((v) => ({ v, y: y(v) }));
        return {
            width: CHART_W,
            height: CHART_H,
            points,
            path,
            grid,
            green: y(thresholds.green),
            amber: y(thresholds.amber),
            left: CHART_PAD.left,
            right: CHART_W - CHART_PAD.right,
            bottom: CHART_H - CHART_PAD.bottom,
        };
    }

    openRecord(model, id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPerspective(perspectiveId, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "bsc.objective",
            domain: [
                ["scorecard_id", "=", this.state.scorecardId],
                ["perspective_id", "=", perspectiveId],
            ],
            context: {
                default_scorecard_id: this.state.scorecardId,
                default_perspective_id: perspectiveId,
            },
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openScorecard() {
        this.openRecord("bsc.scorecard", this.state.scorecardId);
    }

    openMap() {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "bsc_strategy_map",
            params: { scorecard_id: this.state.scorecardId },
        });
    }

    openFigures(onlyMissing = false) {
        const period = this.state.data?.period;
        if (!period) {
            return;
        }
        const domain = [["period_id", "=", period.id]];
        if (onlyMissing) {
            domain.push(["actual_value_set", "=", false]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: onlyMissing
                ? _t("Missing figures - %s", period.name)
                : _t("Figures - %s", period.name),
            res_model: "bsc.measurement",
            domain,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openInitiatives(onlyLive = false) {
        const domain = [["scorecard_id", "=", this.state.scorecardId]];
        if (onlyLive) {
            domain.push(["state", "in", ["approved", "in_progress"]]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Initiatives"),
            res_model: "bsc.initiative",
            domain,
            context: { default_scorecard_id: this.state.scorecardId },
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    async createInitiative(objectiveId) {
        const action = await this.orm.call(
            "bsc.objective", "action_create_corrective_initiative", [[objectiveId]]
        );
        this.action.doAction(action);
    }

    async openReview() {
        const action = await this.orm.call(
            "bsc.period", "action_open_review", [[this.state.periodId]]
        );
        this.action.doAction(action, { onClose: () => this.load() });
    }

    async printBoardPack() {
        const action = await this.orm.call(
            "bsc.scorecard", "action_print_board_pack", [[this.state.scorecardId]],
            { period_id: this.state.periodId || false }
        );
        this.action.doAction(action);
    }
}

registry.category("actions").add("bsc_dashboard", BscDashboard);
