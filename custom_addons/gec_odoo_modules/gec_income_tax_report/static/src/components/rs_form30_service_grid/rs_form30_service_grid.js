import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { x2ManyField } from "@web/views/fields/x2many/x2many_field";

import { RsForm30Grid, many2oneId } from "../rs_form30_grid/rs_form30_grid";

const SERVICE_COLUMNS = [
    {
        field: "identification",
        label: _t("Recipient identification / personal number"),
        cssClass: "o_rsf30_col_svc_id",
        width: 210,
        minWidth: 150,
    },
    {
        field: "first_name",
        label: _t("First name"),
        cssClass: "o_rsf30_col_svc_first",
        width: 180,
        minWidth: 120,
    },
    {
        field: "last_name",
        label: _t("Last name"),
        cssClass: "o_rsf30_col_svc_last",
        width: 180,
        minWidth: 120,
    },
    {
        field: "address",
        label: _t("Address"),
        cssClass: "o_rsf30_col_svc_address",
        width: 230,
        minWidth: 140,
    },
    {
        field: "country_id",
        label: _t("Residency (country)"),
        filterType: "many2one",
        cssClass: "o_rsf30_col_svc_country",
        width: 210,
        minWidth: 140,
    },
    {
        field: "service_type_id",
        label: _t("Service type"),
        filterType: "many2one",
        cssClass: "o_rsf30_col_svc_type",
        width: 260,
        minWidth: 170,
    },
    {
        field: "amount",
        label: _t("Amount"),
        total: true,
        cssClass: "o_rsf30_col_svc_amount",
        width: 160,
        minWidth: 110,
    },
    {
        field: "date",
        label: _t("Payment Date"),
        filterType: "date",
        cssClass: "o_rsf30_col_date",
        width: 130,
        minWidth: 105,
    },
    {
        field: "in_file",
        label: _t("In File"),
        filterType: "boolean",
        cssClass: "o_rsf30_col_treasury",
        width: 100,
        minWidth: 80,
    },
    {
        field: "exported_on",
        label: _t("Exported On"),
        filterType: "date",
        cssClass: "o_rsf30_col_date",
        width: 130,
        minWidth: 105,
    },
];

export class RsForm30ServiceGrid extends RsForm30Grid {
    static template = "gec_income_tax_report.RsForm30ServiceGrid";

    get columns() {
        return SERVICE_COLUMNS;
    }

    get leftOutCount() {
        return this.props.record.data.left_out_service_count || 0;
    }

    get nameColumns() {
        return this.columns.slice(1, 3);
    }

    sourceLabel(record) {
        return record.data.move_id ? _t("Journal Entry") : _t("Payment");
    }

    sourceRecord(record) {
        if (record.data.move_id) {
            return { resModel: "account.move", resId: many2oneId(record.data.move_id) };
        }
        return { resModel: "account.payment", resId: many2oneId(record.data.payment_id) };
    }
}

export const rsForm30ServiceGrid = { ...x2ManyField, component: RsForm30ServiceGrid };

registry.category("fields").add("rs_form30_service_grid", rsForm30ServiceGrid);
