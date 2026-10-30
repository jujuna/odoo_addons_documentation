import { InputGenerator } from "@l10n_be_pos_blackbox/common/blackbox/utils/input_generator";
import { patch } from "@web/core/utils/patch";
import { roundCurrency } from "@point_of_sale/app/models/utils/currency";

// A settle/deposit line uses the tax-less temporary dummy product created by `pos_settle_due` (see its `pos_store.js`)
patch(InputGenerator.prototype, {
    generatePriceChangeInput(line) {
        if (line.isSettleProductLine()) {
            return [];
        }
        return super.generatePriceChangeInput(...arguments);
    },
    generateLineVatInput(line, vals) {
        if (line.isSettleProductLine()) {
            return [
                this.generateTaxVatInput(
                    line,
                    "X",
                    roundCurrency(line.price_unit * vals.qty, line.order_id.currency),
                    vals
                ),
            ];
        }
        return super.generateLineVatInput(...arguments);
    },
    generateProductInput(line) {
        const res = super.generateProductInput(...arguments);
        if (line.isSettleProductLine()) {
            res.unitPrice = roundCurrency(line.price_unit, line.order_id.currency);
        }
        return res;
    },
    getQuantityType(line) {
        if (line.isSettleProductLine()) {
            return "PIECE";
        }
        return super.getQuantityType(...arguments);
    },
});
