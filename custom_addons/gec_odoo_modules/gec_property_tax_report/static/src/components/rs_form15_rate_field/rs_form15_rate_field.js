/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";

// Column 10 on rs.ge takes "1" or "0.xxx": at most 1, three decimals; keystrokes leaving anything else are undone.
// The leasing cap (0.6) is the server's to enforce: it depends on the company and the property type.
const RATE_PATTERN = /^(?:0(?:[.,]\d{0,3})?|1(?:[.,]0{0,3})?)?$/;

export class RsForm15RateField extends FloatField {
    static template = "gec_property_tax_report.RsForm15RateField";

    onFocusIn(ev) {
        super.onFocusIn(ev);
        this.lastValidInput = RATE_PATTERN.test(ev.target.value) ? ev.target.value : "";
    }

    onRateInput(ev) {
        const input = ev.target;
        if (RATE_PATTERN.test(input.value)) {
            this.lastValidInput = input.value;
            return;
        }
        const caret = Math.max((input.selectionStart || 0) - 1, 0);
        input.value = this.lastValidInput ?? "";
        input.setSelectionRange(caret, caret);
        ev.stopImmediatePropagation();
    }
}

export const rsForm15RateField = {
    ...floatField,
    component: RsForm15RateField,
    displayName: _t("rs.ge Rate"),
};

registry.category("fields").add("rs_form15_rate", rsForm15RateField);
