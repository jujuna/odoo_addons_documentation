import { describe, expect, test } from "@odoo/hoot";
import { PosBlackboxBe } from "@l10n_be_pos_blackbox/../tests/unit/data/pos_blackbox_be.data";
import { setupPosBlackboxEnv } from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { PosConfig } from "@point_of_sale/../tests/unit/data/pos_config.data";
import { unpatchSelf } from "@pos_self_order/app/plugins/pos_data_plugin";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

definePosModels();

const setupMobileSelfOrderEnv = ({ withBlackbox = true } = {}) => {
    // Load the PoS data, not the self-order one
    unpatchSelf();
    // pos_self_order mock data points to presets that the blackbox mock data replaces
    patchWithCleanup(PosConfig._records[0], {
        self_ordering_mode: "mobile",
        available_preset_ids: [4, 5],
        default_preset_id: 4,
    });
    if (!withBlackbox) {
        // Unlink both sides, the one2many would set the config's many2one back
        patchWithCleanup(PosConfig._records[0], { l10n_be_blackbox_be_id: false });
        patchWithCleanup(PosBlackboxBe._records[0], { pos_config_ids: [] });
    }
    return setupPosBlackboxEnv();
};

const getOnlinePaymentStatusListener = (store) =>
    store.data.channels.find(({ channel }) => channel === "ONLINE_PAYMENT_STATUS")?.method;

describe("online payment status", () => {
    test("mobile self-order paid online is signed when the blackbox is active", async () => {
        const store = await setupMobileSelfOrderEnv();
        const signedOrderIds = [];
        patchWithCleanup(store, {
            async getSelfOrderToSign(orderId) {
                signedOrderIds.push(orderId);
            },
        });
        expect(store.blackbox.isActive).toBe(true);

        const listener = getOnlinePaymentStatusListener(store);
        listener({ status: "progress", order_id: 1 });
        listener({ status: "success", order_id: 1 });

        expect(signedOrderIds).toEqual([1]);
    });

    test("online payment status is not listened to when the blackbox is not active", async () => {
        const store = await setupMobileSelfOrderEnv({ withBlackbox: false });
        expect(store.blackbox.isActive).toBe(false);

        expect(getOnlinePaymentStatusListener(store)).toBe(undefined);
    });
});
