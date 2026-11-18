import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { sprintf } from "@web/core/utils/strings";
import { deserializeDate, deserializeDateTime, serializeDate } from "@web/core/l10n/dates";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { browser } from "@web/core/browser/browser";
import { SIZES } from "@web/core/ui/ui_utils";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useSetupAction } from "@web/search/action_hook";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { debounce } from "@web/core/utils/timing";
import { Component, onMounted, onWillStart, proxy, signal, useListener, useProps } from "@odoo/owl";
import { DecisionSplit } from "../components/decision_split/decision_split";
import { OccupancyBar } from "../components/occupancy_bar/occupancy_bar";
import { PriceChange } from "../components/price_change/price_change";
import { PricePanel } from "../components/price_panel/price_panel";
import { Sparkline } from "../components/sparkline/sparkline";
import { PricingInsights } from "../insights/insights";
import {
    BULK_PCTS,
    DONE_MESSAGES,
    LEVEL_STEPS,
    STATE_LABELS,
    UNDOABLE,
    daysLeftText,
    formatPct,
    formatPrice,
    levelPct,
    levelStep,
    loadSetting,
    saveSetting,
    shownPrice,
} from "../utils/pricing_utils";

const WEEKEND = [5, 6];
const SMALL_DAYS = [7, 14, 30];
const WIDE_DAYS = [14, 30];
const TOAST_DELAY = 5000;
const LONG_PRESS = 450;
const SWIPE_THRESHOLD = 0.3;
const SWIPE_SLOP = 8;
const SWIPE_HINT_KEY = "hotel_rms.swipe_hint_seen";
const DOCK_KEY = "hotel_rms.dock_collapsed";
const MODE_KEY = "hotel_rms.view_mode";
const MIN_CELL_WIDTH = 88;
const ROOM_COLUMN_WIDTH = 160;
const MAIN_PADDING = 48;
const FIT_DAYS = [14, 45];
const ACTION_LABELS = { up: _t("Raise"), down: _t("Lower"), hold: _t("Keep"), new: _t("New") };
const REVIEW_OUTCOMES = {
    action_accept: "accepted",
    action_use_my_price: "edited",
    action_quick_price: "edited",
    action_reject: "rejected",
};
const MOVES = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

