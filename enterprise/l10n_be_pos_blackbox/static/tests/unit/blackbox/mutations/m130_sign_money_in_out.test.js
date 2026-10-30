import { test, expect, describe, getFixture } from "@odoo/hoot";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import {
    setupPosBlackboxEnv,
    expectGeneralProperties,
    expectFinancial,
} from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { mountWithCleanup, getMockEnv } from "@web/../tests/web_test_helpers";
import { CashMovePopup } from "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup";
import { getFilledOrder } from "@point_of_sale/../tests/unit/utils";

definePosModels();

// see 'enterprise/l10n_be_pos_blackbox/static/tests/unit/data/json/m130_sign_money_in_out.json' for an example request
describe("sign_money_in_out", () => {
    test("data generation", async () => {
        const store = await setupPosBlackboxEnv();
        const result = await store.blackbox.signMoneyInOut.sign(store.models, "1234567890", {
            amount: 100,
            name: "Cash In",
        });
        const cashIn = result.formatted;
        // Check general properties
        expectGeneralProperties(cashIn, { ticketMedium: "DIGITAL" });

        const financials = cashIn.financials;
        expect(financials[0].amount).toBe(100);
        expect(financials[0].name).toBe("Cash In");
        expect(financials[0].amountType).toBe("MONEY_IN_OUT");
        expect(financials[0].inputMethod).toBe("MANUAL");

        const result2 = await store.blackbox.signMoneyInOut.sign(store.models, "1234567890", {
            amount: -100,
            name: "Cash Out",
        });
        const cashOut = result2.formatted;
        const financialsOut = cashOut.financials;
        expectFinancial(financialsOut[0], "Cash Out", "MONEY_IN_OUT", -100, "CASH");

        const result3 = await store.blackbox.signMoneyInOut.sign(store.models, "1234567890", {
            amount: 12.5,
            name: "out",
        });
        expectFinancial(result3.formatted.financials[0], "out", "MONEY_IN_OUT", 12.5, "CASH");

        const result4 = await store.blackbox.signMoneyInOut.sign(store.models, "1234567890", {
            amount: 7.456,
            name: "in",
        });
        expectFinancial(result4.formatted.financials[0], "in", "MONEY_IN_OUT", 7.46, "CASH");
    });

    test("called at right time", async () => {
        let blackboxIsCalled = false;
        let sentFinancials = null;
        const expectRequest = async (mockRequest) => {
            const body = await mockRequest.json();
            if (body.operationName === "M130_signMoneyInOut") {
                blackboxIsCalled = true;
                sentFinancials = body.variables.data.financials;
            }
        };

        const store = await setupPosBlackboxEnv(expectRequest);
        const env = getMockEnv();
        // The cash move receipt is rendered in the container owned by Chrome,
        // which is not mounted when a popup is mounted on its own.
        const receiptContainer = document.createElement("div");
        receiptContainer.id = "receipt-iframe-container";
        getFixture().appendChild(receiptContainer);
        await getFilledOrder(store);
        const comp = await mountWithCleanup(CashMovePopup, {
            props: { close: () => {} },
            env: {
                ...env,
                dialogData: { close: () => {}, isActive: true, scrollToOrigin: () => {} },
            },
        });
        comp.state.amount = "12.50";
        comp.state.type = "out";
        await comp.confirm();
        expect(blackboxIsCalled).toBe(true);
        expectFinancial(sentFinancials[0], "out", "MONEY_IN_OUT", 12.5, "CASH");
    });
});
