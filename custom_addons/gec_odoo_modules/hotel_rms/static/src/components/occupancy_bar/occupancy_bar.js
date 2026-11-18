import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { clampPct } from "../../utils/pricing_utils";

export class OccupancyBar extends Component {
    static template = "hotel_rms.OccupancyBar";
    props = useProps({
        booked_pct: t.number().optional(0),
        forecast_pct: t.number().optional(0),
        confidence: t.string().optional(),
    });

    get low() {
        return this.props.confidence === "low";
    }

    get title() {
        const { booked_pct, forecast_pct } = this.props;
        return this.low
            ? _t("Low confidence: there is little booking history for a night like this")
            : _t("Forecast %(forecast)s%, booked %(booked)s%", {
                  forecast: Math.round(forecast_pct),
                  booked: Math.round(booked_pct),
              });
    }

    width(value) {
        return `width: ${clampPct(value)}%`;
    }
}
