import { registry } from "@web/core/registry";
import { getCurrency } from "@web/core/currency";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { formatFloat, formatMonetary } from "@web/views/fields/formatters";

/**
 * Amount in the unit of its salary rule (suffix), in the currency if the rule has none.
 * The rule must load its input_suffix, e.g. with the salary_rule_unit_tile widget.
 */
export class AmountWithRuleUnitField extends FloatField {
    static template = "hr_payroll.AmountWithRuleUnitField";

    get suffix() {
        return this.props.record.data.salary_rule_id?.input_suffix || "";
    }

    get currencyId() {
        return this.props.record.data.currency_id?.id;
    }

    get unit() {
        return this.suffix || getCurrency(this.currencyId)?.symbol || "";
    }

    get formattedValue() {
        if (!this.props.readonly) {
            return super.formattedValue;
        }
        if (this.suffix) {
            return `${formatFloat(this.value, { trailingZeros: false })} ${this.suffix}`;
        }
        return formatMonetary(this.value, { currencyId: this.currencyId });
    }
}

registry.category("fields").add("amount_with_rule_unit", {
    ...floatField,
    component: AmountWithRuleUnitField,
    fieldDependencies: [
        { name: "currency_id", type: "many2one" },
        { name: "salary_rule_id", type: "many2one" },
    ],
});
