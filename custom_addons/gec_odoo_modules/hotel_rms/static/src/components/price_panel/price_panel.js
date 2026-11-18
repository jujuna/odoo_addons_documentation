import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { deserializeDate, deserializeDateTime } from "@web/core/l10n/dates";
import { Component, onWillStart, proxy, signal, t, useProps } from "@odoo/owl";
import { PaceChart } from "../pace_chart/pace_chart";
import { PriceChange } from "../price_change/price_change";
import { PricePosition } from "../price_position/price_position";
import { Waterfall } from "../waterfall/waterfall";
import { QUICK_PCTS, STATE_LABELS, daysLeftText, formatPct, formatPrice, shownPrice } from "../../utils/pricing_utils";

const CONFIDENCE_LABELS = { low: _t("Low"), medium: _t("Medium"), high: _t("High") };
const DISMISS_DISTANCE = 80;
const EXPAND_DISTANCE = 40;
const TAP_DISTANCE = 5;

export class PricePanel extends Component {
    static template = "hotel_rms.PricePanel";
    static components = { PaceChart, PriceChange, PricePosition, Waterfall };
    props = useProps({
        priceId: t.number(),
        currency: t.object(),
        review: t.object().optional(),
        busy: t.or([t.string(), t.boolean()]).optional(false),
        embedded: t.boolean().optional(false),
        onAction: t.function(),
        onSkip: t.function(),
        onPrevious: t.function(),
        onClose: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.ui = useService("ui");
        this.root = signal.ref();
        this.quickPcts = QUICK_PCTS.map((pct) => ({ pct, label: formatPct(pct) }));
        this.state = proxy({ data: null, ownRate: "", note: "", full: false });
        this.dragStart = null;
        onWillStart(async () => {
            this.state.data = await this.orm.call("hotel.rms.price", "get_panel_data", [[this.props.priceId]]);
            this.state.note = this.state.data.note;
        });
    }

    get title() {
        const { room_type, date } = this.state.data;
        return `${room_type} · ${deserializeDate(date).toFormat("ccc d MMM")}`;
    }

    get progress() {
        const { position, total } = this.props.review;
        return _t("%(position)s of %(total)s", { position, total });
    }

    get shown() {
        return shownPrice(this.state.data);
    }

    /** Phones show the details only at full height; an embedded (form) panel always shows them. */
    get showDetails() {
        return this.props.embedded || !this.ui.isSmall || this.state.full;
    }

    expand() {
        this.state.full = true;
    }

    get hasActions() {
        return Object.values(this.state.data.actions).some(Boolean);
    }

    get stateLabel() {
        return STATE_LABELS[this.state.data.state];
    }

    get booked() {
        const { otb_rooms, capacity } = this.state.data.forecast;
        return _t("%(booked)s of %(rooms)s rooms", { booked: otb_rooms, rooms: capacity });
    }

    get occupancy() {
        return `${Math.round(this.state.data.forecast.forecast_occ)}%`;
    }

    get confidence() {
        return CONFIDENCE_LABELS[this.state.data.forecast.confidence_level] || "-";
    }

    get daysLeft() {
        return daysLeftText(this.state.data.forecast.lead_days);
    }

    get pace() {
        const pace = this.state.data.forecast.pace_pct;
        if (!pace) {
            return _t("As usual");
        }
        return pace > 0 ? _t("%s%% ahead of usual", pace) : _t("%s%% behind usual", -pace);
    }

    price(value) {
        return formatPrice(value, this.props.currency);
    }

    historyDate(value) {
        return deserializeDateTime(value).toFormat("d MMM HH:mm");
    }

    /** The note is saved before the action, so the audit rows keep it. */
    async run(method, args) {
        if (this.state.note !== this.state.data.note) {
            await this.orm.write("hotel.rms.price", [this.props.priceId], { note: this.state.note });
        }
        await this.props.onAction(method, args);
    }

    async useMyPrice() {
        const rate = Number(this.state.ownRate);
        if (rate > 0) {
            await this.orm.write("hotel.rms.price", [this.props.priceId], { decided_rate: rate });
            await this.run("action_use_my_price");
        }
    }

    openRecord() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hotel.rms.price",
            res_id: this.props.priceId,
            views: [[false, "form"]],
        });
    }

    onHandleDown(ev) {
        this.dragStart = ev.clientY;
        ev.target.setPointerCapture(ev.pointerId);
    }

    onHandleMove(ev) {
        if (this.dragStart !== null) {
            this.root().style.transform = `translateY(${Math.max(0, ev.clientY - this.dragStart)}px)`;
        }
    }

    onHandleUp(ev) {
        if (this.dragStart === null) {
            return;
        }
        const dy = ev.clientY - this.dragStart;
        this.root().style.transform = "";
        this.dragStart = null;
        if (Math.abs(dy) < TAP_DISTANCE) {
            this.state.full = !this.state.full;
        } else if (dy < -EXPAND_DISTANCE) {
            this.state.full = true;
        } else if (dy > DISMISS_DISTANCE) {
            if (this.state.full) {
                this.state.full = false;
            } else {
                this.props.onClose();
            }
        }
    }
}
