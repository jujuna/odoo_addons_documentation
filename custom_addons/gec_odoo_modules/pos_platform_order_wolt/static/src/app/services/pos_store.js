import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    /** Wolt only allows rejecting before acceptance: keep accepted Wolt orders on screen. */
    async beforeDeleteOrder(order, options) {
        if (order.isWoltOrder && order.platform_order_status !== "new") {
            this.notification.add(
                _t("Contact Wolt support to reject an order that is already accepted."),
                { type: "warning" }
            );
            return false;
        }
        return super.beforeDeleteOrder(...arguments);
    },

    /**
     * Closing the session cancels the open orders on the server, which first checks them at Wolt
     * and refuses an order still running there: show that error, core hides it. Live Wolt orders
     * skip the kitchen "cancelled" ticket, which would print before the server refuses.
     */
    async deleteOrders(orders, serverIds = [], ignoreChange = false) {
        const woltLive = orders.filter(
            (order) => order.isWoltOrder && order.platform_order_status !== "cancelled"
        );
        if (!woltLive.length) {
            return super.deleteOrders(...arguments);
        }
        const rest = orders.filter((order) => !woltLive.includes(order));
        const results = await Promise.allSettled([
            super.deleteOrders(woltLive, [], true),
            super.deleteOrders(rest, serverIds, ignoreChange),
        ]);
        const refused = results[0].value?.find(
            (result) =>
                result.status === "rejected" &&
                result.reason?.exceptionName === "odoo.exceptions.UserError"
        );
        if (refused) {
            throw refused.reason;
        }
        return results;
    },

    /** Keep a Wolt order on screen when Wolt refuses the rejection. */
    async _rejectOrder(order, reason) {
        if (!order.isWoltOrder) {
            return super._rejectOrder(...arguments);
        }
        try {
            await this.data.callRelated("pos.order", "mark_platform_prep_order_as_printed", [
                [order.id],
            ]);
        } catch {
            // already printed
        }
        const rpcCall = this.data.call(
            "pos.order",
            "platform_order_status_update_from_ui",
            [order.id, "reject"],
            { reason }
        );
        const result = await this._handleRpc(order, rpcCall, {
            successMessage: _t("Order rejected successfully."),
        });
        if (!result.success) {
            return false;
        }
        if (order.uuid === this.selectedOrderUuid) {
            this.selectedOrderUuid = null;
        }
        return true;
    },
});
