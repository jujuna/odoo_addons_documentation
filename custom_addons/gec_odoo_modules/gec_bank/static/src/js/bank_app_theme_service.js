import { registry } from "@web/core/registry";

/**
 * Puts the open app's menu xmlid on <body data-gec-bank-app> so a bank colours only its own app
 * (gec-bank-app-theme mixin); the same screens opened from another app keep Odoo's colours.
 */
registry.category("services").add("gec_bank_app_theme", {
    dependencies: ["menu"],
    start(env, { menu }) {
        const mark = () => {
            const app = menu.getCurrentApp();
            if (app?.xmlid) {
                document.body.dataset.gecBankApp = app.xmlid;
            } else {
                delete document.body.dataset.gecBankApp;
            }
        };
        env.bus.addEventListener("MENUS:APP-CHANGED", mark);
        mark();
    },
});
