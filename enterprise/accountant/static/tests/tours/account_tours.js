import { patch } from "@web/core/utils/patch";
import { accountTourSteps } from "@account/js/tours/account";
import { stepUtils } from "@web_tour/tour_utils";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";


patch(accountTourSteps, {
    goToAccountMenu(description="Open Accounting Menu") {
        return stepUtils.goToAppSteps('accountant.menu_accounting', description);
    },
    newInvoice() {
        return [
            {
                trigger: ".o_widget_account_onboarding [data-icon='circle'].oi-filled",
            },
            {
                trigger: "button[name=action_create_new]",
                content: _t("Now, we'll create your first invoice (accountant)"),
                run: "click",
            },
        ];
    },
});

registry.category("web_tour.tours").add("accountant_readonly_dashboard_tour", {
    url: "/odoo",
    steps: () => [
        {
            trigger: '.o_app[data-menu-xmlid="accountant.menu_accounting"]',
            content: "Open Accounting App as Read-Only User",
            run: "click",
        },
        {
            trigger: 'a[data-menu-xmlid="account.menu_board_journal_1"]',
            content: "Verify Dashboard menu item is visible on top navigation bar and click it",
            run: "click",
        },
        {
            trigger: '.o_account_kanban',
            content: "Verify Dashboard kanban view is displayed",
        },
    ],
});
