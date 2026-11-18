import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { formatFloat } from "@web/views/fields/formatters";
import { _t } from "@web/core/l10n/translation";

const COLUMNS = [
    { field: "rs_status", label: _t("RS"), align: "center", type: "badge" },
    { field: "name", label: _t("Good / Service"), align: "left", type: "char" },
    { field: "g_unit", label: _t("Unit"), align: "center", type: "char" },
    { field: "quantity", label: _t("Qty"), align: "right", type: "float", digits: [16, 4], sum: true },
    { field: "full_amount", label: _t("Total (VAT+Excise)"), align: "right", type: "float", digits: [16, 2], sum: true },
    { field: "tax_type", label: _t("Tax"), align: "center", type: "char" },
    { field: "vat_amount", label: _t("VAT"), align: "right", type: "float", digits: [16, 2], sum: true },
    { field: "excise_amount", label: _t("Excise"), align: "right", type: "float", digits: [16, 2], sum: true },
    { field: "net_amount", label: _t("Net"), align: "right", type: "float", digits: [16, 2], sum: true },
];

function getM2oName(val) {
    if (!val) return "";
    if (Array.isArray(val)) return val[1] || "";
    const name = val["display_name"];
    if (name) return name;
    return "";
}

const STATE_LABELS = {
    skipped: _t("Skipped"),
    not_sent: _t("Not Sent"),
    pending_edit: _t("Pending Edit"),
    synced: _t("Synced"),
    confirmed: _t("Confirmed"),
    superseded: _t("Superseded"),
    cancelled: _t("Cancelled"),
};

const TAX_TYPE_LABELS = {
    untaxed: _t("without VAT"),
    zero: _t("VAT 0%"),
    taxable: _t("taxable"),
};

const STATE_BADGE_CLASS = {
    skipped: "text-bg-secondary",
    not_sent: "text-bg-light",
    pending_edit: "text-bg-warning",
    synced: "text-bg-info",
    confirmed: "text-bg-success",
    superseded: "text-bg-secondary",
    cancelled: "text-bg-danger",
};

function buildRow(rec, idx, settlementMode) {
    const d = rec.data;
    const native = settlementMode === "native_attach";
    const priceTotal = native ? Math.abs(d.price_total || 0) : d.price_total || 0;
    const priceSubtotal = native ? Math.abs(d.price_subtotal || 0) : d.price_subtotal || 0;
    const taxType = d.rs_einv_vat_class || "untaxed";

    const state = d.rs_sync_state || (d.rs_synced ? "synced" : "not_sent");
    return {
        _num: idx + 1,
        rs_status: STATE_LABELS[state] || (d.rs_synced ? _t("Synced") : _t("Not synced")),
        _rs_synced: d.rs_synced,
        _rs_state: state,
        _rs_state_class: STATE_BADGE_CLASS[state] || "text-bg-warning",
        name: d.rs_einv_goods || "",
        g_unit: getM2oName(d.product_uom_id),
        quantity: Math.abs(d.quantity || 0),
        full_amount: priceTotal,
        tax_type: TAX_TYPE_LABELS[taxType],
        vat_amount: Math.abs(d.rs_einv_vat_amount || 0) * (priceTotal < 0 ? -1 : 1),
        excise_amount: 0,
        net_amount: priceSubtotal,
    };
}

export class RseLinesField extends Component {
    static template = "rs_einvoice.RseLinesField";
    props = useProps(standardFieldProps);

    get columns() {
        return COLUMNS;
    }

    _getProductLines() {
        const raw = this.props.record.data[this.props.name];
        if (!raw || !raw.records) return [];
        let lines = raw.records.filter((r) => r.data.display_type === "product");
        if (!lines.length) {
            lines = raw.records.filter((r) => (r.data.price_total || 0) !== 0);
        }
        return lines;
    }

    get lines() {
        return this._getProductLines().map((rec, idx) => {
            const row = buildRow(rec, idx, this.props.record.data.rs_einv_advance_settlement_mode);
            const formatted = {
                _num: row._num,
                _rs_synced: row._rs_synced,
                _rs_state: row._rs_state,
                _rs_state_class: row._rs_state_class,
            };
            for (const col of COLUMNS) {
                if (col.type === "float") {
                    formatted[col.field] = formatFloat(row[col.field], { digits: col.digits });
                } else {
                    formatted[col.field] = row[col.field];
                }
            }
            return formatted;
        });
    }

    get totals() {
        const productLines = this._getProductLines();
        if (!productLines.length) return {};

        const sums = {};
        for (const col of COLUMNS.filter((c) => c.sum)) {
            sums[col.field] = 0;
        }

        productLines.forEach((rec, idx) => {
            const row = buildRow(rec, idx, this.props.record.data.rs_einv_advance_settlement_mode);
            for (const col of COLUMNS.filter((c) => c.sum)) {
                sums[col.field] += row[col.field];
            }
        });

        const formatted = {};
        for (const col of COLUMNS.filter((c) => c.sum)) {
            formatted[col.field] = formatFloat(sums[col.field], { digits: col.digits });
        }
        return formatted;
    }
}

registry.category("fields").add("rse_lines_table", {
    component: RseLinesField,
    supportedTypes: ["one2many"],
});
