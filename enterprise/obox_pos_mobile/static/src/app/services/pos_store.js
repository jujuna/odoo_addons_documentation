import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { mobileNative } from "@pos_mobile_android/app/utils/native";

patch(PosStore.prototype, {
    async afterProcessServerData() {
        const result = await super.afterProcessServerData(...arguments);
        this.watchReceiptPrinter();
        return result;
    },

    watchReceiptPrinter() {
        if (!mobileNative.watchReceiptPrinter) {
            return;
        }
        document.addEventListener("receiptprinteradded", () => {
            browser.localStorage.removeItem(this.ticketPrinter.printerStorageKey);
            browser.location.reload();
        });
        mobileNative
            .watchReceiptPrinter({
                url: browser.location.origin,
                config_id: String(this.config.id),
                config_name: this.config.name,
                manager: this.user._role === "manager",
                linked_printers: this.ticketPrinter.printers
                    .filter((printer) => printer.printer_type === "obox")
                    .map((printer) => (printer.printer_ip || "").split("/").pop())
                    .join(","),
            })
            .catch(console.warn);
    },
});
