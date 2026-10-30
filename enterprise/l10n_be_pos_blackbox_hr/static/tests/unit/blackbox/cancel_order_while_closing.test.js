import { test, expect, describe } from "@odoo/hoot";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import {
    setupPosBlackboxEnv,
    waitForUnawaitedCalls,
    patchReceiptPrinting,
} from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { getFilledOrder } from "@point_of_sale/../tests/unit/utils";

definePosModels();

describe("cancel draft order while closing", () => {
    test("the cancelled order is still signed with the closing cashier", async () => {
        const signed = {};
        const store = await setupPosBlackboxEnv(
            async (mockRequest) => {
                const body = await mockRequest.json();
                signed[body.operationName] = body.variables.data;
            },
            { setupCashier: false }
        );
        patchReceiptPrinting(store);

        const employee = store.models["hr.employee"].get(2);
        store.setCashier(employee);
        const order = await getFilledOrder(store);
        order.updateLastTransactionLines();

        // Core keeps the cashier logged in until the session is really closed, so
        // this no longer happens mid-closing. Guard the fallback anyway: with
        // pos_hr there is no `res.users` behind `loggedCashier`, so anything that
        // clears the cashier leaves FDM events with no employee at all.
        store.accessRight.resetCashier();
        expect(store.accessRight.loggedCashier).toBe(false);

        await store.deleteOrders([order]);
        await waitForUnawaitedCalls(() => expect(signed.M110_signSale).not.toBe(undefined));

        expect(signed.M110_signSale.employeeId).toBe(employee.l10n_be_insz_or_bis_number);
        expect(signed.M121_signOrder.employeeId).toBe(employee.l10n_be_insz_or_bis_number);
    });

    test("re-entering the closing flow does not lose the cashier", async () => {
        const store = await setupPosBlackboxEnv(() => void 0, { setupCashier: false });
        const employee = store.models["hr.employee"].get(2);
        store.setCashier(employee);

        // Repeated clears must not erode the fallback: cancelling the draft orders
        // re-enters `closeSession()`, and an earlier implementation recaptured the
        // INSZ there and overwrote it with the now-empty cashier.
        store.accessRight.resetCashier();
        expect(store.l10nBeSigningInsz).toBe(employee.l10n_be_insz_or_bis_number);
        store.accessRight.resetCashier();
        expect(store.l10nBeSigningInsz).toBe(employee.l10n_be_insz_or_bis_number);
    });
});
