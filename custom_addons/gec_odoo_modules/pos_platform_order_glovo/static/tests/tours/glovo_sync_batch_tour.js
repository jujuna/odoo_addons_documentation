/* global posmodel */
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as FeedbackScreen from "@point_of_sale/../tests/pos/tours/utils/feedback_screen_util";
import * as TicketScreen from "@point_of_sale/../tests/pos/tours/utils/ticket_screen_util";
import { registry } from "@web/core/registry";

const glovo = () => posmodel.models["pos.order"].find((o) => o.platform_order_ref === "7101");

function glovoState() {
    const order = glovo();
    return `dirty=${order.isDirty()} lines=${order.lines.map((l) => `${l.product_id.display_name} x${l.qty}`).join(", ")} payments=${order.payment_ids.length} total=${order.priceIncl}`;
}

/** A step that runs fn; fn returns an empty string when fine, else what is wrong. */
function check(content, fn) {
    return {
        content,
        trigger: "body",
        run: async () => {
            const problem = await fn();
            if (problem) {
                throw new Error(`${content}: ${problem}`);
            }
        },
    };
}

function syncPassSendsNothing(label) {
    return check(`${label}: the Glovo order is not sent again`, async () => {
        window.__syncCalls.length = 0;
        await posmodel.syncAllOrders();
        return window.__syncCalls.length ? JSON.stringify(window.__syncCalls) : "";
    });
}

registry.category("web_tour.tours").add("glovo_sync_batch_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            ProductScreen.enterOpeningAmount("0"),
            check("load Glovo order 7101", async () => {
                const [id] = await posmodel.data.call("pos.order", "search", [[["platform_order_ref", "=", "7101"]]]);
                await posmodel.getServerOrder(id);
                return glovo() ? "" : "not loaded";
            }),
            check("record the orders sent by sync_from_ui", () => {
                window.__syncCalls = [];
                const call = posmodel.data.call.bind(posmodel.data);
                posmodel.data.call = (model, method, args, ...rest) => {
                    if (method === "sync_from_ui") {
                        window.__syncCalls.push(args[0].map((o) => (o.uuid === glovo().uuid ? "GLOVO-7101" : o.pos_reference)));
                    }
                    return call(model, method, args, ...rest);
                };
                return "";
            }),
            check("change the Glovo order locally (bypassing the UI blocks)", async () => {
                const order = glovo();
                order.lines[0].setQuantity(5);
                const pen = posmodel.models["product.template"].find((p) => p.name === "Whiteboard Pen");
                await posmodel.addLineToOrder({ product_tmpl_id: pen }, order, {}, false);
                order.addPaymentline(posmodel.models["pos.payment.method"].find((pm) => pm.type === "cash"));
                posmodel.addPendingOrder([order.id]);
                return order.isDirty() ? "" : "order not dirty";
            }),
            ProductScreen.clickDisplayedProduct("Letter Tray"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Cash"),
            check("the changed Glovo order is pending", () => {
                const { orderToCreate, orderToUpdate } = posmodel.getPendingOrder();
                return [...orderToCreate, ...orderToUpdate].some((o) => o.platform_order_ref === "7101") ? "" : "not pending";
            }),
            PaymentScreen.clickValidate(),
            FeedbackScreen.isShown(),
            check("payment validation sent only the normal order", () =>
                window.__syncCalls.flat().includes("GLOVO-7101") ? JSON.stringify(window.__syncCalls) : ""
            ),
            check("sync pass 1 sends the Glovo order, at most twice", async () => {
                window.__syncCalls.length = 0;
                await posmodel.syncAllOrders();
                const sent = window.__syncCalls.flat();
                return sent.length >= 1 && sent.length <= 2 && sent.every((o) => o === "GLOVO-7101") ? "" : JSON.stringify(sent);
            }),
            check("local Glovo copy matches the server", () => {
                const order = glovo();
                const ok =
                    order.lines.length === 1 &&
                    order.lines[0].product_id.display_name.endsWith("Desk Organizer") &&
                    order.lines[0].qty === 2 &&
                    order.payment_ids.length === 0 &&
                    Math.abs(order.priceIncl - 20) < 0.001 &&
                    !order.isDirty();
                return ok ? "" : `local Glovo copy differs from the server: ${glovoState()}`;
            }),
            syncPassSendsNothing("sync pass 2"),
            syncPassSendsNothing("sync pass 3"),
            FeedbackScreen.clickNextOrder(),
            Chrome.clickOrders(),
            TicketScreen.selectFilter("Paid"),
            TicketScreen.selectOrder("#LOCK7102"),
            {
                content: "cashier clicks Refund on the paid Glovo order",
                trigger: ".ticket-screen .subpads button:contains('Refund')",
                run: "click",
            },
            Dialog.is({ body: "Only a POS manager can refund a Glovo order" }),
            Dialog.confirm(),
            check("no refund order created", () => {
                const refunds = posmodel.models["pos.order"].filter((o) => o.is_refund).length;
                return refunds ? `${refunds} refund orders` : "";
            }),
            Chrome.endTour(),
        ].flat(),
});