class PricingCalendar extends Component {
    static template = "hotel_rms.PricingCalendar";
    static components = {
        DecisionSplit,
        Dropdown,
        DropdownItem,
        OccupancyBar,
        PriceChange,
        PricePanel,
        PricingInsights,
        Sparkline,
    };
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.ui = useService("ui");
        this.mainRef = signal.ref();
        this.modes = [
            { key: "changes", label: _t("Changes") },
            { key: "price", label: _t("Price level") },
            { key: "occupancy", label: _t("Occupancy") },
        ];
        this.levels = Array.from({ length: LEVEL_STEPS }, (_, step) => step);
        this.bulkPcts = BULK_PCTS.map((pct) => ({ pct, label: formatPct(pct) }));
        this.skeletonRows = [0, 1, 2];
        this.skeletonCols = [0, 1, 2, 3, 4, 5, 6, 7];
        const past = this.props.state || {};
        this.state = proxy({
            properties: [],
            propertyId: false,
            dateFrom: past.dateFrom ?? false,
            days: past.days ?? (this.ui.isSmall ? SMALL_DAYS[0] : WIDE_DAYS[0]),
            onlyPending: past.onlyPending ?? this.ui.isSmall,
            hint: !loadSetting(SWIPE_HINT_KEY),
            tab: past.tab ?? "calendar",
            mode: loadSetting(MODE_KEY, "changes"),
            fit: past.fit ?? !this.compact,
            dockCollapsed: Boolean(loadSetting(DOCK_KEY)),
            hover: false,
            highlight: false,
            busy: false,
            skeleton: false,
            data: null,
            cells: {},
            selected: false,
            panelOpen: false,
            version: 0,
            multi: [],
            review: null,
        });
        useSetupAction({
            getLocalState: () => {
                const { tab, propertyId, dateFrom, days, fit, onlyPending } = this.state;
                return { tab, propertyId, dateFrom, days, fit, onlyPending };
            },
        });
        useListener(document, "keydown", (ev) => this.onKeydown(ev));
        useListener(window, "resize", debounce(() => this.refit(), 200));
        onWillStart(async () => {
            this.state.properties = await this.orm.searchRead("hotel.rms.property", [], ["name"]);
            const wanted = past.propertyId ?? this.props.action.context?.property_id;
            this.state.propertyId = this.state.properties.some((p) => p.id === wanted)
                ? wanted
                : this.state.properties[0]?.id;
            this.state.skeleton = Boolean(this.state.propertyId);
        });
        onMounted(() => this.state.propertyId && this.reload());
    }

    async load() {
        const data = await this.orm.call("hotel.rms.property", "get_calendar", [[this.state.propertyId]], {
            date_from: this.state.dateFrom,
            days: this.state.days,
        });
        data.nights.forEach((night, index) => {
            const date = deserializeDate(night.date);
            night.weekday_label = date.toFormat("ccc");
            night.title = date.toFormat("ccc d MMM");
            night.day = date.day;
            night.month = index === 0 || date.day === 1 ? date.toFormat("MMM") : "";
            night.weekend = WEEKEND.includes(night.weekday);
            night.week_start = night.weekday === 0 && index > 0;
            night.today = night.date === data.today;
            night.event_label = night.events.length
                ? night.events[0] + (night.events.length > 1 ? ` +${night.events.length - 1}` : "")
                : "";
        });
        data.months = [];
        for (const night of data.nights) {
            const label = deserializeDate(night.date).toFormat("MMMM yyyy");
            const last = data.months.at(-1);
            if (last?.label === label) {
                last.span++;
            } else {
                data.months.push({ label, span: 1 });
            }
        }
        this.state.cells = Object.fromEntries(data.cells.map((cell) => [`${cell.room_type_id}_${cell.date}`, cell]));
        this.state.dateFrom = data.date_from;
        this.state.data = data;
        if (!this.cellById(this.state.selected)) {
            this.state.selected = false;
        }
    }

    /** Load with the skeleton showing: first load, and a change of hotel or range. */
    async reload() {
        if (this.state.fit && !this.compact) {
            this.state.days = this.fitDays();
        }
        this.state.skeleton = true;
        try {
            await this.load();
        } finally {
            this.state.skeleton = false;
        }
    }

    async withBusy(key, callback) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = key;
        try {
            await callback();
        } finally {
            this.state.busy = false;
        }
    }

    async onChange(key, value) {
        Object.assign(this.state, {
            [key]: value,
            multi: [],
            selected: false,
            review: null,
            panelOpen: false,
            highlight: false,
        });
        await this.reload();
    }

    async onPropertyChange(ev) {
        await this.onChange("propertyId", Number(ev.target.value));
    }

    async onStartChange(ev) {
        if (ev.target.value) {
            await this.onChange("dateFrom", ev.target.value);
        }
    }

    async shift(nights) {
        const date = deserializeDate(this.state.dateFrom).plus({ days: nights });
        await this.onChange("dateFrom", serializeDate(date));
    }

    get dayOptions() {
        const days = this.ui.isSmall ? SMALL_DAYS : WIDE_DAYS;
        const options = days.map((count) => ({ key: count, days: count, fit: false }));
        return this.compact ? options : [{ key: "fit", fit: true }, ...options];
    }

    isActiveDays(option) {
        return option.fit ? this.state.fit : !this.state.fit && this.state.days === option.days;
    }

    fitDays() {
        const width = (this.mainRef()?.clientWidth || 0) - MAIN_PADDING - ROOM_COLUMN_WIDTH;
        const [min, max] = FIT_DAYS;
        return Math.max(min, Math.min(max, Math.floor(width / MIN_CELL_WIDTH)));
    }

    async setDays(option) {
        Object.assign(this.state, {
            fit: option.fit,
            days: option.fit ? this.fitDays() : option.days,
            multi: [],
            selected: false,
            review: null,
            panelOpen: false,
        });
        await this.reload();
    }

    refit() {
        if (this.state.fit && !this.compact && this.state.data && this.fitDays() !== this.state.days) {
            this.state.days = this.fitDays();
            this.reload();
        }
    }

    get wide() {
        return this.ui.size >= SIZES.XXL;
    }

    get docked() {
        return this.isTablet || this.wide;
    }

    get dockToggleTitle() {
        return this.state.dockCollapsed ? _t("Show details") : _t("Hide details");
    }

    toggleDock() {
        this.state.dockCollapsed = !this.state.dockCollapsed;
        saveSetting(DOCK_KEY, this.state.dockCollapsed ? "1" : "");
        setTimeout(() => this.refit(), 250);
    }

    setMode(mode) {
        this.state.mode = mode;
        saveSetting(MODE_KEY, mode);
    }

    get filterOptions() {
        const pending = this.ui.isSmall
            ? _t("To decide (%s)", this.decisionIds.length)
            : _t("Needs decision (%s)", this.decisionIds.length);
        const options = [
            { key: "all", pending: false, label: _t("All nights") },
            { key: "pending", pending: true, label: pending },
        ];
        return this.ui.isSmall ? options.reverse() : options;
    }

    get layout() {
        return this.ui.isSmall ? "list" : "grid";
    }

    get isTablet() {
        return !this.ui.isSmall && this.ui.size <= SIZES.LG;
    }

    get compact() {
        return this.ui.isSmall || this.isTablet;
    }

    get feed() {
        const rooms = this.state.data.room_types;
        const roomIndex = (cell) => rooms.findIndex((room) => room.id === cell.room_type_id);
        return this.cellList
            .filter((cell) => this.needsDecision(cell))
            .sort((a, b) => a.date.localeCompare(b.date) || roomIndex(a) - roomIndex(b))
            .map((cell) => ({ cell, room: rooms[roomIndex(cell)], night: this.nightOf(cell) }));
    }

    nightOf(cell) {
        return this.state.data.nights.find((night) => night.date === cell.date);
    }

    daysLeft(cell) {
        const days = deserializeDate(cell.date).diff(deserializeDate(this.state.data.today), "days").days;
        return daysLeftText(days);
    }

    dismissHint() {
        this.state.hint = false;
        saveSetting(SWIPE_HINT_KEY, "1");
    }

    get currency() {
        return this.state.data.property.currency;
    }

    get cellList() {
        return Object.values(this.state.cells);
    }

    needsDecision(cell) {
        return cell.state === "pending" && !cell.locked && !cell.not_for_sale && Boolean(cell.recommended);
    }

    get decisionIds() {
        return this.cellList.filter((cell) => this.needsDecision(cell)).map((cell) => cell.id);
    }

    get decisionMessage() {
        const count = this.decisionIds.length;
        return count === 1 ? _t("1 price needs a decision") : _t("%s prices need a decision", count);
    }

    get reviewLabel() {
        const count = this.decisionIds.length;
        return count === 1 ? _t("Review 1 price") : _t("Review %s prices", count);
    }

    get freshness() {
        const { last_data_at, is_stale, kpis } = this.state.data;
        if (is_stale) {
            return {
                stale: true,
                label: last_data_at
                    ? _t("Data %s days old · prices frozen", kpis.data_age_days)
                    : _t("No booking data · prices frozen"),
            };
        }
        return { stale: false, label: _t("Updated %s", deserializeDateTime(last_data_at).toRelative()) };
    }

    kpiDelta(key, points) {
        const previous = this.state.data.kpis_previous;
        if (!previous || (!points && !previous[key])) {
            return null;
        }
        const current = this.state.data.kpis[key];
        const diff = points ? current - previous[key] : ((current - previous[key]) / previous[key]) * 100;
        const rounded = Math.round(diff);
        const signed = `${rounded > 0 ? "+" : ""}${rounded}`;
        const text = points ? _t("%s pts vs 7 days ago", signed) : _t("%s%% vs 7 days ago", signed);
        return { text, tone: rounded > 0 ? "up" : rounded < 0 ? "down" : "same" };
    }

    get kpis() {
        const kpis = this.state.data.kpis;
        return [
            {
                label: _t("Booked occupancy · 30 nights"),
                value: this.percent(kpis.booked_occ),
                pct: kpis.booked_occ,
                delta: this.kpiDelta("booked_occ", true),
            },
            {
                label: _t("Forecast occupancy · 30 nights"),
                value: this.percent(kpis.forecast_occ),
                pct: kpis.forecast_occ,
                series: kpis.forecast_series,
                delta: this.kpiDelta("forecast_occ", true),
            },
            { label: _t("ADR on the books"), value: this.price(kpis.adr), delta: this.kpiDelta("adr", false) },
            { label: _t("Estimated RevPAR"), value: this.price(kpis.revpar), delta: this.kpiDelta("revpar", false) },
        ];
    }

    get coldStartNote() {
        const forecasts = this.state.data.nights.filter((night) => night.forecast_occ !== null);
        return forecasts.filter((night) => night.cold_start).length * 2 > forecasts.length;
    }

    get setupSteps() {
        const { setup } = this.state.data;
        const openHotel = () => this.openHotel();
        return [
            { done: setup.rooms, label: _t("Add your rooms, with one reference room"), button: _t("Open hotel"), run: openHotel },
            { done: setup.season, label: _t("Add seasons that cover every night ahead"), button: _t("Open hotel"), run: openHotel },
            { done: setup.bookings, label: _t("Bring in your bookings"), button: _t("Import bookings"), run: () => this.importBookings() },
            { done: setup.run, label: _t("Run the engine for the first time"), button: _t("Run now"), run: () => this.runNow() },
        ];
    }

    get showSetup() {
        const data = this.state.data;
        return Boolean(data) && (!data.setup.rooms || !data.setup.bookings || !data.setup.run
            || !data.nights.some((night) => night.has_season));
    }

    get reviewDone() {
        return Boolean(this.state.review?.done);
    }

    get panelVisible() {
        return this.wide ? !this.state.dockCollapsed : this.state.panelOpen || this.reviewDone;
    }

    get panelReview() {
        const review = this.state.review;
        return review && !review.done ? { position: review.index + 1, total: review.queue.length } : undefined;
    }

    percent(value) {
        return `${Math.round(value)}%`;
    }

    price(value) {
        return formatPrice(value, this.currency);
    }

    shown(cell) {
        return shownPrice(cell);
    }

    getCell(room, night) {
        const cell = this.state.cells[`${room.id}_${night.date}`];
        return cell && (!this.state.onlyPending || this.needsDecision(cell)) ? cell : false;
    }

    /** The visible cells of one night with their room type, for the list layout. */
    nightCells(night) {
        return this.state.data.room_types
            .map((room) => ({ room, cell: this.getCell(room, night) }))
            .filter((item) => item.cell);
    }

    cellTitle(cell) {
        return [STATE_LABELS[cell.state], ACTION_LABELS[cell.action], cell.locked && _t("Locked")]
            .filter(Boolean)
            .join(" · ");
    }

    /** The percent a cell shows in the price level view (place in the season range) and the occupancy view. */
    levelValue(cell) {
        if (this.layout !== "grid" || this.state.mode === "changes") {
            return null;
        }
        const pct =
            this.state.mode === "price"
                ? levelPct(shownPrice(cell), cell.season_min, cell.season_max)
                : levelPct(this.nightOf(cell)?.forecast_occ, 0, 100);
        return pct === null ? null : Math.round(pct);
    }

    get levelCaption() {
        return this.state.mode === "price"
            ? _t("of the season range: 0% season minimum, 100% season maximum")
            : _t("forecast occupancy");
    }

    cellClass(cell) {
        const pct = this.levelValue(cell);
        return [
            "o_rms_cell",
            pct === null ? `o_rms_cell_${cell.state}` : `o_rms_level_${levelStep(pct)}`,
            cell.not_for_sale && "o_rms_cell_nfs",
            this.state.selected === cell.id && "o_rms_selected",
            this.state.multi.includes(cell.id) && "o_rms_multi",
        ]
            .filter(Boolean)
            .join(" ");
    }

    setHover(room, night) {
        this.state.hover = { room: room.id, date: night.date };
    }

    clearHover() {
        this.state.hover = false;
    }

    crossClass(room, night) {
        const hover = this.state.hover;
        return {
            o_rms_weekend: night.weekend,
            o_rms_week_start: night.week_start,
            o_rms_highlight: night.date === this.state.highlight,
            o_rms_xhair: hover && (hover.room === room?.id || hover.date === night.date),
        };
    }

    cellById(id) {
        return this.cellList.find((cell) => cell.id === id);
    }

    async openNight(date) {
        Object.assign(this.state, { tab: "calendar", dateFrom: date, highlight: date });
        await this.reload();
    }

    setTab(tab) {
        Object.assign(this.state, { tab, multi: [], selected: false, panelOpen: false, review: null });
    }

    clearMulti() {
        this.state.multi = [];
    }

    endReview() {
        this.state.review = null;
    }

    select(id, openPanel) {
        this.state.selected = id;
        if (openPanel) {
            this.state.panelOpen = true;
            this.state.dockCollapsed = false;
            if (this.reviewDone) {
                this.state.review = null;
            }
        }
        this.followReview(id);
    }

    followReview(id) {
        const review = this.state.review;
        if (!review || review.done) {
            return;
        }
        const index = review.queue.indexOf(id);
        if (index === -1) {
            this.state.review = null;
        } else {
            review.index = index;
        }
    }

    closePanel() {
        this.state.panelOpen = false;
        if (this.docked) {
            this.state.selected = false;
        }
    }

    toggleMulti(id) {
        const multi = this.state.multi;
        this.state.multi = multi.includes(id) ? multi.filter((other) => other !== id) : [...multi, id];
    }

    /** A long touch press toggles the cell in multi-select, as ctrl or cmd+click does with a mouse. */
    onCellDown(ev, cell) {
        if (ev.pointerType === "touch" && this.state.data.can_decide) {
            this.longPress = setTimeout(() => {
                this.skipNextClick();
                this.toggleMulti(cell.id);
            }, LONG_PRESS);
        }
    }

    cancelLongPress() {
        clearTimeout(this.longPress);
    }

    /** The click that follows a long press or a swipe must not open the panel. */
    skipNextClick() {
        this.clickSkipped = true;
        setTimeout(() => (this.clickSkipped = false), LONG_PRESS);
    }

    onCellClick(ev, cell) {
        if (this.clickSkipped) {
            this.clickSkipped = false;
            return;
        }
        const canMulti = this.state.data.can_decide && this.layout === "grid";
        if (canMulti && this.state.multi.length && ev.pointerType === "touch") {
            this.toggleMulti(cell.id);
        } else if (ev.shiftKey && canMulti && this.state.selected) {
            this.state.multi = this.cellsBetween(this.cellById(this.state.selected), cell);
        } else if ((ev.metaKey || ev.ctrlKey) && canMulti && this.state.selected) {
            this.state.multi = this.state.multi.length ? this.state.multi : [this.state.selected];
            this.toggleMulti(cell.id);
        } else {
            this.state.multi = [];
            this.select(cell.id, true);
        }
    }

    onSwipeStart(ev) {
        if (!this.state.data.can_decide) {
            return;
        }
        this.swipe = { x: ev.clientX, dx: 0, moved: false, card: ev.currentTarget };
        try {
            ev.currentTarget.setPointerCapture(ev.pointerId);
        } catch {
            // no active pointer to capture (a synthetic event)
        }
    }

    onSwipeMove(ev) {
        const swipe = this.swipe;
        if (!swipe) {
            return;
        }
        swipe.dx = ev.clientX - swipe.x;
        if (!swipe.moved && Math.abs(swipe.dx) < SWIPE_SLOP) {
            return;
        }
        swipe.moved = true;
        const { card } = swipe;
        card.style.transition = "none";
        card.style.transform = `translateX(${swipe.dx}px)`;
        card.parentElement.dataset.dir = swipe.dx > 0 ? "right" : "left";
        card.parentElement.style.setProperty(
            "--swipe",
            Math.min(1, Math.abs(swipe.dx) / (card.offsetWidth * SWIPE_THRESHOLD))
        );
    }

    onSwipeEnd(cell) {
        const swipe = this.swipe;
        this.swipe = null;
        if (!swipe || !swipe.moved) {
            return;
        }
        this.skipNextClick();
        const { card, dx } = swipe;
        card.style.transition = "";
        if (Math.abs(dx) > card.offsetWidth * SWIPE_THRESHOLD) {
            card.style.transform = `translateX(${dx > 0 ? 100 : -100}%)`;
            const reduced = browser.matchMedia("(prefers-reduced-motion: reduce)").matches;
            setTimeout(() => this.act(dx > 0 ? "action_accept" : "action_reject", [cell.id]), reduced ? 0 : 150);
        } else {
            card.style.transform = "";
            card.parentElement.style.setProperty("--swipe", 0);
        }
    }

    /** Ids of the visible cells in the room and night rectangle between two cells. */
    cellsBetween(from, to) {
        const { room_types, nights } = this.state.data;
        const rooms = [from, to].map((cell) => room_types.findIndex((r) => r.id === cell.room_type_id));
        const days = [from, to].map((cell) => nights.findIndex((n) => n.date === cell.date));
        const ids = [];
        for (let r = Math.min(...rooms); r <= Math.max(...rooms); r++) {
            for (let d = Math.min(...days); d <= Math.max(...days); d++) {
                const cell = this.getCell(room_types[r], nights[d]);
                if (cell) {
                    ids.push(cell.id);
                }
            }
        }
        return ids;
    }

    moveSelection(dx, dy) {
        const { room_types, nights } = this.state.data;
        const current = this.cellById(this.state.selected);
        const room = current ? room_types.findIndex((r) => r.id === current.room_type_id) : 0;
        const night = current ? nights.findIndex((n) => n.date === current.date) : 0;
        const next = this.getCell(
            room_types[Math.max(0, Math.min(room_types.length - 1, room + dy))],
            nights[Math.max(0, Math.min(nights.length - 1, night + dx))]
        );
        if (next) {
            this.select(next.id, false);
        }
    }

    onKeydown(ev) {
        const { data } = this.state;
        if (!data || this.state.tab !== "calendar") {
            return;
        }
        if (ev.target.closest("input, textarea, select") || document.querySelector(".modal")) {
            return;
        }
        if (ev.ctrlKey || ev.metaKey || ev.altKey) {
            return;
        }
        const key = ev.key.length === 1 ? ev.key.toLowerCase() : ev.key;
        const cell = this.cellById(this.state.selected);
        if (MOVES[key]) {
            this.moveSelection(...MOVES[key]);
        } else if (key === "Enter" && cell) {
            this.select(cell.id, true);
        } else if (key === "Escape") {
            if (this.state.multi.length) {
                this.state.multi = [];
            } else {
                this.closePanel();
            }
        } else if (data.can_decide && cell && key === "a") {
            this.act("action_accept", [cell.id]);
        } else if (data.can_decide && cell && key === "r") {
            this.act("action_reject", [cell.id]);
        } else if (data.can_decide && cell && key === "l") {
            this.act(cell.locked ? "action_unlock" : "action_lock", [cell.id]);
        } else if (this.state.review && (key === "j" || key === "k")) {
            this.reviewStep(key === "j" ? 1 : -1);
        } else {
            return;
        }
        ev.preventDefault();
    }

    notifyDone(method, ids) {
        const [one, many] = DONE_MESSAGES[method];
        const undoable = UNDOABLE.includes(method);
        this.notification.add(ids.length === 1 ? one : sprintf(many, ids.length), {
            type: "success",
            autocloseDelay: TOAST_DELAY,
            buttons: undoable ? [{ name: _t("Undo"), onClick: () => this.act("action_undo", ids) }] : [],
        });
    }

    async act(method, ids, args = []) {
        await this.withBusy(method, async () => {
            const review = this.state.review;
            const advancing = review && !review.done && ids.length === 1 && ids[0] === this.state.selected;
            await this.orm.call("hotel.rms.price", method, [ids, ...args]);
            this.notifyDone(method, ids);
            this.state.multi = [];
            await this.load();
            this.state.version++;
            if (advancing && REVIEW_OUTCOMES[method]) {
                this.reviewStep(1, REVIEW_OUTCOMES[method]);
            }
        });
    }

    startReview() {
        const rooms = this.state.data.room_types;
        const order = (cell) => rooms.findIndex((room) => room.id === cell.room_type_id);
        const queue = this.cellList
            .filter((cell) => this.needsDecision(cell))
            .sort((a, b) => a.date.localeCompare(b.date) || order(a) - order(b))
            .map((cell) => cell.id);
        this.state.review = { queue, index: 0, accepted: 0, edited: 0, rejected: 0, done: false };
        this.state.multi = [];
        this.select(queue[0], true);
    }

    reviewStep(delta, outcome) {
        const review = this.state.review;
        if (outcome) {
            review[outcome]++;
        }
        review.index = Math.max(0, review.index + delta);
        if (review.index >= review.queue.length) {
            review.done = true;
            this.closePanel();
        } else {
            this.select(review.queue[review.index], true);
        }
    }

    acceptAll() {
        const ids = this.decisionIds;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Accept all"),
            body: _t("Accept the recommended price of %s nights?", ids.length),
            confirmLabel: _t("Accept"),
            confirm: () => this.act("action_accept", ids),
            cancel: () => {},
        });
    }

    async runNow() {
        await this.withBusy("run", async () => {
            await this.orm.call("hotel.rms.property", "action_run_engine", [[this.state.propertyId]]);
            await this.load();
            const run = this.state.data.last_run;
            if (run) {
                const done = run.state === "done";
                this.notification.add(run.message || (done ? _t("The run is finished.") : run.state_label), {
                    type: done ? "success" : "warning",
                });
            }
        });
    }

    async publish() {
        await this.withBusy("publish", async () => {
            const { method, done } = this.state.data.publish;
            const count = this.state.data.to_export_count;
            const result = await this.orm.call("hotel.rms.property", method, [[this.state.propertyId]]);
            if (result) {
                await this.action.doAction(result);
            }
            this.notification.add(sprintf(done, count), { type: "success" });
            await this.load();
        });
    }

    openHotel() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hotel.rms.property",
            res_id: this.state.propertyId || false,
            views: [[false, "form"]],
        });
    }

    importBookings() {
        this.action.doAction("hotel_rms.action_hotel_rms_import_new", {
            additionalContext: { default_property_id: this.state.propertyId },
        });
    }
}

registry.category("actions").add("hotel_rms.pricing_calendar", PricingCalendar);
