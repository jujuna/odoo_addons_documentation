import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(TicketScreen.prototype, {
    /** @override Stop before the refund order exists: the server refuses it for cashiers. */
    async onDoRefund() {
        const order = this.getSelectedOrder();
        if (order?.isGlovoOrder && this.pos.accessRight.loggedCashier?._role !== "manager") {
            this.dialog.add(AlertDialog, {
                title: _t("Glovo order"),
                body: _t("Only a POS manager can refund a Glovo order or delete its payments."),
            });
            return;
        }
        return super.onDoRefund(...arguments);
    },

    async onCustomerPickedUpClicked(order) {
        const rpcCall = this.pos.data.call("pos.order", "platform_order_status_update_from_ui", [
            order.id,
            "customer_picked_up",
        ]);
        const result = await this._handleRpc(order, rpcCall, { block: true });
        if (result.success) {
            await this.pos.getServerOrder(order.id);
            this.pos.notification.add(result.message, { type: "success" });
        }
    },
});
