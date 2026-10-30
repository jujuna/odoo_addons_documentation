import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// first match wins: the suffix of an input is its unit, translated in the user language
const UNIT_ICONS = [
    [/%/, "percent"],
    [/\bkm\b|kilomet|\bmiles?\b/i, "directions_car"],
    [/night|nuit|nacht/i, "bed"],
    [/^h$|hour|heure|\buur\b|stunde/i, "schedule"],
    [/^d$|day|jour|\bdag|\btag|week|semaine|month|mois|maand|monat|year|année|jaar|jahr/i, "calendar_today"],
    [/ticket|voucher|chèque|cheque/i, "confirmation_number"],
    [/[€$£¥₹]|\b(eur|usd|gbp|chf|aed|sar|inr)\b/i, "payments"],
];

/**
 * Icon of the unit of a payslip input, from the suffix of its salary rule: on the suffix
 * itself, or on the salary rule.
 */
export class InputUnitTileField extends Component {
    static template = "hr_payroll.InputUnitTileField";
    props = useProps(standardFieldProps);

    get suffix() {
        const value = this.props.record.data[this.props.name];
        return (this.props.record.fields[this.props.name].type === "many2one" ? value?.input_suffix : value) || "";
    }

    get icon() {
        const suffix = this.suffix.trim();
        return UNIT_ICONS.find(([pattern]) => pattern.test(suffix))?.[1] || "calculate";
    }
}

registry.category("fields").add("input_unit_tile", {
    component: InputUnitTileField,
});

registry.category("fields").add("salary_rule_unit_tile", {
    component: InputUnitTileField,
    relatedFields: [{ name: "input_suffix", type: "char" }],
});
