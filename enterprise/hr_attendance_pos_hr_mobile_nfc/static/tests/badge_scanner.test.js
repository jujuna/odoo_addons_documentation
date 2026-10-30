import { expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame, microTick } from "@odoo/hoot-mock";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BadgeScanner } from "@hr_attendance/views/badge_scanner/badge_scanner";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { setupPosEnvForPrepDisplay } from "@pos_enterprise/../tests/unit/utils";
import mobile from "@web_mobile/js/services/core";

definePosModels();

test("an NFC tap reads the UID as the badge of the employee", async () => {
    const reads = [[{ uid: "04AABBCCDDEEFF" }]];
    patchWithCleanup(mobile.methods, {
        enableNfcReader: async () => ({ success: true }),
        getNfcReaderData: async () => ({ success: true, data: reads.shift() ?? [] }),
        disableNfcReader: async () => ({ success: true }),
    });
    patchWithCleanup(BadgeScanner.prototype, {
        onBarcodeScanned(barcode) {
            expect.step(barcode);
        },
    });
    await setupPosEnvForPrepDisplay();
    await mountWithCleanup(BadgeScanner, { props: { action: { context: { active_id: 3 } } } });
    await animationFrame();
    await advanceTime(100);
    await microTick();
    await microTick();
    expect.verifySteps(["04AABBCCDDEEFF"]);
});
