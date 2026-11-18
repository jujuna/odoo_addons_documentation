/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// state value -> { icon: data-icon name, cls: colour class (see .scss) }.
const STATE_ICONS = {
    draft:     { icon: "description",  cls: "o_rs_state_draft" },
    active:    { icon: "check_circle", cls: "o_rs_state_active", filled: true },
    completed: { icon: "check_circle", cls: "o_rs_state_completed" },
    cancelled: { icon: "cancel",       cls: "o_rs_state_cancelled" },
};

class WaybillStateIcon extends Component {
    static template = "rs_waybill.WaybillStateIcon";
    props = useProps(standardFieldProps);

    get value() {
        return this.props.record.data[this.props.name];
    }

    get info() {
        return STATE_ICONS[this.value] || { icon: "radio_button_unchecked", cls: "" };
    }

    get label() {
        const selection = this.props.record.fields[this.props.name].selection || [];
        const found = selection.find((option) => option[0] === this.value);
        return found ? found[1] : this.value || "";
    }
}

export const waybillStateIcon = {
    component: WaybillStateIcon,
    displayName: "Waybill State Icon",
    supportedTypes: ["selection"],
};

registry.category("fields").add("waybill_state_icon", waybillStateIcon);
