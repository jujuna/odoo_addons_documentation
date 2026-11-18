import { Component, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class NightCellField extends Component {
    static template = "hotel_rms.NightCellField";
    props = useProps(standardFieldProps);

    get night() {
        return this.props.record.data[this.props.name]?.toFormat("ccc d MMM") || "";
    }

    /** The room type is its own column on wide screens; on a phone it moves under the night. */
    get room() {
        return this.props.record.data.room_type_id?.display_name || "";
    }
}

export const nightCellField = {
    component: NightCellField,
    displayName: _t("Night and room"),
    supportedTypes: ["date"],
};

registry.category("fields").add("rms_night", nightCellField);
