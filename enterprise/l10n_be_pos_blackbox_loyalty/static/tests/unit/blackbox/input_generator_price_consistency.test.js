import { test, describe, expect } from "@odoo/hoot";
import { setupPosEnv, getFilledOrder } from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import {
    getComboOrder,
    expectGeneralProperties,
    expectTransactionLine,
} from "@l10n_be_pos_blackbox/../tests/unit/utils";
import {
    applyDiscountReward,
    buildInputGenerator,
    claimFreeProductReward,
    findPriceChange,
} from "@l10n_be_pos_blackbox_loyalty/../tests/unit/utils";

definePosModels();

describe("input generator price consistency", () => {
    const generateOrderInput = (order) => buildInputGenerator(order).generateSignSaleInput();

    test("[case 1] test order with 10% discount loyalty", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        const orderPrice = order.priceIncl;
        applyDiscountReward(order);
        expect(order.priceIncl).toBeCloseTo(orderPrice * 0.9);

        const input = generateOrderInput(order);
        expectGeneralProperties(input, {
            order: order,
            mustHavePriceChanges: true,
            ticketMedium: "DIGITAL",
        });

        const transLines = input.transaction.transactionLines;
        // The reward line itself is never sent: it only exists as a price change on the
        // lines it discounts.
        expect(transLines).toHaveLength(2);
        expect(transLines[0].mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].scope).toBe("EVENT");
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].name).toBe("LOYALTY_DISCOUNT");
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].amount).toBe(-10.5);
        expect(transLines[0].mainProduct.vats[0].price).toBe(105);

        expect(transLines[1].mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(transLines[1].mainProduct.vats[0].priceChanges[0].scope).toBe("EVENT");
        expect(transLines[1].mainProduct.vats[0].priceChanges[0].name).toBe("LOYALTY_DISCOUNT");
        expect(transLines[1].mainProduct.vats[0].priceChanges[0].amount).toBe(-8);
        expect(transLines[1].mainProduct.vats[0].price).toBe(80);
    });

    test("[case 2] test order with 10% discount loyalty with combo order", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const models = store.models;
        const order = await getComboOrder(store);
        const menu = models["product.product"].find((m) => m.name === "Business Menu All-In");

        const orderPrice = order.priceIncl;
        applyDiscountReward(order);
        expect(order.priceIncl).toBeCloseTo(orderPrice * 0.9);

        const input = generateOrderInput(order);
        expectGeneralProperties(input, {
            order: order,
            mustHavePriceChanges: true,
            ticketMedium: "DIGITAL",
        });

        const transLines = input.transaction.transactionLines;
        expect(transLines).toHaveLength(1);
        expectTransactionLine(transLines[0], menu, 1, "PIECE", 58, "A", "COMPOSITE_PRODUCT");
        // A combo carries no price of its own, so the discount lands on its children.
        expect(transLines[0].subProducts[0].vats[0].price).toBe(20);
        expect(transLines[0].subProducts[0].vats[0].priceChanges).toHaveLength(2);
        expect(transLines[0].subProducts[0].vats[0].priceChanges[0].name).toBe("MENU_DISCOUNT");
        expect(transLines[0].subProducts[0].vats[0].priceChanges[0].amount).toBe(-3.89);
        expect(transLines[0].subProducts[0].vats[0].priceChanges[1].name).toBe("LOYALTY_DISCOUNT");
        expect(transLines[0].subProducts[0].vats[0].priceChanges[1].amount).toBe(-1.61);
    });

    test("[case 3] test order with 10% discount loyalty with mixed order", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const models = store.models;
        const order = await getComboOrder(store, false, true);
        const menu = models["product.product"].find((m) => m.name === "Business Menu All-In");

        const orderPrice = order.priceIncl;
        applyDiscountReward(order);
        expect(order.priceIncl).toBeCloseTo(orderPrice * 0.9);

        const input = generateOrderInput(order);
        expectGeneralProperties(input, {
            order: order,
            mustHavePriceChanges: true,
            ticketMedium: "DIGITAL",
        });

        const transLines = input.transaction.transactionLines;
        expect(transLines).toHaveLength(2);
        expect(transLines[0].mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].scope).toBe("EVENT");
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].name).toBe("LOYALTY_DISCOUNT");
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].amount).toBe(-0.61);
        expect(transLines[0].mainProduct.vats[0].price).toBe(6.08);

        expectTransactionLine(transLines[1], menu, 1, "PIECE", 58, "A", "COMPOSITE_PRODUCT");
        expect(transLines[1].subProducts[0].vats[0].price).toBe(20);
        expect(transLines[1].subProducts[0].vats[0].priceChanges).toHaveLength(2);
        expect(transLines[1].subProducts[0].vats[0].priceChanges[0].name).toBe("MENU_DISCOUNT");
        expect(transLines[1].subProducts[0].vats[0].priceChanges[0].amount).toBe(-3.89);
        expect(transLines[1].subProducts[0].vats[0].priceChanges[1].name).toBe("LOYALTY_DISCOUNT");
        expect(transLines[1].subProducts[0].vats[0].priceChanges[1].amount).toBe(-1.61);
    });

    test("[case 4] test order with 10% discount loyalty on cheapest product", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);
        order.lines.forEach((line) => (line.qty = 1));

        expect(order.priceIncl).toBe(75);
        applyDiscountReward(order, "cheapest");
        // Only the cheapest line (35.0) is discounted: 75 - 3.5.
        expect(order.priceIncl).toBeCloseTo(71.5);

        const input = generateOrderInput(order);
        expectGeneralProperties(input, {
            order: order,
            mustHavePriceChanges: true,
            ticketMedium: "DIGITAL",
        });

        const transLines = input.transaction.transactionLines;
        expect(transLines).toHaveLength(2);
        expect(transLines[0].mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].scope).toBe("LINE");
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].name).toBe("LOYALTY_DISCOUNT");
        expect(transLines[0].mainProduct.vats[0].priceChanges[0].amount).toBe(-3.5);

        expect(transLines[1].mainProduct.vats[0].priceChanges).toHaveLength(0);
    });

    test("[case 5] test order with 10% discount loyalty on specific product", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const models = store.models;
        const order = await getFilledOrder(store);

        const reward = models["loyalty.reward"].get(35);
        // Restrict the discount to the second line's product (Chardonnay White, 2 x 40.0).
        reward.all_discount_product_ids = [order.lines[1].product_id];

        expect(order.priceIncl).toBe(185);
        applyDiscountReward(order, "specific");
        expect(order.priceIncl).toBeCloseTo(177);

        const input = generateOrderInput(order);
        expectGeneralProperties(input, {
            order: order,
            mustHavePriceChanges: true,
            ticketMedium: "DIGITAL",
        });

        const transLines = input.transaction.transactionLines;
        expect(transLines).toHaveLength(2);
        expect(transLines[0].mainProduct.vats[0].priceChanges).toHaveLength(0);

        expect(transLines[1].mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(transLines[1].mainProduct.vats[0].price).toBe(80);
        expect(transLines[1].mainProduct.vats[0].priceChanges[0].scope).toBe("LINE");
        expect(transLines[1].mainProduct.vats[0].priceChanges[0].name).toBe("LOYALTY_DISCOUNT");
        expect(transLines[1].mainProduct.vats[0].priceChanges[0].amount).toBe(-8);
    });

    test("[case 6] test order with a free product", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        expect(order.priceIncl).toBe(185);
        const rewardLine = claimFreeProductReward(order);
        // Since the pos_loyalty refactor a free product is a 0 priced line of the rewarded
        // product, so it doesn't change the order total.
        expect(rewardLine.product_id.name).toBe("Bourgogne Red");
        expect(rewardLine.qty).toBe(1);
        expect(order.priceIncl).toBe(185);

        const input = generateOrderInput(order);
        expectGeneralProperties(input, {
            order: order,
            mustHavePriceChanges: true,
            ticketMedium: "DIGITAL",
        });

        const transLines = input.transaction.transactionLines;
        // The free product is real merchandise: the FDM must see it leave the store.
        expect(transLines).toHaveLength(3);
        const freeTransLine = transLines[2];
        expect(freeTransLine.mainProduct.productId).toBe(`product_id_${rewardLine.product_id.id}`);
        expect(freeTransLine.mainProduct.quantity).toBe(1);
        // Reported at its catalog price, brought back to 0 by the reward's price change.
        expect(freeTransLine.mainProduct.vats[0].price).toBe(35);
        expect(freeTransLine.mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(freeTransLine.mainProduct.vats[0].priceChanges[0].name).toBe("LOYALTY_FREE_PRODUCT");
        expect(freeTransLine.mainProduct.vats[0].priceChanges[0].id).toBe("7");
        expect(freeTransLine.mainProduct.vats[0].priceChanges[0].type).toBe("PUBLIC");
        expect(freeTransLine.mainProduct.vats[0].priceChanges[0].scope).toBe("LINE");
        expect(freeTransLine.mainProduct.vats[0].priceChanges[0].amount).toBe(-35);
        expect(freeTransLine.lineTotal).toBe(0);
    });

    test("[case 7] a free product of qty 2 is reported at twice its catalog price", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const models = store.models;
        const order = await getFilledOrder(store);

        // Two points are needed for two free products: rule 33 gives one per order, so bump
        // the free product reward to a reward the order can afford twice.
        models["loyalty.rule"].get(33).reward_point_amount = 2;
        const rewardLine = claimFreeProductReward(order, 2);
        expect(rewardLine.qty).toBe(2);

        const input = generateOrderInput(order);
        expectGeneralProperties(input, {
            order: order,
            mustHavePriceChanges: true,
            ticketMedium: "DIGITAL",
        });

        const freeTransLine = input.transaction.transactionLines[2];
        expect(freeTransLine.mainProduct.quantity).toBe(2);
        expect(freeTransLine.mainProduct.vats[0].price).toBe(70);
        expect(freeTransLine.mainProduct.vats[0].priceChanges[0].name).toBe("LOYALTY_FREE_PRODUCT");
        expect(freeTransLine.mainProduct.vats[0].priceChanges[0].amount).toBe(-70);
        expect(freeTransLine.lineTotal).toBe(0);
    });

    test("[case 8] a global discount never applies to a free product line", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        const rewardLine = claimFreeProductReward(order);

        // Simulate a 10% order-level global discount. The order total is left untouched, so
        // only the free line is asserted here (not the overall transaction consistency).
        Object.defineProperty(order, "globalDiscountPc", {
            get: () => ({ value: 10, type: "percent" }),
            configurable: true,
        });

        const transLinesMap = buildInputGenerator(order).generateTransactionLinesInput();
        const freeTransLine = transLinesMap[rewardLine.uuid].transLine;

        // lineTotal stays 0: a global discount has no room to apply on a free product.
        expect(freeTransLine.lineTotal).toBe(0);
        expect(freeTransLine.mainProduct.vats[0].priceChanges).toHaveLength(1);
        expect(findPriceChange(freeTransLine, "LOYALTY_FREE_PRODUCT")).not.toBe(null);
        expect(findPriceChange(freeTransLine, "GLOBAL_DISCOUNT_10P")).toBe(null);
    });

    test("[case 9] a free product line keeps its uuid across reward recomputations", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        const uuid = claimFreeProductReward(order).uuid;
        // Every order change drops and rebuilds the reward lines; the FDM tracks them by
        // uuid, so the rebuilt line must keep the same one.
        order.recomputeRewards();
        const rebuiltLine = order.lines.find((line) => line.is_reward_line);

        expect(rebuiltLine.uuid).toBe(uuid);
        expect(uuid).toBe(`${order.uuid}-loyalty-34-5`);
    });

    test("[case 10] removing a free product records a blackbox correction", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        const freeLine = claimFreeProductReward(order);
        const uuid = freeLine.uuid;

        order.removeOrderline(freeLine);

        expect(order.lines.some((line) => line.is_reward_line)).toBe(false);
        // The goods never left the store, so the FDM must be corrected for them.
        expect(Object.keys(order.uiState.deletedLines)).toEqual([uuid]);
        expect(order.uiState.deletedLines[uuid].mainProduct.vats[0].price).toBe(35);
    });

    test("[case 11] removing a discount reward records no blackbox correction", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        applyDiscountReward(order);
        const rewardLine = order.lines.find((line) => line.is_reward_line);
        order.removeOrderline(rewardLine);

        expect(order.lines.some((line) => line.is_reward_line)).toBe(false);
        // A discount reward line is never sent as goods, so there is nothing to correct.
        expect(Object.keys(order.uiState.deletedLines)).toEqual([]);
    });
});
