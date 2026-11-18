import { hrGanttView } from "@hr_gantt/hr_gantt_view";
import { exportTimeOffRecords } from "@hr_holidays/views/hr_leave_export";
import { TimeOffFormViewDialog } from "@hr_holidays/views/view_dialog/form_view_dialog";
import { userHasEmployeeInCurrentCompany } from "@hr_holidays/utils";
import { onWillStart } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useBus } from "@web/core/utils/hooks";

export class HrHolidaysGanttController extends hrGanttView.Controller {
    setup() {
        super.setup();
        useBus(this.env.searchModel, "direct-export-data", () => this.onDirectExportData());
        onWillStart(async () => {
            this.hasEmployee = await userHasEmployeeInCurrentCompany(this.orm);
        });
    }

    async onDirectExportData() {
        const { resModel } = this.model.metaData;
        const { domain, context } = this.model.searchParams;
        await exportTimeOffRecords({ resModel, domain, context });
    }

    /**
     * @override
     */
    create(context) {
        if (!this.hasEmployee && !this.props.context?.default_employee_id) {
            this.dialogService.add(AlertDialog, {
                title: _t("UserError"),
                body: _t(
                    "This operation is not allowed as you are not linked to an employee in the current company."
                ),
            });
            return;
        }
        return this.openDialog(
            { context, title: _t("New Time Off"), size: "md" },
            {},
            TimeOffFormViewDialog
        );
    }

    /**
     * @override
     */
    _getDialogProps(props) {
        const dialogProps = super._getDialogProps(...arguments);
        if (props.resId) {
            return dialogProps;
        }
        return {
            ...dialogProps,
            onRecordDeleted: () => {},
            onLeaveCancelled: () => this.model.fetchData(),
        };
    }
}
