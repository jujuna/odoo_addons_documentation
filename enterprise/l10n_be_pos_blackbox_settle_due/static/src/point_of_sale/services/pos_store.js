import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
// Ensure the base blackbox `_onBeforeDeleteOrder` is patched before us so our super call reaches it.
import "@l10n_be_pos_blackbox/point_of_sale/services/pos_store";

patch(PosStore.prototype, {
    async _onBeforeDeleteOrder(order) {
        if (
            this.blackbox.isActive &&
            order.uiState.l10n_be_settleToSign &&
            !order.l10n_be_short_signature
        ) {
            this.l10nBeMoveDepositAmountToSettleLine(order);
            // Sign as sale, put 'isTransferred' to skip cancellation (see override of '_onBeforeDeleteOrder')
            order.uiState.isTransferred = true;
            const usr = this.l10nBeSigningInsz;
            await this.blackbox.signSale.sign(order, usr, this.ticketPrinter.hasReceiptPrinters);
        }
        return super._onBeforeDeleteOrder(...arguments);
    },
    l10nBeMoveDepositAmountToSettleLine(order) {
        // `onClickDepositMoney` create an order with a single settle line
        const [settleLine] = order.lines;
        if (
            !order.uiState.depositMoney ||
            order.lines.length !== 1 ||
            !settleLine.isSettleProductLine() ||
            settleLine.qty !== 1
        ) {
            return;
        }
        const paid = order.payment_ids.reduce((total, payment) => total + payment.amount, 0);
        settleLine.setUnitPrice(paid);
    },
});
