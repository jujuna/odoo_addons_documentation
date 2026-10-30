import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { InputGenerator } from "@l10n_be_pos_blackbox/common/blackbox/utils/input_generator";

patch(PosOrder.prototype, {
    initState() {
        super.initState(...arguments);
        if (this.config.trackBlackboxCorrections) {
            this.uiState.deletedLines = {};
        }
    },
    get isPartialRefund() {
        if (!this.isRefund) {
            return false;
        }

        const refundLine = this.lines.find((l) => l.refunded_orderline_id?.order_id);
        if (!refundLine) {
            return false;
        }

        const refundedOrder = this.refunded_order_id;
        return refundedOrder && Math.abs(refundedOrder.priceIncl) !== Math.abs(this.priceIncl);
    },
    get isCopyTicket() {
        return this.nb_print > 0;
    },
    get isSigned() {
        return this.l10n_be_short_signature && this.finalized;
    },
    get isSignedOrTraining() {
        return this.isSigned || (this.config.l10n_be_training_mode && this.finalized);
    },
    get orderTypeStringBlackbox() {
        if (this.config.l10n_be_training_mode) {
            return _t("THIS IS NOT A VAT TICKET");
        }
        if (this.isCopyTicket && this.isSigned) {
            return _t("COPY TICKET");
        }
        if (this.isRefund && this.isSigned) {
            return _t("VAT TICKET REFUND");
        }
        if (this.isSigned || this.uiState.isEmptyReceipt) {
            return _t("VAT TICKET");
        }
        return _t("PROVISIONAL BILL");
    },
    get generateTransactionLines() {
        const generator = new InputGenerator({
            models: this.models,
            order: this,
        });
        return generator.generateTransactionLinesInput();
    },
    updateLastTransactionLines() {
        this.l10n_be_last_transaction_by_line = this.generateTransactionLines;
    },
    generateCostCenterInput() {
        const customer = this.partner_id;
        const table = this.table_id;
        const orderUuid = this.uuid;

        const type = this.getCostCenterType(customer, table);

        const id = customer
            ? `${customer.id} ${customer.name}`
            : table?.table_number
            ? table.table_number.toString()
            : this.getName();

        const reference = customer?.vat ? customer.vat.toString() : orderUuid?.toString();

        return { id: id.toString().trim(), type, reference: reference.trim() };
    },
    getCostCenterType(customer, table) {
        if (this.source == "kiosk") {
            return "KIOSK";
        } else if (this.source == "mobile") {
            return "WEBSHOP";
        } else if (customer) {
            return "CUSTOMER";
        } else if (table) {
            return "TABLE";
        } else {
            return "ON_HOLD";
        }
    },
    /* Get the order lines for which we want to generate transaction lines input
     *   - We never want to include global discount lines
     *   _ We don't send line with 0 quantity
     *   - Tip line:
     *      - Included only for refund orders (to refund the tip)
     *      - Excluded for normal orders (as tip is handled as a separate payment line)
     */
    get linesSendableToBlackbox() {
        return this.refunded_order_id
            ? this.lines.filter((line) => !line.isGlobalDiscountLine() && line.qty != 0)
            : this.lines.filter(
                  (line) => !line.isTipLine() && !line.isGlobalDiscountLine() && line.qty != 0
              );
    },
    trackDeletedLinesForBlackbox(line) {
        // Lines that are part of a combo are corrected through their parent line
        return this.config.trackBlackboxCorrections && !line.combo_parent_id;
    },
    wasSignedToBlackbox(line) {
        return Boolean(line?.uuid && this.l10n_be_last_transaction_by_line?.[line.uuid]);
    },
    buildInitialTransactionLine(line) {
        const generator = new InputGenerator({
            models: this.models,
            order: this,
        });
        const initialTransLine = generator.generateTransactionLine(line, {
            qty: line.uiState.maxQuantity || line.qty,
        });
        initialTransLine.lineTotal = generator.computeTransactionLineTotal(initialTransLine);
        return initialTransLine;
    },
    removeOrderline(line) {
        if (!this.trackDeletedLinesForBlackbox(line)) {
            return super.removeOrderline(...arguments);
        }
        // Lines already known by the blackbox are corrected from their last signed state
        this.uiState.deletedLines[line.uuid] = this.wasSignedToBlackbox(line)
            ? null
            : this.buildInitialTransactionLine(line);
        return super.removeOrderline(...arguments);
    },
    resetDeletedLines() {
        this.uiState.deletedLines = {};
    },
});
