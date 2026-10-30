import { registry } from "@web/core/registry";
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { L10nBeBlackboxWarning } from "@l10n_be_pos_blackbox/common/blackbox/utils/blackbox_warning";
import { L10nBeBlackboxError } from "@l10n_be_pos_blackbox/common/blackbox/utils/blackbox_error";
import { L10nBeBlackboxConnectionError } from "@l10n_be_pos_blackbox/common/blackbox/utils/blackbox_connection_error";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError } from "@web/core/network/rpc";
import { LocalStorageQueue } from "./utils/localstorage_queue";
import { InspectPopup } from "@l10n_be_pos_blackbox/common/components/popups/inspect_popup/inspect_popup";
import { roundCurrency } from "@point_of_sale/app/models/utils/currency";
import { getLNATargetAddressSpace } from "@point_of_sale/app/utils/init_lna";

const { DateTime } = luxon;
const CONSOLE_COLOR = "#62da56";
const BLACKBOX_SIGNATURE_QUEUE_KEY = "l10n_be_blackbox_signature_queue";
const FDM_REQUEST_TIMEOUT = 5000;
export const SELF_ORDERING_INSZ_NUMBER = "00000000029";
export const DEVICE_IDENTIFIER_KEY = "l10n_be_pos_blackbox-device-id-identifier";

export class PosBlackboxBe {
    constructor() {
        this.setup(...arguments);
    }

    async setup({
        models,
        data,
        dialog,
        notification,
        ensureClockedInFunc,
        showBlackboxErrorPopupFunc,
        handleBlackboxSignatureFunc,
        logBlackboxErrorFunc,
    }) {
        this.models = models;
        this.data = data;
        this.dialog = dialog;
        this.notification = notification;
        this.signatureQueue = new LocalStorageQueue(BLACKBOX_SIGNATURE_QUEUE_KEY);

        // Queues arn't stored in the local storage because in case of error
        // the PoS will retry the request/signature and we don't want to keep
        // retrying indefinitely if the error is not transient (ex: syntax error or invalid input)
        this.requestQueue = [];

        // These functions given as parameter, because it's handled differently
        // when using `PosBlackboxBe` class in POS or in Kiosk
        this.ensureClockedInFunc = ensureClockedInFunc;
        this.showBlackboxErrorPopupFunc = showBlackboxErrorPopupFunc;
        this.handleBlackboxSignatureFunc = handleBlackboxSignatureFunc;
        // Not given in Kiosk: errors are only logged from the POS
        this.logBlackboxErrorFunc = logBlackboxErrorFunc;

        for (const Mutation of registry.category("l10n_be_pos_blackbox.mutations").getAll()) {
            this[Mutation.name] = new Mutation(this);
        }

        window.addEventListener("pos-network-online", this.processSignatureQueue.bind(this));
    }

    get session() {
        return (
            this.models["pos.session"].get(odoo.pos_session_id) ||
            this.models["pos.session"].getFirst()
        );
    }

    get config() {
        return this.session?.config_id || this.models["pos.config"].getFirst();
    }

    get blackbox() {
        return this.config.l10n_be_blackbox_be_id;
    }

    get isActive() {
        return Boolean(this.config.l10n_be_blackbox_be_id);
    }

    get fdmProtocol() {
        return this.blackbox?.use_lna ? "http:" : window.location.protocol;
    }

    get fdmUrl() {
        return `${this.fdmProtocol}//${this.blackbox?.local_ip}/graphql`;
    }

    processSignatureQueue() {
        // Chained so signatures reach the server in the order they were signed
        this.signatureFlush = (this.signatureFlush || Promise.resolve()).then(() =>
            this._sendSignatureQueue()
        );
        return this.signatureFlush;
    }

