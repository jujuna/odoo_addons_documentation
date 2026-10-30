import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { mobileNative } from "@pos_mobile_android/app/utils/native";

async function openKiosk(env, action) {
    const { config_id, config_name, linked_printers } = action.params;
    const inKioskMode = await mobileNative.isKioskModeEnabled?.().catch(() => false);
    if (mobileNative.proposeReceiptPrinter && !inKioskMode) {
        await mobileNative
            .proposeReceiptPrinter({
                url: browser.location.origin,
                config_id: String(config_id),
                config_name,
                linked_printers,
            })
            .catch(() => false);
    }
    return env.services.action.doAction({ ...action, tag: "pos_self_order_mobile.open_kiosk" });
}

registry.category("actions").add("obox_pos_self_order_android.open_kiosk", openKiosk);
