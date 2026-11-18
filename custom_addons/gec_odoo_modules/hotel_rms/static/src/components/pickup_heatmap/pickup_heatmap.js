import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { LEVEL_STEPS } from "../../utils/pricing_utils";

const { DateTime } = luxon;

const MIN_SCALE = 5;
const NEGATIVE_STEPS = 2;
const MINUS = "−";

function signed(count) {
    return `${count > 0 ? "+" : count < 0 ? MINUS : ""}${Math.abs(count)}`;
}

export class PickupHeatmap extends Component {
    static template = "hotel_rms.PickupHeatmap";
    props = useProps({
        days: t.array(t.object()),
        onNightClick: t.function().optional(() => () => {}),
    });

    get weekdays() {
        return Array.from({ length: 7 }, (_, index) => DateTime.fromObject({ weekday: index + 1 }).toFormat("ccc"));
    }

    /** Floors, so that a lone booking does not paint the darkest shade. */
    get scales() {
        const pickups = this.props.days.map((day) => day.pickup);
        return {
            up: Math.max(MIN_SCALE, ...pickups),
            down: Math.max(NEGATIVE_STEPS, ...pickups.map((pickup) => -pickup)),
        };
    }

    changeText(pickup) {
        if (!pickup) {
            return _t("No change");
        }
        return Math.abs(pickup) === 1 ? _t("%s room", signed(pickup)) : _t("%s rooms", signed(pickup));
    }

    shade(pickup) {
        const { up, down } = this.scales;
        if (pickup > 0) {
            return `o_rms_level_${Math.min(LEVEL_STEPS - 1, Math.ceil((pickup / up) * LEVEL_STEPS) - 1)}`;
        }
        return pickup < 0
            ? `o_rms_neg_${Math.min(NEGATIVE_STEPS - 1, Math.ceil((-pickup / down) * NEGATIVE_STEPS) - 1)}`
            : "o_rms_hm_zero";
    }

    /** Rows start on Monday; the first row is padded before the first night. */
    get weeks() {
        const { days } = this.props;
        const weeks = [];
        let row = null;
        days.forEach((day, index) => {
            const date = deserializeDate(day.date);
            if (!row || date.weekday === 1) {
                row = { key: day.date, label: date.toFormat("d MMM"), cells: Array(index ? 0 : date.weekday - 1).fill(null) };
                weeks.push(row);
            }
            const title = date.toFormat("ccc d MMM");
            const tooltip = _t("%(night)s · %(change)s this week · %(booked)s of %(capacity)s booked", {
                night: title,
                change: this.changeText(day.pickup),
                booked: day.booked,
                capacity: day.capacity,
            });
            row.cells.push({
                date: day.date,
                day: date.day,
                text: day.pickup ? signed(day.pickup) : "",
                cls: `o_rms_hm_cell ${this.shade(day.pickup)} ${index === 0 ? "o_rms_hm_today" : ""}`,
                tooltip,
            });
        });
        return weeks;
    }

    /** Each label is the first number of its shade. */
    get legend() {
        const { up, down } = this.scales;
        const gains = Array.from({ length: LEVEL_STEPS }, (_, step) => ({
            cls: `o_rms_level_${step}`,
            label: signed(Math.floor((step * up) / LEVEL_STEPS) + 1),
        }));
        const losses = Array.from({ length: NEGATIVE_STEPS }, (_, step) => ({
            cls: `o_rms_neg_${NEGATIVE_STEPS - 1 - step}`,
            label: signed(-(Math.floor(((NEGATIVE_STEPS - 1 - step) * down) / NEGATIVE_STEPS) + 1)),
        }));
        return [...losses, { cls: "o_rms_hm_zero", label: "0" }, ...gains];
    }
}
