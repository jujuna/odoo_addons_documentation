import { signal, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Field } from "@web/views/fields/field";
import { FileUploader } from "@web/views/fields/file_handler";
import { formatFloat } from "@web/views/fields/formatters";
import { X2ManyField, x2ManyField, x2ManyFieldProps } from "@web/views/fields/x2many/x2many_field";
import { useFocusCell } from "../focus_cell_hook";

const KORECT_GROUP = "ანგარიშ ფაქტურა რომლის კორექტირებაც წარმოებს";
const SPEC_GROUP = "ნსაფ მათ შორის კორექტირების";
const SPEC_KORECT_GROUP = "ნსაფ რომლის კორექტ-აც ხდება";
const STATION_GROUP = "სტაციონარის რეგისტრაციის N";
const B8_GROUP = "დღგ ბრუნვის კორექტირებაზე (დღგ-ის შესამცირებელი თანხა)";
const B9_GROUP = "დღგ უკუდაბეგვრით დასაბეგრი ოპერაციის კორექტირებაზე (დღგ-ის შესამცირებელი თანხა)";

/** Invoice grid columns of ბ I and ბ II; they differ only in partner and VAT headers and totals. */
function invoiceColumns({ tinLabel, amountLabel, totals }) {
    return [
        { field: "series", label: "სერია", width: 12 },
        { field: "number", label: "ნომერი", width: 15 },
        { field: "operation_month", label: "დასაბეგრი ოპერაციის განხორციელების თვე", width: 15, month: true },
        { field: "partner_tin", label: tinLabel, width: 15 },
        { field: "amount", label: amountLabel, width: 10, group: "დღგ-ს თანხა", total: totals[0] },
        {
            field: "reduce_amount",
            label: "კორექტირების შედეგად შესამცირებელი",
            width: 10,
            group: "დღგ-ს თანხა",
            total: totals[1],
        },
        { field: "korect_series", label: "სერია", width: 12, group: KORECT_GROUP },
        { field: "korect_number", label: "ნომერი", width: 11, group: KORECT_GROUP },
    ];
}

/** Petroleum grid columns of tabs 13 and 14; only the partner and VAT headers and totals differ. */
function specColumns({ tinLabel, amountLabel, totals }) {
    return [
        { field: "series", label: "სერია", width: 5, group: SPEC_GROUP },
        { field: "number", label: "N", width: 7, group: SPEC_GROUP },
        { field: "operation_date", label: "თარიღი", width: 8, group: SPEC_GROUP },
        { field: "korect_series", label: "სერია", width: 5, group: SPEC_KORECT_GROUP },
        { field: "korect_number", label: "N", width: 7, group: SPEC_KORECT_GROUP },
        { field: "korect_date", label: "თარიღი", width: 8, group: SPEC_KORECT_GROUP },
        { field: "station_from", label: "გაგზავნის", width: 7, group: STATION_GROUP },
        { field: "station_to", label: "დანიშნულების", width: 7, group: STATION_GROUP },
        { field: "partner_tin", label: tinLabel, width: 9 },
        { field: "product_code", label: "ნ/პროდუქტის კოდი", width: 7 },
        { field: "quantity_l", label: "რაოდ. ლ-ში", width: 7 },
        { field: "quantity_kg", label: "რაოდ. კგ-ში", width: 7 },
        { field: "amount", label: amountLabel, width: 8, group: "დღგ-ის თანხა", total: totals[0] },
        {
            field: "reduce_amount",
            label: "კორექტირების შედეგად შესამცირებელი",
            width: 8,
            group: "დღგ-ის თანხა",
            total: totals[1],
        },
    ];
}

function advanceColumns(total, delivery = "მიწოდების ფაქტურის") {
    return [
        { field: "delivery_series", label: `${delivery} სერია`, width: 20 },
        { field: "delivery_number", label: `${delivery} ნომერი`, width: 20 },
        { field: "advance_series", label: "ავანსის ფაქტურის სერია", width: 20 },
        { field: "advance_number", label: "ავანსის ფაქტურის ნომერი", width: 20 },
        { field: "amount", label: "თანხა", width: 20, total },
    ];
}

