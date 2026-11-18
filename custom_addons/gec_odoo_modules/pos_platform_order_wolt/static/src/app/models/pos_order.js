import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PosOrder.prototype, {
    get isWoltOrder() {
        return this.platform_order_provider_code === "wolt";
    },
    get canMarkWoltDelivered() {
        return (
            this.isWoltOrder &&
            this.platform_order_food_ready &&
            (this.platform_order_type === "pickup" || this.wolt_self_delivery) &&
            ["accepted", "driver_allocated", "driver_arrived", "collected"].includes(
                this.platform_order_status
            )
        );
    },
    get rejectReasonOptions() {
        if (this.isWoltOrder) {
            return [
                {
                    id: "ITEMS_UNAVAILABLE",
                    label: _t("Items unavailable"),
                    item: "ITEMS_UNAVAILABLE",
                },
                { id: "VENUE_CLOSING_SOON", label: _t("Closing soon"), item: "VENUE_CLOSING_SOON" },
                { id: "GENERIC", label: _t("Other reason"), item: "GENERIC" },
            ];
        }
        return super.rejectReasonOptions;
    },
});
