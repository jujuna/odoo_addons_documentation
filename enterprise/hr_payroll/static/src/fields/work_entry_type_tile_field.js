import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Display code of a time type on a tile of its color, e.g. on the worked days cards of the payslip.
 */
export class WorkEntryTypeTileField extends Component {
    static template = "hr_payroll.WorkEntryTypeTileField";
    props = useProps(standardFieldProps);

    get workEntryType() {
        return this.props.record.data[this.props.name];
    }
}

registry.category("fields").add("work_entry_type_tile", {
    component: WorkEntryTypeTileField,
    relatedFields: [
        { name: "display_code", type: "char" },
        { name: "color", type: "integer" },
    ],
});
