import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { L10nBeBlackboxErrorPopup } from "@l10n_be_pos_blackbox/common/blackbox/utils/error_popup/error_popup";
import { serializeDateTime } from "@web/core/l10n/dates";
import { CustomSelectCreateDialog } from "@point_of_sale/app/components/custom_select_create_dialog/custom_select_create_dialog";
import { uuidv4 } from "@point_of_sale/utils";
import { OpeningDeviceErrorPopup } from "@l10n_be_pos_blackbox/point_of_sale/components/popups/opening_device_error_popup/opening_device_error_popup";
import { MustClockInPopup } from "@l10n_be_pos_blackbox/point_of_sale/components/popups/must_clock_in_popup/must_clock_in_popup";
import {
    PosBlackboxBe,
    SELF_ORDERING_INSZ_NUMBER,
    DEVICE_IDENTIFIER_KEY,
} from "@l10n_be_pos_blackbox/common/blackbox/blackbox";
import { deepEqual } from "@web/core/utils/objects";
import { user } from "@web/core/user";
import { Mutex } from "@web/core/utils/concurrency";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

const { DateTime } = luxon;
const CONSOLE_COLOR = "#62da56";
// SPF Finance require a POS session to be closed at least once every 24h
// In order for the Z report to be sent to the FDM.
const L10N_BE_MAX_SESSION_HOURS = 24;
const L10N_BE_SESSION_WARNING_HOURS = 20;
const L10N_BE_SESSION_CHECK_INTERVAL_MS = 5 * 60 * 1000;

