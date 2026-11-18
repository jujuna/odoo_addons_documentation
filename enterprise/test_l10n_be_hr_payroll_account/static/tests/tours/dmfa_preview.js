import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("l10n_be_dmfa_preview", {
    steps: () => [
        {
            content: "Open the preview of the DmfA",
            trigger: ".o_form_view button[name='action_report_dmfa_preview']:not([disabled])",
            run: "click",
        },
        {
            content: "The whole company is previewed",
            trigger: ".o_l10n_be_dmfa_preview iframe:iframe h3:contains('Branch Worker')",
        },
        {
            trigger: ".o_l10n_be_dmfa_preview iframe:iframe h3:contains('Head Office Worker')",
        },
        {
            content: "Preview the branch",
            trigger: ".o_l10n_be_dmfa_preview select",
            run: "selectByIndex 2",
        },
        {
            content: "Only the employees of the branch are previewed",
            trigger: ".o_l10n_be_dmfa_preview iframe:iframe h2:contains('Perwez')",
        },
        {
            trigger: ".o_l10n_be_dmfa_preview iframe:iframe:not(:has(h3:contains('Head Office Worker')))",
        },
        {
            trigger: ".o_l10n_be_dmfa_preview iframe:iframe h3:contains('Branch Worker')",
        },
        {
            content: "Print the preview of the branch",
            trigger: ".o_l10n_be_dmfa_preview button.btn-primary:not([disabled]):contains('Print')",
            run: "click",
        },
        {
            content: "The report is printed",
            trigger: ".o_l10n_be_dmfa_preview button.btn-primary:not([disabled]):contains('Print')",
        },
    ],
});
