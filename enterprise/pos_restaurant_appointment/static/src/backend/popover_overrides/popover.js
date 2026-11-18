import { patch } from "@web/core/utils/patch";
import { POSAppointmentCalendarEventPopover } from "@pos_appointment/app/popover_extend/popover";

patch(POSAppointmentCalendarEventPopover.prototype, {
    async onClickAppointmentStatus(status) {
        const viewMode = this.pos.action.currentController?.view?.type;
        await super.onClickAppointmentStatus(...arguments);
        if (
            status !== "attended" ||
            this.props.data.appointment_type_schedule_based_on !== "resources"
        ) {
            return;
        }
        const resources = await this._getAssignedResources();
        this.pos.showResourceAssignNotification({ id: this.props.resId }, resources, {
            viewMode,
        });
    },

    async _getAssignedResources() {
        const resources = this.props.data.resource_ids?.records?.map((r) => r.data);
        if (resources) {
            return resources;
        }
        const [event] = await this.env.services.orm.webRead("calendar.event", [this.props.resId], {
            specification: { resource_ids: { fields: { display_name: {} } } },
            context: { from_pos_booking: true },
        });
        return event.resource_ids;
    },
});
