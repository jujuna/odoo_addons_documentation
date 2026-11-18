import { patch } from "@web/core/utils/patch";
import { OrderTabs } from "@point_of_sale/app/components/order_tabs/order_tabs";

patch(OrderTabs.prototype, {
    /** @override Core closes all dialogs after navigating, which would hide why navigate refused the Glovo order. */
    selectFloatingOrder(order) {
        if (!order.isGlovoOrder) {
            return super.selectFloatingOrder(...arguments);
        }
        this.dialog.closeAll();
        this.pos.navigate("ProductScreen", { orderUuid: order.uuid });
    },
});
