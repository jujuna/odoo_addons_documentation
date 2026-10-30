import { test, expect, describe } from "@odoo/hoot";
import {
    expectTransactionLine,
    setupPosBlackboxEnv,
    expectGeneralProperties,
    payOrder,
    expectFinancial,
} from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { getFilledOrder } from "@point_of_sale/../tests/unit/utils";
import {
    GIFT_CARD_PROGRAM_ID,
    redeemGiftCard,
    spendEWallet,
} from "@l10n_be_pos_blackbox_loyalty/../tests/unit/utils";

definePosModels();

const { DateTime } = luxon;

/**
 * Sell a gift card the way the POS does: add its trigger product for the chosen program,
 * then record the printed code and expiration date on the line (what `manageGiftCard` does).
 * @returns {Promise<object>} the created order line
 */
const sellGiftCard = async (store, program, { priceUnit = 100 } = {}) => {
    const line = await store.addLineToCurrentOrder(
        {
            product_tmpl_id: store.models["product.template"].get(100),
            product_id: store.models["product.product"].get(100),
            qty: 1,
            price_unit: priceUnit,
        },
        { paymentProgram: program }
    );
    line.gift_card_vals = {
        ...line.gift_card_vals,
        code: "GIFT_CODE",
        expiration_date: DateTime.now().plus({ days: 1 }).toISODate(),
    };
    return line;
};

// see enterprise/l10n_be_pos_blackbox_loyalty/static/tests/unit/data/json/uc260_mpv_signSale.json
describe("sign_sale with a gift card", () => {
    test("check signSale request when selling a gift card", async () => {
        const store = await setupPosBlackboxEnv();
        const models = store.models;
        const order = store.addNewOrder();
        const giftProgram = models["loyalty.program"].get(GIFT_CARD_PROGRAM_ID);
        const giftCardProduct = models["product.product"].get(100);

        const line = await sellGiftCard(store, giftProgram);
        // The line funds the gift card program, which is what creates the card server-side.
        expect(line.payment_program_id).toBe(giftProgram);

        payOrder(store, order);
        const response = await store.blackbox.signSale.sign(order, "1234567890");
        await store.syncAllOrders();
        const input = response.formatted;
        expectGeneralProperties(input, { order: order, ticketMedium: "DIGITAL" });

        const transactions = input.transaction.transactionLines;
        const financials = input.financials;

        // Selling a gift card is a plain untaxed ("X") transaction line.
        expect(transactions).toHaveLength(1);
        expectTransactionLine(
            transactions[0],
            giftCardProduct,
            1,
            "PIECE",
            100,
            "X",
            "SINGLE_PRODUCT"
        );

        expect(financials).toHaveLength(1);
        expectFinancial(financials[0], "Cash", "PAYMENT", 100, "CASH");
    });

    test("check signSale request when selling a gift card with price change", async () => {
        const store = await setupPosBlackboxEnv();
        const models = store.models;
        const order = store.addNewOrder();
        const giftProgram = models["loyalty.program"].get(GIFT_CARD_PROGRAM_ID);
        const giftCardProduct = models["product.product"].get(100);

        const line = await sellGiftCard(store, giftProgram);
        line.price_type = "manual";
        line.setUnitPrice(120); // set a price change

        payOrder(store, order);
        const response = await store.blackbox.signSale.sign(order, "1234567890");
        await store.syncAllOrders();
        const input = response.formatted;
        expectGeneralProperties(input, {
            order: order,
            ticketMedium: "DIGITAL",
            mustHavePriceChanges: true,
        });

        const transactions = input.transaction.transactionLines;
        const financials = input.financials;

        expect(transactions).toHaveLength(1);
        expectTransactionLine(
            transactions[0],
            giftCardProduct,
            1,
            "PIECE",
            100,
            "X",
            "SINGLE_PRODUCT"
        );
        expect(transactions[0].mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(transactions[0].mainProduct.vats[0].priceChanges[0].scope).toBe("LINE");
        expect(transactions[0].mainProduct.vats[0].priceChanges[0].name).toBe("UNIT_PRICE_CHANGE");

        expect(financials).toHaveLength(1);
        expectFinancial(financials[0], "Cash", "PAYMENT", 120, "CASH");
    });

    test("check signSale request using a gift card", async () => {
        const store = await setupPosBlackboxEnv();
        const models = store.models;
        const order = await getFilledOrder(store);
        const chardonnay = models["product.product"].get(6);
        const bourgogne = models["product.product"].get(5);

        const rewardLine = redeemGiftCard(order);
        expect(rewardLine.priceIncl).toBe(-50);
        expect(order.priceIncl).toBe(135);

        order.state = "paid";
        models["pos.payment"].create({
            amount: order.priceIncl - 50,
            pos_order_id: order,
            payment_method_id: models["pos.payment.method"].find((m) => m.name === "Cash"),
        });
        store.addPendingOrder([order.id]);

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        expectGeneralProperties(input, { order: order, ticketMedium: "DIGITAL" });

        const transactions = input.transaction.transactionLines;
        const financials = input.financials;

        // The redemption line is a payment, not goods: it doesn't reach the transaction, and
        // the transaction total stays the full price of the goods (185).
        expect(transactions).toHaveLength(2);
        expectTransactionLine(transactions[0], bourgogne, 3, "PIECE", 35, "A", "SINGLE_PRODUCT");
        expectTransactionLine(transactions[1], chardonnay, 2, "PIECE", 40, "A", "SINGLE_PRODUCT");
        expect(input.transaction.transactionTotal).toBe(185);

        expect(financials).toHaveLength(2);
        expectFinancial(financials[0], "Cash", "PAYMENT", 85, "CASH");
        expectFinancial(financials[1], "Gift Card Redemption", "PAYMENT", 50, "VOUCHER_STORE");
    });

    test("check signSale request using an eWallet", async () => {
        const store = await setupPosBlackboxEnv();
        const models = store.models;
        const order = await getFilledOrder(store);

        const rewardLine = spendEWallet(order);
        expect(rewardLine.priceIncl).toBe(-30);
        expect(order.priceIncl).toBe(155);

        order.state = "paid";
        models["pos.payment"].create({
            amount: order.priceIncl - 30,
            pos_order_id: order,
            payment_method_id: models["pos.payment.method"].find((m) => m.name === "Cash"),
        });
        store.addPendingOrder([order.id]);

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        expectGeneralProperties(input, { order: order, ticketMedium: "DIGITAL" });

        expect(input.transaction.transactionLines).toHaveLength(2);
        expect(input.transaction.transactionTotal).toBe(185);

        const financials = input.financials;
        expect(financials).toHaveLength(2);
        expectFinancial(financials[0], "Cash", "PAYMENT", 125, "CASH");
        expectFinancial(financials[1], "EWallet Redemption", "PAYMENT", 30, "VOUCHER_OTHER");
    });
});
