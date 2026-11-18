import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

import { markup } from "@odoo/owl";

registry.category("web_tour.tours").add("timesheet_tour", {
    steps: () => [
        stepUtils.showAppsMenuItem(),
        {
            trigger: '.o_app[data-menu-xmlid="hr_timesheet.timesheet_menu_root"]',
            content: markup(
                _t(
                    "<b>Start managing your timesheets</b> <br/> <i>Everything you track begins here.</i>"
                )
            ),
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            trigger:
                ".o_grid_view .o_grid_row.o_grid_column_cell.o_grid_highlightable.text-900.o_grid_cell_today.bg-info-subtle div span, .o_grid_component_timesheet_uom",
            content: markup(
                _t(
                    "<b>Add time in the Grid view</b> <br/> <i>Click a cell to enter hours. Press Tab or Enter to navigate easily.</i>"
                )
            ),
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            id: "open_timesheet_systray",
            trigger: "div.o_menu_systray button.o-dropdown i[data-icon='play_circle']",
            content: markup(
                _t(
                    "<b>Use the timer to track your activities</b> <br/> <i>Start the timer, then log a timesheet when your activity ends. It restarts automatically for the next task.</i>"
                )
            ),
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            isActive: ["div.o_menu_systray button.o-dropdown > i.oi.oi-filled.text-danger"],
            trigger: "div.o_wrap_btn_sign_out button.btn-primary",
            content: markup(
                _t("<b>Start your session</b> <br/> <i>A session must be running to log a timesheet.</i>")
            ),
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            trigger: "div[name=description_field]",
            content: markup(
                _t(
                    '<b>Add a description</b> <br/> <i>Briefly summarize your activity, e.g., "Meeting with the customer."</i>'
                )
            ),
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            trigger: "div[name=project_field] div[name=project_id] input.o_input",
            content: markup(
                _t(
                    "<b>Select a project</b> <br/> <i>Choose the relevant project, such as a customer or team project.</i>"
                )
            ),
            tooltipPosition: "right",
            run: "edit Internal",
        },
        {
            isActive: ["auto"],
            trigger: "div[name=project_field] div[name=project_id] .o-autocomplete--dropdown-item a:contains('Internal')",
            run: "click",
        },
        {
            isActive: ["auto"],
            trigger: "button[name=save_btn]",
            run: "press ctrl+Enter",
        },
        {
            isActive: ["auto"],
            trigger: ".list-group-item:has(p.fw-medium:contains('/')):has(p.small:contains('Internal'))",
        },
        {
            isActive: ["manual"],
            trigger: "button[name=save_btn]",
            content: markup(
                _t(
                    "<b>Create the timesheet</b> <br/> <i>Once saved, the timer automatically restarts for your next activity.</i>"
                )
            ),
            tooltipPosition: "right",
            run: "click",
        },
    ],
});
