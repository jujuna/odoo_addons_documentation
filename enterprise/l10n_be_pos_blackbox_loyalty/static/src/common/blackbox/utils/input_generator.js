import { InputGenerator } from "@l10n_be_pos_blackbox/common/blackbox/utils/input_generator";
import { patch } from "@web/core/utils/patch";
import { uuidv4 } from "@point_of_sale/utils";
import { roundCurrency } from "@point_of_sale/app/models/utils/currency";

/**
 * Handling of loyalty programs when using the blackbox.
 *
 * `pos_loyalty` expresses every reward as an extra order line; the FDM has no notion of a
 * reward line, so each kind of reward is translated into something the FDM understands:
 *
 * Gift cards:
 *  - Selling a gift card is a plain transaction line with the gift card amount and a 0% VAT
 *    (the product is forbidden from carrying taxes, see `models/product_template.py`).
 *  - Redeeming a gift card is a financial of type VOUCHER_STORE for the redeemed amount. The
 *    redemption line itself is *not* sent as a transaction line, otherwise the sum of the
 *    transaction lines would no longer match the transaction total.
 * EWallets:
 *  - Same as a gift card redemption, with the financial type VOUCHER_OTHER.
 * Discount rewards:
 *  - The reward line is not sent. Instead the discount is spread over the transaction
 *    line(s) it discounts as a negative LOYALTY_DISCOUNT price change, weighted by each
 *    line's share of the discounted total. Its scope is EVENT for an order-wide discount
 *    and LINE for a cheapest/specific one.
 * Free product rewards:
 *  - The reward line carries the rewarded product at a 0 price, so it *is* sent as a
 *    transaction line: the goods do leave the store and the FDM must know about them. Its
 *    VAT price is the product's catalog price and a negative LOYALTY_FREE_PRODUCT price
 *    change brings the line total back to 0.
 */
