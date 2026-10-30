import { CashMovePopup } from "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup";
import { patch } from "@web/core/utils/patch";
import { parseFloat } from "@web/views/fields/parsers";

patch(CashMovePopup.prototype, {
    setup() {
        super.setup();
        this.env.dialogData.dismiss = this.cancel.bind(this);
    },
    async confirm() {
        if (!this.pos.blackbox.isActive) {
            return super.confirm(...arguments);
        }

        const cashier = this.pos.l10nBeSigningInsz;
        const parsedAmount = parseFloat(this.state.amount);
        const amount = Math.abs(parsedAmount);
        let name = this.state.type;
        if (parsedAmount < 0) {
            name = name == "out" ? "in" : "out";
        }
        const result = await this.pos.blackbox.signMoneyInOut.sign(
            this.pos.models,
            cashier,
            {
                amount,
                name,
            },
            this.pos.ticketPrinter.hasReceiptPrinters
        );

        if (!result) {
            return false;
        }

        return super.confirm(...arguments);
    },
    async cancel() {
        if (!this.pos.blackbox.isActive) {
            return super.cancel(...arguments);
        }

        const cashier = this.pos.l10nBeSigningInsz;
        const result = await this.pos.blackbox.signDrawerOpen.sign(this.pos.models, cashier);

        if (!result) {
            return false;
        }

        return super.cancel(...arguments);
    },
});
