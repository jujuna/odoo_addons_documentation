import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    // @Override
    setToInvoice(to_invoice) {
        if (this.company.country_id?.code === "MX" && !this.l10n_mx_edi_usage) {
            super.setToInvoice(false);
        } else {
            super.setToInvoice(to_invoice);
        }
    },
    // @Override
    addPaymentline(payment_method) {
        // Customer account orders are invoiced, use the partner usage
        // so setToInvoice is not blocked by the missing CFDI usage.
        if (
            this.company.country_id?.code === "MX" &&
            payment_method.type === "pay_later" &&
            !this.l10n_mx_edi_usage
        ) {
            this.l10n_mx_edi_usage = this.partner_id?.l10n_mx_edi_usage || "G03";
        }
        return super.addPaymentline(...arguments);
    },
    // @Override
    serializeForORM() {
        const data = super.serializeForORM(...arguments);
        if (this.company.country_id?.code === "MX") {
            data.l10n_mx_edi_cfdi_to_public = this.l10n_mx_edi_cfdi_to_public;
        }
        return data;
    },
});
