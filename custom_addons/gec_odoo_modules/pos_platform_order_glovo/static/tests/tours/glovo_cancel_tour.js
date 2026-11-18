/* global posmodel */
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as TicketScreen from "@point_of_sale/../tests/pos/tours/utils/ticket_screen_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import { registry } from "@web/core/registry";

function spyCancelledPrep() {
    return {
        content: "record preparation sends flagged cancelled",
        trigger: "body",
        run: () => {
            window.__cancelledPrep = [];
            const original = posmodel.sendOrderInPreparation.bind(posmodel);
            posmodel.sendOrderInPreparation = (order, opts = {}) => {
                if (opts.cancelled) {
                    window.__cancelledPrep.push(order.floating_order_name);
                }
                return original(order, opts);
            };
        },
    };
}

function cancelledPrepIs(expected) {
    return {
        content: `cancelled preparation sends are ${JSON.stringify(expected)}`,
        trigger: "body",
        run: () => {
            const got = JSON.stringify(window.__cancelledPrep);
            if (got !== JSON.stringify(expected)) {
                throw new Error(`cancelled preparation sends: ${got}, expected ${JSON.stringify(expected)}`);
            }
        },
    };
}

registry.category("web_tour.tours").add("glovo_cancel_blocked_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            spyCancelledPrep(),
            Chrome.clickOrders(),
            TicketScreen.deleteOrder("#GLV5001"),
            Dialog.is({ body: "Glovo orders can't be cancelled here" }),
            Dialog.confirm(),
            { content: "Glovo order still listed", trigger: ".ticket-screen .order-row:contains('#GLV5001')" },
            cancelledPrepIs([]),
            TicketScreen.deleteOrder("NormalDraft"),
            Dialog.confirm(),
            {
                content: "normal order removed",
                trigger: ".ticket-screen:not(:has(.order-row:contains('NormalDraft')))",
            },
            Chrome.waitRequest(),
            cancelledPrepIs(["NormalDraft"]),
        ].flat(),
});
