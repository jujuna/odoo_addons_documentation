import { PosConfig } from "@point_of_sale/app/models/pos_config";
import { patch } from "@web/core/utils/patch";

patch(PosConfig.prototype, {
    get l10nItFiskalyActive() {
        return (
            Boolean(this.l10n_it_fiskaly_system_id) &&
            !this.receipt_printer_ids.some(
                (printer) => printer.printer_type === "it_fiscal_printer"
            )
        );
    },
});
