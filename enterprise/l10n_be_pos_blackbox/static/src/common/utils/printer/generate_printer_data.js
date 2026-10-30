import { patch } from "@web/core/utils/patch";
import { GeneratePrinterData } from "@point_of_sale/app/utils/printer/generate_printer_data";

/**
 * This class is a JS copy of the class PosOrderReceipt in Python.
 */
patch(GeneratePrinterData.prototype, {
    generateReceiptData() {
        const data = super.generateReceiptData(...arguments);
        if (!this.config.l10n_be_blackbox_be_id) {
            return data;
        }

        data.conditions.l10n_be_blackbox_be_id = Boolean(this.config.l10n_be_blackbox_be_id);
        data.conditions.l10n_be_is_pro_forma =
            !this.order.isSigned && !this.order.uiState.isEmptyReceipt;

        data.extra_data.l10n_be_order_type_string = this.order.orderTypeStringBlackbox;
        data.extra_data.establishment_number = this.config.establishment_number;
        if (this.order.refunded_order_id) {
            data.extra_data.refunded_order_id = {
                pos_reference: this.order.refunded_order_id.pos_reference,
                l10n_be_fdm_id: this.order.refunded_order_id.l10n_be_fdm_id,
                l10n_be_pos_id: this.order.refunded_order_id.l10n_be_pos_id,
                l10n_be_terminal_id: this.order.refunded_order_id.l10n_be_terminal_id,
                l10n_be_device_id: this.order.refunded_order_id.l10n_be_device_id,
                l10n_be_fdm_date_time:
                    this.order.refunded_order_id.l10n_be_fdm_date_time?.toFormat(
                        "yyyy-MM-dd HH:mm:ss"
                    ) || false,
                l10n_be_event_label: this.order.refunded_order_id.l10n_be_event_label,
                l10n_be_event_counter: this.order.refunded_order_id.l10n_be_event_counter,
                l10n_be_total_counter: this.order.refunded_order_id.l10n_be_total_counter,
                l10n_be_short_signature: this.order.refunded_order_id.l10n_be_short_signature,
            };
        }
        data.extra_data.fdmSwVersion = this.order.l10n_be_fdm_sw_version;
        data.extra_data.posSwVersion = this.config.posSwVersion;

        data.image.l10n_be_verification_qr = this.generateQrCode(
            this.order.l10n_be_verification_url
        );
        return data;
    },
    generateLineData() {
        const data = super.generateLineData(...arguments);
        if (!this.config.l10n_be_blackbox_be_id) {
            return data;
        }
        for (const index in this.order.lines) {
            const line = this.order.lines[index];
            const lineData = data[index];
            lineData.tax_group_labels = line.taxGroupLabels;
        }
        return data;
    },
});
