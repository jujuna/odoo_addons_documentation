import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { formatPrice } from "../../utils/pricing_utils";

export class Waterfall extends Component {
    static template = "hotel_rms.Waterfall";
    props = useProps({
        rows: t.array(t.object({ code: t.string(), label: t.string(), amount: t.number() })),
        base: t.number().optional(0),
        total: t.number().optional(0),
        currency: t.object(),
    });

    get bars() {
        let running = this.props.base;
        const bars = [{ code: "base", label: _t("Base"), from: 0, to: running, amount: running }];
        for (const row of this.props.rows.filter((row) => row.amount)) {
            bars.push({ ...row, from: running, to: running + row.amount, signed: true });
            running += row.amount;
        }
        bars.push({ code: "total", label: _t("Recommended"), from: 0, to: this.props.total, amount: this.props.total });
        const scale = Math.max(...bars.map((bar) => Math.max(bar.from, bar.to))) || 1;
        return bars.map((bar) => {
            const left = Math.min(bar.from, bar.to);
            return {
                ...bar,
                style: `left: ${(left / scale) * 100}%; width: ${(Math.abs(bar.to - bar.from) / scale) * 100}%`,
                tone: bar.signed ? (bar.amount > 0 ? "up" : "down") : bar.code,
                text: (bar.signed && bar.amount > 0 ? "+" : "") + formatPrice(bar.amount, this.props.currency),
            };
        });
    }
}
