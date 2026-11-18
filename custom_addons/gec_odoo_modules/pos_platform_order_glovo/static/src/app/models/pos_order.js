import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    get isGlovoOrder() {
        return this.platform_order_provider_id?.code === "glovo";
    },
    get canMarkCustomerPickedUp() {
        return (
            this.isGlovoOrder &&
            this.platform_order_type === "pickup" &&
            this.state === "draft" &&
            this.platform_order_status !== "cancelled"
        );
    },
});
