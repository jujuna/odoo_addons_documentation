import { Component, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class LockIconField extends Component {
    static template = "hotel_rms.LockIconField";
    props = useProps(standardFieldProps);
}

export const lockIconField = {
    component: LockIconField,
    displayName: _t("Lock icon"),
    supportedTypes: ["boolean"],
};

registry.category("fields").add("rms_lock", lockIconField);
