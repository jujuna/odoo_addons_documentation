import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(OrderPaymentValidation.prototype, {
    async isOrderValid(_isForceValidate) {
        if (this.pos.config.l10nItFiskalyActive && !this.pos.l10nItFiskalyCheckOrder(this.order)) {
            return false;
        }
        return super.isOrderValid(...arguments);
    },

    async afterOrderValidation() {
        if (this.pos.config.l10nItFiskalyActive && this.order.isUnsyncedPaid) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Fiskaly SIGN IT"),
                body: _t(
                    "The Point of Sale is offline: this transaction will be transmitted to the" +
                        " Agenzia delle Entrate once the order is synchronized with the server."
                ),
            });
        }
        await super.afterOrderValidation(...arguments);
    },
});
