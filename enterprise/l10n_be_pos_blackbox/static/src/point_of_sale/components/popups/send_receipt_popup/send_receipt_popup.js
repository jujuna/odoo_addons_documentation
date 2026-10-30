import { SendReceiptPopup } from "@point_of_sale/app/components/popups/send_receipt_popup/send_receipt_popup";
import { patch } from "@web/core/utils/patch";

patch(SendReceiptPopup.prototype, {
    async actionSendReceiptOnEmail() {
        if (!this.pos.blackbox.isActive) {
            return super.actionSendReceiptOnEmail(...arguments);
        }
        const order = this.order;
        try {
            await this.pos.beforePrintBlackboxOrder(order, false);
            return super.actionSendReceiptOnEmail(...arguments);
        } finally {
            order.l10n_be_copy_event_data = {};
        }
    },
    async _sendReceiptToCustomer({ action, destination }) {
        if (!this.pos.blackbox.isActive) {
            return super._sendReceiptToCustomer(...arguments);
        }
        await this.pos.data.call("pos.order", action, [[this.order.id], destination], {
            context: {
                l10n_be_copy_event_data: this.order.l10n_be_copy_event_data || false,
            },
        });
    },
});
