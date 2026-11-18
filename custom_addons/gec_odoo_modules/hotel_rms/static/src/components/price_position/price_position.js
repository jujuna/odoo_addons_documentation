import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { clampPct, formatPrice } from "../../utils/pricing_utils";

export class PricePosition extends Component {
    static template = "hotel_rms.PricePosition";
    props = useProps({
        min: t.number().optional(0),
        max: t.number().optional(0),
        current: t.number().optional(0),
        target: t.number().optional(0),
        recommended: t.number().optional(0),
        currency: t.object(),
    });

    get visible() {
        return this.props.max > this.props.min && this.props.recommended;
    }

    get markers() {
        const { min, max, current, target, recommended } = this.props;
        return [
            { key: "current", label: _t("Current"), value: current },
            { key: "target", label: _t("Model target"), value: target },
            { key: "recommended", label: _t("Recommended"), value: recommended },
        ]
            .filter((marker) => marker.value)
            .map((marker) => ({
                ...marker,
                style: `left: ${clampPct(((marker.value - min) / (max - min)) * 100)}%`,
                text: formatPrice(marker.value, this.props.currency),
            }));
    }

    price(value) {
        return formatPrice(value, this.props.currency);
    }
}