    async _sendSignatureQueue() {
        const payload = this.signatureQueue.purge();
        if (!payload.length) {
            return true;
        }

        try {
            await this.handleBlackboxSignatureFunc(payload);
            return true;
        } catch (error) {
            // Only network errors are retried, a rejected payload would block the next ones.
            // It is kept in the blackbox logs (request_data) to be recovered if needed.
            if (error instanceof ConnectionLostError) {
                // Put back in front of signatures queued meanwhile to keep the order
                this.signatureQueue.push(...payload, ...this.signatureQueue.purge());
            } else {
                this.logError(error, { formatted: payload }, "handle_blackbox_signature");
            }
            return false;
        }
    }

    /**
     * @param {*} order - The order object to process.
     * @param {*} signature - The signature object returned by the FDM.
     * @description
     * This method processes the order with the signature received from the FDM.
     * It updates the order with the event label, event counter, total counter,
     * short signature, FDM ID, and FDM date time.
     */
    async processOrderWithSignature(order, signature) {
        if (!order) {
            // Since we queue the request, the order may not be available
            logPosMessage(
                "Blackbox",
                "processOrderWithSignature",
                "No order found to process with signature.",
                CONSOLE_COLOR
            );
            return;
        }
        if (signature.eventOperation === "ORDER") {
            order.l10n_be_last_transaction_by_line = order.uiState.transactionLinesMap;
            order.l10n_be_has_order_event = true;
        } else if (signature.eventOperation === "COPY") {
            order.l10n_be_copy_event_data = {
                l10n_be_fdm_id: signature.fdmRef.fdmId,
                l10n_be_fdm_date_time: DateTime.fromISO(signature.fdmRef.fdmDateTime).toFormat(
                    "yyyy-MM-dd HH:mm:ss"
                ),
                l10n_be_event_label: signature.fdmRef.eventLabel,
                l10n_be_event_counter: signature.fdmRef.eventCounter,
                l10n_be_total_counter: signature.fdmRef.totalCounter,
            };
            return;
        } else if (signature.eventOperation === "PRE_BILL") {
            order.l10n_be_pre_bill_event_data = {
                l10n_be_fdm_id: signature.fdmRef.fdmId,
                l10n_be_fdm_date_time: DateTime.fromISO(signature.fdmRef.fdmDateTime).toFormat(
                    "yyyy-MM-dd HH:mm:ss"
                ),
                l10n_be_event_label: signature.fdmRef.eventLabel,
                l10n_be_event_counter: signature.fdmRef.eventCounter,
                l10n_be_total_counter: signature.fdmRef.totalCounter,
            };
            return;
        } else if (signature.eventOperation === "INVOICE") {
            return await this.setFdmRefEventI(order, signature);
        } else if (signature.eventOperation === "SALE") {
            order.l10n_be_vat_calc = signature.vatCalc;
            order.l10n_be_event_label = signature.fdmRef.eventLabel;
            order.l10n_be_event_counter = signature.fdmRef.eventCounter;
            order.l10n_be_total_counter = signature.fdmRef.totalCounter;
            order.l10n_be_fdm_id = signature.fdmRef.fdmId;
            order.l10n_be_fdm_date_time = DateTime.fromISO(signature.fdmRef.fdmDateTime);
            order.l10n_be_pos_id = signature.posId;
            order.l10n_be_terminal_id = signature.terminalId;
            order.l10n_be_device_id = signature.deviceId;
            order.l10n_be_fdm_sw_version = signature.fdmSwVersion;
            order.l10n_be_pos_date_time = DateTime.fromISO(signature.posDateTime);
            order.l10n_be_verification_url = signature.verificationUrl;
            order.l10n_be_footer = signature.footer;
        }

        if (!this.config.l10n_be_training_mode && signature.shortSignature) {
            order.l10n_be_short_signature = signature.shortSignature;
        }
    }

    async setFdmRefEventI(order, signature) {
        this.data.write("pos.order", [order.id], {
            l10n_be_I_event_label: signature.fdmRef.eventLabel,
            l10n_be_I_event_counter: signature.fdmRef.eventCounter,
            l10n_be_I_total_counter: signature.fdmRef.totalCounter,
            l10n_be_I_fdm_id: signature.fdmRef.fdmId,
            l10n_be_I_fdm_date_time: DateTime.fromISO(signature.fdmRef.fdmDateTime).toFormat(
                "yyyy-LL-dd HH:mm:ss"
            ),
        });
    }

