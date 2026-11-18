/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { x2ManyField } from "@web/views/fields/x2many/x2many_field";

import { RsForm15Grid } from "../rs_form15_grid/rs_form15_grid";

// Declaration columns 2 to 15. Columns 8 and 9 sit under one spanning header, as on
// the paper form. Columns 11, 13 and 15 are locked: the portal recomputes them.
const PART3_COLUMNS = [
    { field: "property_type_id", label: _t("Property"), cssClass: "o_rsf15_col_type", filterType: "many2one", width: 260, minWidth: 170 },
    { field: "asset_id", label: _t("Name"), cssClass: "o_rsf15_col_name", filterType: "many2one", width: 220, minWidth: 140 },
    { field: "territory_id", label: _t("Territorial unit"), cssClass: "o_rsf15_col_territory", filterType: "many2one", width: 230, minWidth: 150 },
    { field: "acquisition_year_id", label: _t("Year acquired"), cssClass: "o_rsf15_col_year", filterType: "many2one", width: 120, minWidth: 90 },
    { field: "average_value", label: _t("Average annual NBV"), cssClass: "o_rsf15_col_nbv", total: true, width: 190, minWidth: 130 },
    { field: "revaluation_coefficient_id", label: _t("Revaluation coefficient"), cssClass: "o_rsf15_col_coefficient", filterType: "many2one", width: 150, minWidth: 110 },
    { field: "exemption_amount", label: _t("Amount"), group: _t("Tax exemption"), cssClass: "o_rsf15_col_exemption", total: true, width: 150, minWidth: 110 },
    { field: "exemption_basis_id", label: _t("Basis"), group: _t("Tax exemption"), cssClass: "o_rsf15_col_basis", filterType: "many2one", width: 230, minWidth: 140 },
    { field: "tax_rate", label: _t("Rate"), cssClass: "o_rsf15_col_rate", width: 120, minWidth: 90 },
    { field: "tax_amount", label: _t("Tax"), cssClass: "o_rsf15_col_tax", total: true, locked: true, width: 160, minWidth: 115 },
    { field: "advance_amount", label: _t("Current payment"), cssClass: "o_rsf15_col_advance", total: true, width: 170, minWidth: 120 },
    { field: "difference", label: _t("To add (+) / reduce (-)"), cssClass: "o_rsf15_col_difference", total: true, locked: true, width: 165, minWidth: 120 },
    { field: "months_of_existence", label: _t("Months existing"), cssClass: "o_rsf15_col_months", width: 120, minWidth: 90 },
    { field: "prorated_amount", label: _t("Tax for the period"), cssClass: "o_rsf15_col_prorated", total: true, locked: true, width: 185, minWidth: 130 },
];

// The portal hides these two columns unless the property type is immovable,
// and asks for the object's name only for named types.
const IMMOVABLE_ONLY = new Set(["acquisition_year_id", "revaluation_coefficient_id"]);
// Column 2 of a named row: the asset is picked here and its name is what the portal
// receives. A row Generate built from an asset group shows the group's name instead.
const NAMED_ONLY = new Set(["asset_id"]);

export class RsForm15Part3Grid extends RsForm15Grid {
    get columns() {
        return PART3_COLUMNS;
    }

    get explainPart() {
        return "part3";
    }

    get gridTitle() {
        return _t("Form V-01 — Part III");
    }

    get gridSubtitle() {
        return _t("Property tax other than land");
    }

    get gridIcon() {
        return "business";
    }

    get gridHint() {
        return _t(
            "Rows are built from Fixed Assets and grouped by property type and territorial " +
            "unit; named types such as pipelines and buildings get one row per asset or asset group. Locked " +
            "columns are recomputed by rs.ge; a yellow row needs review."
        );
    }

    get emptyHint() {
        return _t("Tag your assets with a property type and a territorial unit, then press Generate.");
    }

    isColumnShown(column) {
        if (IMMOVABLE_ONLY.has(column.field)) {
            return this.records.some((record) => record.data.is_immovable);
        }
        if (NAMED_ONLY.has(column.field)) {
            return this.records.some((record) => record.data.has_name);
        }
        return true;
    }

    isCellHidden(record, column) {
        return (
            (IMMOVABLE_ONLY.has(column.field) && !record.data.is_immovable) ||
            (NAMED_ONLY.has(column.field) && !record.data.has_name)
        );
    }

    cellText(record, column) {
        return column.field === "asset_id" && record.data.asset_group_id ? record.data.name || "" : "";
    }
}

export const rsForm15Part3Grid = {
    ...x2ManyField,
    component: RsForm15Part3Grid,
};

registry.category("fields").add("rs_form15_part3_grid", rsForm15Part3Grid);
