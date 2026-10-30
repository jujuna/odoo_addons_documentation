import {X2ManyField, x2ManyField} from "@web/views/fields/x2many/x2many_field";
import {PayslipListRowVisibilityRenderer} from "../views/payslip_form/hr_payslip_list_row_visibility_renderer";
import {registry} from "@web/core/registry";


export class PayslipLines2ManyField extends X2ManyField {
    static components = { ...X2ManyField.components, ListRenderer: PayslipListRowVisibilityRenderer }
}

export const payslipLines2ManyField = {
    ...x2ManyField,
    component: PayslipLines2ManyField,
};

registry.category("fields").add("payslip_lines_2many", payslipLines2ManyField);

// loads the style of the salary rule of a payslip line, applied on its row by the payslip lines list
registry.category("fields").add("salary_rule_style", {
    ...registry.category("fields").get("many2one"),
    relatedFields: [
        { name: "bold", type: "boolean" },
        { name: "italic", type: "boolean" },
        { name: "underline", type: "boolean" },
        { name: "indented", type: "boolean" },
        { name: "space_above", type: "boolean" },
        { name: "title", type: "boolean" },
        { name: "color", type: "char" },
    ],
});
