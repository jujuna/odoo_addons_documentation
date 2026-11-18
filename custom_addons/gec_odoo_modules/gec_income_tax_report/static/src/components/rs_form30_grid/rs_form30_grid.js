import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { Field } from "@web/views/fields/field";
import { formatFloat } from "@web/views/fields/formatters";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

import { onMounted, onWillUnmount, proxy, signal } from "@odoo/owl";

const ACTION_COLUMN_WIDTH = 74;

export { many2oneId };

const COLUMNS = [
    { field: "identification", cssClass: "o_rsf30_col_identification", width: 145, minWidth: 115 },
    { field: "first_name", cssClass: "o_rsf30_col_first_name", width: 145, minWidth: 100 },
    { field: "last_name", cssClass: "o_rsf30_col_last_name", width: 170, minWidth: 110 },
    { field: "address", cssClass: "o_rsf30_col_address", width: 210, minWidth: 125 },
    {
        field: "country_id",
        cssClass: "o_rsf30_col_country",
        filterType: "many2one",
        width: 170,
        minWidth: 120,
    },
    {
        field: "category_id",
        cssClass: "o_rsf30_col_category",
        filterType: "many2one",
        width: 200,
        minWidth: 140,
    },
    {
        field: "income_type_id",
        cssClass: "o_rsf30_col_income",
        filterType: "many2one",
        width: 190,
        minWidth: 140,
    },
    { field: "amount", cssClass: "o_rsf30_col_amount", total: true, width: 130, minWidth: 95 },
    {
        field: "pension_amount",
        cssClass: "o_rsf30_col_pension",
        total: true,
        width: 230,
        minWidth: 160,
    },
    {
        field: "other_relief",
        cssClass: "o_rsf30_col_relief",
        total: true,
        width: 130,
        minWidth: 95,
    },
    { field: "date", cssClass: "o_rsf30_col_date", filterType: "date", width: 130, minWidth: 105 },
    { field: "rate", cssClass: "o_rsf30_col_rate", width: 140, minWidth: 100 },
    { field: "tax_amount", cssClass: "o_rsf30_col_tax", total: true, width: 150, minWidth: 110 },
    {
        field: "international_agreement_exempt_tax",
        cssClass: "o_rsf30_col_treaty",
        total: true,
        width: 210,
        minWidth: 145,
    },
    {
        field: "foreign_tax_credit",
        cssClass: "o_rsf30_col_foreign",
        total: true,
        width: 210,
        minWidth: 145,
    },
    {
        field: "from_treasury",
        cssClass: "o_rsf30_col_treasury",
        filterType: "boolean",
        width: 120,
        minWidth: 90,
    },
    {
        field: "in_file",
        cssClass: "o_rsf30_col_treasury",
        filterType: "boolean",
        width: 100,
        minWidth: 80,
    },
    {
        field: "exported_on",
        cssClass: "o_rsf30_col_date",
        filterType: "date",
        width: 130,
        minWidth: 105,
    },
];

const SOURCE_LABELS = {
    payslip: _t("Payslip"),
    payment: _t("Payment"),
    entry: _t("Journal Entry"),
    bill: _t("Vendor Bill"),
    manual: _t("Manual"),
};

const ISSUE_ICONS = { note: "info", warning: "warning", blocker: "error" };
const ISSUE_CLASSES = { note: "text-info", warning: "text-warning", blocker: "text-danger" };

function many2oneId(value) {
    if (!value) {
        return false;
    }
    if (Array.isArray(value)) {
        return value[0];
    }
    return value.id;
}

function many2oneName(value) {
    if (!value) {
        return "";
    }
    if (Array.isArray(value)) {
        return value[1] || "";
    }
    return value.display_name || "";
}

function searchableValue(value) {
    if (value === false || value === null || value === undefined) {
        return "";
    }
    if (value && typeof value.toISODate === "function") {
        return value.toISODate();
    }
    return String(value);
}

