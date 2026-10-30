import { onMounted, providePlugins, proxy, signal, status, t, usePlugin } from "@odoo/owl";
import { useBus } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { PayslipListRenderer } from "./hr_payslip_list_renderer";
import { PayrunNewDropdown } from "@hr_payroll/views/payslip_run_new_dropdown/payslip_run_new_dropdown";
import { PayRunLayout } from "@hr_payroll/search/payrun_layout";
import { PayslipListPlugin } from "@hr_payroll/views/payslip_list/payslip_list_plugin";

export class PayslipListController extends ListController {
    static template = "hr_payroll.PayslipListView";
    static components = {
        ...PayslipListController.components,
        PayrunNewDropdown,
        Layout: PayRunLayout,
    };
    setup() {
        super.setup();

        const payRunId = signal(
            this.props.context?.payrun_id ?? null,
            { type: t.or([t.number(), t.literal(null)]) },
        );
        providePlugins([PayslipListPlugin], {payRunId: payRunId});
        this.payslipListPlugin = usePlugin(PayslipListPlugin);

        this.state = proxy({});

        this.displayHeaderButtonsTransitions = {
            draft: ["action_refresh_from_work_entries", "action_validate"],
            validated: ["action_payslip_paid"],
            paid: ["action_payslip_draft"],
        };

        const syncPayRunFromDomain = () => {
            const newId =
                this.env.searchModel.domain.find(
                    ([field, operator]) => field === "payslip_run_id" && operator === "="
                )?.[2] || null;
            if (newId !== this.payslipListPlugin.payRunId()) {
                this.payslipListPlugin.payRunId.set(newId);
            }
        };
        onMounted(syncPayRunFromDomain);
        useBus(this.env.searchModel, "update", syncPayRunFromDomain);
    }

    get modelParams() {
        const params = super.modelParams;
        const superOnRootLoaded = params.hooks?.onRootLoaded;
        params.hooks = {
            ...params.hooks,
            onRootLoaded: (root) => {
                superOnRootLoaded?.(root);
                if (status(this) === "mounted") {
                    // component remounted, payrun may have changed, rerender the payrun
                    this.env.bus.trigger("HR_PAYROLL:UPDATE_PAYRUN");
                }
            },
        };
        return params;
    }

    getSelectionFields() {
        return ["state"];
    }

    async onSelectionChanged() {
        await super.onSelectionChanged();
        let selection;
        if ((selection = await this.model.root.getResIds(true))) {
            this.state.selectionStates = await this.orm.read("hr.payslip", selection, this.getSelectionFields());
        }
    }

    displayButton(button) {
        const stateButtons = Object.values(this.displayHeaderButtonsTransitions).flat();
        const btnName = button.clickParams.name;

        if (!stateButtons.includes(btnName)) {
            return true;
        }
        const states = (this.state.selectionStates || []).map((s) => s.state);

        const effectiveState = states.includes("draft")
            ? "draft"
            : states.includes("validated")
            ? "validated"
            : "paid";

        return (this.displayHeaderButtonsTransitions[effectiveState] || []).includes(btnName);
    }

    createNewPayslip() {
        return this.actionService.doAction("hr_payroll.action_hr_payslip_new");
    }

    createNewPayRun() {
        return this.actionService.doAction("hr_payroll.action_hr_payslip_run_create");
    }
}

export const payslipListView = {
    ...listView,
    Renderer: PayslipListRenderer,
    Controller: PayslipListController,
    buttonTemplate: "hr_payroll.PayslipListView.Buttons",
};

registry.category("views").add("hr_payroll_payslip_list", payslipListView);
