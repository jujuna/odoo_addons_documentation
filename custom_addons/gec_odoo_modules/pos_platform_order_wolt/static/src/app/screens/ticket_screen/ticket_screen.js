import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
const { DateTime } = luxon;

// Wolt rejects a preorder that is not confirmed within 15 minutes
// (instant orders: provider's 3 minutes).
const PREORDER_CONFIRM_SECONDS = 15 * 60;

patch(TicketScreen.prototype, {
    get selectedOrderExpiration() {
        const order = this.getSelectedOrder();
        if (!order?.isWoltOrder || order.wolt_order_type !== "preorder") {
            return super.selectedOrderExpiration;
        }
        const expirationMs = PREORDER_CONFIRM_SECONDS * 1000;
        const createdAt = DateTime.fromISO(order.create_date);
        const elapsedMs = this.state.currentTime.diff(createdAt).toMillis();
        const remainingMs = Math.max(0, expirationMs - elapsedMs);
        return {
            isExpired: remainingMs === 0,
            formattedRemainingTime: DateTime.fromMillis(remainingMs).toFormat("mm:ss"),
            remainingTimePercentage: (remainingMs / expirationMs) * 100,
        };
    },
    async onMarkWoltDeliveredClicked(order) {
        const rpcCall = this.pos.data.call("pos.order", "platform_order_status_update_from_ui", [
            order.id,
            "delivered",
        ]);
        await this._handleRpc(order, rpcCall, { block: true });
    },
});
