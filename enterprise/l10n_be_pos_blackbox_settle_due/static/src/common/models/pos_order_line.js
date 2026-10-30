import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";

export const SETTLE_PRODUCT_TMPL_ID = "dummy_product_for_settle_stuff";

patch(PosOrderline.prototype, {
    isSettleProductLine() {
        return this.product_id?.product_tmpl_id?.id === SETTLE_PRODUCT_TMPL_ID;
    },
    get haveQuantityCorrection() {
        return this.isSettleProductLine() ? false : super.haveQuantityCorrection;
    },
    get haveMaxUnitPriceCorrection() {
        return this.isSettleProductLine() ? false : super.haveMaxUnitPriceCorrection;
    },
});
