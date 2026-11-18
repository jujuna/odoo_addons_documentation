import * as TicketScreen from "@point_of_sale/../tests/pos/tours/utils/ticket_screen_util";
import * as PlatformOrder from "@pos_platform_order/../tests/tours/utils/pos_platform_order_utils";
import * as ChromePos from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as ChromeRestaurant from "@pos_restaurant/../tests/tours/utils/chrome";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import { registry } from "@web/core/registry";

const Chrome = { ...ChromePos, ...ChromeRestaurant };

registry.category("web_tour.tours").add("test_wolt_takeaway_flow", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            Chrome.clickOrders(),
            TicketScreen.nthRowContains(1, "Wolt #042"),
            TicketScreen.nthRowContains(1, "New"),
            TicketScreen.selectOrder("Wolt #042"),
            PlatformOrder.orderButtonClick("Accept Order"),
            TicketScreen.nthRowContains(1, "Accepted"),
            PlatformOrder.orderButtonClick("Set Food Ready"),
            PlatformOrder.foodReadyButtonIsDisabled(),
            PlatformOrder.orderButtonClick("Mark Delivered"),
            {
                content: "Mark Delivered button disappears once delivered",
                trigger: "body:not(:has(.wolt-delivered-button))",
            },
        ].flat(),
});
