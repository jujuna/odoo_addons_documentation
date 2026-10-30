import { CONSOLE_COLOR, PosStore } from "@point_of_sale/app/services/pos_store";
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async _fetchUrbanpiperOrder(order_id) {
        await super._fetchUrbanpiperOrder(...arguments);
        const order = this.models["pos.order"].get(order_id);
        if (this.blackbox.isActive && order) {
            if (
                !order.l10n_be_short_signature &&
                order.state === "paid" &&
                ["food_ready", "dispatched", "completed"].includes(order.delivery_status)
            ) {
                await this.signUrbanPiperOrder(order.id);
            }
        }
    },
    async signUrbanPiperOrder(orderId) {
        // Every PoS of the config is notified, only the one that gets the order signs it
        try {
            await this.getSelfOrderToSign(orderId, this.l10nBeSigningInsz);
        } catch {
            logPosMessage(
                "Store",
                "signUrbanPiperOrder",
                "Another instance is already signing the order",
                CONSOLE_COLOR
            );
        }
    },
});
