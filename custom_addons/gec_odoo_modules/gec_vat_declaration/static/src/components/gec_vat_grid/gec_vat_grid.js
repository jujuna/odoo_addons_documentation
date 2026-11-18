import { signal, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { floatIsZero } from "@web/core/utils/numbers";
import { Field } from "@web/views/fields/field";
import { formatFloat } from "@web/views/fields/formatters";
import { X2ManyField, x2ManyField, x2ManyFieldProps } from "@web/views/fields/x2many/x2many_field";
import { useFocusCell } from "../focus_cell_hook";

const CONTENT_HEADER = "ოპერაციის შინაარსი";

/** Portal texts of the five pages: green title, value columns, optional extra header rows. */
const TAB_LAYOUT = {
    1: {
        title: 'დანართი "ა" ნაწილი I დღგ-ით დასაბეგრი ოპერაციები',
        columns: ["დასაბეგრი ბრუნვა", "18%"],
    },
    2: {
        title: 'დანართი "ა" ნაწილი II უკუდაბეგვრის წესით დარიცხული დღგ',
        columns: ["უკუდაბეგვრას დაქვემდებარებული ბრუნვა", "18%"],
    },
    3: {
        title: 'დანართი "ა" ნაწილი III დღგ-ის ჩასათვლელი თანხა',
        columns: [
            "ჯამი (სვეტი 4+ სვეტი 5)",
            "საქონელზე/მომსახურებაზე გადახდილი დღგ",
            "ძირითად საშუალებაზე გადახდილი დღგ-ის თანხა",
        ],
    },
    16: {
        title: "დღგ-ის საერთო თანხის გაანგარიშება",
        labelHeader: "",
        columns: ["დასაბეგრი ოპერაციები", "დღგ-ის გადასახდელი თანხა", "დღგ-ის შესამცირებელი თანხა"],
        numbering: ["1", "2", "3"],
    },
    17: {
        title: "სპეციალური სქემით დაბეგრილი ოპერაციების შესახებ ნაწილი III - დღგ-ს საერთო თანხის გაანგარიშება დანართი №III-19⁶",
        labelHeader: "დასაბეგრი ოპერაციები",
        columns: [
            "საქონლის შესყიდვის ფასი",
            "საქონლის მიწოდების ფასი",
            "დღგ-ს თანხა ((სვ.4 - სვ.3) : 1,18 x 0,18)",
        ],
        groupHeader: { label: "მოგების მარჟა(სვ.4-სვ.3)", span: 2 },
    },
};

export class GecVatGrid extends X2ManyField {
    static template = "gec_vat_declaration.GecVatGrid";
    static components = { ...X2ManyField.components, Field };
    props = useProps({ ...x2ManyFieldProps, tab: t.string() });
    root = signal.ref();
    calculatedTitle = _t("Calculated by the portal");
    cellToFocus = null;

    setup() {
        super.setup();
        this.orm = useService("orm");
        useFocusCell(this, ({ cellId }) =>
            this.root()?.querySelector(`td[data-cell-id="${cellId}"] input`)
        );
    }

    get layout() {
        return TAB_LAYOUT[this.props.tab];
    }

    get contentHeader() {
        return this.layout.labelHeader ?? CONTENT_HEADER;
    }

    get slots() {
        return this.layout.columns.map((column, index) => index + 1);
    }

    /** One entry per portal row, in record order, with its cells by value column (slot). */
    get rows() {
        const rows = [];
        const byLine = new Map();
        for (const record of this.list.records || []) {
            const { line, line_label, name, note, slot } = record.data;
            let row = byLine.get(line);
            if (!row) {
                row = { key: line, label: line_label, name, note, cells: {} };
                byLine.set(line, row);
                rows.push(row);
            }
            row.cells[slot] = record;
        }
        return rows;
    }

    isEditable(cell) {
        return !this.props.readonly && !cell.data.locked;
    }

    /** Open the cell for typing and put the cursor in it with the same click. */
    async onCellClick(cell) {
        if (this.isEditable(cell) && !cell.isInEdition) {
            this.cellToFocus = { cellId: cell.id };
            await this.list.enterEditMode(cell);
        }
    }

    onCellKeydown(ev, cell) {
        if (ev.key === "Enter" && ev.target === ev.currentTarget) {
            this.onCellClick(cell);
        }
    }

    async openAudit(cell) {
        if (!(await this.props.record.save())) {
            return;
        }
        const action = await this.orm.call("gec.vat.declaration.line", "action_gec_audit", [
            [cell.resId],
        ]);
        return this.action.doAction(action);
    }

    wandTitle(cell) {
        return _t(
            "Odoo proposes %s; the cell follows Odoo until you type your own value",
            formatFloat(cell.data.proposed_value)
        );
    }

    /** What Odoo says for the cell: its proposal on a proposed cell, else its own report figure. */
    odooFigure(cell) {
        return cell.data.proposed ? cell.data.proposed_value : cell.data.odoo_value;
    }

    /** Shown only when Odoo has a figure for the cell and the cell differs from it. */
    showOdooValue(cell) {
        const figure = this.odooFigure(cell);
        const hasFigure = cell.data.proposed || !floatIsZero(figure, 2);
        return hasFigure && !floatIsZero(figure - cell.data.value, 2);
    }

    odooValueText(cell) {
        return _t("Odoo %s", formatFloat(this.odooFigure(cell)));
    }
}

export const gecVatGrid = {
    ...x2ManyField,
    component: GecVatGrid,
    extractProps: (staticInfo, dynamicInfo) => ({
        ...x2ManyField.extractProps(staticInfo, dynamicInfo),
        tab: staticInfo.options.tab,
    }),
};

registry.category("fields").add("gec_vat_grid", gecVatGrid);
