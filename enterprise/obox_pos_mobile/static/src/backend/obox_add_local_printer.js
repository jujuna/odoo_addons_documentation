import { Component, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { mobileNative } from "@pos_mobile_android/app/utils/native";
import { delay } from "@web/core/utils/concurrency";

const SYNC_ATTEMPTS = 5;
const SYNC_DELAY = 1000;

export function localPrinterDomain(serialNumber) {
    const domain = [["type", "=", "printer"]];
    const serial = serialNumber?.trim().toUpperCase();
    if (serial) {
        domain.push(["obox_id.serial_number", "=", serial]);
    }
    return domain;
}

export function chosenPrinterDomain(serialNumber, identifier) {
    return [...localPrinterDomain(serialNumber), ["identifier", "=", identifier]];
}

export class OboxAddLocalPrinter extends Component {
    static template = "obox_pos_mobile.OboxAddLocalPrinter";
    props = useProps(standardWidgetProps);

    setup() {
        super.setup();
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.available = Boolean(mobileNative.chooseDevice || mobileNative.openDeviceManager);
    }

    async addLocalPrinter() {
        if (mobileNative.chooseDevice) {
            return this.chooseLocalPrinter();
        }
        try {
            await mobileNative.openDeviceManager({
                url: browser.location.origin,
                return_when_done: true,
            });
        } catch {
            this.notification.add(_t("Could not open the device manager"), { type: "danger" });
            return;
        }
        await this.selectLocalPrinter();
    }

    async chooseLocalPrinter() {
        let chosen;
        try {
            chosen = await mobileNative.chooseDevice({
                url: browser.location.origin,
                type: "printer",
            });
        } catch {
            this.notification.add(_t("Could not open the device manager"), { type: "danger" });
            return;
        }
        if (!chosen) {
            return;
        }
        const printer = await this.findChosenPrinter(chosen.identifier);
        if (!printer) {
            this.notification.add(
                _t("Odoo does not know this printer yet. Try again in a moment."),
                {
                    type: "warning",
                }
            );
            return;
        }
        await this.props.record.update({
            printer_type: "obox",
            obox_device_id: { id: printer.id, display_name: printer.display_name },
        });
    }

    async findChosenPrinter(identifier) {
        const domain = chosenPrinterDomain(await this.getLocalSerialNumber(), identifier);
        for (let attempt = 0; attempt < SYNC_ATTEMPTS; attempt++) {
            const { records } = await this.orm.webSearchRead("obox.device", domain, {
                specification: { display_name: {} },
                limit: 1,
            });
            if (records.length) {
                return records[0];
            }
            await delay(SYNC_DELAY);
        }
    }

    // Select the last printer that was added to the device manager for the current obox, if any.
    async selectLocalPrinter() {
        const record = this.props.record;
        if (record.data.obox_device_id) {
            return;
        }
        const serialNumber = await this.getLocalSerialNumber();
        const printer = serialNumber && (await this.findLastPrinter(serialNumber));
        if (printer) {
            await record.update({
                printer_type: "obox",
                obox_device_id: { id: printer.id, display_name: printer.display_name },
            });
        }
    }

    async findLastPrinter(serialNumber) {
        const { records } = await this.orm.webSearchRead(
            "obox.device",
            localPrinterDomain(serialNumber),
            { specification: { display_name: {} }, order: "id desc", limit: 1 }
        );
        return records[0];
    }

    async getLocalSerialNumber() {
        if (!mobileNative.getDeviceManagerStatus) {
            return null;
        }
        try {
            return (await mobileNative.getDeviceManagerStatus()).serial;
        } catch {
            return null;
        }
    }
}

registry.category("view_widgets").add("obox_add_local_printer", { component: OboxAddLocalPrinter });
