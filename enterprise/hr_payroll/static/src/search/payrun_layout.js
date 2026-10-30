import { usePlugin, useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { PayRunChatterService } from "@hr_payroll/js/payrun_chatter_service";
import { PayslipListPlugin } from "@hr_payroll/views/payslip_list/payslip_list_plugin";
import { PayRunControlPanel } from "@hr_payroll/search/payrun_control_panel";
import { Chatter } from "@mail/chatter/web_portal_project/chatter";

export class PayRunLayout extends Layout {
    static template = "hr_payroll.PayRunLayout";
    static components = {
        ...Layout.components,
        Chatter,
        PayRunControlPanel,
    };

    setup() {
        super.setup();
        this.components = { ...this.components, ControlPanel: PayRunControlPanel };
        this.uiService = useService("ui");
        this.payRunChatter = usePlugin(PayRunChatterService);
        this.payslipListPlugin = usePlugin(PayslipListPlugin);

        useEffect(() => {
            const payRunId = this.payslipListPlugin.payRunId();
            if (payRunId) {
                this.payRunChatter.selectPayslipRun({ resId: payRunId });
            } else {
                this.payRunChatter.closeChatter();
            }
        });
    }
}
