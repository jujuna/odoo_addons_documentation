import { patch } from "@web/core/utils/patch";
import { BadgeScanner } from "@hr_attendance/views/badge_scanner/badge_scanner";
import { useNfcReader } from "@pos_mobile/app/hooks/nfc_reader";

patch(BadgeScanner.prototype, {
    setup() {
        super.setup(...arguments);
        useNfcReader((uid) => this.onBarcodeScanned(uid));
    },
});
