import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";

patch(Navbar.prototype, {
    async showSaleDetails() {
        const result = await super.showSaleDetails(...arguments);
        if (this.pos.blackbox.isActive) {
            await this.pos.signTurnoverReport();
        }
        return result;
    },
});
