import { patch } from "@web/core/utils/patch";
import { PosTicketPrinterPlugin } from "@point_of_sale/app/plugins/pos_ticket_printer_plugin";
import "@obox_point_of_sale/app/plugins/pos_ticket_printer_plugin";
import { resolveDeviceAddress } from "@obox_pos_mobile/app/utils/device_address";

patch(PosTicketPrinterPlugin.prototype, {
    reachesOboxLocally() {
        return true;
    },
    async createPrinterInstance(printer) {
        if (printer.printer_type === "obox" && this.reachesOboxLocally()) {
            printer.printer_ip = await resolveDeviceAddress(
                printer.printer_ip,
                printer.obox_serial
            );
        }
        return await super.createPrinterInstance(...arguments);
    },
});
