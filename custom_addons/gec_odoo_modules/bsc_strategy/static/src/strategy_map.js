/** @odoo-module **/

import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { formatFloat } from "@web/core/utils/numbers";
import { useSetupAction } from "@web/search/action_hook";

// Geometry lives here, not in CSS: an SVG path cannot read a stylesheet.
const CARD_W = 212;
const CARD_H = 92;
const GAP_X = 28;
const GAP_Y = 58;
const ROW_GAP = 18;
const LABEL_W = 164;
const PAD = 24;
const MAX_PER_ROW = 6;

const STROKE_BY_STRENGTH = { weak: 1.3, medium: 2.2, strong: 3.4 };
const ARROW_HEAD_LENGTH = 11;
const ARROW_HEAD_WIDTH = 10;

export class StrategyMap extends Component {
    static template = "bsc_strategy.StrategyMap";
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            scorecards: [],
            scorecardId: null,
            data: null,
            loading: true,
            error: null,
            panelError: null,
            dimUnvalidated: false,
            selectedLinkId: null,
            // The inspector: {type: 'objective'|'link', id, data}
            selection: null,
            panelLoading: false,
            panelCollapsed: false,
            // Inspector page; reset on every new selection so a card opens on the overview.
            panelTab: "overview",
        });

        useSetupAction({
            getLocalState: () => ({ scorecardId: this.state.scorecardId }),
        });

        onWillStart(async () => {
            const requested =
                this.props.state?.scorecardId ||
                this.props.action?.params?.scorecard_id ||
                this.props.action?.context?.default_scorecard_id;
            this.state.scorecards = await this.orm.call(
                "bsc.scorecard", "get_map_scorecards", [], { scorecard_id: requested || false }
            );
            const available = this.state.scorecards.map((c) => c.id);
            this.state.scorecardId =
                (available.includes(requested) && requested) || available[0] || null;
            await this.loadMap();
        });
    }

    async loadMap() {
        if (!this.state.scorecardId) {
            this.state.loading = false;
            this.state.data = null;
            return;
        }
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(
                "bsc.scorecard", "get_strategy_map", [[this.state.scorecardId]]
            );
        } catch (error) {
            this.state.error = this.errorText(error);
            this.state.data = null;
        }
        this.state.loading = false;
    }

    errorText(error) {
        return error.data?.message || error.message || String(error);
    }

    fmt(value, digits = 1) {
        return formatFloat(Number(value), { digits: [0, digits], trailingZeros: false });
    }

    async onScorecardChange(ev) {
        this.state.scorecardId = parseInt(ev.target.value, 10);
        this.clearSelection();
        await this.loadMap();
    }

    get layout() {
        const data = this.state.data;
        if (!data || !data.objectives.length) {
            return null;
        }
        const byPerspective = new Map();
        for (const objective of data.objectives) {
            if (!byPerspective.has(objective.perspective_id)) {
                byPerspective.set(objective.perspective_id, []);
            }
            byPerspective.get(objective.perspective_id).push(objective);
        }

        const bands = [];
        const cardById = new Map();
        let y = PAD;
        let maxColumns = 1;

        for (const perspective of data.perspectives) {
            const objectives = byPerspective.get(perspective.id) || [];
            const columns = Math.min(Math.max(objectives.length, 1), MAX_PER_ROW);
            const rows = Math.max(1, Math.ceil(objectives.length / MAX_PER_ROW));
            maxColumns = Math.max(maxColumns, columns);
            const bandHeight = rows * CARD_H + (rows - 1) * ROW_GAP + PAD;

            objectives.forEach((objective, index) => {
                const row = Math.floor(index / MAX_PER_ROW);
                const column = index % MAX_PER_ROW;
                cardById.set(objective.id, {
                    ...objective,
                    x: LABEL_W + PAD + column * (CARD_W + GAP_X),
                    y: y + PAD / 2 + row * (CARD_H + ROW_GAP),
                    w: CARD_W,
                    h: CARD_H,
                });
            });

            bands.push({
                ...perspective,
                y,
                h: bandHeight,
                count: objectives.length,
            });
            y += bandHeight + GAP_Y;
        }

        const pending = [];
        const ports = new Map(); // "cardId:edge" -> [{arrow, end, otherX, otherY}]
        const addPort = (cardId, edge, entry) => {
            const key = `${cardId}:${edge}`;
            if (!ports.has(key)) {
                ports.set(key, []);
            }
            ports.get(key).push(entry);
        };
        for (const link of data.links) {
            const source = cardById.get(link.source_id);
            const target = cardById.get(link.target_id);
            if (!source || !target) {
                continue;
            }
            const edges = this.arrowEdges(source, target);
            const arrow = {
                ...link,
                source,
                target,
                ...edges,
                width: STROKE_BY_STRENGTH[link.strength] || 2,
                sourceName: source.code || source.name,
                targetName: target.code || target.name,
            };
            pending.push(arrow);
            addPort(source.id, edges.fromEdge, {
                arrow, end: "from", otherX: target.x + target.w / 2, otherY: target.y + target.h / 2,
            });
            addPort(target.id, edges.toEdge, {
                arrow, end: "to", otherX: source.x + source.w / 2, otherY: source.y + source.h / 2,
            });
        }
        for (const [key, entries] of ports) {
            const [cardId, edge] = key.split(":");
            const card = cardById.get(parseInt(cardId, 10));
            const horizontal = edge === "top" || edge === "bottom";
            entries.sort((a, b) => (horizontal ? a.otherX - b.otherX : a.otherY - b.otherY));
            const n = entries.length;
            entries.forEach((entry, index) => {
                const t = n === 1 ? 0.5 : 0.15 + (0.7 * index) / (n - 1);
                const point = horizontal
                    ? { x: card.x + card.w * t, y: edge === "top" ? card.y : card.y + card.h }
                    : { x: edge === "left" ? card.x : card.x + card.w, y: card.y + card.h * t };
                entry.arrow[entry.end] = point;
            });
        }
        const arrows = pending.map((arrow) => {
            const { source, target, ...rest } = arrow;
            return { ...rest, ...this.arrowGeometry(arrow) };
        });

        return {
            bands,
            cards: [...cardById.values()],
            arrows,
            width:
                LABEL_W + PAD * 2 + maxColumns * CARD_W + (maxColumns - 1) * GAP_X + PAD,
            height: y - GAP_Y + PAD,
            labelWidth: LABEL_W,
        };
    }

    /** Edges an arrow leaves its cause by and enters its effect by: top to bottom, else sides or opposite edges. */
    arrowEdges(source, target) {
        if (target.y + target.h < source.y) {
            return { fromEdge: "top", toEdge: "bottom" };
        }
        if (target.y > source.y + source.h) {
            return { fromEdge: "bottom", toEdge: "top" };
        }
        const leftward = target.x < source.x;
        return {
            fromEdge: leftward ? "left" : "right",
            toEdge: leftward ? "right" : "left",
        };
    }

    /** The curve and its head. The head is its own shape:
     *  an SVG marker scales with the stroke width and cannot be recoloured. */
    arrowGeometry(arrow) {
        const { from, to, fromEdge, toEdge } = arrow;
        const out = { top: [0, -1], bottom: [0, 1], left: [-1, 0], right: [1, 0] };
        const vertical = fromEdge === "top" || fromEdge === "bottom";
        const span = vertical ? Math.abs(to.y - from.y) : Math.abs(to.x - from.x);
        const bend = Math.max(30, span / 2);
        const c1 = { x: from.x + out[fromEdge][0] * bend, y: from.y + out[fromEdge][1] * bend };
        const dir = { x: -out[toEdge][0], y: -out[toEdge][1] };
        const headLength = ARROW_HEAD_LENGTH;
        const base = { x: to.x - dir.x * headLength, y: to.y - dir.y * headLength };
        const c2 = { x: base.x - dir.x * bend, y: base.y - dir.y * bend };
        const half = ARROW_HEAD_WIDTH / 2;
        const perp = { x: -dir.y, y: dir.x };
        const head = [
            `M ${to.x} ${to.y}`,
            `L ${base.x + perp.x * half} ${base.y + perp.y * half}`,
            `L ${base.x - perp.x * half} ${base.y - perp.y * half}`,
            "Z",
        ].join(" ");
        return {
            path: `M ${from.x} ${from.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${base.x} ${base.y}`,
            head,
            midX: (from.x + to.x) / 2,
            midY: (from.y + to.y) / 2,
        };
    }

    get counts() {
        const data = this.state.data;
        if (!data) {
            return null;
        }
        const links = data.links;
        return {
            objectives: data.objectives.length,
            links: links.length,
            validated: links.filter((link) => link.validated).length,
            unvalidated: links.filter((link) => !link.validated).length,
            offTrack: data.objectives.filter((o) => o.status === "red").length,
            unlinked: data.objectives.filter(
                (o) =>
                    !links.some(
                        (link) => link.source_id === o.id || link.target_id === o.id
                    )
            ).length,
        };
    }

    get offTrackObjectives() {
        return (this.state.data?.objectives || []).filter((o) => o.status === "red");
    }

    arrowClass(arrow) {
        const classes = ["o_bsc_link"];
        classes.push(arrow.validated ? "o_bsc_link_validated" : "o_bsc_link_assumed");
        if (this.state.dimUnvalidated && !arrow.validated) {
            classes.push("o_bsc_link_dimmed");
        }
        const focused = this.focusedObjectiveId;
        if (focused) {
            const touches =
                arrow.source_id === focused || arrow.target_id === focused;
            classes.push(touches ? "o_bsc_link_connected" : "o_bsc_link_unrelated");
        }
        if (this.state.selectedLinkId === arrow.id) {
            classes.push("o_bsc_link_selected");
        }
        return classes.join(" ");
    }

    cardTitle(card) {
        return card.owner ? _t("%s - owner %s", card.name, card.owner) : card.name;
    }

    get panelToggleTitle() {
        return this.state.panelCollapsed
            ? _t("Show the detail panel")
            : _t("Give the map the full width");
    }

    cardClass(card) {
        const classes = ["o_bsc_card", `o_bsc_card_${card.status}`];
        if (this.isSelected("objective", card.id)) {
            classes.push("o_bsc_card_focused");
        }
        return classes.join(" ");
    }

    arrowTitle(arrow) {
        const belief = arrow.validated
            ? _t("validated with data")
            : _t("assumed, not yet checked");
        return `${arrow.sourceName} → ${arrow.targetName}\n${arrow.hypothesis}\n(${arrow.strength_label}, ${belief})`;
    }

    clearSelection() {
        this.state.panelError = null;
        this.state.selection = null;
        this.state.selectedLinkId = null;
        this.state.panelLoading = false;
    }

    isSelected(type, id) {
        return this.state.selection?.type === type && this.state.selection.id === id;
    }

    /** Loads a detail payload into the inspector, or closes it if re-clicked. */
    async _select(type, model, id, extra = {}) {
        if (this.state.panelCollapsed) {
            // A click while the panel is hidden must reveal it, not toggle it off.
            this.state.panelCollapsed = false;
            if (this.isSelected(type, id)) {
                return;
            }
        } else if (this.isSelected(type, id)) {
            this.clearSelection();
            return;
        }
        this.state.panelError = null;
        this.state.selection = { type, id, data: null };
        this.state.selectedLinkId = type === "link" ? id : null;
        this.state.panelTab = "overview";
        Object.assign(this.state, extra);
        this.state.panelLoading = true;
        try {
            const data = await this.orm.call(model, "get_map_detail", [[id]]);
            // Guard against a slower request landing after a newer click.
            if (this.isSelected(type, id)) {
                this.state.selection = { type, id, data };
            }
        } catch (error) {
            this.clearSelection();
            this.state.panelError = this.errorText(error);
        }
        this.state.panelLoading = false;
    }

    selectObjective(objectiveId) {
        return this._select("objective", "bsc.objective", objectiveId);
    }

    selectLink(linkId) {
        return this._select("link", "bsc.objective.link", linkId);
    }

    /** The objective the inspector is on, if any - used to light up its arrows. */
    get focusedObjectiveId() {
        return this.state.selection?.type === "objective"
            ? this.state.selection.id
            : null;
    }

    toggleDim() {
        this.state.dimUnvalidated = !this.state.dimUnvalidated;
    }

    /** Hides the inspector so the map gets the full width - worth ~1.5 cards. */
    togglePanel() {
        this.state.panelCollapsed = !this.state.panelCollapsed;
    }

    setPanelTab(tab) {
        this.state.panelTab = tab;
    }

    isPanelTab(tab) {
        return this.state.panelTab === tab;
    }

    /** Open any record where it can be edited. */
    openRecord(model, id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** The KPI's figure for the current period - where it is entered. */
    async openKpiFigure(kpiId) {
        const action = await this.orm.call(
            "bsc.kpi", "action_open_current_measurement", [[kpiId]]
        );
        this.action.doAction(action);
    }

    openObjective(objectiveId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bsc.objective",
            res_id: objectiveId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openInitiative(initiativeId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bsc.initiative",
            res_id: initiativeId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** All initiatives serving this objective, as an ordinary list view. */
    openObjectiveInitiatives(objectiveId, objectiveName) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: objectiveName,
            res_model: "bsc.initiative",
            domain: [["objective_ids", "in", [objectiveId]]],
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openProject(projectId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: projectId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openTask(taskId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: taskId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** The task board of an initiative's project, not the project record. */
    openProjectTasks(projectId, projectName) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: projectName,
            res_model: "project.task",
            domain: [["project_id", "=", projectId]],
            context: { default_project_id: projectId },
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    /** Propose one straight from the map, pre-filled from the objective. */
    async createInitiative(objectiveId) {
        const action = await this.orm.call(
            "bsc.objective", "action_create_corrective_initiative", [[objectiveId]]
        );
        this.action.doAction(action);
    }

    openScorecard() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bsc.scorecard",
            res_id: this.state.scorecardId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** Sets a link to the value the user clicked for, not to "the opposite of whatever is stored". */
    async toggleValidated(linkId, validated) {
        this.state.panelError = null;
        try {
            await this.orm.call(
                "bsc.objective.link", "action_toggle_validated_from_map", [[linkId]],
                { validated }
            );
            await this.loadMap();
            // Whatever the inspector is showing may have just changed underneath it.
            const open = this.state.selection;
            if (open) {
                const model =
                    open.type === "link" ? "bsc.objective.link" : "bsc.objective";
                const data = await this.orm.call(model, "get_map_detail", [[open.id]]);
                this.state.selection = { ...open, data };
            }
        } catch (error) {
            this.state.panelError = this.errorText(error);
            this.state.panelCollapsed = false;
        }
    }
}

registry.category("actions").add("bsc_strategy_map", StrategyMap);
