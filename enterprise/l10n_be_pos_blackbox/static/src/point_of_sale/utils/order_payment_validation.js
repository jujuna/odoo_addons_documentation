import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { patch } from "@web/core/utils/patch";
import { ConnectionLostError } from "@web/core/network/rpc";
import { L10nBeBlackboxError } from "@l10n_be_pos_blackbox/common/blackbox/utils/blackbox_error";
import { L10nBeBlackboxConnectionError } from "@l10n_be_pos_blackbox/common/blackbox/utils/blackbox_connection_error";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(OrderPaymentValidation.prototype, {
    async validateOrder() {
        if (!this.pos.blackbox.isActive) {
            return super.validateOrder(...arguments);
        }

        // Stop the process if the blackbox is not reachable, the user
        // shouldn't be able to print ticket or validate orders without
        // blackbox signature.
        const pingResult = await this.pos.blackbox.ping();
        if (pingResult) {
            return super.validateOrder(...arguments);
        }

        this.pos.dialog.add(AlertDialog, {
            title: _t("Network Error"),
            body: _t(
                "With a blackbox, a network error will prevent the order from being signed. Please check your connection and try again."
            ),
        });
        return false;
    },
    async shouldHideValidationBehindFeedbackScreen() {
        if (!this.pos.blackbox.isActive) {
            return super.shouldHideValidationBehindFeedbackScreen(...arguments);
        }

        // For blackbox POS, we first ensure that the order has been properly signed by the FDM before leaving the payment screen
        try {
            this.pos.env.services.ui.block();
            await this.finalizeValidation();
        } finally {
            this.pos.env.services.ui.unblock();
        }

        if (!this.order.finalized) {
            // The order is not finalized (FDM error, ...), we stay on payment screen
            return false;
        }

        const nextPage = this.nextPage;
        this.pos.navigate(nextPage.page, nextPage.params);
    },
    async afterOrderValidation() {
        if (this.order.state == "paid" && !this.order.l10n_be_short_signature) {
            try {
                await this.pos.preSyncAllOrders([this.order]);
            } catch (error) {
                if (error instanceof ConnectionLostError) {
                    this.order.state = "draft";
                    throw error;
                }
            }
        }
        return super.afterOrderValidation();
    },

    get canPrintReceipt() {
        const res = super.canPrintReceipt;
        return this.pos.blackbox.isActive ? res && Boolean(this.order.isSignedOrTraining) : res;
    },

    handleValidationError(error) {
        if (!this.pos.blackbox.isActive) {
            return super.handleValidationError(error);
        }
        try {
            // If it's a blackbox error, no need to retry since it has already been handled
            // If the blackbox is unreachable, a retry will not reach it either
            if (
                error instanceof L10nBeBlackboxError ||
                error instanceof L10nBeBlackboxConnectionError
            ) {
                this.order.state = "draft";
                return error;
            }
            // Otherwise, we will try to sign the order again
            return super.handleValidationError(error);
        } catch (e) {
            // The retry above may itself have failed on the blackbox
            if (e instanceof L10nBeBlackboxError || e instanceof L10nBeBlackboxConnectionError) {
                this.order.state = "draft";
            }
            throw error;
        }
    },
    async finalizeValidation() {
        if (!this.pos.blackbox.isActive) {
            return super.finalizeValidation(...arguments);
        }
        await this.pos.finalizeOrderCorrection(this.order);
        return super.finalizeValidation(...arguments);
    },
});
