import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async l10nItFiskalyVatExemption(vals) {
        const product = this.l10nItFiskalyProduct(vals);
        if (product && product === this.config.down_payment_product_id) {
            return null;
        }
        return super.l10nItFiskalyVatExemption(...arguments);
    },

    l10nItFiskalyAllowsNegativeLine(line) {
        return (
            line.product_id === this.config.down_payment_product_id ||
            super.l10nItFiskalyAllowsNegativeLine(...arguments)
        );
    },
});
