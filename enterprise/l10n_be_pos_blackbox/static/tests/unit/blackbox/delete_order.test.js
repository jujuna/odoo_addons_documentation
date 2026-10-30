import { test, expect, describe } from "@odoo/hoot";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import {
    setupPosBlackboxEnv,
    patchReceiptPrinting,
} from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { onRpc } from "@web/../tests/web_test_helpers";

definePosModels();

const jsonResponse = (payload) =>
    new Response(JSON.stringify(payload), { headers: { "Content-Type": "application/json" } });

const fdmRef = {
    fdmId: "ODO01000002",
    fdmDateTime: "2026-09-01T09:58:05.000Z",
    eventLabel: "N",
    eventCounter: 1,
    totalCounter: 1,
};

// Answers every mutation with a signature and records the received mutations.
const fdmRecording = (mutations) => async (request) => {
    const { operationName } = await request.json();
    mutations.push(operationName);
    if (operationName === "M121_signOrder") {
        return jsonResponse({ data: { signOrder: { eventOperation: "ORDER", fdmRef } } });
    }
    if (operationName === "M110_signSale") {
        return jsonResponse({
            data: {
                signSale: {
                    eventOperation: "SALE",
                    posDateTime: "2026-09-01T11:58:04.996+02:00",
                    fdmRef,
                },
            },
        });
    }
    return jsonResponse({ data: {} });
};

describe("blackbox order deletion", () => {
    test("an order never sent to the FDM is deleted without signing an empty sale", async () => {
        onRpc("pos.session", "handle_blackbox_signature", () => true);
        const mutations = [];
        const store = await setupPosBlackboxEnv(fdmRecording(mutations));
        const printedTemplates = patchReceiptPrinting(store);
        const order = store.addNewOrder();
        mutations.length = 0;

        await store.deleteOrders([order]);

        expect(mutations).not.toInclude("M121_signOrder");
        expect(mutations).not.toInclude("M110_signSale");
        expect(order.uiState.isEmptyReceipt).not.toBe(true);
        expect(printedTemplates).toEqual([]);
    });

    test("an empty order whose removed line is corrected is closed by an empty sale", async () => {
        onRpc("pos.session", "handle_blackbox_signature", () => true);
        const mutations = [];
        const store = await setupPosBlackboxEnv(fdmRecording(mutations));
        const printedTemplates = patchReceiptPrinting(store);
        const order = store.addNewOrder();
        const product = store.models["product.template"].get(5);
        const line = await store.addLineToOrder({ product_tmpl_id: product, qty: 1 }, order);
        order.removeOrderline(line);
        mutations.length = 0;

        await store.deleteOrders([order]);

        expect(mutations).toEqual(["M121_signOrder", "M110_signSale"]);
        expect(order.l10n_be_has_order_event).toBe(true);
        expect(order.uiState.isEmptyReceipt).toBe(true);
        expect(printedTemplates).toEqual(["point_of_sale.pos_order_receipt"]);
    });
});
