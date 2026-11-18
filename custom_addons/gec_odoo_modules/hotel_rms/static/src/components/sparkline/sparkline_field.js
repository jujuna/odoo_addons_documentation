import { Component, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Sparkline } from "./sparkline";

export class SparklineField extends Component {
    static template = "hotel_rms.SparklineField";
    static components = { Sparkline };
    props = useProps(standardFieldProps);

    get values() {
        return this.props.record.data[this.props.name] || [];
    }
}

export const sparklineField = {
    component: SparklineField,
    displayName: _t("Sparkline"),
    supportedTypes: ["json"],
};

registry.category("fields").add("rms_sparkline", sparklineField);
