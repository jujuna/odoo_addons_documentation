/** @odoo-module **/
import { Component, useProps } from "@odoo/owl";
import { AccordionItem } from "@web/core/dropdown/accordion_item";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class DeclareSalaryRenderer extends Component {
    static template = "declare_salary_renderer_template";
    static components = {
        AccordionItem
    };

    props = useProps(standardFieldProps);

    get declaration() {
        return this.props.record.data[this.props.name];
    }
}

export const declareSalaryField = {
    component: DeclareSalaryRenderer,
    displayName: _t("Salary Data"),
};


registry.category("fields").add("declare_salary_widget", declareSalaryField);
