import { advanceTime, beforeEach, expect, test } from "@odoo/hoot";
import { patch } from "@web/core/utils/patch";
import mobile from "@web_mobile/js/services/core";
import { PosTicketPrinterPlugin } from "@point_of_sale/app/plugins/pos_ticket_printer_plugin";
import "@obox_pos_mobile/app/plugins/pos_ticket_printer_plugin";

const OWN_SERIAL = "ODO-ABCDEF1234";
const OWN_PORT = 4546;
const OWN_STATUS_CACHE_MS = 2000;
const STORED_ADDRESS = "10.0.0.99:4545/usb/v1/printer/p";
const LOOPBACK_ADDRESS = `127.0.0.1:${OWN_PORT}/usb/v1/printer/p`;

function ticketPrinter(selfOrderingMode) {
    return Object.create(PosTicketPrinterPlugin.prototype, {
        config: { value: { self_ordering_mode: selfOrderingMode } },
    });
}

async function printerAddress(plugin) {
    const printer = await plugin.createPrinterInstance({
        printer_type: "obox",
        printer_ip: STORED_ADDRESS,
        obox_serial: OWN_SERIAL,
    });
    await advanceTime(OWN_STATUS_CACHE_MS + 1);
    return printer.printer_ip;
}

beforeEach(() => {
    patch(mobile.methods, {
        getDeviceManagerStatus: async () => ({
            success: true,
            data: { paired: true, serial: OWN_SERIAL, ip: "192.168.1.10", port: OWN_PORT },
        }),
    });
});

test("a printer reached locally is this box's printer on loopback", async () => {
    patch(PosTicketPrinterPlugin.prototype, { reachesOboxLocally: () => true });

    expect(await printerAddress(ticketPrinter("mobile"))).toBe(LOOPBACK_ADDRESS);
});

test("a printer not reached locally keeps the stored address", async () => {
    patch(PosTicketPrinterPlugin.prototype, { reachesOboxLocally: () => false });

    expect(await printerAddress(ticketPrinter("kiosk"))).toBe(STORED_ADDRESS);
});
