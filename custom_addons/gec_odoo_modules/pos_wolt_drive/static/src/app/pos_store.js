import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.data.connectWebSocket("WOLT_DRIVE_UPDATE", ({ order_id }) =>
            this.data.loadServerOrders([["id", "=", order_id]])
        );
    },
});
