import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { formatPrice } from "../../utils/pricing_utils";

export class PriceChange extends Component {
    static template = "hotel_rms.PriceChange";
    props = useProps({
        current: t.number().optional(0),
        recommended: t.number().optional(0),
        currency: t.object(),
        compact: t.boolean().optional(false),
        plain: t.boolean().optional(false),
    });

    get price() {
        return this.props.recommended ? formatPrice(this.props.recommended, this.props.currency) : "—";
    }

    /** Change from the live price (the current prop) to the recommended price. */
    get delta() {
        const { current, recommended, currency } = this.props;
        if (!recommended || this.props.plain) {
            return null;
        }
        if (!current) {
            return { kind: "new", label: _t("New") };
        }
        const diff = Number((recommended - current).toFixed(currency.decimals));
        if (!diff) {
            return { kind: "same", label: _t("No change") };
        }
        return {
            kind: diff > 0 ? "up" : "down",
            icon: diff > 0 ? "arrow_upward" : "arrow_downward",
            label: formatPrice(Math.abs(diff), currency),
        };
    }
}
