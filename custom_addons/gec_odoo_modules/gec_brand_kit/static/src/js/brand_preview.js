import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

import { Component, proxy, useProps } from "@odoo/owl";

const HEX = /^#[0-9a-f]{6}$/i;
const BUNDLED_FONTS = {
    FiraGO: "FiraGO",
    Noto_Sans_Georgian: "Noto Sans Georgian",
    Noto_Serif_Georgian: "Noto Serif Georgian",
};

/**
 * Live preview on the Brand Kit form: a small mock Odoo screen drawn from the unsaved form values, so a
 * customer admin sees colors, branding strength and font before Apply. It mirrors brand_theme.scss through
 * the same --gec-app-* variables; only valid #RRGGBB values are used (the inputs are not saved yet).
 */
export class BrandPreview extends Component {
    static template = "gec_brand_kit.BrandPreview";
    props = useProps(standardWidgetProps);

    setup() {
        this.state = proxy({ dark: false });
        this.rows = [
            { name: "S00042", partner: _t("Deco Addict"), amount: "1 250.00 ₾" },
            { name: "S00041", partner: _t("Gemini Furniture"), amount: "830.50 ₾" },
        ];
        this.steps = [_t("Quotation"), _t("Sent"), _t("Sales Order")];
    }

    color(key, fallback) {
        const value = this.props.record.data[key];
        return value && HEX.test(value) ? value : fallback;
    }

    get colors() {
        const light = {
            primary: this.color("color_primary", "#714B67"),
            action: this.color("color_action", "#017E84"),
            background: this.color("color_background", "#F9FAFB"),
            surface: this.color("color_surface", "#FFFFFF"),
            text: this.color("color_text", "#374151"),
        };
        light.accent = this.color("color_accent", light.action);
        if (!this.state.dark) {
            return light;
        }
        return {
            primary: this.color("dark_primary", light.primary),
            action: this.color("dark_action", light.action),
            accent: light.accent,
            background: this.color("dark_background", "#262A36"),
            surface: this.color("dark_surface", "#1B1D26"),
            text: this.color("dark_text", "#E4E4E4"),
            navbar: this.color("dark_surface", light.primary),
        };
    }

    get fontFamily() {
        const { font, font_family } = this.props.record.data;
        const family = BUNDLED_FONTS[font] || (font && font.replace(/_/g, " ")) || font_family;
        return family ? `'${family.replace(/['"\;{}<>]/g, "")}', sans-serif` : "";
    }

    get styleName() {
        return this.props.record.data.ui_style || "standard";
    }

    get rootStyle() {
        const c = this.colors;
        const vars = {
            "--gp-primary": c.primary,
            "--gp-action": c.action,
            "--gp-accent": c.accent,
            "--gp-background": c.background,
            "--gp-surface": c.surface,
            "--gp-text": c.text,
            "--gp-navbar": c.navbar || c.primary,
        };
        let style = Object.entries(vars).map(([k, v]) => `${k}: ${v}`).join("; ");
        if (this.fontFamily) {
            style += `; font-family: ${this.fontFamily}`;
        }
        return style;
    }

    get rootClass() {
        return `o_gec_brand_preview o_gec_bp_${this.styleName}${this.state.dark ? " o_gec_bp_dark" : ""}`;
    }

    get appName() {
        return this.props.record.data.name || "Odoo";
    }

    toggleDark() {
        this.state.dark = !this.state.dark;
    }
}

export const brandPreview = {
    component: BrandPreview,
};

registry.category("view_widgets").add("gec_brand_preview", brandPreview);
