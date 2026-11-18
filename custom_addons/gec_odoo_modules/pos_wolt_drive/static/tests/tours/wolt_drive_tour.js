import * as TicketScreen from "@point_of_sale/../tests/pos/tours/utils/ticket_screen_util";
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("test_wolt_drive_booking", {
    steps: () =>
        [
            Chrome.startPoS(),
            Chrome.clickOrders(),
            TicketScreen.selectFilter("Paid"),
            TicketScreen.selectOrder("Nino"),
            { trigger: ".wolt-courier-button", run: "click" },
            Dialog.confirm(),
            { trigger: ".wolt-courier-status:contains('Wolt courier requested')" },
            { trigger: ".wolt-courier-cancel-button" },
        ].flat(),
});
