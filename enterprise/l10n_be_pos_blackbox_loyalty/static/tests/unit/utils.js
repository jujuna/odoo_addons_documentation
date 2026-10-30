import { InputGenerator } from "@l10n_be_pos_blackbox/common/blackbox/utils/input_generator";

/** Ids of the loyalty records this module adds, see `data/loyalty_program.data.js`. */
export const GIFT_CARD_PROGRAM_ID = 33;
export const GIFT_CARD_REWARD_ID = 33;
export const GIFT_CARD_ID = 33;
export const FREE_PRODUCT_REWARD_ID = 34;
export const EWALLET_REWARD_ID = 36;
export const EWALLET_CARD_ID = 36;
export const DISCOUNT_REWARD_ID = 35;
/** Code that activates the 10% discount program (rule 34). */
export const DISCOUNT_CODE = "BB_DISCOUNT_10";

export const buildInputGenerator = (order) =>
    new InputGenerator({
        models: order.models,
        order: order,
        inszOrBisNumber: "1234567890",
    });

/**
 * Apply the module's 10% discount reward on `order` the way the POS does: opt the order into
 * the program with its code, then let the reward recomputation build the reward line(s).
 * @param {object} order
 * @param {string} [applicability] - "order" (default), "cheapest" or "specific"
 * @returns {object} the applied reward
 */
export const applyDiscountReward = (order, applicability = "order") => {
    const reward = order.models["loyalty.reward"].get(DISCOUNT_REWARD_ID);
    reward.discount_applicability = applicability;
    order.applied_codes = [DISCOUNT_CODE];
    order.recomputeRewards();
    return reward;
};

/**
 * Claim the module's free product reward (one "Bourgogne Red") on `order`, as the Rewards
 * control button does: register it in `active_rewards` and recompute.
 * @param {object} order
 * @param {number} [qty]
 * @returns {object} the reward line the reward produced
 */
export const claimFreeProductReward = (order, qty = 1) => {
    order.active_rewards = [{ reward_id: FREE_PRODUCT_REWARD_ID, qty: qty }];
    order.recomputeRewards();
    return order.lines.find(
        (line) => line.is_reward_line && line.reward_id?.id === FREE_PRODUCT_REWARD_ID
    );
};

/**
 * Redeem the module's 50.0 gift card on `order`, as scanning its code does.
 * @param {object} order
 * @returns {object} the reward line the redemption produced
 */
export const redeemGiftCard = (order) => {
    order.active_payment_programs = [{ reward_id: GIFT_CARD_REWARD_ID, card_id: GIFT_CARD_ID }];
    order.recomputeRewards();
    return order.lines.find(
        (line) => line.is_reward_line && line.reward_id?.id === GIFT_CARD_REWARD_ID
    );
};

/**
 * Spend the module's 30.0 eWallet balance on `order`.
 * @param {object} order
 * @returns {object} the reward line the payment produced
 */
export const spendEWallet = (order) => {
    order.active_payment_programs = [{ reward_id: EWALLET_REWARD_ID, card_id: EWALLET_CARD_ID }];
    order.recomputeRewards();
    return order.lines.find(
        (line) => line.is_reward_line && line.reward_id?.id === EWALLET_REWARD_ID
    );
};

/** The price change of the given name on the first VAT of a transaction line, or null. */
export const findPriceChange = (transLine, name, { subProduct = null } = {}) => {
    const product = subProduct === null ? transLine.mainProduct : transLine.subProducts[subProduct];
    return product.vats[0].priceChanges.find((pc) => pc.name === name) ?? null;
};

/** The transaction line of the given product, or undefined. */
export const findTransactionLine = (transLines, product) =>
    transLines.find((line) => line.mainProduct.productId === `product_id_${product.id}`);
