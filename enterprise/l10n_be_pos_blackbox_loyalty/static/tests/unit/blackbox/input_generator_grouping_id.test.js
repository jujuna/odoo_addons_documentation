import { test, describe, expect } from "@odoo/hoot";
import { setupPosEnv, getFilledOrder } from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import {
    applyDiscountReward,
    buildInputGenerator,
    claimFreeProductReward,
    findPriceChange,
} from "@l10n_be_pos_blackbox_loyalty/../tests/unit/utils";

definePosModels();

describe("input generator loyalty groupingId", () => {
    /**
     * Test groupingId 1 — Order-wide LOYALTY_DISCOUNT: all discounted lines share the same
     * groupingId, since they all come from the same reward.
     * Counter = 1 after generation (a single allocation for the whole reward).
     */
    test("[groupingId 1] order-wide LOYALTY_DISCOUNT: all affected lines share the same groupingId", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        applyDiscountReward(order);

        const input = buildInputGenerator(order).generateSignSaleInput();
        const transLines = input.transaction.transactionLines;

        expect(transLines).toHaveLength(2);
        const pc0 = findPriceChange(transLines[0], "LOYALTY_DISCOUNT");
        const pc1 = findPriceChange(transLines[1], "LOYALTY_DISCOUNT");
        expect(pc0).not.toBe(null);
        expect(pc1).not.toBe(null);
        // Same reward → same groupingId shared across all discounted lines
        expect(pc0.groupingId).toBe(1);
        expect(pc1.groupingId).toBe(1);
        expect(order.l10n_be_grouping_id.groupingIdCount).toBe(1);
    });

    /**
     * Test groupingId 2 — Loyalty groupingId is allocated lazily in
     * generatePriceChangeInput, AFTER the base price-change IDs of the line that first
     * triggers it.
     *
     * Expected allocation order:
     *   1  DISCOUNT_10P      (line 0 — allocated by base during generatePriceChangeInput)
     *   2  LOYALTY_DISCOUNT  (allocated on first encounter, after line 0's base IDs)
     *   3  DISCOUNT_10P      (line 1 — each line owns its own discount id)
     */
    test("[groupingId 2] loyalty groupingId allocated after base line-discount IDs", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        applyDiscountReward(order);
        // Add a 10% line discount to the regular lines after the reward is applied
        for (const line of order.lines.filter((l) => !l.is_reward_line)) {
            line.discount = 10;
        }

        const input = buildInputGenerator(order).generateSignSaleInput();
        const transLines = input.transaction.transactionLines;

        expect(transLines).toHaveLength(2);
        const loyaltyPc = findPriceChange(transLines[0], "LOYALTY_DISCOUNT");
        const discountPc = findPriceChange(transLines[0], "DISCOUNT_10P");

        // Line discount allocated first (base IDs come before loyalty)
        expect(discountPc.groupingId).toBe(1);
        // Loyalty ID allocated lazily after line 0's base IDs → greater than base
        expect(loyaltyPc.groupingId).toBe(2);
        // Two product lines × one discount each = counter 3 (2 line discounts + 1 loyalty)
        expect(order.l10n_be_grouping_id.groupingIdCount).toBe(3);
    });

    /**
     * Test groupingId 3 — Two distinct rewards get different groupingIds: each reward owns
     * its own entry in state.loyaltyRewards, and the ids come from the shared counter.
     *
     * We call getLoyaltyGroupingId directly to avoid the complexity of combining two
     * rewards in a full signSale flow.
     */
    test("[groupingId 3] two distinct rewards get different groupingIds", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        const generator = buildInputGenerator(order);

        const idA = generator.getLoyaltyGroupingId("reward_1");
        const idB = generator.getLoyaltyGroupingId("reward_2");
        // Same reward again → reuses the existing id, counter stays at 2
        const idAAgain = generator.getLoyaltyGroupingId("reward_1");

        // Different rewards → different ids
        expect(idA).not.toBe(idB);
        // Same reward → same id (stable across calls)
        expect(idAAgain).toBe(idA);
        // Exactly 2 ids allocated from the shared persistent counter
        expect(order.l10n_be_grouping_id.groupingIdCount).toBe(2);
    });

    /**
     * Test groupingId 4 — A free product reward line gets its own groupingId, distinct
     * from the one a discount reward allocates on the other lines. It is allocated by the
     * base generator's per-line unit price change bookkeeping, since the free product is a
     * price change on its own line.
     */
    test("[groupingId 4] LOYALTY_FREE_PRODUCT gets its own groupingId", async () => {
        const store = await setupPosEnv({ setupCashier: false });
        const order = await getFilledOrder(store);

        applyDiscountReward(order);
        const freeLine = claimFreeProductReward(order);

        const generator = buildInputGenerator(order);
        const transLinesMap = generator.generateTransactionLinesInput();
        const discountedLine = order.lines.find(
            (line) => !line.is_reward_line && line.uuid !== freeLine.uuid
        );

        const freePc = findPriceChange(
            transLinesMap[freeLine.uuid].transLine,
            "LOYALTY_FREE_PRODUCT"
        );
        const discountPc = findPriceChange(
            transLinesMap[discountedLine.uuid].transLine,
            "LOYALTY_DISCOUNT"
        );

        expect(freePc).not.toBe(null);
        expect(discountPc).not.toBe(null);
        expect(freePc.groupingId).not.toBe(discountPc.groupingId);
    });
});
