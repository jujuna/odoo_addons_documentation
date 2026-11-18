import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate, deserializeDateTime } from "@web/core/l10n/dates";
import { formatCurrency } from "@web/core/currency";
import { useService } from "@web/core/utils/hooks";
import { AccuracyChart } from "../components/accuracy_chart/accuracy_chart";
import { CountUp } from "../components/count_up/count_up";
import { DecisionDoughnut } from "../components/decision_doughnut/decision_doughnut";
import { ListDialog } from "../components/list_dialog/list_dialog";
import { NightsChart } from "../components/nights_chart/nights_chart";
import { PickupHeatmap } from "../components/pickup_heatmap/pickup_heatmap";
import { PriceChange } from "../components/price_change/price_change";
import { Sparkline } from "../components/sparkline/sparkline";
import { YearPaceChart } from "../components/year_pace_chart/year_pace_chart";
import { formatPrice, loadSetting, saveSetting } from "../utils/pricing_utils";

const AUDIT_ACTIONS = { accepted: "accept", edited: "edit", rejected: "reject" };
const PERIODS = [30, 60, 90];
const PERIOD_KEY = "hotel_rms.insights_nights";
const MINUS = "−";

export class PricingInsights extends Component {
    static template = "hotel_rms.PricingInsights";
    static components = {
        AccuracyChart,
        CountUp,
        DecisionDoughnut,
        NightsChart,
        PickupHeatmap,
        PriceChange,
        Sparkline,
        YearPaceChart,
    };
    props = useProps({ propertyId: t.number(), onNightClick: t.function() });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        const saved = Number(loadSetting(PERIOD_KEY, PERIODS[0]));
        this.state = proxy({ data: null, nights: PERIODS.includes(saved) ? saved : PERIODS[0], loading: false });
        this.periods = PERIODS;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            const data = await this.orm.call("hotel.rms.property", "get_insights", [[this.props.propertyId]], {
                nights: this.state.nights,
            });
            data.window = data.days.slice(0, data.nights);
            data.heat = data.days.slice(0, data.heatmap_days);
            data.pace = data.days.slice(0, data.pace_days);
            this.state.data = data;
        } finally {
            this.state.loading = false;
        }
    }

    async setNights(nights) {
        if (nights !== this.state.nights && !this.state.loading) {
            this.state.nights = nights;
            saveSetting(PERIOD_KEY, nights);
            await this.load();
        }
    }

    money = (value) => formatCurrency(value, this.state.data.currency.id, { digits: [69, 0] });

    rooms = (value) => `${Math.round(value)}`;

    percent = (value) => `${Math.round(value)}%`;

    signedRooms = (value) => `${Math.round(value) ? "+" : ""}${Math.round(value)}`;

    signedMoney(value) {
        return `${value < 0 ? MINUS : "+"}${this.money(Math.abs(value))}`;
    }

    get hasForecast() {
        return this.state.data.window.some((day) => day.forecast !== null);
    }

    get hasNights() {
        return this.hasForecast || this.state.data.window.some((day) => day.booked);
    }

    get tiles() {
        const { pulse, nights } = this.state.data;
        const change = pulse.revenue - pulse.revenue_before;
        const wholeBookings = _t("Counts only nights inside the period; the list shows whole bookings");
        return [
            {
                key: "revenue",
                label: _t("Revenue on the books, next %s nights", nights),
                value: pulse.revenue,
                format: this.money,
                note: change ? _t("%s vs 7 days ago", this.signedMoney(change)) : _t("No change vs 7 days ago"),
                tone: change > 0 ? "up" : change < 0 ? "down" : "same",
                open: () => this.openReservations(_t("Bookings"), []),
            },
            {
                key: "new",
                label: _t("New bookings, last 7 days"),
                value: pulse.new_rooms,
                format: this.signedRooms,
                unit: _t("room nights in the next %s nights", nights),
                title: wholeBookings,
                note: _t("%s added", this.money(pulse.new_revenue)),
                tone: pulse.new_rooms ? "up" : "same",
                open: () => this.openReservations(_t("Booked in the last 7 days"), [
                    ["booking_date", ">", this.state.data.week_ago],
                    ["booking_date", "<=", this.state.data.today],
                ]),
            },
            {
                key: "cancelled",
                label: _t("Cancellations, last 7 days"),
                value: pulse.cancel_rooms,
                format: this.rooms,
                unit: _t("room nights in the next %s nights", nights),
                title: wholeBookings,
                note: _t("%s lost", this.money(pulse.cancel_revenue)),
                tone: pulse.cancel_rooms ? "down" : "same",
                open: () => this.openReservations(_t("Cancelled in the last 7 days"), [
                    ["status", "=", "cancelled"],
                    ["cancel_date", ">", this.state.data.week_ago],
                    ["cancel_date", "<=", this.state.data.today],
                ], true),
            },
            {
                key: "forecast",
                label: _t("Forecast occupancy, next %s nights", nights),
                value: pulse.forecast_occ ?? 0,
                format: this.percent,
                note: pulse.forecast_occ === null ? _t("No forecast yet: run the engine.") : "",
                tone: "same",
                open: () => this.openForecast(),
            },
        ];
    }

    /** Pace against the same nights a year ago; empty when last year has no bookings. */
    get pace() {
        const days = this.state.data.pace;
        const now = days.reduce((sum, day) => sum + day.booked, 0);
        const before = days.reduce((sum, day) => sum + day.last_year, 0);
        if (!before) {
            return { empty: true };
        }
        const pct = Math.round((now / before - 1) * 100);
        return {
            empty: false,
            tone: pct > 0 ? "up" : pct < 0 ? "down" : "same",
            verdict: pct > 0
                ? _t("%s%% ahead of last year", pct)
                : pct < 0
                  ? _t("%s%% behind last year", -pct)
                  : _t("On par with last year"),
        };
    }

    get decisionTotal() {
        const { accepted, edited, rejected } = this.state.data.decisions;
        return accepted + edited + rejected;
    }

    get ownChange() {
        const pct = this.state.data.decisions.own_change_pct;
        return pct === null ? "" : `${pct > 0 ? "+" : ""}${Math.round(pct)}%`;
    }

    get ownChangeNote() {
        return _t("Own prices vs recommended");
    }

    price(value) {
        return formatPrice(value, this.state.data.currency);
    }

    get acceptanceNote() {
        const weeks = this.state.data.decisions.acceptance_weeks;
        return _t("%s accepted in the latest week", this.percent(weeks.at(-1)));
    }

    get leads() {
        return Object.keys(this.state.data.accuracy.rooms)
            .map(Number)
            .sort((a, b) => a - b);
    }

    /** A plain verdict on the nearest forecast: its level and how many rooms it is off on average. */
    get quality() {
        const { accuracy } = this.state.data;
        const [lead] = this.leads;
        const rooms = accuracy.rooms[lead];
        const level = { good: _t("Good"), fair: _t("Fair"), poor: _t("Poor") }[accuracy.level[lead]];
        const off = rooms < 0.5 ? _t("less than 1 room") : Math.round(rooms) === 1 ? _t("1 room") : _t("%s rooms", Math.round(rooms));
        const ahead = lead === 7 ? _t("a week ahead") : _t("%s days ahead", lead);
        return {
            tone: accuracy.level[lead],
            text: _t("%(level)s: about %(off)s off %(ahead)s", { level, off, ahead }),
        };
    }

    changeTime(change) {
        return deserializeDateTime(change.date).toRelative();
    }

    changeNight(change) {
        return deserializeDate(change.night).toFormat("ccc d MMM");
    }

    /** A list opens in a pop-up over the page; its Open full list button shows it full page. */
    openList(title, resModel, domain) {
        this.dialog.add(ListDialog, {
            title,
            resModel,
            domain: [["property_id", "=", this.props.propertyId], ...domain],
        });
    }

    /** Bookings overlapping the nights of the page: arrival before its end, departure after today. */
    openReservations(name, domain, cancelled = false) {
        const { today, end } = this.state.data;
        this.openList(name, "hotel.rms.reservation", [
            ...(cancelled ? [] : [["status", "!=", "cancelled"]]),
            ["departure", ">", today],
            ["arrival", "<", end],
            ...domain,
        ]);
    }

    openForecast() {
        const { today, end } = this.state.data;
        this.openList(_t("Forecast"), "hotel.rms.forecast", [
            ["is_current", "=", true],
            ["stay_date", ">=", today],
            ["stay_date", "<", end],
        ]);
    }

    openDecisions(slice) {
        this.openList(_t("Price History"), "hotel.rms.price.audit", [
            ["action", "=", AUDIT_ACTIONS[slice]],
            ["create_date", ">=", this.state.data.decisions.month_start],
        ]);
    }

    openPrice(change) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Price"),
            res_model: "hotel.rms.price",
            res_id: change.price_id,
            views: [[false, "form"]],
        });
    }
}
