/* global Sha1 */

import { beforeEach, expect, test } from "@odoo/hoot";
import { advanceTime, microTick } from "@odoo/hoot-mock";
import { mountWithCleanup, onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { ConnectionLostError } from "@web/core/network/rpc";
import mobile from "@web_mobile/js/services/core";
import { setupPosEnvForPrepDisplay } from "@pos_enterprise/../tests/unit/utils";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { HrEmployee } from "@pos_hr/../tests/unit/data/hr_employee.data";

definePosModels();

const UID = "04DE5F1EACC040";
const SECURE_BADGE = `https://odoo.com/badge?uid=${UID}&ctr=000001&cmac=94EED9EE65337086`;
const FORGED_BADGE = `https://odoo.com/badge?uid=${UID}&ctr=000001&cmac=0000000000000000`;
let offline = false;
let role = "cashier";

beforeEach(() => {
    patchWithCleanup(HrEmployee.prototype, {
        _load_pos_data_read(records) {
            for (const employee of super._load_pos_data_read(records)) {
                if (employee.id === 3) {
                    employee._barcode = Sha1.hash(UID);
                    employee._pin = Sha1.hash("1234");
                    employee._role = role;
                }
            }
            return records;
        },
    });
    offline = false;
    role = "cashier";
    onRpc("pos.config", "verify_nfc_badge", ({ args }) => {
        expect.step("verify");
        if (offline) {
            throw new ConnectionLostError("/web/dataset/call_kw");
        }
        return args[1] === SECURE_BADGE ? 3 : false;
    });
});

async function tapBadge(secure, { secureLogin = true, managerPin = false } = {}) {
    const reads = [[{ uid: UID, secure: secureLogin && secure }]];
    patchWithCleanup(mobile.methods, {
        enableNfcReader: async (args) => {
            expect.step("enableNfcReader");
            expect(args.secure).toBe(secureLogin);
            return { success: true };
        },
        getNfcReaderData: async (args) => {
            expect.step(`poll ${args.secure}`);
            return { success: true, data: reads.shift() ?? [] };
        },
        disableNfcReader: async () => ({ success: true }),
    });
    const store = await setupPosEnvForPrepDisplay();
    store.config.nfc_secure_login = secureLogin;
    store.config.nfc_manager_pin_required = managerPin;
    patchWithCleanup(store.accessRight, {
        async checkPin() {
            expect.step("checkPin");
            return false;
        },
    });
    await mountWithCleanup(LoginScreen, {});
    await advanceTime(100);
    await microTick();
    await microTick();
    return {
        store,
        cashier: store.accessRight.loggedCashier,
        employee: store.data.models["hr.employee"].get(3),
    };
}

test("a plain NFC badge selects the employee and asks the PIN", async () => {
    const { cashier, employee } = await tapBadge();
    expect.verifySteps(["enableNfcReader", "poll true", "checkPin"]);
    expect(cashier).not.toBe(employee);
});

test("a secure NFC badge logs the employee in without PIN", async () => {
    const { cashier, employee } = await tapBadge(SECURE_BADGE);
    expect.verifySteps(["enableNfcReader", "poll true", "verify"]);
    expect(cashier).toBe(employee);
});

test("a secure NFC badge rejected by the server falls back to the PIN", async () => {
    const { cashier, employee } = await tapBadge(FORGED_BADGE);
    expect.verifySteps(["enableNfcReader", "poll true", "verify", "checkPin"]);
    expect(cashier).not.toBe(employee);
});

test("a secure NFC badge falls back to the PIN when the server is unreachable", async () => {
    offline = true;
    const { cashier, employee } = await tapBadge(SECURE_BADGE);
    expect.verifySteps(["enableNfcReader", "poll true", "verify", "checkPin"]);
    expect(cashier).not.toBe(employee);
});

test("without Secure NFC Badges, a badge is not verified and only selects the employee", async () => {
    const { cashier, employee } = await tapBadge(SECURE_BADGE, { secureLogin: false });
    expect.verifySteps(["enableNfcReader", "poll false", "checkPin"]);
    expect(cashier).not.toBe(employee);
});

test("a secure NFC badge logs a manager in without PIN by default", async () => {
    role = "manager";
    const { cashier, employee } = await tapBadge(SECURE_BADGE);
    expect.verifySteps(["enableNfcReader", "poll true", "verify"]);
    expect(cashier).toBe(employee);
});

test("with PIN Required for Managers, a secure NFC badge of a manager asks the PIN", async () => {
    role = "manager";
    const { cashier, employee } = await tapBadge(SECURE_BADGE, { managerPin: true });
    expect.verifySteps(["enableNfcReader", "poll true", "verify", "checkPin"]);
    expect(cashier).not.toBe(employee);
});

test("the reader follows the Secure NFC Badges setting while the screen stays open", async () => {
    const { store } = await tapBadge(undefined, { secureLogin: false });
    expect.verifySteps(["enableNfcReader", "poll false", "checkPin"]);
    store.config.nfc_secure_login = true;
    await advanceTime(100);
    await microTick();
    expect.verifySteps(["poll true"]);
});
