import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";

patch(ClosePosPopup.prototype, {
    async closeSession() {
        if (this.pos.config.iot_display_id) {
            this.pos.closeIotCustomerDisplay();
        }
        await super.closeSession(...arguments);
    },
});
