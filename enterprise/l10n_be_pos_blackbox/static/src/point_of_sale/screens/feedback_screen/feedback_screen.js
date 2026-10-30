import { FeedbackScreen } from "@point_of_sale/app/screens/feedback_screen/feedback_screen";
import { patch } from "@web/core/utils/patch";

patch(FeedbackScreen.prototype, {
    async clickPrint() {
        if (!this.pos.blackbox.isActive) {
            return super.clickPrint();
        }
        const order = this.currentOrder;
        try {
            await this.pos.beforePrintBlackboxOrder(order);
            await super.clickPrint();
        } finally {
            order.l10n_be_copy_event_data = {};
        }
    },
});
