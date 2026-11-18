import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("hr_payroll_payslip_new_time_off_tour", {
    steps: () => [
        {
            content: "Wait for the payslip form to load",
            trigger: ".o_form_view .o_field_widget[name='employee_id']",
        },
        {
            content: "Open the employee calendar from the payslip",
            trigger: "button[name='action_open_employee_calendar']",
            run: "click",
        },
        {
            content: "The calendar view is open",
            trigger: ".o_calendar_view",
        },
        {
            content: "Switch to the gantt view",
            trigger: ".o_switch_view.o_gantt",
            run: "click",
        },
        {
            content: "Create a new time off",
            trigger: ".o_gantt_view .o_gantt_button_add",
            run: "click",
        },
        {
            content: "Pick the time type",
            trigger: ".modal .o_field_widget[name='work_entry_type_id'] input",
            run: "edit Tour Time Off",
        },
        {
            content: "Select it",
            trigger: ".o-autocomplete--dropdown-item:contains(Tour Time Off)",
            run: "click",
        },
        {
            content: "Save the time off",
            trigger: ".modal .o_form_button_save",
            run: "click",
        },
        {
            content: "The dialog closed and the gantt shows the time off",
            trigger: "body:not(:has(.modal)) .o_gantt_view .o_gantt_pill",
        },
    ],
});
