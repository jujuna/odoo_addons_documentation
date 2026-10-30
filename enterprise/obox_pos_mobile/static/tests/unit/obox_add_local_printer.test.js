import { expect, test } from "@odoo/hoot";
import {
    chosenPrinterDomain,
    localPrinterDomain,
} from "@obox_pos_mobile/backend/obox_add_local_printer";

test("the device's Obox is matched on its serial number", () => {
    expect(localPrinterDomain("phone-1 ")).toEqual([
        ["type", "=", "printer"],
        ["obox_id.serial_number", "=", "PHONE-1"],
    ]);
});

test("every printer is matched when the serial number is unknown", () => {
    expect(localPrinterDomain(null)).toEqual([["type", "=", "printer"]]);
    expect(localPrinterDomain(undefined)).toEqual([["type", "=", "printer"]]);
    expect(localPrinterDomain("   ")).toEqual([["type", "=", "printer"]]);
});

test("the chosen printer is the one of this device with that identifier", () => {
    expect(chosenPrinterDomain("phone-1", "usb_04b8_0e32_SERIAL")).toEqual([
        ["type", "=", "printer"],
        ["obox_id.serial_number", "=", "PHONE-1"],
        ["identifier", "=", "usb_04b8_0e32_SERIAL"],
    ]);
});
