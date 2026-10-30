import { patch } from "@web/core/utils/patch";
import { PosTicketPrinterPlugin } from "@point_of_sale/app/plugins/pos_ticket_printer_plugin";
import "@obox_pos_mobile/app/plugins/pos_ticket_printer_plugin";

patch(PosTicketPrinterPlugin.prototype, {
    reachesOboxLocally() {
        return this.config.self_ordering_mode === "kiosk";
    },
});
