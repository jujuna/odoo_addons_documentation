import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { x2ManyField } from "@web/views/fields/x2many/x2many_field";

import { RsForm30Grid } from "../rs_form30_grid/rs_form30_grid";

// Vehicle is an input column only: it fills the other cells and is never exported.
const CAR_COLUMNS = [
    {
        field: "vehicle_id",
        label: _t("Vehicle"),
        cssClass: "o_rsf30_col_vehicle",
        width: 220,
        minWidth: 150,
    },
    {
        field: "license_plate",
        label: _t("Registration number (state plate)"),
        cssClass: "o_rsf30_col_plate",
        width: 230,
        minWidth: 150,
    },
    {
        field: "engine_id",
        label: _t("Engine volume"),
        cssClass: "o_rsf30_col_engine",
        width: 260,
        minWidth: 170,
    },
    {
        field: "employee_id",
        label: _t("Employee"),
        cssClass: "o_rsf30_col_employee",
        width: 220,
        minWidth: 150,
    },
    {
        field: "name",
        label: _t("Surname, name"),
        cssClass: "o_rsf30_col_person",
        width: 240,
        minWidth: 160,
    },
    {
        field: "identification",
        label: _t("Personal number"),
        cssClass: "o_rsf30_col_personal_no",
        width: 210,
        minWidth: 140,
    },
    {
        field: "amount",
        label: _t("Tax amount"),
        cssClass: "o_rsf30_col_car_tax",
        total: true,
        width: 180,
        minWidth: 120,
    },
];

export class RsForm30CarGrid extends RsForm30Grid {
    static template = "gec_income_tax_report.RsForm30CarGrid";

    get columns() {
        return CAR_COLUMNS;
    }

    get leafColumns() {
        return this.columns.slice(0, -1);
    }

    get taxColumn() {
        return this.columns.at(-1);
    }

    get canEdit() {
        return !this.props.readonly;
    }

    onRowClick(record) {
        if (this.canEdit && !record.isInEdition) {
            this.list.enterEditMode(record);
        }
    }

    addLine() {
        this.list.addNewRecord({ position: "bottom", mode: "edit" });
    }

    removeLine(record) {
        this.list.delete(record);
    }
}

export const rsForm30CarGrid = { ...x2ManyField, component: RsForm30CarGrid };

registry.category("fields").add("rs_form30_car_grid", rsForm30CarGrid);
