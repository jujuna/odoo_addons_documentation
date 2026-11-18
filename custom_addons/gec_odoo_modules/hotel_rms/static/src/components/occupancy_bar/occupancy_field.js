import { Component, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { OccupancyBar } from "./occupancy_bar";

export class OccupancyField extends Component {
    static template = "hotel_rms.OccupancyField";
    static components = { OccupancyBar };
    props = useProps(standardFieldProps);

    get forecast() {
        return this.props.record.data[this.props.name] || 0;
    }

    /** Needs otb_occ and confidence_level in the view; a missing otb_occ reads as 0. */
    get booked() {
        return this.props.record.data.otb_occ || 0;
    }

    get confidence() {
        return this.props.record.data.confidence_level || undefined;
    }
}

export const occupancyField = {
    component: OccupancyField,
    displayName: _t("Occupancy bar"),
    supportedTypes: ["float"],
};

registry.category("fields").add("rms_occupancy", occupancyField);

/** Average of a group row in a list, rounded like the occupancy bar. */
registry.category("formatters").add("rms_occupancy", (value) => (typeof value === "number" ? `${Math.round(value)}%` : ""));