    /**
     * @param {Array} data Formatted data.
     * @param {string} mutation - The GraphQL mutation to execute.
     * @param {string} code - The code for the mutation operation.
     * @param {string} name - The name of the field to extract from the response.
     *
     * @description
     * This method sends a request to the FDM to sign the provided data.
     * Every request that does not need to be awaited should use this method.
     * The returned promise resolves once the queue has been processed, so
     * callers that must not go on before the FDM answered (eg. the kiosk,
     * which is reloaded as soon as the session is closed) can await it.
     */
    async signWithDelay(data, mutation, code, name, opts = {}) {
        logPosMessage(
            "Blackbox",
            name,
            `Queueing ${data.length} object(s) for signing`,
            CONSOLE_COLOR
        );

        const rawData = { formatted: data.formatted, sessionId: data.sessionId, order: data.order };
        this.requestQueue.push({ data: rawData, mutation, code, name, opts });
        return this.processRequestQueue();
    }

    /**
     * Process the queue of requests to the FDM.
     * This method will process each item in the queue and send the request to the FDM.
     * If a request fails, it will be kept in the queue for later processing.
     */
    async processRequestQueue() {
        if (this.processingQueue) {
            await new Promise((resolve) => setTimeout(resolve, 2000));
            return this.processRequestQueue();
        }
        try {
            this.processingQueue = true;
            const errors = [];
            const batch = [...this.requestQueue];
            this.requestQueue = [];

            for (const item of batch) {
                const { data, mutation, code, name, opts } = item;
                try {
                    await this.sign(data, mutation, code, name, { ...opts, throwError: true });
                } catch (error) {
                    if (this.shouldRetryMutation(error)) {
                        errors.push(item);
                    }
                }
            }
            if (errors.length) {
                this.requestQueue.push(...errors);
            }
        } finally {
            this.processingQueue = false;
        }
    }

    shouldRetryMutation(error) {
        if (error instanceof L10nBeBlackboxError) {
            // Retry only generic blackbox errors
            // Hard failures like invalid input or syntax errors are not recoverable (will never succeed).
            const isHardFailure = error.invalidInputError || error.isSyntaxError;

            if (isHardFailure) {
                logPosMessage(
                    "Blackbox",
                    "shouldRetryMutation",
                    `Not retrying: ${error.invalidInputError ? "invalid input" : "syntax"} error`,
                    CONSOLE_COLOR,
                    [error]
                );
                return false;
            }

            return true;
        }

        logPosMessage(
            "Blackbox",
            "shouldRetryMutation",
            "Unknown error type, not retrying",
            CONSOLE_COLOR,
            [error]
        );
        return false;
    }

    /**
     * @returns {Promise<boolean>}
     * @description
     * Check the connection to the FDM by sending it a ping. When the
     * user no longer has an internet connection and can no longer reach
     * the Odoo server, the FDM may still be reachable.
     */
    async ping() {
        try {
            await this._sendRequest({}, "{ status{ device { fdmId } } }", false);
            return true;
        } catch (error) {
            this.logError(error, {}, "ping");
            return false;
        }
    }