patch(PosStore.prototype, {
    async setup(env, deps) {
        this.clockMutex = new Mutex();
        await super.setup(...arguments);
        if (this.blackbox.isActive) {
            this.doingClockIn = false;
            this.l10nBeWarnedHours = new Set();
            this._l10nBeSessionAgeInterval = setInterval(
                () => this.l10nBeWarnIfSessionAging(),
                L10N_BE_SESSION_CHECK_INTERVAL_MS
            );
            this.l10nBeWarnIfSessionAging();
        }
        this.isDeviceAuthorized = await this.ensureBlackboxDeviceLog();
    },
    l10nBeWarnIfSessionAging() {
        if (!this.blackbox.isActive || this.session.state !== "opened" || !this.session.start_at) {
            return;
        }
        const hours = Math.floor(DateTime.now().diff(this.session.start_at, "hours").hours);
        if (hours < L10N_BE_SESSION_WARNING_HOURS || hours >= L10N_BE_MAX_SESSION_HOURS) {
            return;
        }
        if (this.l10nBeWarnedHours.has(hours)) {
            return;
        }
        this.l10nBeWarnedHours.add(hours);
        this.l10nBeShowSessionAgingDialog(hours);
    },
    l10nBeShowSessionAgingDialog(hours) {
        this.dialog.add(AlertDialog, {
            title: _t("Blackbox Session aging"),
            body: _t(
                "This POS session has been open for over %s hours. " +
                    "Belgian fiscal regulations require it to be closed at least once a day. " +
                    "Please close the current session and open a new one to keep selling.",
                hours
            ),
        });
    },
    async afterProcessServerData() {
        this.blackbox = new PosBlackboxBe({
            models: this.models,
            data: this.data,
            dialog: this.dialog,
            notification: this.notification,
            ensureClockedInFunc: this.ensureClockedInPos.bind(this),
            showBlackboxErrorPopupFunc: this.showBlackboxErrorPopupPos.bind(this),
            handleBlackboxSignatureFunc: this.handleBlackboxSignature.bind(this),
            logBlackboxErrorFunc: this.logBlackboxError.bind(this),
        });

        await super.afterProcessServerData(...arguments);
    },
    getDeviceUuid() {
        let device = localStorage.getItem(DEVICE_IDENTIFIER_KEY);
        if (!device) {
            device = uuidv4();
            localStorage.setItem(DEVICE_IDENTIFIER_KEY, device);
        }
        return device;
    },
    async ensureBlackboxDeviceLog() {
        const device = this.getDeviceUuid();
        const result = await this.data.call("pos.blackbox.log.device", "log_device", [
            this.session.config_id.id,
            device,
        ]);
        if (!result) {
            this.dialog.closeAll();
            this.dialog.add(OpeningDeviceErrorPopup);
            return false;
        }
        return true;
    },
    shouldShowOpeningControl() {
        return this.isDeviceAuthorized && super.shouldShowOpeningControl(...arguments);
    },
    get l10nBeSigningInsz() {
        // Fall back to the last cashier's INSZ (useful when the current cashier has been cleared)
        return (
            this.accessRight.loggedCashier?.l10n_be_insz_or_bis_number || this.l10nBeLastCashierInsz
        );
    },
    isCashierClockedIn(cashierId = this.accessRight.loggedCashier?.id) {
        return this.session.l10n_be_users_clocked_ids.map((u) => u.id).includes(cashierId);
    },
    async handleClockInOut(cashier, action = "in") {
        return this.clockMutex.exec(() => this._handleClockInOut(cashier, action));
    },
    async _handleClockInOut(cashier, action = "in") {
        if (this.blackbox.isActive && this.session.state === "opened") {
            let result;
            // Cashier can either be "res.users" or "hr.employee"
            const cashierClocked = this.isCashierClockedIn(cashier.id);

            if (!cashierClocked && action === "in") {
                result = await this.blackbox.signWorkIn.sign(
                    this.models,
                    cashier.l10n_be_insz_or_bis_number
                );
            } else if (cashierClocked && action === "out") {
                result = await this.blackbox.signWorkOut.sign(
                    this.models,
                    cashier.l10n_be_insz_or_bis_number
                );
            }

            if (result) {
                if (!this.config.module_pos_hr) {
                    action === "in"
                        ? (this.session.l10n_be_users_clocked_ids = [cashier])
                        : (this.session.l10n_be_users_clocked_ids = []);
                }
                await this.data.call("pos.session", "set_work_in_out_cashier", [
                    this.session.id,
                    cashier.id,
                    action,
                ]);
            }

            return Boolean(result);
        }

        return true;
    },
    setCashier(cashier) {
        if (this.blackbox?.isActive) {
            this.handleClockInOut(cashier, "in");
        }
        this.l10nBeLastCashierInsz = cashier?.l10n_be_insz_or_bis_number;
        super.setCashier(cashier);
    },
    resetCashier() {
        const cashier = this.accessRight.loggedCashier;
        if (cashier && this.blackbox.isActive) {
            this.handleClockInOut(cashier, "out");
        }
        return super.resetCashier(...arguments);
    },
    get idleTimeout() {
        const timeouts = super.idleTimeout;
        if (!this.blackbox?.isActive) {
            return timeouts;
        }
        // Clock-out the user when SaverScreen is shown
        return timeouts.map((timeout) => ({
            ...timeout,
            action: () => {
                const navigated = timeout.action();
                if (
                    this.router.currentScreen() === "SaverScreen" &&
                    this.accessRight.loggedCashier
                ) {
                    this.resetCashier();
                }
                return navigated;
            },
        }));
    },
    /**
     * @param {Object} [options]
     * @param {boolean} [options.ignoreSessionState=false] clock out the
     *  cashiers even if the session is not opened anymore. Used by the closing
     *  flow, which only signs the FDM events once the session is closed.
     */
    async workOutAllCashiers({ ignoreSessionState = false } = {}) {
        if (this.blackbox.isActive && (ignoreSessionState || this.session.state === "opened")) {
            const clockedOutCashiersInsz = await this.data.call(
                "pos.session",
                "work_out_all_cashiers",
                [this.session.id]
            );
            for (const cashierInsz of clockedOutCashiersInsz) {
                await this.blackbox.signWorkOut.sign(this.models, cashierInsz);
            }
            if (!this.config.module_pos_hr) {
                this.session.l10n_be_users_clocked_ids = [];
            }
        }
    },
    getSyncAllOrdersContext(orders, options = {}) {
        return {
            ...super.getSyncAllOrdersContext(...arguments),
            device_id: this.getDeviceUuid(),
        };
    },
    isL10nBeSessionExpired() {
        const start = this.session.start_at;
        if (!start) {
            return false;
        }
        return DateTime.now().diff(start, "hours").hours >= L10N_BE_MAX_SESSION_HOURS;
    },
    l10nBeWarnIfSessionExpired() {
        if (!this.isL10nBeSessionExpired()) {
            return false;
        }
        const hours = Math.floor(DateTime.now().diff(this.session.start_at, "hours").hours);
        this.dialog.closeAll();
        this.l10nBeShowSessionAgingDialog(hours);
        return true;
    },
    async preSyncAllOrders(orders) {
        if (!this.blackbox.isActive || orders.length === 0 || orders[0].l10n_be_short_signature) {
            return await super.preSyncAllOrders(...arguments);
        }
        this.l10nBeWarnIfSessionExpired();
        const order = orders[0];
        const usr = this.l10nBeSigningInsz;
        const hasReceiptPrinters = this.ticketPrinter.hasReceiptPrinters;

        // Signature that must happen before syncing
        if (order.isPartialRefund) {
            await this.blackbox.signSaleRefundPartial.sign(order, usr, hasReceiptPrinters);
        } else if (order.isRefund) {
            await this.blackbox.signSaleRefund.sign(order, usr, hasReceiptPrinters);
        } else if (order.state === "paid") {
            await this.blackbox.signSale.sign(order, usr, hasReceiptPrinters);
        } else {
            await this.blackbox.signOrder.sign(order, usr);
        }

        // Only sync draft orders & the one that have been paid and signed (or training mode)
        const processedOrder = !order.finalized || order.isSignedOrTraining;

        if (processedOrder) {
            order.resetDeletedLines();
            order.lines.forEach((line) => line.resetMaxValues());
        }

        return processedOrder ? super.preSyncAllOrders([order]) : super.preSyncAllOrders([]);
    },
    async postSyncAllOrders(orders) {
        super.postSyncAllOrders(orders);
        if (
            this.blackbox.isActive &&
            orders.length === 1 &&
            orders[0].isSignedOrTraining &&
            orders[0].to_invoice &&
            !orders[0].l10n_be_I_total_counter
        ) {
            const usr = this.l10nBeSigningInsz;
            // This must be done after syncing because we need the order account move to be created to sign the invoice
            await this.blackbox.signInvoice.sign(orders[0], usr);
        }
    },
    async prepareOrderTransfer(order, destinationTable) {
        if (!this.blackbox.isActive) {
            return await super.prepareOrderTransfer(...arguments);
        }
        const originalTable = order.table_id;
        const oldCostCenter = order.generateCostCenterInput();
        const res = await super.prepareOrderTransfer(...arguments);
        // In this case we are transferring/merging to another table (without order), so no order is created we just change the source order's table_id
        if (!res && destinationTable.rootTable.id !== originalTable?.id) {
            const usr = this.l10nBeSigningInsz;
            const newCostCenter = order.generateCostCenterInput();
            await this.blackbox.signCostCenterChange.signCostCenterChange(
                order,
                oldCostCenter,
                newCostCenter,
                usr
            );
        }
        return res;
    },
    async _mergeLines(orphanLine, destinationLine, destOrder, sourceOrder, mergedCourses) {
        const res = await super._mergeLines(...arguments);
        if (this.blackbox.isActive) {
            this.sourceLinesNextUuidMap[orphanLine.uuid] = res;
        }
        return res;
    },
    async _mergeOrders(sourceOrder, destinationOrder) {
        if (!this.blackbox.isActive || !destinationOrder) {
            return super._mergeOrders(...arguments);
        }
        const usr = this.l10nBeSigningInsz;
        // This is called when a merge/transfer is done to a table with an existing order
        const sourceOrderTransLines = sourceOrder.l10n_be_last_transaction_by_line || {};
        const destOrderTransLines = destinationOrder.l10n_be_last_transaction_by_line || {};
        const signed = await this.blackbox.signCostCenterChange.signCostCenterChange(
            sourceOrder,
            sourceOrder.generateCostCenterInput(),
            destinationOrder.generateCostCenterInput(),
            usr
        );
        // We set this flag to avoid triggering a useless signOrder when it will be deleted (see _onBeforeDeleteOrder)
        sourceOrder.uiState.isTransferred = true;
        // We keep track of the source order lines uuids and the corresponding destination line uuids (after merge)
        this.sourceLinesNextUuidMap = {};
        const srcOrderDiscountPc = sourceOrder.globalDiscountPc.value;
        const destOrderDiscountPcBeforeMerge = destinationOrder.globalDiscountPc.value;
        const res = await super._mergeOrders(...arguments);
        // Transfer groupingId line states from the source order to the destination order
        // for lines that could not be merged (orphan lines that received a fresh UUID on
        // the destination order).  Merged lines already carry the destination UUID, so
        // their entry in l10n_be_grouping_id.lines already exists on destinationOrder and
        // should NOT be overwritten.
        if (sourceOrder.l10n_be_grouping_id) {
            if (!destinationOrder.l10n_be_grouping_id) {
                destinationOrder.l10n_be_grouping_id = {
                    groupingIdCount: 0,
                    globalDiscountGId: null,
                    roundingAdaptationGId: null,
                    lines: {},
                };
            }
            const srcGroupingState = sourceOrder.l10n_be_grouping_id;
            const destGroupingState = destinationOrder.l10n_be_grouping_id;
            const srcLines = srcGroupingState.lines || {};
            for (const [oldUuid, newUuid] of Object.entries(this.sourceLinesNextUuidMap)) {
                // Only copy if the destination does not already know about this UUID
                // (i.e. the line was transferred as-is, not merged into an existing line)
                if (srcLines[oldUuid] && !destGroupingState.lines[newUuid]) {
                    destGroupingState.lines[newUuid] = { ...srcLines[oldUuid] };
                }
            }
            // Ensure the destination counter is at least as high as the source counter
            // so that IDs allocated on the source order are never recycled.
            destGroupingState.groupingIdCount = Math.max(
                destGroupingState.groupingIdCount,
                srcGroupingState.groupingIdCount
            );
        }
        if (signed) {
            // If the destination have a global discount, we apply it before the next signOrder (that will be triggered inside `syncAllOrders`, see 'mergeOrders' inside 'pos_restaurant')
            const destOrderDiscountPc = destinationOrder.globalDiscountPc.value;
            if (destOrderDiscountPc) {
                await this.applyDiscount(
                    destOrderDiscountPc,
                    destinationOrder.globalDiscountPc.type || "percent",
                    destinationOrder
                );
            }
            // If the GD is different of both order is different, we have to make a 'PRICE_CHANGE' correction (cancel old GD, apply new one)
            if (destOrderDiscountPcBeforeMerge != srcOrderDiscountPc) {
                if (srcOrderDiscountPc === destOrderDiscountPc) {
                    // If the applied discount of the merged order is the same as the source order, we need to correct old destination order lines
                    await this.blackbox.signOrder.signGlobalDiscountChange(
                        destinationOrder,
                        destOrderTransLines,
                        false,
                        usr
                    );
                } else if (destOrderDiscountPcBeforeMerge === destOrderDiscountPc) {
                    // If the applied discount of the merged order is the same as the destination order, we need to correct source order lines
                    await this.blackbox.signOrder.signGlobalDiscountChange(
                        destinationOrder,
                        sourceOrderTransLines,
                        this.sourceLinesNextUuidMap,
                        usr
                    );
                }
            }
            // Update the last transaction by line of the orders
            sourceOrder.l10n_be_last_transaction_by_line = {};
            destinationOrder.updateLastTransactionLines();
        }
        return res;
    },
    async transferOrder(orderUuid, destinationTable, destinationOrder) {
        if (!this.blackbox.isActive) {
            return super.transferOrder(...arguments);
        }
        const sourceOrder = this.models["pos.order"].getBy("uuid", orderUuid);
        const usr = this.l10nBeSigningInsz;
        // Before transferring orders, we push the potential changes of the source order to the blackbox
        await this.blackbox.signOrder.sign(sourceOrder, usr);
        return super.transferOrder(...arguments);
    },
    async mergeTableOrders(orderUuid, destinationTable) {
        if (!this.blackbox.isActive) {
            return super.mergeTableOrders(...arguments);
        }
        const sourceOrder = this.models["pos.order"].getBy("uuid", orderUuid);
        const usr = this.l10nBeSigningInsz;
        // Before merging orders, we push the potential changes of the source order to the blackbox
        await this.blackbox.signOrder.sign(sourceOrder, usr);
        return super.mergeTableOrders(...arguments);
    },
    async _onBeforeDeleteOrder(order) {
        const result = await super._onBeforeDeleteOrder(...arguments);
        // Nothing to register if the FDM never received this order and it has no line left
        const hasBlackboxContent =
            order.lines.length ||
            Object.keys(order.uiState.deletedLines || {}).length ||
            Object.keys(order.l10n_be_last_transaction_by_line || {}).length;
        if (
            this.blackbox.isActive &&
            hasBlackboxContent &&
            !order.uiState.isTransferred &&
            !order.uiState.isDeleteInProgress
        ) {
            // Flag to avoid duplicate blackbox call if we try to quickly delete the order multiple times from ticket screen
            order.uiState.isDeleteInProgress = true;
            try {
                const usr = this.l10nBeSigningInsz;
                const correctionSigned = await this.finalizeOrderCorrection(order);
                const cancellationSigned = await this.blackbox.signOrder.signCanceledOrder(
                    order,
                    usr
                );
                // ORDER events sent to the FDM must be closed with an empty sale
                // -> we only do it if the order has already been sent to the FDM
                if (order.l10n_be_has_order_event || correctionSigned || cancellationSigned) {
                    await this.blackbox.signSale.signEmptyOrder(
                        order,
                        usr,
                        this.ticketPrinter.hasReceiptPrinters
                    );
                    order.uiState.isEmptyReceipt = true;
                    this.ticketPrinter.printEmptyReceipt({ order });
                }
            } finally {
                order.uiState.isDeleteInProgress = false;
            }
        }
        return result;
    },
    async finalizeOrderCorrection(order) {
        const correction = {};
        for (const line of order.lines) {
            if (line.combo_parent_id) {
                continue;
            }
            // Lines with a zero quantity are kept on the order but are excluded from
            // 'linesSendableToBlackbox': if the blackbox never got them, they have to be declared
            // then corrected, exactly like a deleted line (see 'blackboxTransLineBeforeZeroQty').
            if (line.qty === 0 && line.uiState.initialTransLine) {
                correction[line.uuid] = {
                    initialTransLine: line.uiState.initialTransLine,
                };
                continue;
            }
            if (line.haveQuantityCorrection || line.haveMaxUnitPriceCorrection) {
                correction[line.uuid] = {
                    qty: line.uiState.maxQuantity || line.qty,
                    priceUnit: line.uiState.maxUnitPrice || line.blackboxPriceUnitNoDiscount,
                    discount: line.discount,
                    globalDiscount: line.order_id.globalDiscountPc.value,
                    globalDiscountType: line.order_id.globalDiscountPc.type || "percent",
                    line: line,
                };
            }
        }
        // Lines that have been totally removed from the order
        if (Object.keys(order.uiState.deletedLines).length) {
            for (const [lineUuid, initialTransLine] of Object.entries(order.uiState.deletedLines)) {
                correction[lineUuid] = {
                    initialTransLine,
                };
            }
        }
        let signed;
        if (Object.keys(correction).length) {
            signed = await this.blackbox.signOrder.signOrderWithCorrection(
                order,
                correction,
                this.l10nBeSigningInsz
            );
        }
        order.resetDeletedLines();
        order.lines.forEach((line) => line.resetMaxValues());
        return signed;
    },
    async signTurnoverReport(sessionId = this.session.id, state = this.session.state) {
        const saleDetails = await this.data.call(
            "report.point_of_sale.report_saledetails",
            "get_sale_details",
            [false, false, false, [sessionId]]
        );
        if (state === "closed") {
            if (saleDetails.l10n_be_turnover_z_report_fdm_ref) {
                this.blackbox.signCopy.signReportWithDelay(
                    this.models,
                    saleDetails.l10n_be_turnover_z_report_fdm_ref,
                    this.l10nBeSigningInsz
                );
            } else {
                this.blackbox.signReportTurnoverZ.signWithDelay(
                    this.models,
                    saleDetails,
                    sessionId,
                    this.l10nBeSigningInsz
                );
            }
        } else {
            this.blackbox.signReportTurnoverX.signWithDelay(
                this.models,
                saleDetails,
                this.l10nBeSigningInsz
            );
        }
    },
    async signUserReport(sessionId = this.session.id, state = this.session.state) {
        const userReportData = await this.data.call("pos.session", "get_l10n_be_user_report_data", [
            sessionId,
        ]);
        if (state === "closed") {
            if (userReportData.l10n_be_user_z_report_fdm_ref) {
                this.blackbox.signCopy.signReportWithDelay(
                    this.models,
                    userReportData.l10n_be_user_z_report_fdm_ref,
                    this.l10nBeSigningInsz
                );
            } else {
                this.blackbox.signReportUserZ.signWithDelay(
                    this.models,
                    userReportData,
                    sessionId,
                    this.l10nBeSigningInsz
                );
            }
        } else {
            this.blackbox.signReportUserX.signWithDelay(
                this.models,
                userReportData,
                this.l10nBeSigningInsz
            );
        }
    },
    async signExternalOrder(order, insz = false) {
        const usr = insz || this.l10nBeSigningInsz;
        await this.blackbox.signSale.sign(order, usr, this.ticketPrinter.hasReceiptPrinters);
        if (order.l10n_be_short_signature) {
            this.data.write("pos.order", [order.id], {
                l10n_be_short_signature: order.l10n_be_short_signature,
                l10n_be_event_label: order.l10n_be_event_label,
                l10n_be_event_counter: order.l10n_be_event_counter,
                l10n_be_total_counter: order.l10n_be_total_counter,
                l10n_be_fdm_id: order.l10n_be_fdm_id,
                l10n_be_fdm_date_time: serializeDateTime(order.l10n_be_fdm_date_time),
                l10n_be_pos_id: order.l10n_be_pos_id,
                l10n_be_terminal_id: order.l10n_be_terminal_id,
                l10n_be_device_id: order.l10n_be_device_id,
                l10n_be_fdm_sw_version: order.l10n_be_fdm_sw_version,
                l10n_be_verification_url: order.l10n_be_verification_url,
                l10n_be_pos_date_time: serializeDateTime(order.l10n_be_pos_date_time),
                l10n_be_vat_calc: order.l10n_be_vat_calc,
                l10n_be_footer: order.l10n_be_footer,
            });
        }
        return order;
    },
    async pay() {
        if (this.blackbox.isActive) {
            const cashier = this.accessRight.loggedCashier;
            if (!this.isCashierClockedIn(cashier.id)) {
                this.dialog.closeAll();
                await this.dialog.add(MustClockInPopup);
                return;
            }
            const order = this.getOrder();
            const identifier = cashier.l10n_be_insz_or_bis_number;
            // We only 'signOrder' if the order has already be sent to the blackbox, otherwise it's a direct sale (no need to signOrder before the signSale)
            if (order.l10n_be_last_transaction_by_line) {
                await this.blackbox.signOrder.sign(order, identifier);
            }
        }
        return super.pay(...arguments);
    },
    async openCashboxManually() {
        if (this.blackbox.isActive) {
            this.blackbox.signDrawerOpen.sign(this.models, this.l10nBeSigningInsz);
        }
        return super.openCashboxManually(...arguments);
    },
    async selectPartner(currentOrder = this.getOrder()) {
        if (currentOrder && this.blackbox.isActive) {
            const usr = this.l10nBeSigningInsz;
            // We signOrder before changing its partner because we will costCenterChange afterwards (see setPartnerToCurrentOrder)
            this.blackbox.signOrder.sign(currentOrder, usr);
        }
        return super.selectPartner(...arguments);
    },
    setPartnerToCurrentOrder(partner) {
        const order = this.getOrder();
        if (!this.blackbox.isActive || !order) {
            return super.setPartnerToCurrentOrder(...arguments);
        }
        const oldCostCenter = order.generateCostCenterInput();
        const result = super.setPartnerToCurrentOrder(...arguments);
        const newCostCenter = order.generateCostCenterInput();

        if (!deepEqual(oldCostCenter, newCostCenter) && order.l10n_be_last_transaction_by_line) {
            const identifier = this.l10nBeSigningInsz;
            this.blackbox.signCostCenterChange.signCostCenterChange(
                order,
                oldCostCenter,
                newCostCenter,
                identifier
            );
        }
        return result;
    },
    // Handles the blackbox signing required before printing/reprinting an order.
    async beforePrintBlackboxOrder(
        order,
        hasReceiptPrinters = this.ticketPrinter.hasReceiptPrinters
    ) {
        if (this.blackbox.isActive && order.finalized) {
            const usr = this.l10nBeSigningInsz;
            // If the order was already printed
            if (order.nb_print > 0 && order.l10n_be_short_signature) {
                await this.blackbox.signCopy.sign(order, usr, hasReceiptPrinters);
            } else if (order.nb_print === 0 && !order.l10n_be_short_signature) {
                await this.signExternalOrder(order);
            }
        }
    },
    async getSelfOrderToSign(orderId, insz = SELF_ORDERING_INSZ_NUMBER) {
        const result = await this.data.callRelated("pos.order", "get_order_to_sign", [orderId]);
        let order = result["pos.order"][0];
        try {
            order = await this.signExternalOrder(order, insz);
        } catch (error) {
            this.data.silentCall("pos.order", "release_order_to_sign", [orderId]);
            throw error;
        }
        return order;
    },
    async ensureClockedInPos(name, insz) {
        // Find the cashier by the INSZ that is performing the mutation.
        // Falling back to accessRight.loggedCashier handles the edge case where insz is not available.
        const model = this.config.module_pos_hr ? "hr.employee" : "res.users";

        const cashierByInsz = insz
            ? this.models[model].find((c) => c.l10n_be_insz_or_bis_number === insz)
            : null;
        // Falling back to accessRight.loggedCashier handles the edge case where insz is not available.
        const cashier = cashierByInsz || this.accessRight.loggedCashier;
        // Mobile self-order can be signed without cashier
        if (!cashier) {
            return;
        }
        // We'll automatically clock-in the cashier if:
        // - the initial mutation is not already a 'signWorkIn'
        // - we're not already doing it (recursively)
        // - the cashier is not clocked-in yet
        if (
            !["signWorkIn", "signWorkOut"].includes(name) &&
            !this.doingClockIn &&
            !this.isCashierClockedIn(cashier.id)
        ) {
            try {
                logPosMessage(
                    "Blackbox",
                    "ensureClockedIn",
                    `${cashier.name} was not clocked in. Attempting to clock in.`,
                    CONSOLE_COLOR
                );
                this.doingClockIn = true;
                await this.handleClockInOut(cashier, "in");
            } finally {
                this.doingClockIn = false;
            }
        }
    },
    async showBlackboxErrorPopupPos(error, data, name) {
        this.dialog.closeAll();
        this.dialog.add(L10nBeBlackboxErrorPopup, {
            errors: error.errors || [],
            data: data,
            mutationName: name,
        });
    },
    async handleBlackboxSignature(payload) {
        const sessionId = this.session.id;
        await this.data.call("pos.session", "handle_blackbox_signature", [sessionId, payload]);
    },
    async logBlackboxError(log) {
        await this.data.call("pos.session", "log_blackbox_error", [this.session.id, log]);
    },
    openSalesReportsList(reportService, sessionId = false) {
        const domain = [
            ["config_id", "=", this.config.id],
            ["pos_clock_in_out_ids", "!=", false],
        ];
        const callback = async (resIds) => {
            const sessionId = resIds[0];
            user.updateContext({ called_from_pos: true });
            let res;
            try {
                res = await reportService.doAction("point_of_sale.sale_details_report", [
                    sessionId,
                ]);
            } finally {
                user.updateContext({ called_from_pos: false });
            }
            if (res?.success) {
                const [session] = await this.data.orm.read("pos.session", [sessionId], ["state"]);
                this.signTurnoverReport(
                    sessionId,
                    session.state === "closed" ? "closed" : "opened"
                );
            }
        };
        if (sessionId) {
            callback([sessionId]);
        } else {
            this.dialog.add(CustomSelectCreateDialog, {
                title: _t("Select a session to print the sales report"),
                resModel: "pos.session",
                listViewId: this.models["ir.ui.view"].find(
                    (v) => v.name == "pos_session_reports_list_view"
                )?.id,
                noCreate: true,
                multiSelect: false,
                domain,
                context: {},
                onSelected: callback.bind(this),
            });
        }
    },
});
