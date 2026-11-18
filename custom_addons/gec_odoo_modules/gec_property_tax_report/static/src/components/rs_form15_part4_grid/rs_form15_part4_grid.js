/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { x2ManyField } from "@web/views/fields/x2many/x2many_field";

import { RsForm15Grid, many2oneId } from "../rs_form15_grid/rs_form15_grid";

// Declaration columns 2 to 8. The rate and the tax are locked: rs.ge derives both from
// the territorial unit and the land type, and recomputes them on import.
const PART4_COLUMNS = [
    { field: "land_type_id", label: _t("Kind and description"), cssClass: "o_rsf15_col_land_type", filterType: "many2one", width: 240, minWidth: 150 },
    { field: "land_territory_id", label: _t("Territorial unit, location"), cssClass: "o_rsf15_col_land_territory", filterType: "many2one", width: 320, minWidth: 190 },
    { field: "area", label: _t("Area (ha, m²)"), cssClass: "o_rsf15_col_area", total: true, width: 140, minWidth: 105 },
    { field: "taxable_area", label: _t("Taxable area after exemption"), cssClass: "o_rsf15_col_taxable_area", total: true, width: 200, minWidth: 130 },
    { field: "exemption_basis_id", label: _t("Exemption basis"), cssClass: "o_rsf15_col_basis", filterType: "many2one", width: 230, minWidth: 140 },
    { field: "rate", label: _t("Rate"), cssClass: "o_rsf15_col_rate", locked: true, width: 120, minWidth: 90 },
    { field: "tax_amount", label: _t("Property tax (GEL)"), cssClass: "o_rsf15_col_tax", total: true, locked: true, width: 160, minWidth: 115 },
];

export class RsForm15Part4Grid extends RsForm15Grid {
    get columns() {
        return PART4_COLUMNS;
    }

    get explainPart() {
        return "part4";
    }

    get gridTitle() {
        return _t("Form V-01 — Part IV");
    }

    get gridSubtitle() {
        return _t("Property tax on land, as at 1 April");
    }

    get gridIcon() {
        return "map";
    }

    get gridHint() {
        return _t(
            "Rows are built from the land plot register. The rate is the rs.ge table value: " +
            "for non-agricultural land it is a municipal coefficient on 0.24 GEL/m², not an " +
            "amount. Locked columns are recomputed by rs.ge."
        );
    }

    get emptyHint() {
        return _t("Register your land plots under Configuration, then press Generate.");
    }

    // The portal fills the taxable area only when an exemption applies.
    isCellHidden(record, column) {
        return column.field === "taxable_area" && !many2oneId(record.data.exemption_basis_id);
    }

    // Like the portal, a coefficient rate shows the base it multiplies: "0 *0.24".
    cellSuffix(record, column) {
        return column.field === "rate" && record.data.base_rate ? `*${record.data.base_rate}` : "";
    }

    sourceRecord(record) {
        const plotId = many2oneId(record.data.plot_id);
        return plotId ? { resModel: "rs.form15.land.plot", resId: plotId } : null;
    }
}

export const rsForm15Part4Grid = {
    ...x2ManyField,
    component: RsForm15Part4Grid,
};

registry.category("fields").add("rs_form15_part4_grid", rsForm15Part4Grid);
