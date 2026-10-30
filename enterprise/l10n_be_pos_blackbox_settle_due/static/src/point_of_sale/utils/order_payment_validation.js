import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { patch } from "@web/core/utils/patch";
// Ensure `pos_settle_due` defines `settlingInvoices`/`depositMoney` before we patch them
import "@pos_settle_due/app/utils/order_payment_validation";

// `pos_settle_due` settles invoices and deposits money through a temporary order
// that is validated (payments created on the backend) and then deleted, without
// ever going through the regular `validateOrder` signing path.
// For Blackbox we flag the order as "to sign" so that, once the settlement succeeded and the order is about to
// be deleted, `pos_store._onBeforeDeleteOrder` signs it as a sale.
patch(OrderPaymentValidation.prototype, {
    async settlingInvoices() {
        return this._signSettlementOnSuccess(() => super.settlingInvoices(...arguments));
    },
    async depositMoney() {
        return this._signSettlementOnSuccess(() => super.depositMoney(...arguments));
    },
    async _signSettlementOnSuccess(run) {
        const order = this.order;
        order.uiState.l10n_be_settleToSign = true;
        const res = await run();
        // At this step order is supposed to be already deleted (see 'pos_settle_due' override), but if it's not we clear the flag
        if (order?.uiState) {
            order.uiState.l10n_be_settleToSign = false;
        }
        return res;
    },
});
