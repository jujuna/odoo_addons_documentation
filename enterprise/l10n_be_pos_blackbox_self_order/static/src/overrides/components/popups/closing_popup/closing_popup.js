import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";

patch(ClosePosPopup.prototype, {
    async closeSession() {
        if (this.pos.blackbox.isActive) {
            try {
                const unsignedOrderIds = await this.pos.data.call(
                    "pos.session",
                    "get_unsigned_mobile_orders",
                    [this.pos.session.id]
                );
                for (const orderId of unsignedOrderIds) {
                    try {
                        await this.pos.getSelfOrderToSign(orderId);
                    } catch (error) {
                        console.warn("Error signing mobile order", orderId, ":", error);
                    }
                }
            } catch (error) {
                console.warn("Error fetching unsigned mobile orders:", error);
            }
        }
        return super.closeSession();
    },
});