export class RsForm30Grid extends X2ManyField {
    static template = "gec_income_tax_report.RsForm30Grid";
    static components = { ...X2ManyField.components, Field };

    setup() {
        super.setup();
        this.gridRef = signal.ref();
        this.state = proxy({
            filters: Object.fromEntries(this.columns.map((column) => [column.field, ""])),
            columnWidths: Object.fromEntries(
                this.columns.map((column) => [column.field, column.width])
            ),
            autoFit: true,
        });
        onMounted(() => {
            this.resizeObserver = new ResizeObserver((entries) => {
                if (this.state.autoFit && entries[0]) {
                    this.fitColumns(entries[0].contentRect.width);
                }
            });
            this.resizeObserver.observe(this.gridRef());
            this.fitColumns();
        });
        onWillUnmount(() => {
            this.resizeObserver?.disconnect();
            this.stopColumnResize();
        });
    }

    get columns() {
        return COLUMNS;
    }

    get records() {
        return this.list.records || [];
    }

    get visibleRecords() {
        return this.records.filter((record) =>
            this.columns.every((column) => this.matchesFilter(record, column))
        );
    }

    get hasFilters() {
        return Object.values(this.state.filters).some(Boolean);
    }

    get warningCount() {
        return this.props.record.data.warning_count || 0;
    }

    get blockerCount() {
        return this.props.record.data.blocker_count || 0;
    }

    get leftOutCount() {
        return this.props.record.data.left_out_count || 0;
    }

    get totals() {
        const totals = Object.fromEntries(
            this.columns.filter((column) => column.total).map((column) => [column.field, 0])
        );
        for (const record of this.visibleRecords) {
            for (const fieldName of Object.keys(totals)) {
                totals[fieldName] += record.data[fieldName] || 0;
            }
        }
        return Object.fromEntries(
            Object.entries(totals).map(([fieldName, value]) => [
                fieldName,
                formatFloat(value, { digits: [16, 2] }),
            ])
        );
    }

    get tableStyle() {
        const width = ACTION_COLUMN_WIDTH + Object.values(this.state.columnWidths).reduce(
            (total, columnWidth) => total + columnWidth,
            0
        );
        return `width: ${Math.ceil(width)}px`;
    }

    matchesFilter(record, column) {
        const filter = this.state.filters[column.field];
        if (!filter) {
            return true;
        }
        const value = record.data[column.field];
        if (column.filterType === "many2one") {
            return String(many2oneId(value) || "") === filter;
        }
        if (column.filterType === "boolean") {
            return (value ? "1" : "0") === filter;
        }
        return searchableValue(value).toLocaleLowerCase().includes(filter.toLocaleLowerCase());
    }

    filterOptions(fieldName) {
        const values = new Map();
        for (const record of this.records) {
            const value = record.data[fieldName];
            const id = many2oneId(value);
            if (id) {
                values.set(String(id), many2oneName(value));
            }
        }
        return [...values.entries()]
            .map(([value, label]) => ({ value, label }))
            .sort((a, b) => a.label.localeCompare(b.label));
    }

    onFilterInput(fieldName, event) {
        this.state.filters[fieldName] = event.target.value;
    }

    clearFilters() {
        for (const column of this.columns) {
            this.state.filters[column.field] = "";
        }
    }

    columnStyle(column) {
        return `width: ${Math.round(this.state.columnWidths[column.field])}px`;
    }

    resetColumnWidths() {
        this.fitColumns();
    }

    fitColumns(containerWidth = this.gridRef()?.clientWidth || 0) {
        const availableWidth = Math.max(containerWidth - ACTION_COLUMN_WIDTH, 0);
        const minimumWidth = this.columns.reduce((total, column) => total + column.minWidth, 0);
        const defaultWidth = this.columns.reduce((total, column) => total + column.width, 0);
        const targetWidth = Math.max(availableWidth, minimumWidth);

        if (targetWidth <= defaultWidth) {
            const capacity = defaultWidth - minimumWidth;
            const ratio = capacity ? (targetWidth - minimumWidth) / capacity : 0;
            for (const column of this.columns) {
                this.state.columnWidths[column.field] =
                    column.minWidth + (column.width - column.minWidth) * ratio;
            }
        } else {
            const extraWidth = targetWidth - defaultWidth;
            for (const column of this.columns) {
                this.state.columnWidths[column.field] =
                    column.width + extraWidth * (column.width / defaultWidth);
            }
        }
        this.state.autoFit = true;
    }

