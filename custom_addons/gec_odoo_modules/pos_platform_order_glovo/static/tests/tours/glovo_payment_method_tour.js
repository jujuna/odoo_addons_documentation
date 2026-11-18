/* global posmodel */
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import { registry } from "@web/core/registry";

const row = (ref) => `.ticket-screen .order-row:contains('#LOCK${ref}')`;

registry.category("web_tour.tours").add("glovo_payment_method_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            ProductScreen.enterOpeningAmount("0"),
            {
                content: "load the CASH and DELAYED Glovo orders",
                trigger: ".product-screen",
                run: async () => {
                    const ids = await posmodel.data.call("pos.order", "search", [
                        [["platform_order_ref", "in", ["7701", "7702"]]],
                    ]);
                    for (const id of ids) {
                        await posmodel.getServerOrder(id);
                    }
                },
            },
            Chrome.clickOrders(),
            {
                content: "CASH order: the courier pays the order total in cash",
                trigger: `${row(7701)} .glovo-payment-method:contains('Courier pays cash: '):contains('20.00')`,
            },
            {
                content: "CASH order shows no invoice text",
                trigger: `${row(7701)}:not(:contains('Paid by Glovo invoice'))`,
            },
            {
                content: "DELAYED order: paid by Glovo invoice",
                trigger: `${row(7702)} .glovo-payment-method:contains('Paid by Glovo invoice')`,
            },
            {
                content: "DELAYED order shows no cash text",
                trigger: `${row(7702)}:not(:contains('Courier pays cash'))`,
            },
            Chrome.endTour(),
        ].flat(),
});
