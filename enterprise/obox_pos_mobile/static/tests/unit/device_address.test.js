import { resolveDeviceAddress } from "@obox_pos_mobile/app/utils/device_address";
import { advanceTime, beforeEach, expect, test } from "@odoo/hoot";
import { patch } from "@web/core/utils/patch";
import mobile from "@web_mobile/js/services/core";

const OWN_IP = "192.168.1.10";
const OWN_SERIAL = "ODO-ABCDEF1234";
const OWN_PORT = 4546;
const OWN_STATUS_CACHE_MS = 2000;

let nativeCalls;

const forgetCachedStatus = () => advanceTime(OWN_STATUS_CACHE_MS + 1);

beforeEach(() => {
    nativeCalls = 0;
    patch(mobile.methods, {
        getDeviceManagerStatus: async () => {
            nativeCalls++;
            return {
                success: true,
                data: { paired: true, serial: OWN_SERIAL, ip: OWN_IP, port: OWN_PORT },
            };
        },
    });
});

test("this box's printer becomes loopback whatever its stale ip", async () => {
    expect(await resolveDeviceAddress("10.0.0.99:4545/usb/v1/printer/p", OWN_SERIAL)).toBe(
        `127.0.0.1:${OWN_PORT}/usb/v1/printer/p`
    );
    await forgetCachedStatus();
});

test("a full url keeps its scheme and path", async () => {
    expect(await resolveDeviceAddress("http://10.0.0.99:4545/usb/v1", OWN_SERIAL)).toBe(
        `http://127.0.0.1:${OWN_PORT}/usb/v1`
    );
    await forgetCachedStatus();
});

test("the serial is compared without case or spaces", async () => {
    expect(await resolveDeviceAddress("10.0.0.99:4545", ` ${OWN_SERIAL.toLowerCase()} `)).toBe(
        `127.0.0.1:${OWN_PORT}`
    );
    await forgetCachedStatus();
});

test("another box's printer is left alone even on this device's ip", async () => {
    expect(await resolveDeviceAddress(`${OWN_IP}:4545`, "ODO-OTHER")).toBe(`${OWN_IP}:4545`);
    await forgetCachedStatus();
});

test("a printer without a serial is matched on the ip and keeps its port", async () => {
    expect(await resolveDeviceAddress(`${OWN_IP}:4545`)).toBe("127.0.0.1:4545");
    expect(await resolveDeviceAddress(OWN_IP)).toBe("127.0.0.1");
    expect(await resolveDeviceAddress("192.168.1.20:4545")).toBe("192.168.1.20:4545");
    await forgetCachedStatus();
});

test("the stored port is kept when the app tells none", async () => {
    patch(mobile.methods, {
        getDeviceManagerStatus: async () => ({ success: true, data: { serial: OWN_SERIAL } }),
    });
    expect(await resolveDeviceAddress("10.0.0.99:4545", OWN_SERIAL)).toBe("127.0.0.1:4545");
    await forgetCachedStatus();
});

test("setting up several devices asks the app once", async () => {
    await Promise.all([
        resolveDeviceAddress("10.0.0.99:4545", OWN_SERIAL),
        resolveDeviceAddress(`${OWN_IP}:4545`),
        resolveDeviceAddress("192.168.1.20"),
    ]);
    expect(nativeCalls).toBe(1);
    await forgetCachedStatus();
});

test("the status is asked again once the cache is forgotten", async () => {
    await resolveDeviceAddress("10.0.0.99:4545", OWN_SERIAL);
    await forgetCachedStatus();
    await resolveDeviceAddress("10.0.0.99:4545", OWN_SERIAL);
    expect(nativeCalls).toBe(2);
    await forgetCachedStatus();
});

test("outside the app the address is left alone", async () => {
    patch(mobile.methods, { getDeviceManagerStatus: undefined });
    expect(await resolveDeviceAddress("10.0.0.99:4545", OWN_SERIAL)).toBe("10.0.0.99:4545");
    expect(nativeCalls).toBe(0);
});

test("a native failure leaves the address alone", async () => {
    patch(mobile.methods, {
        getDeviceManagerStatus: async () => ({ success: false, data: "not paired" }),
    });
    expect(await resolveDeviceAddress("10.0.0.99:4545", OWN_SERIAL)).toBe("10.0.0.99:4545");
    await forgetCachedStatus();
});
