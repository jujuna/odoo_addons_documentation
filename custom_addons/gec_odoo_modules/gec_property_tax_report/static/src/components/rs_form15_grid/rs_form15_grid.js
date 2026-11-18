/** @odoo-module **/

import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Field } from "@web/views/fields/field";
import { formatFloat } from "@web/views/fields/formatters";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

import { onMounted, onPatched, onWillUnmount, proxy, signal } from "@odoo/owl";

const ACTION_COLUMN_WIDTH = 96;

export { many2oneId };

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

/** Shared worktable of the rs.ge form 15 annexes; the header is data-driven: a column with a `group` joins
 * its neighbours under one spanning header, others span both header rows (parts III and IV share one template). */
export class RsForm15Grid extends X2ManyField {
    static template = "gec_property_tax_report.RsForm15Grid";
    static components = {
        ...X2ManyField.components,
        Field,
    };

    setup() {
        super.setup();
        this.action = useService("action");
        this.dialog = useService("dialog");
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
        this.shownColumnsKey = this.shownColumnsSignature;
        onPatched(() => {
            const key = this.shownColumnsSignature;
            if (key !== this.shownColumnsKey) {
                this.shownColumnsKey = key;
                if (this.state.autoFit) {
                    this.fitColumns();
                }
            }
        });
        onWillUnmount(() => {
            this.resizeObserver?.disconnect();
            this.stopColumnResize();
        });
    }

    // what a subclass overrides
    get columns() {
        return [];
    }

    get gridTitle() {
        return "";
    }

    get gridSubtitle() {
        return "";
    }

    get gridIcon() {
        return "table_chart";
    }

    get gridHint() {
        return "";
    }

    get emptyHint() {
        return _t("Press Generate to build the rows.");
    }

    /** A cell the portal hides for this row: render a dash instead of an input. */
    isCellHidden() {
        return false;
    }

    /** Text the portal prints after the value of a cell, such as "*0.24" after a rate. */
    cellSuffix() {
        return "";
    }

    /** A column no row needs at all is left out of the table, header included. */
    isColumnShown() {
        return true;
    }

    get shownColumns() {
        return this.columns.filter((column) => this.isColumnShown(column));
    }

    get shownColumnsSignature() {
        return this.shownColumns.map((column) => column.field).join(",");
    }

    /** The record a row was generated from, for the external-link button. */
    sourceRecord() {
        return null;
    }

    /** "part3" or "part4": which line model the explanation wizard should read. */
    get explainPart() {
        return "";
    }

    get headerLayout() {
        const top = [];
        const leaf = [];
        for (const column of this.shownColumns) {
            const previous = top.at(-1);
            if (column.group && previous && previous.group === column.group) {
                previous.span += 1;
                leaf.push(column);
            } else if (column.group) {
                top.push({ key: column.field, label: column.group, group: column.group, span: 1 });
                leaf.push(column);
            } else {
                top.push({ key: column.field, label: column.label, column, span: 1 });
            }
        }
        const hasGroups = leaf.length > 0;
        for (const head of top) {
            // Computed here: mixing boolean operators with a ternary in a QWeb attribute is error-prone.
            head.colspan = head.span > 1 ? head.span : false;
            head.rowspan = hasGroups && head.span === 1 ? 2 : false;
        }
        return { top, leaf, hasGroups, indexRowspan: hasGroups ? 2 : false };
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
        return this.visibleRecords.filter((record) => record.data.warning).length;
    }

    get canEdit() {
        return !this.props.readonly;
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
        const width =
            ACTION_COLUMN_WIDTH +
            this.shownColumns.reduce(
                (total, column) => total + this.state.columnWidths[column.field],
                0
            );
        return `width: ${Math.ceil(width)}px`;
    }

    /** Plain read-only text to show instead of the column's field, or "" for the field. */
    cellText(record, column) {
        return "";
    }

    cellClass(record, column) {
        return {
            [column.cssClass]: true,
            o_rsf15_locked_cell: Boolean(column.locked),
            o_rsf15_hidden_cell: this.isCellHidden(record, column),
        };
    }

    /** Locked columns, a read-only form and read-only fields; readonly=false would offer an input that never saves. */
    isCellReadonly(column) {
        return (
            Boolean(column.locked) ||
            !this.canEdit ||
            Boolean(this.list.fields[column.field]?.readonly)
        );
    }

    /** The column's <field> node from the list arch, so its domain, options and placeholder reach the cell. */
    fieldInfo(column) {
        return this.archInfo.fieldNodes?.[`${column.field}_0`];
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
        const columns = this.shownColumns;
        const minimumWidth = columns.reduce((total, column) => total + column.minWidth, 0);
        const defaultWidth = columns.reduce((total, column) => total + column.width, 0);
        const targetWidth = Math.max(availableWidth, minimumWidth);

        if (targetWidth <= defaultWidth) {
            const capacity = defaultWidth - minimumWidth;
            const ratio = capacity ? (targetWidth - minimumWidth) / capacity : 0;
            for (const column of columns) {
                this.state.columnWidths[column.field] =
                    column.minWidth + (column.width - column.minWidth) * ratio;
            }
        } else {
            const extraWidth = targetWidth - defaultWidth;
            for (const column of columns) {
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
        document.body.classList.add("o_rsf15_resizing");
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
        document.body.classList.remove("o_rsf15_resizing");
    }

    /** A saved row opens for editing only through its Edit button, as on the portal. */
    editLine(record) {
        this.list.enterEditMode(record);
    }

    /** Close the edited row and save so the server checks it at once, as the portal does; a refused row stays. */
    async finishLine() {
        if (await this.list.leaveEditMode({ validate: true })) {
            await this.props.record.save();
        }
    }

    addLine() {
        this.list.addNewRecord({ position: "bottom", mode: "edit" });
    }

    removeLine(record) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove Row"),
            body: _t("Remove this row from the declaration?"),
            confirmLabel: _t("Remove"),
            confirmClass: "btn-danger",
            confirm: () => this.list.delete(record),
            cancel: () => {},
        });
    }

    canExplain(record) {
        return Boolean(this.explainPart && this.props.record.resId && record.resId);
    }

    explain(record) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("How this row was built"),
            res_model: "rs.form15.explain",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_declaration_id: this.props.record.resId,
                default_line_part: this.explainPart,
                default_line_ref: record.resId,
                dialog_size: "large",
            },
        });
    }

    canOpenSource(record) {
        return Boolean(this.sourceRecord(record)?.resId);
    }

    sourceUrl(record) {
        const source = this.sourceRecord(record);
        return source?.resId ? `/odoo/${source.resModel}/${source.resId}` : "#";
    }
}

export const rsForm15Grid = {
    ...x2ManyField,
    component: RsForm15Grid,
};

registry.category("fields").add("rs_form15_grid", rsForm15Grid);
