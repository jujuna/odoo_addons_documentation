import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
// `linesSendableToBlackbox` is defined by the base blackbox patch; import it so it is always
// applied before this one, otherwise `super` here wouldn't find it (patch order follows the
// module loader, which only honours import edges).
import "@l10n_be_pos_blackbox/common/models/pos_order";

patch(PosOrder.prototype, {
    /**
     * A reward line only represents merchandise when the reward hands out a free product:
     * since the pos_loyalty refactor such a line carries the rewarded product itself at a
     * 0 price, so it must reach the FDM as a regular transaction line (with a
     * LOYALTY_FREE_PRODUCT price change, see `input_generator.js`).
     * The other reward lines are not goods and are reported differently:
     *  - discount rewards become LOYALTY_DISCOUNT price changes on the discounted lines
     *  - gift card / eWallet redemptions become financials (VOUCHER_STORE / VOUCHER_OTHER)
     */
    get linesSendableToBlackbox() {
        return super.linesSendableToBlackbox.filter(
            (line) => !line.is_reward_line || line.reward_id?.reward_type === "product"
        );
    },
    /**
     * The uuid a free product reward line must be rebuilt under.
     *
     * `pos_loyalty` deletes and recreates every reward line on each order change
     * (`recomputeRewards`), while the FDM tracks lines by uuid from one `signOrder` to the
     * next. A brand new uuid for the same free product would therefore be reported as
     * "the previous free product line was removed and another one was added", burning an
     * FDM correction on every keystroke. Deriving the uuid from the order, the reward and
     * the rewarded product keeps it the same line for the FDM, so only real changes
     * (quantity, rewarded product) are corrected.
     */
    l10nBeRewardLineUuid(reward, product) {
        return `${this.uuid}-loyalty-${reward.id}-${product.id}`;
    },
    /**
     * A free product the cashier takes back off the order must still be corrected on the
     * FDM. `pos_loyalty` drops a reward by deleting its lines outright instead of deferring
     * to `super`, so the blackbox tracking never sees them go: record them here, where this
     * module (loaded after both patches) always runs first. Only the lines the FDM knows
     * about are recorded, otherwise a discount reward would be corrected as phantom goods.
     */
    removeOrderline(lineToRemove) {
        if (lineToRemove.is_reward_line && this.trackDeletedLinesForBlackbox(lineToRemove)) {
            const sendableLines = this.linesSendableToBlackbox;
            // Removing one reward line removes every line of that reward.
            const removedLines = this.lines.filter(
                (line) =>
                    line.is_reward_line &&
                    line.reward_id?.id === lineToRemove.reward_id?.id &&
                    sendableLines.includes(line)
            );
            for (const line of removedLines) {
                this.uiState.deletedLines[line.uuid] = this.wasSignedToBlackbox(line)
                    ? null
                    : this.buildInitialTransactionLine(line);
            }
        }
        return super.removeOrderline(...arguments);
    },
});
