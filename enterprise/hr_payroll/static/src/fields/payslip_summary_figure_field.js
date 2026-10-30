import { Component, useProps } from "@odoo/owl";
import { getCurrency } from "@web/core/currency";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { formatFloat } from "@web/views/fields/formatters";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Figure of the summary of the payslip (net salary, worked days): its decimals smaller,
 * the currency symbol as big as the units.
 */
export class PayslipSummaryFigureField extends Component {
    static template = "hr_payroll.PayslipSummaryFigureField";
    props = useProps(standardFieldProps);

    get currency() {
        const { record, name } = this.props;
        if (record.fields[name].type !== "monetary") {
            return null;
        }
        const currencyField = record.fields[name].currency_field || "currency_id";
        return getCurrency(record.data[currencyField]?.id);
    }

    /**
     * @returns {{ main: string, decimals: string, symbol: string, symbolBefore: boolean }}
     *  e.g. "4,320", ".00", "€" and false
     */
    get parts() {
        const value = this.props.record.data[this.props.name] || 0;
        const currency = this.currency;
        const formatted = currency
            ? formatFloat(value, { digits: currency.digits })
            : formatFloat(value, { digits: [16, 2], trailingZeros: false });
        const index = formatted.lastIndexOf(localization.decimalPoint);
        return {
            main: index === -1 ? formatted : formatted.slice(0, index),
            decimals: index === -1 ? "" : formatted.slice(index),
            symbol: currency?.symbol || "",
            symbolBefore: currency?.position === "before",
        };
    }
}

registry.category("fields").add("payslip_summary_figure", {
    component: PayslipSummaryFigureField,
    supportedTypes: ["float", "monetary"],
});
