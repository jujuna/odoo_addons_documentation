import { PosPayment } from "@point_of_sale/app/models/pos_payment";
import { patch } from "@web/core/utils/patch";

patch(PosPayment.prototype, {
    setAmount(...args) {
        super.setAmount(...args);

        const order = this.pos_order_id;
        if (order?.uiState?.depositMoney) {
            const depositLine = order.lines[0];
            if (depositLine) {
                const total = order.payment_ids.reduce(
                    (sum, payment) => sum + payment.getAmount(),
                    0
                );
                depositLine.setUnitPrice(total);
            }
        }
    },
});
