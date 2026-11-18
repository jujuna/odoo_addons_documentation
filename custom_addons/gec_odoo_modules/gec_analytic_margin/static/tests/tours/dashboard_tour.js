import { registry } from "@web/core/registry";

/** Checks the dashboard draws its cards and charts, and that a click lands on the rows behind a figure. */
registry.category("web_tour.tours").add("gec_abc_dashboard_tour", {
    url: "/odoo/action-gec_analytic_margin.action_gec_margin_dashboard",
    steps: () => [
        {
            content: "the revenue card shows both projects' revenue",
            trigger: ".o_gec_kpi:contains('Revenue'):contains('240')",
        },
        {
            content: "the ladder closes on Net: revenue less cost",
            trigger: ".o_gec_ladder_row:contains('Net'):contains('150')",
        },
        {
            content: "the trend chart is drawn",
            trigger: ".o_gec_chart canvas",
        },
        {
            content: "open the revenue tab",
            trigger: ".o_gec_tabs a:contains('Revenue')",
            run: "click",
        },
        {
            content: "a cost object row opens its rows",
            trigger: ".o_gec_table tr:contains('UI Project')",
            run: "click",
        },
        {
            content: "the drill-down is the margin analysis for that project",
            trigger: ".o_pivot",
        },
    ],
});
