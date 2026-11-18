import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { formatFloat } from "@web/views/fields/formatters";
import { parseFloat } from "@web/views/fields/parsers";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { Component, t, useProps } from "@odoo/owl";

// Rows of annex 3 that rs.ge asks the revaluation part for: loans given and loans received.
const LOAN_SEQUENCES = [1, 2];

/**
 * Annex 3 drawn like the rs.ge e-form: white boxes for the opening balance, increase and decrease (and their
 * revaluation part for loans), and the closing balance locked as opening + increase - decrease.
 */
export class RsCitAnnex3Field extends Component {
    static template = "gec_profit_tax_report.RsCitAnnex3Field";
    props = useProps({ ...standardFieldProps });

    get records() {
        return [...this.props.record.data[this.props.name].records].sort((a, b) => a.data.sequence - b.data.sequence);
    }

    hasRevaluation(rec) {
        return LOAN_SEQUENCES.includes(rec.data.sequence);
    }

    format(value) {
        return formatFloat(value || 0, { digits: [16, 2] });
    }

    closing(rec) {
        return (rec.data.amount1 || 0) + (rec.data.amount2 || 0) - (rec.data.amount4 || 0);
    }

    async onChange(rec, fname, ev) {
        let value;
        try {
            value = parseFloat(ev.target.value || "0");
        } catch {
            ev.target.value = this.format(rec.data[fname]);
            return;
        }
        if (Math.abs(value - (rec.data[fname] || 0)) < 0.005) {
            return;
        }
        await rec.update({ [fname]: Math.round(value * 100) / 100 });
        await this.props.record.save();
    }
}

export const rsCitAnnex3Field = {
    component: RsCitAnnex3Field,
    displayName: _t("Profit Tax Annex 3"),
    supportedTypes: ["one2many"],
    useSubView: true,
};

registry.category("fields").add("rs_cit_annex3", rsCitAnnex3Field);
