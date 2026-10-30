import { CONSOLE_COLOR, PosStore } from "@point_of_sale/app/services/pos_store";
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.signingSelfOrders = new Set();
        if (this.blackbox.isActive && this.config.self_ordering_mode === "mobile") {
            this.data.connectWebSocket("ONLINE_PAYMENT_STATUS", (notification) => {
                if (notification.status !== "success") {
                    return;
                }
                const orderId = notification.order_id;
                if (!orderId) {
                    return;
                }
                this.signSelfOrder(orderId);
            });
        }
    },
    async signSelfOrder(orderId) {
        // The same payment can be notified twice, don't sign the order twice
        if (this.signingSelfOrders.has(orderId)) {
            return;
        }
        this.signingSelfOrders.add(orderId);

        try {
            await this.getSelfOrderToSign(orderId);
        } catch {
            logPosMessage(
                "Store",
                "signSelfOrder",
                "Another instance is already signing the order",
                CONSOLE_COLOR
            );
        } finally {
            this.signingSelfOrders.delete(orderId);
        }
    },
});