    /**
     * @param {Array} data Formatted data.
     * @param {string} mutation - The GraphQL mutation to execute.
     * @param {string} code - The code for the mutation operation.
     * @param {string} name - The name of the field to extract from the response.
     * @returns {Promise<Array | Boolean>} - Returns a promise that resolves to an array of processed
     *
     * @description
     * This method sends a request to the FDM to sign the provided data.
     * Every request that needs to be awaited should use this method.
     */
    async sign(
        data,
        mutation,
        code,
        name,
        { responseName = name, throwError = false, shouldBeClocked = true } = {}
    ) {
        if (!data) {
            return false;
        }

        logPosMessage("Blackbox", name, `Start processing ${data.length} object(s)`, CONSOLE_COLOR);
        try {
            if (shouldBeClocked) {
                await this.ensureClockedInFunc(name, data.formatted?.employeeId);
            }

            const result = await this._sendRequest(data.formatted, mutation, code);
            const signature = result.data?.[responseName];

            if (location.search && location.search.includes("debug_blackbox")) {
                this.dialog.add(InspectPopup, {
                    request: data.formatted,
                    response: result.data,
                });
            }

            return this._processBlackboxSignature(signature, data, name, responseName);
        } catch (error) {
            this.logError(error, data, name);
            if (data.order && !data.order.l10n_be_short_signature) {
                data.order.state = "draft";
            }
            if (error instanceof L10nBeBlackboxConnectionError) {
                this.dialog.closeAll();
                this.dialog.add(AlertDialog, {
                    title: _t("FDM Connection Error"),
                    body: _t(
                        "Unable to contact the Fiscal Data Module. Please check the connection.\n%s",
                        error.message
                    ),
                });
                return;
            }
            if (error instanceof L10nBeBlackboxError) {
                this.showBlackboxErrorPopupFunc(error, data, name);
            }
            logPosMessage(
                "Blackbox: ",
                name,
                ` mutation returned an error. Data: ${JSON.stringify(data.formatted, null, 2)}`,
                CONSOLE_COLOR
            );
            if (throwError) {
                throw error;
            }
            return false;
        }
    }

    /**
     * Log an FDM error to the backend (as an `ir.logging` entry) since it's
     * otherwise only visible in the browser. Never throws: logging failures
     * are swallowed so they don't disrupt the POS.
     */
    async logError(error, data, mutation) {
        if (!this.logBlackboxErrorFunc) {
            return;
        }
        try {
            await this.logBlackboxErrorFunc({
                mutation: mutation,
                device: localStorage.getItem(DEVICE_IDENTIFIER_KEY),
                order_uuid: data?.order?.uuid,
                request_data: data?.formatted,
                ...this.getErrorLogValues(error),
            });
        } catch (e) {
            logPosMessage(
                "Blackbox",
                "logError",
                "The FDM error could not be logged in the backend",
                CONSOLE_COLOR,
                [e]
            );
        }
    }

    /**
     * Extract the type, code and message of an error, whatever its origin.
     */
    getErrorLogValues(error) {
        if (error instanceof L10nBeBlackboxError) {
            const details = error.errors?.[0]?.details || {};
            let errorType = "fdm";
            if (error.isSyntaxError) {
                errorType = "syntax";
            } else if (error.invalidInputError) {
                errorType = "invalid_input";
            }
            return {
                error_type: errorType,
                error_code: details.code,
                error_category: details.category,
                message: error.getMessage().toString(),
                error_data: error.errors,
            };
        }
        if (error instanceof L10nBeBlackboxConnectionError) {
            return {
                error_type: "connection",
                error_code: "CONNECTION_ERROR",
                message: error.message,
                error_data: {
                    ip: this.blackbox?.local_ip,
                    use_lna: this.blackbox?.use_lna,
                    url: this.fdmUrl,
                    page_protocol: window.location.protocol,
                    online: navigator.onLine,
                    user_agent: navigator.userAgent,
                },
            };
        }
        return {
            error_type: "unknown",
            error_code: error?.name,
            message: error?.message || String(error),
            error_data: { name: error?.name, message: error?.message, stack: error?.stack },
        };
    }

