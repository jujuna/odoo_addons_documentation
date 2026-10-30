import { test, expect, describe } from "@odoo/hoot";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { getFilledOrder } from "@point_of_sale/../tests/unit/utils";
import { setupPosBlackboxEnv } from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { onRpc, patchTranslations } from "@web/../tests/web_test_helpers";

definePosModels();

const jsonResponse = (payload) =>
    new Response(JSON.stringify(payload), { headers: { "Content-Type": "application/json" } });

// Answers every request but `refusedMutation`, which the FDM rejects.
const fdmRefusing = (refusedMutation) => async (request) => {
    const { operationName } = await request.json();
    if (operationName === refusedMutation) {
        return jsonResponse({
            errors: [
                {
                    message: "The FDM is locked",
                    path: [refusedMutation],
                    extensions: { code: "FDM_LOCKED", category: "FDM" },
                },
            ],
        });
    }
    return jsonResponse({ data: {} });
};

// Answers `signSale` with a complete signature, as a working FDM would.
const fdmSigning = () => async (request) => {
    const { operationName } = await request.json();
    if (operationName !== "M110_signSale") {
        return jsonResponse({ data: {} });
    }
    return jsonResponse({
        data: {
            signSale: {
                eventOperation: "SALE",
                posId: "CPOS0031234567",
                terminalId: "1",
                deviceId: "deviceId",
                posDateTime: "2026-09-01T11:58:04.996+02:00",
                fdmSwVersion: "1.0",
                shortSignature: "ABCDEFGH",
                verificationUrl: "https://www.fdm.be/verify",
                footer: "footer",
                vatCalc: [],
                fdmRef: {
                    fdmId: "ODO01000002",
                    fdmDateTime: "2026-09-01T09:58:05.000Z",
                    eventLabel: "N",
                    eventCounter: 1,
                    totalCounter: 1,
                },
            },
        },
    });
};

// An order ready to be validated, with the POS sitting on the payment screen.
const getOrderToValidate = async (store) => {
    const order = await getFilledOrder(store);
    store.setOrder(order);
    order.addPaymentline(store.models["pos.payment.method"].find((pm) => pm.type === "cash"));
    store.navigate("PaymentScreen", { orderUuid: order.uuid });
    return order;
};

describe("blackbox payment validation", () => {
    test("an order refused by the FDM stays on the payment screen", async () => {
        patchTranslations();
        const store = await setupPosBlackboxEnv(fdmRefusing("M110_signSale"));
        const order = await getOrderToValidate(store);

        await store.validateOrder();

        expect(store.router.currentScreen()).toBe("PaymentScreen");
        expect(order.state).toBe("draft");
        expect(order.l10n_be_short_signature).toBeEmpty();
    });

    test("an order signed by the FDM still goes to the feedback screen", async () => {
        patchTranslations();
        onRpc("pos.session", "handle_blackbox_signature", () => true);
        const store = await setupPosBlackboxEnv(fdmSigning());
        const order = await getOrderToValidate(store);

        await store.validateOrder();

        expect(store.router.currentScreen()).toBe("FeedbackScreen");
        expect(order.state).toBe("paid");
        expect(order.l10n_be_short_signature).toBe("ABCDEFGH");
    });
});
