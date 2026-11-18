import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

const BOOKABLE_AGAIN = ["not_delivered", "cancelled"];
const STATUS_LABELS = {
    requested: _t("Wolt courier requested"),
    courier_assigned: _t("Wolt courier on the way"),
    courier_at_pickup: _t("Wolt courier arrived"),
    picked_up: _t("Picked up by Wolt"),
    delivered: _t("Delivered by Wolt"),
    not_delivered: _t("Not delivered by Wolt"),
    cancelled: _t("Wolt courier cancelled"),
};

patch(PosOrder.prototype, {
    get isWaitingForWolt() {
        return this.wolt_drive_status === "requested" && !this.wolt_drive_ref;
    },
    get woltDriveStatusLabel() {
        if (this.isWaitingForWolt) {
            return _t("Waiting for Wolt");
        }
        return STATUS_LABELS[this.wolt_drive_status] || "";
    },
    get canBookWoltCourier() {
        const partner = this.partner_id;
        const status = this.wolt_drive_status;
        const canBookAgain = !status || this.isWaitingForWolt || BOOKABLE_AGAIN.includes(status);
        return (
            Boolean(this.config?.wolt_drive_venue_id) &&
            typeof this.id === "number" &&
            canBookAgain &&
            !this.is_refund &&
            this.priceIncl >= 0 &&
            Boolean(partner?.phone && partner?.street && (partner?.city || partner?.zip))
        );
    },
});