    startColumnResize(column, event) {
        this.stopColumnResize();
        this.state.autoFit = false;
        const startX = event.clientX;
        const startWidth = this.state.columnWidths[column.field];
        this.columnResizeMove = (moveEvent) => {
            this.state.columnWidths[column.field] = Math.max(
                column.minWidth,
                startWidth + moveEvent.clientX - startX
            );
        };
        this.columnResizeEnd = () => this.stopColumnResize();
        window.addEventListener("mousemove", this.columnResizeMove);
        window.addEventListener("mouseup", this.columnResizeEnd, { once: true });
        document.body.classList.add("o_rsf30_resizing");
    }

    stopColumnResize() {
        if (this.columnResizeMove) {
            window.removeEventListener("mousemove", this.columnResizeMove);
            this.columnResizeMove = null;
        }
        if (this.columnResizeEnd) {
            window.removeEventListener("mouseup", this.columnResizeEnd);
            this.columnResizeEnd = null;
        }
        document.body.classList.remove("o_rsf30_resizing");
    }

    sourceLabel(record) {
        return SOURCE_LABELS[record.data.source] || SOURCE_LABELS.manual;
    }

    issueLevel(record) {
        return record.data.issue_level || (record.data.warning ? "warning" : "");
    }

    issueIcon(record) {
        return ISSUE_ICONS[this.issueLevel(record)];
    }

    issueClass(record) {
        return ISSUE_CLASSES[this.issueLevel(record)];
    }

    get manualRowTitle() {
        return _t("Open manual row");
    }

    isManualRow(record) {
        return record.data.source === "manual" && Boolean(record.resId);
    }

    openManualRow(record) {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Manual Row"),
                res_model: "rs.form30.line",
                res_id: record.resId,
                views: [[false, "form"]],
                target: "new",
                context: {
                    dialog_size: "large",
                    rs_form30_locked: this.props.record.data.state !== "draft",
                },
            },
            { onClose: () => this.props.record.load() }
        );
    }

    sourceRecord(record) {
        if (record.data.source === "entry" || record.data.source === "bill") {
            return { resModel: "account.move", resId: many2oneId(record.data.move_id) };
        }
        if (record.data.source === "payslip") {
            return { resModel: "hr.payslip", resId: many2oneId(record.data.payslip_id) };
        }
        if (record.data.source === "payment") {
            return { resModel: "account.payment", resId: many2oneId(record.data.payment_id) };
        }
        return null;
    }

    canOpenSource(record) {
        return Boolean(this.sourceRecord(record)?.resId);
    }

    sourceButtonTitle(record) {
        return _t("Open source record: %s", this.sourceLabel(record));
    }

    sourceUrl(record) {
        const source = this.sourceRecord(record);
        return source?.resId ? `/odoo/${source.resModel}/${source.resId}` : "#";
    }

    isPartnerColumn(column) {
        return column.field === "first_name" || column.field === "last_name";
    }

    partnerUrl(record) {
        const partnerId = many2oneId(record.data.partner_id);
        return partnerId ? `/odoo/res.partner/${partnerId}` : "";
    }

    /** Open the row's contact like a many2one link; Ctrl/Cmd-click opens a new tab. */
    openPartner(record, ev) {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "res.partner",
                res_id: many2oneId(record.data.partner_id),
                views: [[false, "form"]],
            },
            { newWindow: ev.ctrlKey || ev.metaKey }
        );
    }
}

export const rsForm30Grid = { ...x2ManyField, component: RsForm30Grid };

registry.category("fields").add("rs_form30_grid", rsForm30Grid);
