import { registry } from "@web/core/registry";

/** Walks the filter bar like a person: no server-side test sees the OWL component
 * (inheriting an Enterprise template) failing to render its controls. */
registry.category("web_tour.tours").add("gec_margin_statement_tour", {
    url: "/odoo/action-gec_analytic_margin.action_gec_margin_statement_report",
    steps: () => [
        {
            content: "the report renders",
            trigger: ".o_content .line_name",
        },
        {
            content: "the section selector is on the bar",
            trigger: "#gec_filter_section button:contains('By Analytic Plans')",
            run: "click",
        },
        {
            content: "every reading is offered",
            trigger: ".dropdown-menu .dropdown-item:contains('By Projects')",
            run: "click",
        },
        {
            content: "the bar says which reading is showing",
            trigger: "#gec_filter_section button:contains('By Projects')",
        },
        {
            content: "both projects are sections of their own",
            trigger: ".line_name:contains('UI Other')",
        },
        {
            content: "open the picker",
            trigger: "#gec_filter_section_pick button:contains('All')",
            run: "click",
        },
        {
            content: "pick one section",
            trigger: ".dropdown-menu .dropdown-item:contains('UI Project')",
            run: "click",
        },
        {
            content: "the other one is gone from the report",
            trigger: ".o_content:not(:has(.line_name:contains('UI Other')))",
        },
        {
            content: "and the picker says what is picked",
            trigger: "#gec_filter_section_pick button:contains('UI Project')",
        },
        {
            content: "clear the pick",
            trigger: ".dropdown-menu .dropdown-item:contains('All')",
            run: "click",
        },
        {
            content: "the other section is back",
            trigger: ".line_name:contains('UI Other')",
        },
        {
            content: "this report's own toggles live with the extra options",
            trigger: "#filter_extra_options button",
            run: "click",
        },
        {
            content: "Ladder First is offered",
            trigger: ".dropdown-menu .dropdown-item:contains('Ladder First')",
            run: "click",
        },
        {
            content: "Before Allocation is offered too",
            trigger: ".dropdown-menu .dropdown-item:contains('Before Allocation')",
            run: "click",
        },
        {
            content: "a foldable line is there to open",
            trigger: "i[data-id=btn_foldable][data-icon=arrow_right]",
            run: "click",
        },
        {
            content: "clicking it opens the line",
            trigger: "i[data-id=btn_foldable][data-icon=arrow_drop_down]",
        },
    ],
});