    /**
     * Processes the blackbox signature received, handling warnings,
     * updating orders and session data, and managing event counters as needed.
     *
     * @param {Object} signature - The signature object returned by the blackbox, possibly containing warnings and FDM reference data.
     * @param {Object} data - The data object related to the blackbox operation, including order, sessionId, and formatted transaction details.
     * @param {string} name - The name of the operation or request being processed.
     * @param {string} responseName - The name of the response, used to determine specific processing logic (e.g., "signReportTurnoverZ").
     * @returns {Object} The original data object, after processing.
     */
    async _processBlackboxSignature(signature, data, name, responseName) {
        if (!signature) {
            return data;
        }

        if (signature.warnings) {
            signature.warnings.forEach((warning) => {
                new L10nBeBlackboxWarning(warning, { notification: this.notification });
            });
        }

        // Some request (like work-in/out) are not linked to an order,
        // so we don't need to process the signature
        const order = data.order;
        if (order) {
            this.processOrderWithSignature(data.order, signature);
        }

        // Some fields must be updated in the backend like event counters
        // or fdm references for reports
        const isInvoice = signature.fdmRef?.eventLabel === "I";
        const transactionTotal = data.formatted.transaction?.transactionTotal || 0;
        const amount =
            isInvoice && order ? roundCurrency(order.priceIncl, order.currency) : transactionTotal;
        const payload = {
            signature: signature,
            amount: amount,
            isSelfSession: data.sessionId ? data.sessionId == this.session.id : true,
            sessionId: data.sessionId,
            data: data.formatted,
        };

        // The FDM signature is final, the server only records counters and references:
        // send it in background so the UI never waits on the network.
        this.signatureQueue.push(payload);
        this.processSignatureQueue();

        logPosMessage("Blackbox", name, `End processing successfully`, CONSOLE_COLOR);
        return data;
    }

    /**
     * Send a GraphQL request to the FDM.
     * @param {object} data - The variables of the query.
     * @param {string} mutation - The GraphQL query.
     * @param {string} operation - The GraphQL operation name.
     * @returns {Promise<object>} - The response from the FDM.
     * @throws {L10nBeBlackboxConnectionError} If the FDM could not be reached.
     * @throws {L10nBeBlackboxError} If the FDM answered with errors.
     */
    async _sendRequest(data, mutation, operation = "") {
        const variables = { data, training: this.config.l10n_be_training_mode };
        const payload = { query: mutation, variables, operationName: operation };
        if (!operation) {
            delete payload.operationName;
        }

        const url = new URL(this.fdmUrl).href;
        const body = JSON.stringify(payload);

        let response;
        try {
            response = await fetch(url, {
                method: "POST",
                signal: AbortSignal.timeout(FDM_REQUEST_TIMEOUT),
                targetAddressSpace: this.blackbox?.use_lna
                    ? getLNATargetAddressSpace(url)
                    : undefined,
                headers: {
                    "Content-Type": "application/json",
                },

                body,
            });
        } catch (error) {
            // `fetch` resolves even on a 4xx/5xx: it only rejects when the request never completed
            // -> So any rejection here is a connection failure
            logPosMessage(
                "Blackbox",
                "_sendRequest",
                "The FDM could not be reached",
                CONSOLE_COLOR,
                [error]
            );
            throw new L10nBeBlackboxConnectionError(error.message || String(error));
        }

        return await this._handleResponse(response);
    }

    /**
     * Handles the HTTP response from the blackbox service.
     * Parses the JSON response and throws a custom error if any errors are present.
     *
     * @async
     * @param {Response} response - The fetch API Response object to handle.
     * @returns {Promise<Object>} The parsed JSON result if the response is successful and contains no errors.
     * @throws {L10nBeBlackboxError} If the response contains errors.
     * @throws {L10nBeBlackboxConnectionError} If the response is not usable.
     */
    async _handleResponse(response) {
        let result;
        try {
            result = await response.json();
        } catch {
            throw new L10nBeBlackboxConnectionError(
                _t("Invalid answer from the Fiscal Data Module (HTTP %s)", response.status)
            );
        }
        if (result.errors) {
            throw new L10nBeBlackboxError("Blackbox error", result.errors);
        }
        if (!response.ok) {
            throw new L10nBeBlackboxConnectionError(
                _t("The Fiscal Data Module answered with an HTTP %s error", response.status)
            );
        }
        return result;
    }
}