const STOCK_FIELDS = [
    "opening",
    "received",
    "spec_sold",
    "sold",
    "sold_amount",
    "discount_sold",
    "discount_amount",
    "own_use",
    "processed",
    "closing",
];
/** Tab 15 columns (3) to (12) of the portal, each in kg then in litres. */
const STOCK_COLUMNS = [
    { field: "product_code", label: "(1)", width: 6 },
    ...STOCK_FIELDS.flatMap((name, index) => [
        { field: `${name}_kg`, label: `კგ (${index + 3})`, width: 4 },
        { field: `${name}_l`, label: `ლ (${index + 3})`, width: 4 },
    ]),
];

/** Portal texts and widths of the annex grids: title, header (a `group` column shares a header cell), "?" help,
 * the declaration field holding each column total, and the field marking a row Odoo built. */
const GRID_LAYOUT = {
    b1: {
        title: 'დანართი "ბ" ნაწილი I დასაბეგრ ოპერაციებზე (მათ შორის, ჩათვლის უფლებით გათავისუფლებულ ოპერაციებზე) გამოწერილი საგადასახადო ანგარიშ-ფაქტურები (მათ შორის, კორექტირების)',
        info: "აისახება დასაბეგრ (მ.შ. კორექტირების) ოპერაციებზე (მ.შ. ჩათვლის უფლებით გათავისუფლებულ ოპერაციებზე), აგრეთვე დასაბეგრი „ავანსების“ მიხედვით გამოწერილი საფ-ების მონაცემები.",
        odooField: "move_id",
        columns: invoiceColumns({
            tinLabel: "მყიდველის/ მიმღების ს/ნ",
            amountLabel: "გადასახდელი (მათ შორის, კორექტირების შედეგად დამატებით გადასახდელი)",
            totals: ["b1_amount", "b1_reduce_amount"],
        }),
    },
    b1_advance: {
        info: "აისახება „ავანსის“ საფ-ების მონაცემები და დღგ-ის ის თანხა, რომლითაც შემცირდება საანგარიშო თვის დასაბეგრ ოპერაციებზე დარიცხული დღგ.",
        odooField: "settlement_id",
        columns: advanceColumns("b1_advance_amount"),
    },
    b2: {
        title: 'დანართი "ბ" ნაწილი II შეძენილ საქონელზე/მომსახურებაზე გამოწერილი საგადასახადო ანგარიშ-ფაქტურები (მათ შორის, კორექტირების)',
        info: "აისახება შეძენილ (მ.შ. კორექტირების) ოპერაციებზე (მ.შ. ჩათვლის უფლებით გათავისუფლებულ ოპერაციებზე), აგრეთვე გადახდილი „ავანსების“ მიხედვით გამოწერილი საფ-ების მონაცემები.",
        odooField: "move_id",
        columns: invoiceColumns({
            tinLabel: "მომწოდებლის ს/ნ",
            amountLabel: "ჩასათვლელი, მათ შორის, კორექტირების შედეგად დამატებით ჩასათვლელი",
            totals: ["b2_amount", "b2_reduce_amount"],
        }),
    },
    b2_advance: {
        info: "აისახება „ავანსის“ საფ-ების მონაცემები და დღგ-ის ის თანხა, რომლითაც შემცირდება შეძენილ საქონელზე/მომსახურებაზე გამოწერილი საფ-ების მიხედვით ჩასათვლელი დღგ.",
        odooField: "settlement_id",
        columns: advanceColumns("b2_advance_amount"),
    },
    spec13: {
        title: "გამოწერილი (მათ შორის, შიდა გადაზიდვაზე) ნავთობპროდუქტების საგადასახადო ანგარიშ-ფაქტურები (მათ შორის, კორექტირების)",
        odooField: "move_id",
        columns: specColumns({
            tinLabel: "მყიდველის ს/ნ",
            amountLabel: "გადასახდელი (მათ შორის, კორექტირების შედეგად დამატებით გადახდილი)",
            totals: ["b13_amount", "b13_reduce_amount"],
        }),
    },
    spec13_advance: {
        odooField: "settlement_id",
        columns: advanceColumns("b13_advance_amount", "მიწოდების სპეც ფაქტურის"),
    },
    spec14: {
        title: "შეძენილი ნავთობპროდუქტებზე გამოწერილი ნავთობპროდუქტების საგადასახადო ანგარიშ-ფაქტურები (მათ შორის, კორექტირების)",
        odooField: "move_id",
        columns: specColumns({
            tinLabel: "გამყიდველის ს/ნ",
            amountLabel: "ჩასათვლელი (მათ შორის, კორექტირების შედეგად დამატებით ჩასათვლელი)",
            totals: ["b14_amount", "b14_reduce_amount"],
        }),
    },
    spec14_advance: {
        odooField: "settlement_id",
        columns: advanceColumns("b14_advance_amount", "მიწოდების სპეც ფაქტურის"),
    },
    stock15: {
        title: "ფაქტიურად დარიცხული ნაშთები",
        odooField: "product_ids",
        columns: STOCK_COLUMNS,
        header: [
            [
                { label: "ოთხნიშნა კოდი", colspan: 1, rowspan: 4 },
                { label: "ნაშთი თვის დასაწყისში", colspan: 2, rowspan: 4 },
                { label: "მიღებული და წარმოებული", colspan: 2, rowspan: 4 },
                { label: "თვის განმავლობაში ფაქტიურად გახარჯული", colspan: 14, rowspan: 1 },
                { label: "12=3+4-5-6-8-10-11", colspan: 2, rowspan: 4 },
            ],
            [
                { label: "რეალიზებული ნსაფ-ით", colspan: 2, rowspan: 3 },
                { label: "რეალიზებული ნსაფის გარეშე", colspan: 8, rowspan: 1 },
                { label: "გახარჯული (პირადი მოხმარებისათვის)", colspan: 2, rowspan: 3 },
                { label: "გადამუშავებულის ოდენობა", colspan: 2, rowspan: 3 },
            ],
            [
                { label: "ფასდათმობის გარეშე რეალიზებული", colspan: 4, rowspan: 1 },
                { label: "ფასდათმობით რეალიზებული", colspan: 4, rowspan: 1 },
            ],
            [
                { label: "რაოდენობა", colspan: 2, rowspan: 1 },
                { label: "თანხა", colspan: 2, rowspan: 1 },
                { label: "რაოდენობა", colspan: 2, rowspan: 1 },
                { label: "თანხა", colspan: 2, rowspan: 1 },
            ],
            STOCK_COLUMNS.map(({ label }) => ({ label, colspan: 1, rowspan: 1 })),
        ],
    },
    b3: {
        title: 'დანართი "ბ" ნაწილი III საქონლის იმპორტისას წარდგენილი საბაჟო დეკლარაციები',
        info: "მიეთითება დღგ-ის ჩათვლაში გამოყენებული საბაჟო დეკლარაციის მონაცემები. კერძოდ, საბაჟო დეკლარაციის გრაფაში მითითებული შეფასების ნომერი (მხოლოდ ციფრები), თარიღი და დღგ-ის თანხა, ხოლო თუ საბაჟო დეკლარაციას არ გააჩნია გრაფა – საბაჟო დეკლარაციის ნომერი (მხოლოდ ციფრები), თარიღი და დღგ-ის თანხა.",
        upload: true,
        fileField: "attachment_id",
        columns: [
            { field: "assessment_number", label: "შეფასების ნომერი", width: 20 },
            { field: "customs_code", label: "საბაჟოს კოდი", width: 14 },
            { field: "assessment_date", label: "შეფასების თარიღი", width: 22 },
            { field: "amount", label: "დღგ-ის თანხა", width: 20, total: "b3_amount" },
            { field: "pdf_type", label: "ტიპი", width: 16 },
        ],
    },
    b4: {
        title: 'დანართი "ბ" ნაწილი IV',
        info: "მიეთითება საგადასახადო დავალიანების გადახდევინების უზრუნველყოფის ღონისძიების ფარგლებში ან სხვა ფულადი ვალდებულების გადახდევინების მიზნით საქონლის აუქციონის, პირდაპირი მიყიდვის ან სხვა წესით რეალიზაციის შემთხვევაში საქონლის შეძენის დამადასტურებელი შესაბამისი დოკუმენტის ნომერი, რეალიზაციის განმახორციელებელი უფლებამოსილი პირის ან/და საქონლის/სამეურვეო ქონების მესაკუთრის საიდენტიფიკაციო მონაცემები, ქონების შესყიდვის თარიღი და დღგ-ის თანხა.",
        columns: [
            {
                field: "ref_number",
                label: "შეძენის დამადასტურებელი შესაბამისი დოკუმენტის ნომერი",
                width: 15,
            },
            {
                field: "partner_tin",
                label: "რეალიზაციის განმახორციელებელი უფლებამოსილი პირის საიდენტიფიკაციო ნომერი",
                width: 12,
            },
            {
                field: "partner_name",
                label: "რეალიზაციის განმახორციელებელი უფლებამოსილი პირის დასახელება",
                width: 16,
            },
            {
                field: "owner_tin",
                label: "საქონლის/სამეურვეო ქონების მესაკუთრის საიდენტიფიკაციო ნომერი",
                width: 12,
            },
            { field: "owner_name", label: "საქონლის/სამეურვეო ქონების მესაკუთრის დასახელება", width: 16 },
            { field: "ref_date", label: "საქონლის/სამეურვეო ქონების შესყიდვის თარიღი", width: 11 },
            { field: "amount", label: "დღგ-ის თანხა", width: 10, total: "b4_amount" },
        ],
    },
    b5: {
        title: 'დანართი "ბ" ნაწილი V',
        info: "ივსება იმ შემთხვევაში, თუ გაცვლის (ბარტერის) თითოეული ოპერაცია იბეგრება დღგით (არ გამოწერილა საფ-ი) და საქონლის მიწოდება/მომსახურების გაწევა განხორციელებულია 2021 წლის 1 იანვრამდე, ხოლო სანაცვლო საქონლის მიწოდება/მომსახურების გაწევა ხორციელდება 2021 წლის 1 იანვარს ან შემდგომ პერიოდებში. მიეთითება: იმ დეკლარაციის სარეგისტრაციო ნომერი, რომლითაც დადეკლარირდა ბარტერის ფარგლებში მიწოდებულ საქონელზე/მომსახურებაზე გადასახდელი დღგ. შენიშვნა: ამ დანართით ასახული დღგ-ის თანხა არ უნდა იყოს ამავე დანართში მითითებული დღგ-ის დეკლარაციით ბარტერულ ოპერაციაზე დარიცხულ დღგ-ის თანხაზე მეტი.",
        columns: [
            { field: "ref_number", label: "დეკლარაციის ნომერი", width: 20 },
            { field: "partner_tin", label: "მომწოდებლის ს/ნ", width: 16 },
            { field: "partner_name", label: "მომწოდებლის დასახელება", width: 26 },
            { field: "period", label: "საანგარიშო პერიოდი (თვე და წელი)", width: 16, month: true },
            { field: "amount", label: "დღგ-ის თანხა", width: 14, total: "b5_amount" },
        ],
    },
    b8: {
        title: 'დანართი "ბ" ნაწილი VIII',
        info: "დანართი ივსება იმ შემთხვევაში, თუ გასულ საანგარიშო პერიოდებში დღგ-ით დაბეგრილია ოპერაცია, არ არის გამოწერილი საფ-ი და ხდება ასეთი ოპერაციის კორექტირება (შემცირება) სსკ-ის 179-ე მუხლის შესაბამისად. მიეთითება დღგ-ის იმ დეკლარაციის მონაცემები, რომლითაც განხორციელდა დასაბეგრ ოპერაციაზე (კორექტირებამდე) დღგ-ის დეკლარირება, აგრეთვე დღგ-ის თანხა, რომლითაც მცირდება ბიუჯეტში შესატანი დღგ. შენიშვნა: დღგ-ის თანხა არ უნდა იყოს მითითებული დღგ-ის დეკლარაციით დარიცხულ დღგ-სა და ამავე საანგარიშო პერიოდებზე გამოწერილი საფ-ების მიხედვით დღგ-ის სხვაობაზე მეტი.",
        columns: [
            { field: "ref_number", label: "დეკლარაციის ნომერი", width: 34, group: B8_GROUP },
            {
                field: "period",
                label: "საანგარიშო პერიოდი",
                width: 33,
                month: true,
                group: B8_GROUP,
            },
            {
                field: "amount",
                label: "დღგ-ის თანხა",
                width: 33,
                total: "b8_amount",
                group: B8_GROUP,
            },
        ],
    },
    b9: {
        title: 'დანართი "ბ" ნაწილი IX',
        info: "დანართი ივსება იმ შემთხვევაში, როდესაც სსკ-ის 179-ე მუხლის შესაბამისად განხორციელდა უკუდაბეგვრის წესით დაბეგრილი დღგ-ით დასაბეგრი ოპერაციის კორექტირება (შემცირება). მიეთითება დღგ-ის დეკლარაციის/გაანგარიშების სარეგისტრაციო ნომერი, რომელშიც ასახულია კორექტირებამდე უკუდაბეგვრით დასაბეგრი ოპერაცია. ასევე, მიეთითება დეკლარაციის/გაანგარიშების მონაცემები და დღგ-ის თანხა, რომლითაც ხდება დღგ-ით უკუდაბეგვრით დასაბეგრი ოპერაციის კორექტირება (შემცირება). შენიშვნა: დღგ-ის თანხა არ უნდა იყოს მითითებული დეკლარაციით/გაანგარიშებით დარიცხულ დღგ-ზე მეტი.",
        columns: [
            { field: "ref_number", label: "დეკლარაციის ნომერი", width: 34, group: B9_GROUP },
            {
                field: "period",
                label: "საანგარიშო პერიოდი",
                width: 33,
                month: true,
                group: B9_GROUP,
            },
            {
                field: "amount",
                label: "დღგ-ის თანხა",
                width: 33,
                total: "b9_amount",
                group: B9_GROUP,
            },
        ],
    },
    rc_services: {
        title: "I ნაწილი",
        odooField: "move_id",
        columns: [
            { field: "partner_name", label: "უცხოელი დასაბეგრი პირის დასახელება", width: 22 },
            {
                field: "description",
                label: "უცხოელი დასაბეგრი პირის მიერ გაწეული/გასაწევი მომსახურების სახე",
                width: 26,
            },
            {
                field: "date",
                label: "მომსახურების გაწევის მომენტი (საანგარიშო პერიოდი)",
                width: 16,
            },
            {
                field: "amount",
                label: "მომსახურებისათვის გასაცემი საკომპენსაციო თანხა",
                width: 20,
                total: "services_amount_total",
            },
            { field: "vat", label: "დღგ", width: 16, total: "services_vat_total" },
        ],
    },
    rc_goods: {
        title: "III ნაწილი",
        columns: [
            { field: "description", label: "მოთხოვნის უზრუნველყოფის საგანი (საქონელი)", width: 34 },
            {
                field: "date",
                label: "მოთხოვნის უზრუნველყოფის საგნის (საქონლის) საკუთრებაში გადაცემის მომენტი",
                width: 22,
            },
            {
                field: "amount",
                label: "მოთხოვნის უზრუნველყოფის საგნის (საქონლის) ფასი დღგ-ის გარეშე",
                width: 28,
                total: "goods_amount_total",
            },
            { field: "vat", label: "დღგ", width: 16, total: "goods_vat_total" },
        ],
    },
};

