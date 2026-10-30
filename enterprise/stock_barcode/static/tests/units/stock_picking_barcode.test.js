import { BarcodeVideoScanner } from "@web/core/barcode/barcode_video_scanner";
import { beforeEach, expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame, mockVibrate } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    getService,
    mountWebClient,
    onRpc,
    serverState,
} from "@web/../tests/web_test_helpers";
import { mailModels } from "@mail/../tests/mail_test_helpers";
import { patch } from "@web/core/utils/patch";

import { WebClientEnterprise } from "@web_enterprise/webclient/webclient";

defineModels(mailModels);

beforeEach(() => {
    this.clientData = {
        action: {
            tag: "stock_barcode_client_action",
            type: "ir.actions.client",
            res_model: "stock.picking",
            context: {},
        },
        currentState: {
            actions: {},
            data: {
                records: {
                    "barcode.nomenclature": [
                        {
                            id: 1,
                            rule_ids: [],
                        },
                    ],
                    "stock.location": [],
                    "stock.move.line": [],
                    "stock.picking": [],
                },
                nomenclature_id: 1,
            },
            groups: {},
        },
    };
    onRpc("/stock_barcode/get_barcode_data", () => Promise.resolve(this.clientData.currentState));
});

const mountBarcodeClient = async () => {
    await mountWebClient({ WebClient: WebClientEnterprise });
    await getService("action").doAction(this.clientData.action);
};

async function scan(barcode) {
    getService("barcode").bus.trigger("barcode_scanned", { barcode });
    await animationFrame();
}

test("exclamation-triangle when picking is done", async () => {
    const pickingRecord = {
        id: 2,
        state: "done",
        move_line_ids: [],
    };
    this.clientData.action.context.active_id = pickingRecord.id;
    this.clientData.currentState.data.records["stock.picking"].push(pickingRecord);

    await mountBarcodeClient();
    expect(".oi-5x[data-icon='warning']:not(.d-none)").toHaveCount(1, {
        message: "Should have warning icon",
    });
});

test.tags("mobile");
test("scan barcode button in mobile device and check video scanner delay", async () => {
    patch(BarcodeVideoScanner.prototype, {
        setup() {
            expect(this.props.delayBetweenScan).toEqual(2000);
            super.setup();
        },
    });
    const pickingRecord = {
        id: 2,
        state: "done",
        move_line_ids: [],
    };
    this.clientData.action.context.active_id = pickingRecord.id;
    this.clientData.currentState.data.records["stock.picking"].push(pickingRecord);
    this.clientData.currentState.groups.group_stock_multi_locations = false;

    await mountBarcodeClient();
    expect(".o_stock_mobile_barcode").toHaveCount(1);
    await contains(".o_stock_mobile_barcode").click();
});

test("validate partial reception with mandatory destination scan option", async () => {
    mockVibrate(() => true);
    this.clientData.action.context.active_id = 1;
    Object.assign(this.clientData.currentState.data.records, {
        "product.product": [
            { id: 1, barcode: "P1", display_name: "P1", tracking: "none", uom_id: 1 },
        ],
        "stock.location": [
            { id: 1, barcode: "WH-STOCK", display_name: "WH/Stock", parent_path: "1/" },
            { id: 2, barcode: "VENDOR", display_name: "VendorLoc", parent_path: "" },
        ],
        "stock.move.line": [
            {
                id: 1,
                product_id: 1,
                uom_id: 1,
                location_id: 2,
                location_dest_id: 1,
                quantity: 2,
                qty_done: 0,
            },
        ],
        "stock.picking": [
            {
                id: 1,
                name: "WH/IN/00001",
                state: "assigned",
                picking_type_code: "incoming",
                picking_type_id: 1,
                location_id: 1,
                location_dest_id: 1,
                move_ids: [],
                move_line_ids: [1],
                user_id: serverState.userId,
            },
        ],
        "stock.picking.type": [{ id: 1 }],
        "uom.uom": [{ id: 1, name: "Units", factor: 1, rounding: 0.01 }],
    });
    this.clientData.currentState.data.config = {
        barcode_separator_regex: ".^",
        create_backorder: "ask",
        lines_need_destination_location: true,
        play_sound: false,
        restrict_scan_dest_location: "mandatory",
        show_backorder_dialog: true,
    };
    Object.assign(this.clientData.currentState.groups, {
        group_stock_multi_locations: true,
        group_uom: false,
    });

    await mountBarcodeClient();
    await scan("P1");
    await scan("WH-STOCK");
    await click(".o_validate_page");
    await animationFrame();
    expect(".o_barcode_backorder_dialog").toHaveCount(1, {
        message: "Partial reception so validation should open backorder window",
    });
});
