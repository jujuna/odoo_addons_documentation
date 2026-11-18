/* global posmodel */
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import { registry } from "@web/core/registry";

const row = (ref) => `.ticket-screen .order-row:contains('#LOCK${ref}')`;
const BUTTON = ".ticket-screen button.customer-picked-up-button:contains('Customer Picked Up')";

registry.category("web_tour.tours").add("glovo_customer_pickup_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            ProductScreen.enterOpeningAmount("0"),
            {
                content: "load the pickup and the courier Glovo orders",
                trigger: ".product-screen",
                run: async () => {
                    const ids = await posmodel.data.call("pos.order", "search", [
                        [["platform_order_ref", "in", ["8201", "8202"]]],
                    ]);
                    for (const id of ids) {
                        await posmodel.getServerOrder(id);
                    }
                },
            },
            Chrome.clickOrders(),
            { content: "select the courier order", trigger: row(8202), run: "click" },
            { content: "courier order is selected", trigger: `${row(8202)}.highlight` },
            {
                content: "courier order: Set Food Ready shows, Customer Picked Up does not",
                trigger: ".ticket-screen:has(.set-food-ready-button):not(:has(.customer-picked-up-button))",
            },
            { content: "select the pickup order", trigger: row(8201), run: "click" },
            { content: "pickup order is selected", trigger: `${row(8201)}.highlight` },
            { content: "click Customer Picked Up", trigger: BUTTON, run: "click" },
            {
                content: "the cashier is told the sale is booked",
                trigger: ".o_notification:contains('The customer picked up the order; the sale is booked.')",
            },
            {
                content: "Customer Picked Up is gone for the booked order",
                trigger: ".ticket-screen:not(:has(.customer-picked-up-button))",
            },
            Chrome.endTour(),
        ].flat(),
});
