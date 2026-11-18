import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Field } from "@web/views/fields/field";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

export class RsForm30SummaryGrid extends X2ManyField {
    static template = "gec_income_tax_report.RsForm30SummaryGrid";
    static components = { ...X2ManyField.components, Field };

    setup() {
        super.setup();
        this.action = useService("action");
    }

    get records() {
        return this.list.records || [];
    }

    get canEdit() {
        return !this.props.readonly;
    }

    get canExplain() {
        return Boolean(this.props.record.resId);
    }

    explain(record) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Cell %s: %s", record.data.code, record.data.name),
            res_model: "rs.form30.explain",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_declaration_id: this.props.record.resId,
                default_cell_code: record.data.code,
                dialog_size: "large",
            },
        });
    }

    wandTitle(record) {
        if (record.data.is_boolean) {
            return _t("Refreshed by Odoo at every Generate and Export");
        }
        return _t(
            "Odoo proposes %s; the cell follows Odoo until you type your own value",
            record.data.proposed_value
        );
    }

    isEditable(record) {
        return this.canEdit && !record.data.computed && !record.data.is_section;
    }

    onRowClick(record) {
        if (this.isEditable(record) && !record.isInEdition) {
            this.list.enterEditMode(record);
        }
    }
}

export const rsForm30SummaryGrid = { ...x2ManyField, component: RsForm30SummaryGrid };

registry.category("fields").add("rs_form30_summary_grid", rsForm30SummaryGrid);
