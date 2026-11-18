import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/views/fields/formatters";
import { parseFloat } from "@web/views/fields/parsers";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { Component, t, useProps } from "@odoo/owl";

// Formula rows rs.ge still lets the taxpayer type in: they are taken from the annexes here.
const TYPED_FORMULA_ROWS = ["25.1", "25.3", "27.4"];
// Rows rs.ge locks in both columns although Odoo reads them from accounting.
const LOCKED_ROWS = ["16.2"];

/**
 * Part III of the profit tax declaration drawn like the rs.ge e-form: nested row codes, the row text, and the
 * amounts of columns 2 and 3 as white boxes (typed) or grey locked boxes (computed). Typing a box stores the
 * difference from Odoo's calculation as the row's adjustment, then saves so the formulas run.
 */
export class RsCitPart3Field extends Component {
    static template = "gec_profit_tax_report.RsCitPart3Field";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get records() {
        return this.props.record.data[this.props.name].records;
    }

    get columnKeys() {
        return ["col2", "col3"];
    }

    get col3Open() {
        return this.props.record.data.col3_rate > 0;
    }

    /**
     * One entry per row, as an outline: the table has three code columns (16 │ 16.1 │ 16.1.1), the text, then the
     * amounts. Each row writes its own code in the column of its level, so 16 comes first, then 16.1 indented under
     * it, then 16.1.1 under that. The text fills the code columns to the right of the code.
     */
    get rows() {
        const records = this.records;
        const codes = records.map((rec) => rec.data.code || "");
        return records.map((rec, index) => {
            const code = codes[index];
            const level = Math.min(code.split(".").length - 1, 2);
            const hasChildren = (codes[index + 1] || "").startsWith(code + ".");
            return {
                rec,
                code,
                level,
                indent: Array.from({ length: level }, (_, depth) => depth),
                textColspan: 3 - level,
                bold: level === 0 || (rec.data.kind === "calc" && hasChildren),
                groupStart: level === 0,
            };
        });
    }

    format(value) {
        return formatFloat(value || 0, { digits: [16, 2] });
    }

    showColumn(row, column) {
        const columns = row.rec.data.columns;
        return columns === "both" || columns === column;
    }

    isTyped(row, column) {
        if (this.props.readonly) {
            return false;
        }
        if (column === "col3" && !this.col3Open) {
            return false;
        }
        if (LOCKED_ROWS.includes(row.code)) {
            return false;
        }
        return row.rec.data.kind !== "calc" || TYPED_FORMULA_ROWS.includes(row.code);
    }

    fields(column) {
        return column === "col2"
            ? { total: "amount", auto: "amount_auto", adjust: "amount_adjust" }
            : { total: "amount3", auto: "amount3_auto", adjust: "amount3_adjust" };
    }

    adjustTitle(row, column) {
        const names = this.fields(column);
        return _t("Calculated %(calculated)s, adjustment %(adjustment)s", {
            calculated: this.format(row.rec.data[names.auto]),
            adjustment: this.format(row.rec.data[names.adjust]),
        });
    }

    isAdjusted(row, column) {
        return Boolean(row.rec.data[this.fields(column).adjust]);
    }

    async onChange(row, column, ev) {
        const names = this.fields(column);
        let value;
        try {
            value = parseFloat(ev.target.value || "0");
        } catch {
            ev.target.value = this.format(row.rec.data[names.total]);
            return;
        }
        const adjust = value - (row.rec.data[names.auto] || 0);
        if (Math.abs(adjust - (row.rec.data[names.adjust] || 0)) < 0.005) {
            ev.target.value = this.format(row.rec.data[names.total]);
            return;
        }
        await row.rec.update({ [names.adjust]: Math.round(adjust * 100) / 100 });
        await this.props.record.save();
    }

    async openItems(row) {
        const action = await this.orm.call("rs.cit.declaration.line", "action_open_move_lines", [[row.rec.resId]]);
        this.action.doAction(action);
    }
}

export const rsCitPart3Field = {
    component: RsCitPart3Field,
    displayName: _t("Profit Tax Part III"),
    supportedTypes: ["one2many"],
    useSubView: true,
};

registry.category("fields").add("rs_cit_part3", rsCitPart3Field);