export class GecVatRows extends X2ManyField {
    static template = "gec_vat_declaration.GecVatRows";
    static components = { ...X2ManyField.components, Field, FileUploader };
    props = useProps({ ...x2ManyFieldProps, grid: t.string() });
    root = signal.ref();
    attachmentIds = [];
    cellToFocus = null;

    setup() {
        super.setup();
        this.orm = useService("orm");
        const nodes = Object.values(this.archInfo.fieldNodes || {});
        this.fieldInfos = Object.fromEntries(nodes.map((node) => [node.name, node]));
        useFocusCell(this, ({ field, recordId }) => {
            const id = recordId ?? this.list.editedRecord?.id;
            const selector = `tr[data-record-id="${id}"] td[data-field="${field}"] input`;
            return id && this.root()?.querySelector(selector);
        });
    }

    get layout() {
        return GRID_LAYOUT[this.props.grid];
    }

    get grouped() {
        return this.layout.columns.some((column) => column.group);
    }

    /** First header row: a plain column spans both rows; consecutive columns of one group share a cell. */
    get headTop() {
        const cells = [];
        for (const column of this.layout.columns) {
            const last = cells.at(-1);
            if (column.group && last?.group === column.group) {
                last.colspan += 1;
            } else if (column.group) {
                cells.push({ label: column.group, group: column.group, colspan: 1, rowspan: 1 });
            } else {
                cells.push({ label: column.label, colspan: 1, rowspan: this.grouped ? 2 : 1 });
            }
        }
        return cells;
    }

