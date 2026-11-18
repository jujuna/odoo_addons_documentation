import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

const VOUCHER_PROGRAM_TYPES = ["gift_card", "ewallet"];

patch(PosStore.prototype, {
    async l10nItFiskalyVatExemption(vals) {
        const product = this.l10nItFiskalyProduct(vals);
        const isVoucher = this.models["loyalty.program"]
            .filter((program) => VOUCHER_PROGRAM_TYPES.includes(program.program_type))
            .some((program) => program.trigger_product_ids.includes(product));
        if (isVoucher) {
            return "NOT_SUBJECT";
        }
        return super.l10nItFiskalyVatExemption(...arguments);
    },

    l10nItFiskalyAllowsNegativeLine(line) {
        return line.is_reward_line || super.l10nItFiskalyAllowsNegativeLine(...arguments);
    },

    l10nItFiskalyLineHasVat(line, _order) {
        const programType = line.card_id?.program_id?.program_type;
        if (line.is_reward_line && VOUCHER_PROGRAM_TYPES.includes(programType)) {
            return true;
        }
        return super.l10nItFiskalyLineHasVat(...arguments);
    },
});
