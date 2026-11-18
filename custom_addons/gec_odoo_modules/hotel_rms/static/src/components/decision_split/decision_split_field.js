import { Component, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { DecisionSplit } from "./decision_split";

export class DecisionSplitField extends Component {
    static template = "hotel_rms.DecisionSplitField";
    static components = { DecisionSplit };
    props = useProps(standardFieldProps);

    get counts() {
        return this.props.record.data[this.props.name] || {};
    }
}

export const decisionSplitField = {
    component: DecisionSplitField,
    displayName: _t("Decision split"),
    supportedTypes: ["json"],
};

registry.category("fields").add("rms_decision_split", decisionSplitField);
