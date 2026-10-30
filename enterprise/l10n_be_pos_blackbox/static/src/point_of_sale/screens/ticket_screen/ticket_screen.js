import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

patch(TicketScreen.prototype, {
    async print(order) {
        if (!this.pos.blackbox.isActive) {
            return super.print(order);
        }
        try {
            await this.pos.beforePrintBlackboxOrder(order);
            await super.print(order);
        } finally {
            order.l10n_be_copy_event_data = {};
        }
    },
});
