import { beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { cookie } from "@web/core/browser/cookie";
import { patch } from "@web/core/utils/patch";
import mobile from "@web_mobile/js/services/core";
import { setupPosEnvForPrepDisplay } from "@pos_enterprise/../tests/unit/utils";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

definePosModels();

let displays;
let openedUrls;

beforeEach(() => {
    cookie.delete("pos_customer_display_id");
    openedUrls = {};
    patch(mobile.methods, {
        getDisplays: async () => ({ success: true, data: displays }),
        showDisplayAndGoToUrl: async ({ url, displayId }) => {
            openedUrls[displayId] = url;
            return { success: true };
        },
    });
});

async function openPos() {
    const store = await setupPosEnvForPrepDisplay();
    await mountWithCleanup(Navbar, store.env);
    await animationFrame();
    return store;
}

test("the customer display opens on the only secondary display", async () => {
    displays = [{ displayId: 2, name: "Customer screen" }];

    const store = await openPos();

    expect(openedUrls).toEqual({ 2: store.customerDisplayUrl });
    expect(cookie.get("pos_customer_display_id")).toBe("2");
});

test("the customer display opens on the remembered display", async () => {
    displays = [
        { displayId: 2, name: "Screen A" },
        { displayId: 3, name: "Screen B" },
    ];
    cookie.set("pos_customer_display_id", 3);

    const store = await openPos();

    expect(openedUrls).toEqual({ 2: "about:blank", 3: store.customerDisplayUrl });
});

test("the customer display opens on the only display when the remembered one is gone", async () => {
    displays = [{ displayId: 2, name: "Customer screen" }];
    cookie.set("pos_customer_display_id", 5);

    const store = await openPos();

    expect(openedUrls).toEqual({ 2: store.customerDisplayUrl });
});

test("several displays without a remembered one stay blank", async () => {
    displays = [
        { displayId: 2, name: "Screen A" },
        { displayId: 3, name: "Screen B" },
    ];

    await openPos();

    expect(openedUrls).toEqual({ 2: "about:blank", 3: "about:blank" });
});
