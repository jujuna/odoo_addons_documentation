/* global posmodel */
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as FeedbackScreen from "@point_of_sale/../tests/pos/tours/utils/feedback_screen_util";
import { registry } from "@web/core/registry";

const LOCK = "Glovo orders can't be changed or paid in the POS";
const ROW = ".ticket-screen .order-row:contains('#LOCK7001')";

const glovoOrder = () => posmodel.models["pos.order"].find((o) => o.platform_order_ref === "7001");

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

function blocked(content, action) {
    return [
        { content: `${content}: no dialog open before`, trigger: "body:not(:has(.modal))" },
        { content, trigger: "body", run: action },
        Dialog.is({ body: LOCK }),
        Dialog.confirm(),
        { content: `${content}: dialog closed`, trigger: "body:not(:has(.modal))" },
        { content: `${content}: still on the order list`, trigger: ".ticket-screen" },
    ];
}

registry.category("web_tour.tours").add("glovo_lock_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            ProductScreen.enterOpeningAmount("0"),
            {
                content: "Glovo webhook notification reaches the POS",
                trigger: ".product-screen",
                run: async () => {
                    const [id] = await posmodel.data.call("pos.order", "search", [[["platform_order_ref", "=", "7001"]]]);
                    await posmodel._fetchPlatformOrder(id, true);
                },
            },
            {
                content: "Review Orders in the new-order notification (the path that let 1023 be edited)",
                trigger: ".o_notification:contains('New platform order received.') button:contains('Review Orders')",
                run: "click",
            },
            { content: "order list shows the Glovo label", trigger: `${ROW} .glovo-order-info:contains('Glovo')` },
            {
                content: "order list shows the pickup code and the courier",
                trigger: `${ROW} .glovo-order-info:contains('Pickup code: 433'):contains('Courier: Lock Courier')`,
            },
            { content: "order screen shows the Glovo badge", trigger: ".ticket-screen .glovo-order-badge:contains('Glovo')" },
            { content: "Glovo order has a header tab", trigger: ".pos-topheader .floating-order-container button:contains('#LOCK7001')" },
            ...blocked("Header tab of the Glovo order (product screen)", () =>
                [...document.querySelectorAll(".pos-topheader .floating-order-container button")]
                    .find((b) => b.textContent.includes("#LOCK7001"))
                    .click()
            ),
            ...blocked("Open the Glovo order on the product screen (navigate)", () =>
                posmodel.navigate("ProductScreen", { orderUuid: glovoOrder().uuid })
            ),
            ...blocked("Payment button with the Glovo order current (pos.pay)", () => {
                posmodel.setOrder(glovoOrder());
                return posmodel.pay();
            }),
            { content: "select the Glovo order in the list", trigger: ROW, run: "click" },
            {
                content: "Set Food Ready",
                trigger: ".ticket-screen button.validation.set-food-ready-button:contains('Set Food Ready')",
                run: "click",
            },
            { content: "Food Is Ready", trigger: ".ticket-screen button.validation.set-food-ready-button:contains('Food Is Ready')" },
            check("Glovo order syncs to the server after the blocks, food ready", async () => {
                const order = glovoOrder();
                await posmodel.syncAllOrders({ orders: [order], throw: true });
                return order.platform_order_food_ready ? "" : "food ready not set";
            }),
            Chrome.createFloatingOrder(),
            ProductScreen.clickDisplayedProduct("Whiteboard Pen"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Cash"),
            PaymentScreen.clickValidate(),
            FeedbackScreen.isShown(),
            Chrome.waitRequest(),
            Chrome.endTour(),
        ].flat(),
});
