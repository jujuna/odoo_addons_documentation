import { browser } from "@web/core/browser/browser";
import { mobileNative } from "@pos_mobile_android/app/utils/native";

const POS_ICON_URL = "/point_of_sale/static/description/icon.png";

export function canAddHomeShortcut() {
    return Boolean(mobileNative.addHomeShortcut);
}

export async function addPosHomeShortcut(config) {
    await mobileNative.addHomeShortcut({
        title: config.display_name,
        shortcut_url: `${browser.location.origin}/pos/ui/${config.id}`,
        web_icon: await posIconBase64(),
    });
}

async function posIconBase64() {
    try {
        const response = await browser.fetch(POS_ICON_URL);
        const bytes = new Uint8Array(await response.arrayBuffer());
        return btoa(String.fromCharCode(...bytes));
    } catch {
        return "";
    }
}
