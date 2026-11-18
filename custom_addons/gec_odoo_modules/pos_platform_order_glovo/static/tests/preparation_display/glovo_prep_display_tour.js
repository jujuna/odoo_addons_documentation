import { registry } from "@web/core/registry";

// the display only holds the Glovo order 7904
const CARD = ".o_pdis_order_card";

registry.category("web_tour.tours").add("glovo_prep_display_tour", {
    steps: () => [
        { content: "the Glovo order is on the display", trigger: CARD },
        { content: "Done while Glovo is down", trigger: `${CARD} button:contains('Done')`, run: "click" },
        {
            content: "the cashier sees the plain message",
            trigger: ".o_notification:contains(\"Glovo isn't responding. Try again in a minute.\")",
        },
        { content: "the order stays on the display", trigger: CARD },
        { content: "Done again once Glovo answers", trigger: `${CARD} button:contains('Done')`, run: "click" },
        { content: "the order leaves the display", trigger: `body:not(:has(${CARD}))` },
    ],
});
