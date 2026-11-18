import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    get totalDue() {
        return this.uiState?.depositMoney ? this.amountPaid : super.totalDue;
    },
});
