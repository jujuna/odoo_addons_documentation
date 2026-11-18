import { Component } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { rpc, rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

/** Nothing is saved in a preview: the server refuses writes, also after the preview has ended. */
export class PreviewBanner extends Component {
    static template = "gec_access_manager.PreviewBanner";

    get preview() {
        return session.gec_preview;
    }

    async exit() {
        const { url } = await rpc("/gec_access_manager/preview/stop");
        browser.location.href = url;
    }
}

const SEEN_KEY = "gec_access_preview";
// what the web client reopens on load: the screen of the session's other user
const RESTORED_KEYS = ["current_action", "current_state", "menu_id"];

/**
 * Entering or leaving a preview starts clean: the web client would reopen the other user's last screen, which this
 * user may not be allowed to read, and show what was cached while the page's and the server's user differed.
 */
registry.category("services").add("gec_access_preview_start", {
    start() {
        const current = session.gec_preview ? `${session.gec_preview.until}${session.gec_preview.ended ? "-ended" : ""}` : "";
        try {
            if ((browser.sessionStorage.getItem(SEEN_KEY) || "") !== current) {
                for (const key of RESTORED_KEYS) {
                    browser.sessionStorage.removeItem(key);
                }
                rpcBus.trigger("CLEAR-CACHES");
                if (current) {
                    browser.sessionStorage.setItem(SEEN_KEY, current);
                } else {
                    browser.sessionStorage.removeItem(SEEN_KEY);
                }
            }
        } catch {
            // no session storage: nothing was stored either
        }
    },
});

if (session.gec_preview) {
    registry.category("main_components").add("gec_access_manager.PreviewBanner", { Component: PreviewBanner });
}
