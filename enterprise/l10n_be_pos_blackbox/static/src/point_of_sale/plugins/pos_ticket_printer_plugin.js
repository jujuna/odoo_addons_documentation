import { patch } from "@web/core/utils/patch";
import { PosTicketPrinterPlugin } from "@point_of_sale/app/plugins/pos_ticket_printer_plugin";

patch(PosTicketPrinterPlugin.prototype, {
    async printEmptyReceipt({ order }) {
        if (!this.hasReceiptPrinters) {
            return;
        }
        const data = this.getOrderReceiptData(order);
        data.lines = [];
        data.payments = [];
        data.conditions.l10n_be_is_empty_receipt = true;
        const iframe = await this.generateIframe("point_of_sale.pos_order_receipt", data);
        return await this.printWithFallback({ iframe });
    },
});
