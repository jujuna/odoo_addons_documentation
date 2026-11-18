import { registry } from "@web/core/registry";

const DELIVERED = "Use only if the courier collected the order";
const CANCELLED = "Use only if Glovo cancelled the order";

function openAction(xmlid) {
    return {
        content: `open ${xmlid}`,
        trigger: ".o_main_navbar",
        run: () => odoo.__WOWL_DEBUG__.root.env.services.action.doAction(xmlid, {
            additionalContext: { active_model: "pos.order", active_ids: [] },
        }),
    };
}

function checkWarning(shown, hidden) {
    return [
        { content: `"${shown}" visible above Confirm`, trigger: `.modal .alert-warning:contains("${shown}")` },
        {
            content: `"${hidden}" not rendered`,
            trigger: ".modal footer button[name=action_confirm]",
            run: () => {
                const alerts = [...document.querySelectorAll(".modal .alert-warning")].map((a) => a.textContent.trim());
                if (alerts.length !== 1 || alerts.some((a) => a.includes(hidden))) {
                    throw new Error(`unexpected alerts ${JSON.stringify(alerts)}`);
                }
            },
        },
        { content: "close dialog", trigger: ".modal footer button.btn-secondary", run: "click" },
        { content: "dialog closed", trigger: "body:not(:has(.modal))" },
    ];
}

registry.category("web_tour.tours").add("glovo_resolve_form_tour", {
    steps: () => [
        openAction("pos_platform_order_glovo.action_pos_glovo_order_mark_delivered"),
        ...checkWarning(DELIVERED, CANCELLED),
        openAction("pos_platform_order_glovo.action_pos_glovo_order_mark_cancelled"),
        ...checkWarning(CANCELLED, DELIVERED),
    ],
});
