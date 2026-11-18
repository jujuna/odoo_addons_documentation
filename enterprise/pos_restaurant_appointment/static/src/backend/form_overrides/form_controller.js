import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { POSAppointmentQuickCreateFormController } from "@pos_appointment/app/form_extend/form_controller";

patch(POSAppointmentQuickCreateFormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
    },

    async onClickAppointmentStatus(status) {
        const viewMode = this.pos.action.currentController?.view?.type;
        const saved = await super.onClickAppointmentStatus(...arguments);
        const record = this.model.root;
        if (
            saved &&
            status === "attended" &&
            record.data.appointment_type_schedule_based_on === "resources"
        ) {
            this.pos.showResourceAssignNotification(record, record.data.resource_ids.records, {
                viewMode,
            });
        }
        return saved;
    },
});
