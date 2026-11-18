import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ViewButton } from "@web/views/view_button/view_button";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class SetAsMainPartner extends Component {
    static template = "account_reports.SetAsMainPartner";
    static components = { ViewButton };

    props = useProps(standardWidgetProps);

    get isVisible() {
        const { vat, has_vat, parent_id } = this.props.record.data;
        const root = this.env.model.root;
        if (!has_vat || parent_id || !root.groupBy.includes("vat")) {
            return false;
        }
        return root.records.filter((r) => r.data.vat === vat && !r.data.parent_id).length > 1;
    }
}

registry.category("view_widgets").add("set_as_main_partner", {
    component: SetAsMainPartner,
    fieldDependencies: [
        { name: "vat", type: "char" },
        { name: "has_vat", type: "boolean" },
        { name: "parent_id", type: "many2one" },
    ],
});
