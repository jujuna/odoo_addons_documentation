import { expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame, microTick } from "@odoo/hoot-mock";
import { mountWithCleanup, onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";
import mobile from "@web_mobile/js/services/core";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { setupPosEnvForPrepDisplay } from "@pos_enterprise/../tests/unit/utils";
import { BadgeScanner } from "@pos_hr_mobile_nfc/views/badge_scanner/badge_scanner";

definePosModels();

async function mountScanner(reads) {
    patchWithCleanup(mobile.methods, {
        enableNfcReader: async () => ({ success: true }),
        getNfcReaderData: async () => ({ success: true, data: reads.shift() ?? [] }),
        disableNfcReader: async () => ({ success: true }),
    });
    patchWithCleanup(BadgeScanner.prototype, {
        goBack() {
            expect.step("back");
        },
    });
    onRpc("hr.employee", "write", ({ args }) => {
        expect.step(`write ${args[0]} ${args[1].barcode}`);
        return true;
    });
    await setupPosEnvForPrepDisplay();
    const scanner = await mountWithCleanup(BadgeScanner, {
        props: { action: { context: { active_id: 3 } } },
    });
    await animationFrame();
    return scanner;
}

test("an NFC tap stores the UID as the badge of the employee and goes back", async () => {
    await mountScanner([[{ uid: "04AABBCCDDEEFF" }]]);
    expect("h4").toHaveText("For Employee1");
    await advanceTime(100);
    await microTick();
    await microTick();
    expect.verifySteps(["write 3 04AABBCCDDEEFF", "back"]);
});

test("a scanned barcode is stored the same way", async () => {
    const scanner = await mountScanner([]);
    await scanner.onBadgeScanned("BADGE-123");
    expect.verifySteps(["write 3 BADGE-123", "back"]);
});
