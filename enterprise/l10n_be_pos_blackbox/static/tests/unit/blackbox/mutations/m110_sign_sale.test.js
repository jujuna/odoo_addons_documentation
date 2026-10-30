import { test, expect, describe } from "@odoo/hoot";
import {
    expectTransactionLine,
    generatePosOrder,
    setupPosBlackboxEnv,
    expectGeneralProperties,
    expectFinancial,
    payOrder,
} from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { getFilledOrder } from "@point_of_sale/../tests/unit/utils";

definePosModels();

// see 'enterprise/l10n_be_pos_blackbox/static/tests/unit/data/json/m110_sign_sale.json' for an example request
describe("sign_sale", () => {
    test("data generation", async () => {
        const store = await setupPosBlackboxEnv();
        const models = store.models;
        const martini = models["product.product"].find((p) => p.name === "Dry Martini");
        const burger = models["product.product"].find((p) => p.name === "Burger of the Chef");
        const order = generatePosOrder(
            models,
            [
                {
                    product_id: martini.id,
                    qty: 2,
                    price_unit: martini.lst_price,
                    tax_ids: martini.taxes_id.map((t) => t.id),
                },
                {
                    product_id: burger.id,
                    qty: 1,
                    price_unit: burger.lst_price,
                    tax_ids: burger.taxes_id.map((t) => t.id),
                },
            ],
            [
                {
                    amount: 52,
                    reference: "Test Payment",
                    uuid: "fake-uuid-1234",
                    payment_method_id: models["pos.payment.method"].find((m) => m.name === "Cash")
                        .id,
                },
            ]
        );
        const response = await store.blackbox.signSale.sign(order, "1234567890", "printer-url");
        const input = response.formatted;
        const transactions = input.transaction.transactionLines;
        const financials = input.financials;
        expectGeneralProperties(input, { order: order });

        expect(transactions).toHaveLength(2);
        expect(input.transaction.transactionTotal).toBe(52);

        // Check transaction details - Dry Martini
        expectTransactionLine(transactions[0], martini, 2, "PIECE", 12, "A", "SINGLE_PRODUCT");
        expect(transactions[0].mainProduct.vats[0].priceChanges).toBeEmpty();

        // Check transaction details - Burger of the Chef
        expectTransactionLine(transactions[1], burger, 1, "PIECE", 28, "B", "SINGLE_PRODUCT");
        expect(transactions[1].mainProduct.vats[0].priceChanges).toBeEmpty();

        // Check payment details
        expect(financials).toHaveLength(1);
        expectFinancial(financials[0], "Cash", "PAYMENT", 52, "CASH");
    });

    test("sign_sale called at right time", async () => {
        let blackboxIsCalled = false;
        const expectRequest = async (mockRequest) => {
            const body = await mockRequest.json();
            if (body.operationName === "M110_signSale") {
                blackboxIsCalled = true;
            }
        };

        const store = await setupPosBlackboxEnv(expectRequest);
        await getFilledOrder(store, {}, true);

        // Creating a paid order should trigger the blackbox signSale when syncing orders
        await store.syncAllOrders();
        expect(blackboxIsCalled).toBe(true);
    });

    test("order with tip amount", async () => {
        const store = await setupPosBlackboxEnv();
        const order = await getFilledOrder(store);
        expect(order.priceIncl).toBe(185);
        await store.setTip(5);
        expect(order.priceIncl).toBe(190);
        payOrder(store, order);
        expect(order.lines).toHaveLength(3); // 2 products + 1 tip line
        // Creating a paid order should trigger the blackbox signSale when syncing orders
        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const transactions = input.transaction.transactionLines;
        const financials = input.financials;

        // Check general properties
        expectGeneralProperties(input, { order: order, ticketMedium: "DIGITAL" });
        expect(transactions).toHaveLength(2); // tip line is not a transaction line
        expect(input.transaction.transactionTotal).toBe(185); // order lines without tip amount
        expect(financials).toHaveLength(2); // payment + tip
        expectFinancial(financials[0], "Cash", "PAYMENT", 185, "CASH");
        expectFinancial(financials[1], "Tip", "TIP", 5, "CASH");
    });

    test("order with tip amount and multiple payment lines", async () => {
        const store = await setupPosBlackboxEnv();
        const cardPm = store.models["pos.payment.method"].find((pm) => pm.type === "bank");
        const cashPm = store.models["pos.payment.method"].find((pm) => pm.type === "cash");
        const order = await getFilledOrder(store);
        await store.setTip(5);
        expect(order.priceIncl).toBe(190);

        order.addPaymentline(cardPm).data.setAmount(30);
        order.addPaymentline(cashPm);
        expect(order.payment_ids[1].amount).toBe(160);
        order.state = "paid";

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const financials = input.financials;

        expect(input.transaction.transactionTotal).toBe(185);
        expect(financials).toHaveLength(3); // 2 payments + tip
        // The tip is deducted from a single payment line, so that the PAYMENT lines sum up to the
        // transaction total
        expectFinancial(financials[0], "Bank", "PAYMENT", 30, "CARD_UNKNOWN");
        expectFinancial(financials[1], "Cash", "PAYMENT", 155, "CASH");
        expectFinancial(financials[2], "Tip", "TIP", 5, "CASH");
    });

    test("order with tip amount greater than each payment line", async () => {
        const store = await setupPosBlackboxEnv();
        const cardPm = store.models["pos.payment.method"].find((pm) => pm.type === "bank");
        const cashPm = store.models["pos.payment.method"].find((pm) => pm.type === "cash");
        const order = await getFilledOrder(store);
        order.removeOrderline(order.lines[1]);
        order.lines[0].qty = 1;
        order.lines[0].setUnitPrice(5);
        await store.setTip(20);
        expect(order.priceIncl).toBe(25);

        order.addPaymentline(cardPm).data.setAmount(12.5);
        order.addPaymentline(cashPm);
        expect(order.payment_ids[1].amount).toBe(12.5);
        order.state = "paid";

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const financials = input.financials;

        expect(input.transaction.transactionTotal).toBe(5);
        expect(financials).toHaveLength(4); // 2 payments + 2 tips
        // No payment line covers the whole tip: it spills over from the last one to the previous
        // one, none of them may become negative
        expectFinancial(financials[0], "Bank", "PAYMENT", 5, "CARD_UNKNOWN");
        expectFinancial(financials[1], "Cash", "PAYMENT", 0, "CASH");
        expectFinancial(financials[2], "Tip", "TIP", 12.5, "CASH");
        expectFinancial(financials[3], "Tip", "TIP", 7.5, "CARD_UNKNOWN");
    });

    test("order with tip amount covered by a previous payment line", async () => {
        const store = await setupPosBlackboxEnv();
        const cardPm = store.models["pos.payment.method"].find((pm) => pm.type === "bank");
        const cashPm = store.models["pos.payment.method"].find((pm) => pm.type === "cash");
        const order = await getFilledOrder(store);
        await store.setTip(5);
        expect(order.priceIncl).toBe(190);

        order.addPaymentline(cardPm).data.setAmount(187);
        order.addPaymentline(cashPm);
        expect(order.payment_ids[1].amount).toBe(3);
        order.state = "paid";

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const financials = input.financials;

        expect(input.transaction.transactionTotal).toBe(185);
        expect(financials).toHaveLength(3); // 2 payments + tip
        // The last payment line can't cover the whole tip, but the previous one can: a single TIP
        expectFinancial(financials[0], "Bank", "PAYMENT", 182, "CARD_UNKNOWN");
        expectFinancial(financials[1], "Cash", "PAYMENT", 3, "CASH");
        expectFinancial(financials[2], "Tip", "TIP", 5, "CARD_UNKNOWN");
    });

    test("order with belgian cash rounding (down)", async () => {
        // Setup POS with cash rounding
        const store = await setupPosBlackboxEnv();
        const config = store.config;
        config.cash_rounding = true;
        config.only_round_cash_method = true;
        config.rounding_method = store.models["account.cash.rounding"].create({
            name: "roudning",
            rounding: 0.05,
            rounding_method: "HALF-UP",
            strategy: "add_invoice_line",
        });
        const cashPm = store.models["pos.payment.method"].find((pm) => pm.type === "cash");

        const order = await getFilledOrder(store);
        order.lines[0].qty = 1;
        order.lines[0].setUnitPrice(10.12);
        expect(order.priceIncl).toBeCloseTo(90.12);

        order.addPaymentline(cashPm);
        expect(order.payment_ids[0].amount).toBe(90.1);
        expect(order.appliedRounding).toBe(-0.02);
        expect(order.canBeValidated()).toBe(true);
        order.state = "paid";

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const financials = input.financials;
        expect(input.posId).toBe("CPOS0031234567");
        expect(input.bookingPeriodId).toBe("0ca2ebb7-5f77-4d03-99a9-77b5673ab248");
        expect(input.posSwVersion).toBe("1.0");
        expect(input.ticketMedium).toBe("DIGITAL");
        expect(input.employeeId).toBe("1234567890");
        expect(input.terminalId).not.toBeEmpty();

        expect(financials).toHaveLength(2); // payment + rounding
        expectFinancial(financials[0], "Cash", "PAYMENT", 90.12, "CASH");
        expectFinancial(financials[1], "Rounding", "ROUNDING", -0.02, "CASH");
    });

    test("order with belgian cash rounding (up)", async () => {
        // Setup POS with cash rounding
        const store = await setupPosBlackboxEnv();
        const config = store.config;
        config.cash_rounding = true;
        config.only_round_cash_method = true;
        config.rounding_method = store.models["account.cash.rounding"].create({
            name: "rounding",
            rounding: 0.05,
            rounding_method: "HALF-UP",
            strategy: "add_invoice_line",
        });
        const cashPm = store.models["pos.payment.method"].find((pm) => pm.type === "cash");

        const order = await getFilledOrder(store);
        order.lines[0].qty = 1;
        order.lines[0].setUnitPrice(10.13);
        expect(order.priceIncl).toBeCloseTo(90.13);

        order.addPaymentline(cashPm);
        expect(order.payment_ids[0].amount).toBe(90.15);
        expect(order.appliedRounding).toBe(0.02);
        expect(order.canBeValidated()).toBe(true);
        order.state = "paid";

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const financials = input.financials;
        expect(input.posId).toBe("CPOS0031234567");
        expect(input.bookingPeriodId).toBe("0ca2ebb7-5f77-4d03-99a9-77b5673ab248");
        expect(input.posSwVersion).toBe("1.0");
        expect(input.ticketMedium).toBe("DIGITAL");
        expect(input.employeeId).toBe("1234567890");
        expect(input.terminalId).not.toBeEmpty();

        expect(financials).toHaveLength(2); // payment + rounding
        expectFinancial(financials[0], "Cash", "PAYMENT", 90.13, "CASH");
        expectFinancial(financials[1], "Rounding", "ROUNDING", 0.02, "CASH");
    });

    test("order with rounding issue", async () => {
        const store = await setupPosBlackboxEnv();
        const models = store.models;
        const tapas = models["product.product"].find((p) => p.name === "Tapas variation");

        const order = generatePosOrder(models, [
            {
                product_id: tapas.id,
                qty: 7,
                price_unit: tapas.lst_price,
                tax_ids: tapas.taxes_id.map((t) => t.id),
            },
        ]);
        payOrder(store, order);
        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const transactions = input.transaction.transactionLines;

        expect(input.transaction.transactionTotal).toBe(23.38);
        expect(transactions).toHaveLength(1);
        expect(transactions[0].lineTotal).toBe(23.38);
        // Check general properties
        expectGeneralProperties(input, { order: order, ticketMedium: "DIGITAL" });
    });
});
