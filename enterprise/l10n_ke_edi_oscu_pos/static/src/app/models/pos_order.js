import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    get l10n_ke_edi_oscu_pos_qrsrc() {
        let res;
        if (this.l10n_ke_oscu_signature) {
            const domain = this.company_id.l10n_ke_server_mode == "test" ? "etims-sbx" : "etims";
            const data = `${this.company_id.vat}${this.company_id.l10n_ke_branch_code}${this.l10n_ke_oscu_signature}`;
            res = `https://${domain}.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData?Data=${data}`;
        }
        return res;
    },
});
