import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { X2ManyFieldDialog } from "@web/views/fields/relational_utils";

async function openAllocation(record, actionService) {
    const action = await record.model.orm.call(record.resModel, "action_open_allocation", [
        [record.resId],
    ]);
    await actionService.doAction(action, {
        onClose: async () => {
            if (!(await record.isDirty())) {
                await record.load();
            }
        },
    });
}

export class HolidayAttestFormController extends FormController {
    /**
     * @override
     **/
    async beforeExecuteActionButton(clickParams) {
        const record = this.model.root;
        if (record.resModel === "l10n.be.holiday.attest" && clickParams.name === "action_open_allocation") {
            await openAllocation(record, this.actionService);
            return false;
        }
        return super.beforeExecuteActionButton(...arguments);
    }
}

// The attests tab of the employee form opens them in an x2many dialog so we need to override `beforeExecuteActionButton` there as well
patch(X2ManyFieldDialog.prototype, {
    /**
     * @override
     **/
    async beforeExecuteActionButton(clickParams) {
        const record = this.record;
        if (record.resModel === "l10n.be.holiday.attest" && clickParams.name === "action_open_allocation") {
            await openAllocation(record, this.actionService);
            return false;
        }
        return super.beforeExecuteActionButton(...arguments);
    },
});

export const holidayAttestFormView = {
    ...formView,
    Controller: HolidayAttestFormController,
};

registry.category("views").add("l10n_be_holiday_attest_form", holidayAttestFormView);