patch(InputGenerator.prototype, {
    setup(params) {
        super.setup(...arguments);
        const rewardLines = this.order?.lines.filter((line) => line.is_reward_line) || [];
        this.giftCardLines = rewardLines.filter(
            (line) => this.getRewardProgramType(line) === "gift_card"
        );
        this.eWalletLines = rewardLines.filter(
            (line) => this.getRewardProgramType(line) === "ewallet"
        );
        this.giftCardTotal = Math.abs(
            this.giftCardLines.reduce((total, line) => total + line.blackboxPrice, 0)
        );
        this.eWalletTotal = Math.abs(
            this.eWalletLines.reduce((total, line) => total + line.blackboxPrice, 0)
        );
        this.orderLineRewardPriceChanges = {};
        this.initRewardsLineData();
    },
    /**
     * The program type a reward line belongs to. A payment reward (gift card / eWallet) is
     * linked to the card it spends from, and falls back on its reward's program for a card
     * that isn't loaded (a code redeemed offline).
     * @param {PosOrderline} line
     * @returns {string|undefined}
     */
    getRewardProgramType(line) {
        return line.card_id?.program_id?.program_type || line.reward_id?.program_id?.program_type;
    },
    isFreeProductRewardLine(line) {
        return Boolean(line.is_reward_line) && line.reward_id?.reward_type === "product";
    },
    /**
     * All the price changes a reward produced on a transaction line, aggregating the combo
     * children for a combo parent (a combo's price changes live on its children).
     * @param {PosOrderline} line
     * @returns {object[]}
     */
    getLineRewardPriceChanges(line) {
        if (!line.combo_line_ids.length) {
            return this.orderLineRewardPriceChanges[line.id] || [];
        }
        return line
            .getAllLinesInCombo()
            .filter((comboLine) => !comboLine.combo_line_ids.length)
            .flatMap((comboLine) => this.orderLineRewardPriceChanges[comboLine.id] || []);
    },
    /**
     * Returns (and lazily allocates) the groupingId shared by all the price changes a single
     * reward produced, so the FDM can tell they are all part of the same reward.
     */
    getLoyaltyGroupingId(rewardKey) {
        const state = this._getGroupingState();
        if (!state.loyaltyRewards) {
            state.loyaltyRewards = {};
        }
        if (state.loyaltyRewards[rewardKey] === undefined) {
            state.loyaltyRewards[rewardKey] = this._nextGroupingId();
        }
        return state.loyaltyRewards[rewardKey];
    },
    pushRewardPriceChange(lineId, priceChange) {
        if (!this.orderLineRewardPriceChanges[lineId]) {
            this.orderLineRewardPriceChanges[lineId] = [];
        }
        this.orderLineRewardPriceChanges[lineId].push(priceChange);
    },
    /**
     * Precompute the price changes the order's rewards produce on the transaction lines and
     * store them in `orderLineRewardPriceChanges`, keyed by order line id.
     *
     * Gift card / eWallet redemptions are handled in `generateFinancialsInput` and free
     * product rewards in `generatePriceChangeInput`, so only discount rewards are collected
     * here.
     */
    initRewardsLineData() {
        if (!this.order) {
            return;
        }
        for (const rewardLine of this.order.lines.filter((line) => line.is_reward_line)) {
            const reward = rewardLine.reward_id;
            if (
                !reward ||
                reward.reward_type !== "discount" ||
                ["gift_card", "ewallet"].includes(this.getRewardProgramType(rewardLine))
            ) {
                continue;
            }
            this.initDiscountRewardPriceChanges(rewardLine, reward);
        }
    },
    /**
     * Spread a discount reward line over the transaction lines it discounts.
     *
     * `LoyaltyReward.getRewardLines` splits a discount into one reward line per tax group,
     * so this mirrors its line selection (combos flattened to their priced children) and
     * then keeps only the lines whose taxes are the ones of `rewardLine`.
     */
    initDiscountRewardPriceChanges(rewardLine, reward) {
        const order = this.order;
        // A combo parent holds no price of its own: the discount lands on its children.
        const discountedLines = reward
            .getDiscountApplicableLines(order)
            .flatMap((line) =>
                line.combo_line_ids.length
                    ? line.getAllLinesInCombo().filter((l) => !l.combo_line_ids.length)
                    : [line]
            )
            .filter((line) => this.getLineTaxKey(line) === this.getRewardTaxKey(rewardLine));
        const discountedTotal = order.currency.round(
            discountedLines.reduce((total, line) => total + line.blackboxPrice, 0)
        );
        if (!discountedLines.length || !discountedTotal) {
            return;
        }
        const rewardAmount = rewardLine.priceIncl;
        const scope = reward.discount_applicability === "order" ? "EVENT" : "LINE";
        for (const line of discountedLines) {
            this.pushRewardPriceChange(line.id, {
                id: "7",
                name: "LOYALTY_DISCOUNT",
                amount: order.currency.round((line.blackboxPrice / discountedTotal) * rewardAmount),
                scope: scope,
                rewardKey: `reward_${reward.id}`,
            });
        }
    },
    /**
     * The taxes of a discountable line, as `LoyaltyReward.getRewardLines` groups them:
     * mapped through the order's fiscal position and without the fixed taxes (a fixed tax
     * is never discounted).
     */
    getLineTaxKey(line) {
        const fiscalPosition = this.order.fiscal_position_id;
        const taxes = fiscalPosition
            ? fiscalPosition.getTaxesAfterFiscalPosition(line.tax_ids)
            : line.tax_ids;
        return this.buildTaxKey(taxes.filter((tax) => tax.amount_type !== "fixed"));
    },
    /** The taxes of a discount reward line, already mapped and filtered when it was built. */
    getRewardTaxKey(rewardLine) {
        return this.buildTaxKey(rewardLine.tax_ids);
    },
    buildTaxKey(taxes) {
        return taxes
            .map((tax) => tax.id)
            .sort((a, b) => a - b)
            .join("-");
    },
    /**
     * Scale a reward amount computed for the whole line down to `qty` units of it, as the
     * signOrder corrections send a line for a partial quantity.
     */
    computeLoyaltyPriceChangeAmount(line, baseAmount, qty) {
        if (!line.qty) {
            return 0;
        }
        return roundCurrency((baseAmount / line.qty) * qty, this.order.currency);
    },
    generatePriceChangeInput(
        line,
        initPrice,
        { priceUnit, discount, globalDiscount, globalDiscountType, qty }
    ) {
        if (this.isFreeProductRewardLine(line)) {
            // The line sells the rewarded product at a 0 price, which the base generator
            // already reports as a unit price change down to 0. Only its label and id have
            // to say that the reward, and not the cashier, set that price.
            const previousDiscountType = this.discountType;
            this.discountType = "LOYALTY_FREE_PRODUCT";
            let res;
            try {
                res = super.generatePriceChangeInput(...arguments);
            } finally {
                this.discountType = previousDiscountType;
            }
            for (const priceChange of res) {
                if (priceChange.name === "LOYALTY_FREE_PRODUCT") {
                    priceChange.id = "7";
                }
            }
            return res;
        }
        const res = super.generatePriceChangeInput(...arguments);
        for (const priceChange of this.orderLineRewardPriceChanges[line.id] || []) {
            res.push({
                id: priceChange.id,
                groupingId: this.getLoyaltyGroupingId(priceChange.rewardKey),
                name: priceChange.name,
                type: "PUBLIC",
                amount: this.computeLoyaltyPriceChangeAmount(line, priceChange.amount, qty),
                scope: priceChange.scope,
            });
        }
        return res;
    },
    /**
     * The FDM requires `lineTotal` to equal the sum of the line's VAT prices and price
     * changes, so the discount rewards spread over the line have to be accounted for here
     * too: the base total only knows about the line's own price and the global discount.
     */
    getTransactionLineTotal(line, qty = line.qty) {
        const res = super.getTransactionLineTotal(...arguments);
        const priceChanges = this.getLineRewardPriceChanges(line);
        if (!priceChanges.length) {
            return res;
        }
        const rewardAmount = priceChanges.reduce(
            (total, priceChange) =>
                total + this.computeLoyaltyPriceChangeAmount(line, priceChange.amount, qty),
            0
        );
        return roundCurrency(res + rewardAmount, this.order.currency);
    },
    generateFinancialsInput() {
        const res = super.generateFinancialsInput(...arguments);
        if (this.giftCardTotal) {
            res.push({
                id: uuidv4(),
                name: "Gift Card Redemption",
                type: "VOUCHER_STORE",
                inputMethod: "MANUAL",
                amount: roundCurrency(this.giftCardTotal, this.order.currency),
                amountType: "PAYMENT",
            });
        }
        if (this.eWalletTotal) {
            res.push({
                id: uuidv4(),
                name: "EWallet Redemption",
                type: "VOUCHER_OTHER",
                inputMethod: "MANUAL",
                amount: roundCurrency(this.eWalletTotal, this.order.currency),
                amountType: "PAYMENT",
            });
        }
        return res;
    },
    /**
     * The gift card / eWallet redemption lines lower the order total but are reported as
     * financials instead of transaction lines, so they must be added back to keep the
     * transaction total equal to the sum of the transaction lines.
     */
    getTransactionTotal() {
        const total = super.getTransactionTotal(...arguments);
        return roundCurrency(total + this.giftCardTotal + this.eWalletTotal, this.order.currency);
    },
});
