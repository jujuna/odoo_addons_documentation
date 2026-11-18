import { ListRenderer } from "@web/views/list/list_renderer";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { proxy } from "@odoo/owl";

const STORAGE_KEY = "hr_payroll.display_all_payslip_lines";
export const payslipShowAllState = proxy({ showAll: JSON.parse(localStorage.getItem(STORAGE_KEY)) || false });

// the default color of a salary rule, the rows keep the color of the theme
const DEFAULT_RULE_COLORS = ["#000000", "#000", "black"];

export class PayslipListRowVisibilityRenderer extends ListRenderer {
    static rowsTemplate = "hr_payroll.PayslipListRowVisibility";
    static recordRowTemplate = "hr_payroll.PayslipListRecordRow";

    /**
     * The salary_rule_style column only loads the style of the rule: it is never displayed.
     * It can't be column_invisible in the arch, the fields of the rule are not read for an
     * always invisible many2one.
     */
    getActiveColumns() {
        return super.getActiveColumns().filter((col) => col.widget !== "salary_rule_style");
    }

    /**
     * Style of the salary rule of the line (bold, italic...), as on the printed payslip.
     * The rule comes with its style fields from the salary_rule_style widget.
     */
    getRule(record) {
        return record.data.salary_rule_id || {};
    }

    getRuleColor(record) {
        const color = (this.getRule(record).color || "").trim();
        return DEFAULT_RULE_COLORS.includes(color.toLowerCase()) ? "" : color;
    }

    getRowClass(record) {
        const rule = this.getRule(record);
        const classNames = [super.getRowClass(record)];
        if (rule.bold) {
            classNames.push("fw-bold");
        }
        if (rule.italic) {
            classNames.push("fst-italic");
        }
        if (rule.underline) {
            classNames.push("text-decoration-underline");
        }
        if (rule.space_above) {
            classNames.push("o_payslip_line_space_above");
        }
        if (this.getRuleColor(record)) {
            classNames.push("o_payslip_line_colored");
        }
        return classNames.join(" ");
    }

    getRowStyle(record) {
        const color = this.getRuleColor(record);
        return color ? `--o-payslip-line-color: ${color};` : "";
    }

    isDefaultValue(column, record) {
        const expr = column.attrs && column.attrs.is_default_value;
        return Boolean(expr) && evaluateBooleanExpr(expr, record.evalContextWithVirtualIds);
    }

    // the value is not rendered but the cell is kept: a hidden cell leaves a hole in the row hover
    isValueHidden(column, record) {
        // a title only shows its name
        if (column.name !== "name" && this.getRule(record).title) {
            return true;
        }
        return !payslipShowAllState.showAll && this.isDefaultValue(column, record);
    }

    getCellClass(column, record) {
        let classNames = super.getCellClass(column, record);
        const rule = this.getRule(record);
        if (column.name === "name" && rule.indented) {
            classNames += " ps-4";
        }
        if (payslipShowAllState.showAll && this.isDefaultValue(column, record)) {
            classNames += " text-muted";
        }
        return classNames;
    }

    get VisibleRows() {
        return this.props.list.records.filter((record) => {
            if (payslipShowAllState.showAll) {
                return true;
            }
            const appears = record.data.appears_on_payslip;
            return appears === 'always' || (appears === 'non_zero' && record.data.total !== 0);
        });
    }
}
