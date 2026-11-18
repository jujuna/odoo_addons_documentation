import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { recordCurrency } from "../../utils/pricing_utils";
import { PriceChange } from "./price_change";

export class PriceChangeField extends Component {
    static template = "hotel_rms.PriceChangeField";
    static components = { PriceChange };
    props = useProps({
        ...standardFieldProps,
        currentField: t.string().optional("published_rate"),
        plain: t.boolean().optional(false),
    });

    get current() {
        return this.props.record.data[this.props.currentField];
    }

    get currency() {
        return recordCurrency(this.props.record);
    }
}

export const priceChangeField = {
    component: PriceChangeField,
    displayName: _t("Price change"),
    supportedTypes: ["monetary"],
    extractProps: ({ options }) => ({ currentField: options.current_field, plain: Boolean(options.plain) }),
};

registry.category("fields").add("rms_price_change", priceChangeField);
