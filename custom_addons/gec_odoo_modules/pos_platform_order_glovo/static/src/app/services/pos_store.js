import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    /** @override Glovo pays the store: its orders stay on the order list, where Set Food Ready is. */
    navigate(routeName, routeParams = {}) {
        const order = routeParams.orderUuid
            ? this.models["pos.order"].getBy("uuid", routeParams.orderUuid)
            : this.getOrder();
        if (["ProductScreen", "PaymentScreen"].includes(routeName) && order?.isGlovoOrder) {
            this.dialog.add(AlertDialog, {
                title: _t("Glovo order"),
                body: _t(
                    "Glovo orders can't be changed or paid in the POS. Glovo pays the store when the courier picks up the order."
                ),
            });
            return super.navigate("TicketScreen");
        }
        return super.navigate(...arguments);
    },

    /** @override The POS opens on its first draft order: never a Glovo order, which navigate would refuse. */
    get openOrder() {
        const order = super.openOrder;
        if (!order.isGlovoOrder) {
            return order;
        }
        return (
            this.models["pos.order"].find((o) => o.state === "draft" && !o.isGlovoOrder) ||
            this.addNewOrder()
        );
    },

    /** @override The server keeps its own version of a Glovo order: drop the lines and payments it never saved. */
    async postSyncAllOrders(orders) {
        for (const order of orders.filter((o) => o.isGlovoOrder)) {
            const localOnly = [...order.lines, ...order.payment_ids].filter((record) => !record.isSynced);
            if (localOnly.length) {
                localOnly.forEach((record) => this.data.localDeleteCascade(record));
                order.unmarkDirty();
            }
        }
        return super.postSyncAllOrders(...arguments);
    },

    /** @override Stop before the platform "Reject Order" flow, which Glovo cannot honour. */
    async beforeDeleteOrder(order) {
        if (this._isGlovoOrderLocked(order)) {
            return false;
        }
        return super.beforeDeleteOrder(...arguments);
    },

    /** @override Covers the deleteOrders callers that skip beforeDeleteOrder, before any preparation ticket. */
    async _onBeforeDeleteOrder(order) {
        if (this._isGlovoOrderLocked(order)) {
            return false;
        }
        return super._onBeforeDeleteOrder(...arguments);
    },

    /** Glovo has no refuse API: only Glovo's cancellation may remove its order. Shows why when blocked. */
    _isGlovoOrderLocked(order) {
        if (!order.isGlovoOrder || order.platform_order_status === "cancelled") {
            return false;
        }
        this.dialog.add(AlertDialog, {
            title: _t("Glovo order"),
            body: _t(
                "Glovo orders can't be cancelled here. Refuse the order in the Glovo Partner Webapp or via Glovo support."
            ),
        });
        return true;
    },
});