    get headSub() {
        return this.layout.columns.filter((column) => column.group);
    }

    get hasTotals() {
        return this.layout.columns.some((column) => column.total);
    }

    get countText() {
        return _t("%s rows", this.list.count);
    }

    isOdooRow(record) {
        const value = record.data[this.layout.odooField];
        return Boolean(value?.currentIds ? value.currentIds.length : value);
    }

    isEditable(record) {
        return !this.props.readonly && !this.isOdooRow(record);
    }

    /** Month as the portal prints it, e.g. 10.2026. */
    monthText(record, column) {
        const value = record.data[column.field];
        return value ? value.toFormat("MM.yyyy") : "";
    }

    totalText(column) {
        return formatFloat(this.props.record.data[column.total] || 0);
    }

    /** Open the row for typing and put the cursor in the clicked cell with the same click. */
    async onCellClick(record, column) {
        if (this.isEditable(record) && !record.isInEdition) {
            this.cellToFocus = { recordId: record.id, field: column.field };
            await this.list.enterEditMode(record);
        }
    }

    async onAddRow() {
        this.cellToFocus = { recordId: null, field: this.layout.columns[0].field };
        await this.onAdd({ editable: "bottom" });
    }

    async onUploadClick() {
        return this.props.record.save();
    }

    async onFileUploaded(file) {
        const [id] = await this.orm.create("ir.attachment", [
            { name: file.name, mimetype: file.type, raw: file.data },
        ]);
        this.attachmentIds.push(id);
    }

