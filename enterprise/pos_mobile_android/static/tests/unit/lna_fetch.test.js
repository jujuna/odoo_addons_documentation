import { expect, test } from "@odoo/hoot";
import { patch } from "@web/core/utils/patch";
import { grantLnaPermission } from "@pos_mobile_android/app/utils/lna_fetch";

const lna = { name: "local-network-access" };
const camera = { name: "camera" };

test("local network access is granted, other permissions are left to the browser", async () => {
    const target = {
        permissions: {
            state: "denied",
            async query(descriptor) {
                expect.step(descriptor.name);
                return { state: this.state };
            },
        },
    };

    grantLnaPermission(target);

    expect(await target.permissions.query(lna)).toEqual({ state: "granted" });
    expect(await target.permissions.query(camera)).toEqual({ state: "denied" });
    expect.verifySteps(["camera"]);
});

test("without the permissions API, other permissions are answered without a state", async () => {
    for (const target of [{}, { permissions: {} }]) {
        grantLnaPermission(target);

        expect(await target.permissions.query(lna)).toEqual({ state: "granted" });
        const status = await target.permissions.query(camera);
        expect(status).toBeInstanceOf(EventTarget);
        expect(status.state).toBe(undefined);
        status.addEventListener("change", (event) => expect.step(event.type));
        status.dispatchEvent(new Event("change"));
    }

    expect.verifySteps(["change", "change"]);
});

test("permissions that cannot be patched are reported without raising", () => {
    patch(console, {
        error: (message, error) => expect.step(`${message}: ${error.message}`),
    });
    const target = {
        permissions: {
            set query(value) {
                throw new Error("read-only");
            },
        },
    };

    grantLnaPermission(target);

    expect.verifySteps(["Failed to grant the local network access permission: read-only"]);
});
