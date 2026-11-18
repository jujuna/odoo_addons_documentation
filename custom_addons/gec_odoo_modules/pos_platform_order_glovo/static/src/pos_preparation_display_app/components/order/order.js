import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Order } from "@pos_enterprise/app/components/order/order";

patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this.notification = useService("notification");
    },

    /** @override A Glovo order stays on the display until Glovo knows the food is ready. */
    async doneOrder() {
        const posOrder = this.order.pos_order_id;
        if (posOrder?.platform_order_provider_code !== "glovo") {
            return super.doneOrder(...arguments);
        }
        const result = await this.orm.call("pos.order", "platform_order_status_update_from_ui", [
            posOrder.id,
            "food_ready",
        ]);
        if (!result.success) {
            this.notification.add(result.message, { type: "danger" });
            return;
        }
        // core's doneOrder calls food_ready again; the server answers success for a Glovo order already ready
        return super.doneOrder(...arguments);
    },
});