    async onUploadComplete() {
        const ids = this.attachmentIds;
        this.attachmentIds = [];
        const { record } = this.props;
        await this.orm.call(record.resModel, "action_gec_customs_upload", [[record.resId], ids]);
        await record.load();
    }

    onDeleteRow(record) {
        return this.list.delete(record);
    }

    openOdooRecord(record) {
        const { odooField } = this.layout;
        const value = record.data[odooField];
        const { relation, type } = this.list.fields[odooField];
        const action = { type: "ir.actions.act_window", res_model: relation };
        if (type !== "many2many") {
            Object.assign(action, { res_id: value.id, views: [[false, "form"]] });
        } else if (value.currentIds.length === 1) {
            Object.assign(action, { res_id: value.currentIds[0], views: [[false, "form"]] });
        } else {
            const views = [[false, "list"], [false, "form"]];
            Object.assign(action, { domain: [["id", "in", value.currentIds]], views });
        }
        return this.action.doAction(action);
    }
}

export const gecVatRows = {
    ...x2ManyField,
    component: GecVatRows,
    extractProps: (staticInfo, dynamicInfo) => ({
        ...x2ManyField.extractProps(staticInfo, dynamicInfo),
        grid: staticInfo.options.grid,
    }),
};

registry.category("fields").add("gec_vat_rows", gecVatRows);
