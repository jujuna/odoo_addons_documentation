import { LoyaltyReward } from "@pos_loyalty/app/models/loyalty_reward";
import { patch } from "@web/core/utils/patch";

patch(LoyaltyReward.prototype, {
    /**
     * Give a free product reward line a stable uuid, so the FDM keeps seeing the same line
     * across `recomputeRewards` passes (see `PosOrder.l10nBeRewardLineUuid`).
     */
    getRewardLines(order, points, opts) {
        const lineValues = super.getRewardLines(order, points, opts);
        if (!order.config_id.l10n_be_blackbox_be_id || this.reward_type !== "product") {
            return lineValues;
        }
        for (const values of lineValues) {
            const uuid = order.l10nBeRewardLineUuid(this, values.product_id);
            // `create` keys the record on the uuid, so never reuse one that is still taken.
            if (!order.models["pos.order.line"].getBy("uuid", uuid)) {
                values.uuid = uuid;
            }
        }
        return lineValues;
    },
});
