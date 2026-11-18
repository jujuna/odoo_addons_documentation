/* global posmodel */

import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as BlackboxOracle from "@l10n_be_pos_blackbox/../tests/tours/blackbox_oracle";
import * as FeedbackScreen from "@point_of_sale/../tests/pos/tours/utils/feedback_screen_util";
import { run } from "@point_of_sale/../tests/generic_helpers/utils";
const originalConsoleError = console.error;

export function startPosBlackbox() {
    return [
        BlackboxOracle.enableBlackboxOracle(),
        ...Chrome.startPoS(),
        Dialog.confirm("Open Register"),
    ];
}

export function endTour() {
    return [BlackboxOracle.disableBlackboxOracle(), Chrome.endTour()];
}

export function setCannotReachBackend() {
    return run(() => {
        // Override console.error to avoid failing tests due to expected connection lost errors
        console.error = (...args) => {
            const message = args[0] instanceof Error ? args[0].message : args[0];
            if (typeof message === "string" && message.includes("ConnectionLostError")) {
                console.info("Connection lost error handled in offline mode:", ...args);
            } else {
                originalConsoleError.apply(console, args);
            }
        };
        window.blackboxTestEnv.canReachBackend = false;
        posmodel.data.network.offline = true;
        posmodel.data.network.warningTriggered = true;
        clearTimeout(posmodel.data.checkConnectivityTimeout);
    }, "Backend unreachable");
}

export function setCanReachBackend() {
    return run(() => {
        window.blackboxTestEnv.canReachBackend = true;
        window.dispatchEvent(new Event("online"));
    }, "Backend reachable");
}

export function waitBackendOnline() {
    return {
        trigger: "body",
        content: "Wait for the heartbeat to bring the PoS back online",
        timeout: 15000,
        async run({ waitUntil }) {
            await waitUntil(() => !posmodel.data.network.offline, { timeout: 10000 });
        },
    };
}

export function waitForPaidOrdersSync() {
    return {
        content: "Wait until the paid orders are synced with the backend",
        trigger: "body",
        timeout: 5000,
        async run({ waitUntil }) {
            await waitUntil(
                () => {
                    const paidOrders = posmodel.models["pos.order"].filter((o) => o.finalized);
                    return paidOrders.length > 0 && paidOrders.every((o) => o.isSynced);
                },
                { timeout: 5000 }
            );
        },
    };
}

export function setCanReachBlackbox() {
    return run(() => {
        window.blackboxTestEnv.canReachBlackbox = true;
    }, "Blackbox reachable");
}

export function setCannotReachBlackbox() {
    // Override console.error to avoid failing tests due to expected blackbox unreachable errors
    console.error = (...args) => {
        const message = args[0] instanceof Error ? args[0].message : args[0];
        if (typeof message === "string" && message.includes("HTTP Error")) {
            console.info(message, ...args);
        } else {
            originalConsoleError.apply(console, args);
        }
    };
    return run(() => {
        window.blackboxTestEnv.canReachBlackbox = false;
    }, "Blackbox unreachable");
}

export function checkUserClockInStatus(status = "Clocked in") {
    return {
        content: `Check if the user clock-in status is (${status})`,
        trigger: `.cashier-name .clock-status[title="${status}"]`,
    };
}

export function confirmFdmErrorDialog() {
    return [Dialog.is({ title: "Network Error" }), Dialog.confirm("Ok")];
}

export function receiptContainsBlackboxData(
    expectedTicketVatLabel = "VAT TICKET",
    expectPrintingFailed = true
) {
    return [
        ...FeedbackScreen.isShown(),
        {
            content: "Check that .blackbox-data contains all expected blackbox fields",
            trigger: "body",
            run: async () => {
                await BlackboxOracle.generateAndCheckTicket(
                    posmodel.getOrder(),
                    expectedTicketVatLabel
                );
            },
        },
        ...(expectPrintingFailed ? [Dialog.is({ title: "Printing Failed" }), Dialog.cancel()] : []),
    ];
}
