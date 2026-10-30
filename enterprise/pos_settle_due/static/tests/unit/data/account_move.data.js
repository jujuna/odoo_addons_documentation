import { patch } from "@web/core/utils/patch";
import { AccountMove } from "@point_of_sale/../tests/unit/data/account_move.data";

patch(AccountMove.prototype, {
    settle_invoices_from_pos() {
        return true;
    },
});
