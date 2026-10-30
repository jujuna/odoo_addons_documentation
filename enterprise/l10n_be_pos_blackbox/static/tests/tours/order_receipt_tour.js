/* global posmodel */

import * as BlackboxUtil from "@l10n_be_pos_blackbox/../tests/tours/blackbox_util";
import * as BlackboxOracle from "@l10n_be_pos_blackbox/../tests/tours/blackbox_oracle";
import { registry } from "@web/core/registry";
import * as FloorScreen from "@pos_restaurant/../tests/tours/utils/floor_screen_util";
import * as ProductScreenPos from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as ProductScreenResto from "@pos_restaurant/../tests/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as FeedbackScreen from "@point_of_sale/../tests/pos/tours/utils/feedback_screen_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";

const ProductScreen = { ...ProductScreenPos, ...ProductScreenResto };

registry.category("web_tour.tours").add("test_l10n_be_pos_blackbox_receipt_data", {
    steps: () =>
        [
            BlackboxUtil.startPosBlackbox(),
            BlackboxUtil.checkUserClockInStatus(),
            FloorScreen.clickTable("5"),
            ProductScreen.clickDisplayedProduct("Coca-Cola"),
            ProductScreen.totalAmountIs("2.20"),
            ProductScreen.clickPayButton(false),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            ...FeedbackScreen.isShown(),
            {
                content: "Verify blackbox receipt data and send to backend for comparison",
                trigger: "body",
                run: async () => {
                    const order = posmodel.getOrder();
                    order.setOrderPrices();
                    order.state = "paid";
                    await posmodel.syncAllOrders({ orders: [order] });
                    await BlackboxOracle.generateAndCheckTicket(order, "VAT TICKET");
                    const data = posmodel.ticketPrinter.getOrderReceiptData(order);
                    try {
                        await posmodel.data.call("pos.order", "get_order_frontend_receipt_data", [
                            [order.id],
                            data,
                        ]);
                    } finally {
                        // Ignore
                    }
                },
            },
            Dialog.is({ title: "Printing Failed" }),
            Dialog.cancel(),
            ...BlackboxUtil.endTour(),
        ].flat(),
});
