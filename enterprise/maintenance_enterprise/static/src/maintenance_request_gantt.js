import { registry } from "@web/core/registry";
import { GanttModel } from "@web_gantt/gantt_model";
import { ganttView } from "@web_gantt/gantt_view";

export class MaintenanceRequestGanttModel extends GanttModel {
    async _reschedule(ids, data, context) {
        if ("equipment_id" in data) {
            context = { ...context, gantt_reschedule: true };
        }
        return super._reschedule(ids, data, context);
    }
}

export const maintenanceRequestGanttView = {
    ...ganttView,
    Model: MaintenanceRequestGanttModel,
};

registry.category("views").add("maintenance_request_gantt", maintenanceRequestGanttView);
