import { OrderDetailsDialog } from "@point_of_sale/app/screens/ticket_screen/order_details_dialog/order_details_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(OrderDetailsDialog.prototype, {
    CanSendNFCe(order) {
        return Boolean(
            this.pos.config.l10n_br_is_nfce &&
                order.l10n_br_last_avatax_status === "error" &&
                order.state !== "draft"
        );
    },

    async SendNFCe() {
        const order = this.props.order;
        this.ui.block();
        try {
            await this.pos.data.call("pos.order", "button_l10n_br_edi", [[order.id]]);
            await this.pos.data.loadServerOrders([["uuid", "=", order.uuid]]);
        } finally {
            this.ui.unblock();
        }

        if (order.l10n_br_last_avatax_status === "accepted") {
            this.pos.notification.add(_t("NFC-e sent successfully."), { type: "success" });
        } else {
            this.pos.notification.add(order.l10n_br_avatax_error, { type: "danger" });
        }
    },
});
