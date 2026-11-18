import { registry } from "@web/core/registry";

// Ticking an app its users cannot open gives it to them, unticking takes it back.
registry.category("web_tour.tours").add("gec_access_manager_tick_grant", {
    steps: () => [
        {
            content: "open the menu tree",
            trigger: ".o_notebook .nav-link:contains(Menus)",
            run: "click",
        },
        {
            content: "the app is not given: shown unticked",
            trigger: ".o_gec_menu_tree_row:contains(GEC Tick App) .o_gec_not_given",
        },
        {
            content: "tick it",
            trigger: ".o_gec_menu_tree_row:contains(GEC Tick App) input[type=checkbox]",
            run: "click",
        },
        {
            content: "given: ticked, and granted",
            trigger: '.o_field_widget[name="granted_group_ids"] .o_tag:contains(GEC Tick App / User)',
        },
        {
            content: "no longer marked",
            trigger: ".o_gec_menu_tree_row:contains(GEC Tick App):not(:has(.o_gec_not_given)) input[type=checkbox]:checked",
        },
        {
            content: "save",
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            content: "saved",
            trigger: ".o_form_saved",
        },
    ],
});

registry.category("web_tour.tours").add("gec_access_manager_untick_grant", {
    steps: () => [
        {
            content: "open the menu tree",
            trigger: ".o_notebook .nav-link:contains(Menus)",
            run: "click",
        },
        {
            content: "untick the app the profile gives",
            trigger: ".o_gec_menu_tree_row:contains(GEC Tick App) input[type=checkbox]:checked",
            run: "click",
        },
        {
            content: "the grant is gone",
            trigger: '.o_field_widget[name="granted_group_ids"]:not(:has(.o_tag:contains(GEC Tick App)))',
        },
        {
            content: "save",
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            content: "saved",
            trigger: ".o_form_saved",
        },
    ],
});
