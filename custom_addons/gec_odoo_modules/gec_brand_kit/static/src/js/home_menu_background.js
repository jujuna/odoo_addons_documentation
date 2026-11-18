import { onMounted, onWillUnmount } from "@odoo/owl";
import { HomeMenu } from "@web_enterprise/webclient/home_menu/home_menu";
import { patch } from "@web/core/utils/patch";

const BODY_CLASSES = ["o_home_menu_background", "o_home_menu_background_custom", "o_gec_brand_background"];

/**
 * Show the brand kit picture behind the home menu, database-wide. Studio's per-company picture
 * (root.backgroundImage) wins when it is set. The picture is set as a CSS variable on <body>, not
 * through a template, so it works with any home menu template (enterprise, gec_home_menu, Studio).
 */
patch(HomeMenu.prototype, {
    setup() {
        super.setup();
        const root = this.menus.getMenu("root");
        const url = root.gecBrandBackgroundUrl;
        if (root.backgroundImage || !url) {
            return;
        }
        onMounted(() => {
            document.body.style.setProperty("--gec-brand-home-background", `url("${url}")`);
            document.body.classList.add(...BODY_CLASSES);
        });
        onWillUnmount(() => {
            document.body.classList.remove(...BODY_CLASSES);
            document.body.style.removeProperty("--gec-brand-home-background");
        });
    },
});
