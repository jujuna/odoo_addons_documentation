import { test, expect, describe } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    mountWithCleanup,
    patchTranslations,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { getFilledOrder } from "@point_of_sale/../tests/unit/utils";
import { setupPosBlackboxEnv } from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { L10nBeBlackboxError } from "@l10n_be_pos_blackbox/common/blackbox/utils/blackbox_error";
import { L10nBeBlackboxErrorPopup } from "@l10n_be_pos_blackbox/common/blackbox/utils/error_popup/error_popup";

definePosModels();

const makeErrors = (...codes) =>
    new L10nBeBlackboxError(
        "The FDM returned an error",
        codes.map((code) => ({
            message: `raw message for ${code}`,
            path: ["signSale", "transaction"],
            extensions: { category: "FDM", code: code },
        }))
    ).errors;

const mountErrorPopup = async (props = {}) =>
    await mountWithCleanup(L10nBeBlackboxErrorPopup, {
        props: {
            errors: [],
            data: {},
            mutationName: "signSale",
            close: () => expect.step("close"),
            ...props,
        },
    });

describe("l10n_be_blackbox_error_popup.js", () => {
    test("displays every error returned by the FDM", async () => {
        patchTranslations();
        const store = await setupPosBlackboxEnv();
        const order = await getFilledOrder(store);
        await mountErrorPopup({
            errors: makeErrors("BUFFER_FULL", "FDM_LOCKED"),
            data: { order: order },
        });

        expect(".modal .total-orders").toHaveText("Errors: 2");
        expect(".o-blackbox-error > div").toHaveCount(2);
        expect(queryAllTexts(".o-blackbox-error > div:first-child h3")).toEqual([
            "signSale",
            "FDM",
            "The FDM buffer is full. No further transactions can be processed.",
            "BUFFER_FULL",
            "signSale/transaction",
        ]);
        expect(queryAllTexts(".o-blackbox-error > div:last-child h3")).toEqual([
            "signSale",
            "FDM",
            "The FDM is locked and cannot process requests.",
            "FDM_LOCKED",
            "signSale/transaction",
        ]);
    });

    test("retry re-syncs the order and closes the popup", async () => {
        patchTranslations();
        const store = await setupPosBlackboxEnv();
        const order = await getFilledOrder(store);
        patchWithCleanup(store, {
            async syncAllOrders({ orders }) {
                expect.step(`syncAllOrders:${orders.map((o) => o.uuid).join(",")}`);
            },
        });
        await mountErrorPopup({
            errors: makeErrors("BUFFER_FULL"),
            data: { order: order },
        });

        await contains(".modal .modal-footer .btn-primary").click();
        expect.verifySteps(["close", `syncAllOrders:${order.uuid}`]);
    });

    test("no retry button when the error is not related to an order", async () => {
        patchTranslations();
        await setupPosBlackboxEnv();
        await mountErrorPopup({ errors: makeErrors("FDM_NOT_OPERATIONAL") });

        expect(".o-blackbox-error > div").toHaveCount(1);
        expect(".modal .modal-footer .btn-primary").toHaveCount(0);
        expect(".o-blackbox-error .btn-info").toHaveClass("disabled");
    });

    test("view order navigates to the unpaid order", async () => {
        patchTranslations();
        const store = await setupPosBlackboxEnv();
        const order = await getFilledOrder(store);
        store.setOrder(store.addNewOrder());
        await mountErrorPopup({
            errors: makeErrors("INTERNAL_ERROR"),
            data: { order: order },
        });

        expect(".o-blackbox-error .btn-info").not.toHaveClass("disabled");
        await contains(".o-blackbox-error .btn-info").click();
        expect.verifySteps(["close"]);
        expect(store.getOrder()).toBe(order);
        expect(store.router.currentScreen()).toBe("ProductScreen");
        expect(store.router.currentScreenParams().orderUuid).toBe(order.uuid);
    });

    test("view order is disabled for an already paid order", async () => {
        patchTranslations();
        const store = await setupPosBlackboxEnv();
        const order = await getFilledOrder(store, {}, true);
        await mountErrorPopup({
            errors: makeErrors("INTERNAL_ERROR"),
            data: { order: order },
        });

        expect(order.state).toBe("paid");
        expect(".o-blackbox-error .btn-info").toHaveClass("disabled");
    });
});
